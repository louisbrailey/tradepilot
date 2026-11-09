"""Synthetic completed WAL snapshot -> isolated restore -> actual Mac mirror."""
from contextlib import closing, nullcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
sys.path.insert(0,str(ROOT/'deploy/windows'))
import snapshots


@unittest.skipIf(os.name=='nt','Mirror runs on a POSIX Mac')
class RestoreMirrorTests(unittest.TestCase):
    def test_completed_wal_snapshot_survives_restore_then_strict_mirror(self):
        spec=importlib.util.spec_from_file_location('home_pc_mirror',ROOT/'scripts/mirror-home-pc-backups.py')
        mirror=importlib.util.module_from_spec(spec);spec.loader.exec_module(mirror)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);private=root/'private';runtime=private/'runtime';runtime.mkdir(parents=True)
            (private/'config.json').write_text(json.dumps({'GATEWAY_DISABLED':'enabled'}))
            with closing(sqlite3.connect(runtime/'paper.sqlite3')) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal')
                db.execute('CREATE TABLE fixture(value)');db.execute('INSERT INTO fixture VALUES(42)');db.commit()
            def directory(path):
                path=Path(path);path.mkdir(mode=0o700,parents=True,exist_ok=True);return path
            lease=Mock()
            with patch.object(snapshots,'private_path',side_effect=lambda p,**kw:Path(p)),patch.object(snapshots,'private_directory',side_effect=directory),patch.object(snapshots,'exclusive_runtime',side_effect=lambda p:nullcontext(lease)):
                snapshot=snapshots.backup(root)
                before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()}
                restored=snapshots.restore(root,snapshot,root/'isolated-restore')
            with closing(sqlite3.connect(restored/'paper.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT value FROM fixture').fetchall(),[(42,)])
            marker=before['complete.json']
            size=sum(p.stat().st_size for p in snapshot.iterdir())
            calls=[]
            def ssh(argv,**kwargs):
                calls.append(argv)
                if 'stdout' in kwargs:
                    with tarfile.open(fileobj=kwargs['stdout'],mode='w') as archive:archive.add(snapshot,arcname=snapshot.name)
                    return subprocess.CompletedProcess(argv,0,stderr=b'')
                return subprocess.CompletedProcess(argv,0,stdout=json.dumps([{'id':snapshot.name,'manifest_sha256':marker,'bytes':size}]).encode(),stderr=b'')
            key=root/'synthetic-key';key.write_text('not a real key');key.chmod(0o600)
            known=root/'synthetic-known-hosts';known.write_text('synthetic host pin')
            destination=root/'mirror';argv=['mirror','--key',str(key),'--known-hosts',str(known),'--destination',str(destination)]
            with patch.object(sys,'argv',argv),patch.object(mirror.subprocess,'run',side_effect=ssh):mirror.main()
            self.assertEqual(len(calls),2)
            self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir()},before)
            self.assertEqual({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (destination/snapshot.name).iterdir()},before)
            with closing(sqlite3.connect((destination/snapshot.name/'paper.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
                self.assertEqual(db.execute('SELECT value FROM fixture').fetchall(),[(42,)])
            self.assertEqual(json.loads((destination/'mirror-status.json').read_text())['copied'],1)


if __name__=='__main__':unittest.main()
