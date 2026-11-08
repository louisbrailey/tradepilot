"""Offline consistent snapshots and isolated fenced restore, never live replacement."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid
import os
import shutil
import threading
import time
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from windows_runtime import exclusive_runtime, private_path, private_directory, admin_control_file


def fenced(root):
    root = private_path(root, directory=True)
    if (root / 'cutover-allow.json').exists():
        raise ValueError('Remove activation through reviewed cutover before maintenance')
    config = json.loads(private_path(root / 'private/config.json').read_text())
    if config.get('GATEWAY_DISABLED') == 'disabled':
        raise ValueError('Gateway must be fenced before maintenance')


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup(root):
    root = Path(root)
    fenced(root)
    with exclusive_runtime(root / 'private') as lease:
        fenced(root)
        return _snapshot(root, lease, 'offline_writer_excluded')


def _snapshot(root, lease, consistency, stopped=None, max_bytes=10*1024**3, min_free=5*1024**3):
    lease.require(root / 'private')
    runtime = private_path(root / 'private/runtime', directory=True)
    files = sorted(runtime.glob('*.sqlite3'))
    if not files: raise ValueError('No databases to snapshot')
    parent = private_directory(root / 'backups')
    # Preserve prior evidence, including partial snapshots; stop at budget, never
    # silently prune a user's ledger history to make a backup succeed.
    used = sum(private_path(p).stat().st_size for p in parent.rglob('*') if p.is_file())
    estimate = sum(private_path(p).stat().st_size for p in files)
    if used + estimate > max_bytes or shutil.disk_usage(parent).free < min_free + estimate:
        raise ValueError('Backup disk budget exhausted')
    out = private_directory(parent / str(uuid.uuid4()))
    records, windows = {}, {}
    for source in files:
        lease.require(root / 'private')
        private_path(source)
        target = out / source.name
        started = datetime.now(timezone.utc).isoformat()
        deadline = time.monotonic() + 60
        def progress(status, remaining, total):
            lease.require(root / 'private')
            if (stopped is not None and stopped.is_set()) or time.monotonic() > deadline:
                raise TimeoutError('Snapshot interrupted or database deadline exceeded')
            if used + sum(p.stat().st_size for p in out.glob('*.sqlite3')) > max_bytes or shutil.disk_usage(out).free < min_free:
                raise ValueError('Snapshot exceeds storage budget')
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst, pages=128, progress=progress, sleep=.1)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Snapshot integrity failure')
        private_path(target)
        # Flush each completed member before publishing the completion marker.
        with target.open('r+b') as stream:
            os.fsync(stream.fileno())
        records[source.name] = digest(target)
        windows[source.name] = {'started':started, 'completed':datetime.now(timezone.utc).isoformat()}
    manifest = out / 'complete.tmp'
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump({'version': 1, 'databases': records, 'consistency':consistency,
                   'whole_set_atomic':False, 'database_windows':windows}, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
    manifest.replace(out / 'complete.json')
    return out


def live_backup(root, lease, **kwargs):
    """Only inside the gateway that already owns the runtime lease.

    SQLite online backup yields a coherent image per DB while its owner keeps
    writing. Different databases can represent different instants; no cross-DB
    transaction/atomic-set guarantee is made. No second writer is introduced.
    """
    return _snapshot(Path(root), lease, 'online_per_database_not_atomic_set', **kwargs)


def start_periodic(root, lease):
    schedule = Path(root) / 'backup-schedule.json'
    if not schedule.exists(): return None
    config = json.loads(admin_control_file(schedule).read_text(encoding="utf-8-sig"))
    if set(config) != {'interval_seconds','max_backup_bytes','min_free_bytes'}:
        raise ValueError('Unexpected backup policy')
    interval, budget, free = (config[x] for x in ('interval_seconds','max_backup_bytes','min_free_bytes'))
    if any(type(x) is not int for x in (interval,budget,free)) or not (900 <= interval <= 86400 and 1024**3 <= budget <= 20*1024**3 and free >= 5*1024**3):
        raise ValueError('Invalid bounded backup policy')
    stopped = threading.Event()
    def work():
        delay = 60
        while not stopped.wait(delay):
            record = {'at':datetime.now(timezone.utc).isoformat(), 'whole_set_atomic':False}
            try:
                out = live_backup(root,lease,stopped=stopped,max_bytes=budget,min_free=free)
                record.update(status='complete', snapshot=out.name)
            except Exception as error:
                record.update(status='failed', error=type(error).__name__)
            target = private_directory(Path(root)/'private/runtime')/'backup-status.json'
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(record)+'\n'); temp.replace(target)
            delay = interval
    thread = threading.Thread(target=work,name='private-sqlite-backup',daemon=True)
    thread.start()
    return stopped, thread


def restore(root, snapshot, destination):
    root, snapshot, destination = map(Path, (root, snapshot, destination))
    fenced(root)
    with exclusive_runtime(root / 'private'):
        fenced(root)
        private_path(snapshot, directory=True)
        record = json.loads(private_path(snapshot / 'complete.json').read_text())
        if record.get('version') != 1 or not isinstance(record.get('databases'), dict) or not record['databases']:
            raise ValueError('Incomplete snapshot')
        if destination.exists(): raise ValueError('Restore destination must be new')
        # Restores cannot overwrite the persistent runtime or any existing evidence.
        private_path(destination.parent, directory=True)
        for name, sha in record['databases'].items():
            if Path(name).name != name or not name.endswith('.sqlite3') or ':' in name:
                raise ValueError('Unsafe manifest name')
            source = private_path(snapshot / name)
            if digest(source) != sha: raise ValueError('Snapshot digest mismatch')
        out = private_directory(destination)
        for name in record['databases']:
            source = snapshot / name
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
                with closing(sqlite3.connect(out / name)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Restored database integrity failure')
            private_path(out / name)
        return out  # Never activates or swaps the restored tree into production.
