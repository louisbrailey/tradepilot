"""Offline consistent snapshots and isolated fenced restore, never live replacement."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from windows_runtime import exclusive_runtime, private_path, private_directory


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
    with exclusive_runtime(root / 'private'):
        fenced(root)
        runtime = private_path(root / 'private/runtime', directory=True)
        files = sorted(runtime.glob('*.sqlite3'))
        if not files: raise ValueError('No databases to snapshot')
        parent = private_directory(root / 'backups')
        out = private_directory(parent / str(uuid.uuid4()))
        records = {}
        for source in files:
            private_path(source)
            target = out / source.name
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise ValueError('Snapshot integrity failure')
            private_path(target)
            # Flush each completed member before publishing the completion marker.
            import os
            with target.open('r+b') as stream:
                os.fsync(stream.fileno())
            records[source.name] = digest(target)
        manifest = out / 'complete.tmp'
        with manifest.open('x', encoding='utf-8') as stream:
            json.dump({'version': 1, 'databases': records}, stream, sort_keys=True)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        manifest.replace(out / 'complete.json')
        return out


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
