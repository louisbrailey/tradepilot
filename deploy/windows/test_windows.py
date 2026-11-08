"""Synthetic owned scratch only. Never invokes SCM, network, broker or installer."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
import windows_runtime as wr
import snapshots
import gateway
from inference_guard import InferenceLock


@unittest.skipUnless(os.name == 'nt', 'NTFS acceptance requires Windows')
class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix='tradepilot-synthetic-'))
        self.root = wr.create_scratch_root(self.parent / 'private')

    def tearDown(self):
        shutil.rmtree(self.parent)

    def test_acl_rejects_public_and_accepts_inherited_private(self):
        with self.assertRaises(ValueError): wr.private_path(self.parent, directory=True)
        child = wr.private_directory(self.root / 'child')
        (child / 'data').write_text('synthetic')
        wr.private_path(child / 'data')

    def test_junction_rejected(self):
        link = self.root / 'link'
        # Owned scratch directory junction only; no production path mutation.
        subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(self.root)],
                       check=True, capture_output=True)
        try:
            with self.assertRaises(ValueError): wr.ordinary_path(link / 'data')
        finally:
            os.rmdir(link)

    def test_lock_excludes_second_writer(self):
        with wr.exclusive_runtime(self.root):
            with self.assertRaises(Exception):
                with wr.exclusive_runtime(self.root): pass
        with wr.exclusive_runtime(self.root): pass

    def test_child_environment_drops_credentials(self):
        env = wr.child_environment({'SystemRoot': 'C:\\Windows', 'WEBULL_APP_SECRET': 'fake',
                                    'APP_ACCESS_TOKEN': 'fake', 'HF_HOME': 'cache'})
        self.assertNotIn('WEBULL_APP_SECRET', env)
        self.assertNotIn('APP_ACCESS_TOKEN', env)
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')

    def test_suspended_job_io_and_timeout(self):
        env = wr.child_environment(os.environ)
        with patch.dict(os.environ, {'TRADEPILOT_RUNTIME': str(self.root)}):
            result = wr.run_model([sys.executable, '-c', 'import sys;print(sys.stdin.read())'],
                                  input='synthetic', timeout=5, env=env, cwd=self.root)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), 'synthetic')
            with self.assertRaises(subprocess.TimeoutExpired):
                wr.run_model([sys.executable, '-c', 'import time;time.sleep(30)'],
                             input='', timeout=.2, env=env, cwd=self.root)

    def test_snapshot_restore_fence_hash_and_lock(self):
        private = wr.private_directory(self.root / 'private')
        runtime = wr.private_directory(private / 'runtime')
        (private / 'config.json').write_text(json.dumps({'GATEWAY_DISABLED': 'enabled'}))
        with closing(sqlite3.connect(runtime / 'paper.sqlite3')) as db:
            db.execute('create table fixture(value)')
            db.execute('insert into fixture values (42)')
            db.commit()
        with wr.exclusive_runtime(private):
            with self.assertRaises(Exception): snapshots.backup(self.root)
        out = snapshots.backup(self.root)
        restored = snapshots.restore(self.root, out, self.root / 'restore')
        with closing(sqlite3.connect(restored / 'paper.sqlite3')) as db:
            self.assertEqual(db.execute('select value from fixture').fetchone(), (42,))
        with self.assertRaises(ValueError): snapshots.restore(self.root, out, restored)
        (out / 'paper.sqlite3').write_bytes(b'corrupt')
        with self.assertRaises(ValueError): snapshots.restore(self.root, out, self.root / 'bad')
        (self.root / 'cutover-allow.json').write_text('{}')
        with self.assertRaises(ValueError): snapshots.backup(self.root)

    def test_poisoned_inference_cannot_overlap(self):
        lock = InferenceLock()
        self.assertTrue(lock.acquire(False))
        lock.poison()
        lock.release()
        self.assertFalse(lock.acquire(False))

    def test_missing_cutover_prevents_all_startup(self):
        with patch.object(gateway, 'remote_module') as remote:
            with self.assertRaises(ValueError):
                gateway.run(self.root, threading.Event(), Path('unused'))
            remote.assert_not_called()

    def test_gateway_shutdown_signals_both_workers_without_network(self):
        import server
        private = wr.private_directory(self.root / 'private')
        (self.root / 'cutover-allow.json').write_text(json.dumps(
            {'gatekeeper':'ALLOW','mac_writer_fenced':True,'activate_windows':True}))
        (private / 'market.env').write_text('# synthetic only')
        stopped = threading.Event()
        worker_stop, alert_stop = threading.Event(), threading.Event()
        worker, alert = Mock(), Mock()
        worker.is_alive.return_value = False
        alert.is_alive.return_value = False
        remote, http = Mock(), Mock()
        remote.read_settings.return_value = {'address':'100.96.0.24'}
        def alerts(*args):
            stopped.set()
            return alert_stop, alert
        with patch.object(gateway, 'remote_module', return_value=remote), \
             patch.object(gateway, 'tailscale_status', return_value={}), \
             patch.object(gateway, 'ollama_idle'), \
             patch.object(server, 'load_private_config'), patch.object(server, 'require_gateway_enabled'), \
             patch.object(server, 'load_market_env'), patch.object(server, 'enable_tls'), \
             patch.object(server, 'GatewayHTTPServer', return_value=http), \
             patch.object(server, 'automation', return_value=Mock()), \
             patch.object(server, 'start_worker', return_value=(worker_stop,worker)), \
             patch.object(server, 'start_alert_worker', side_effect=alerts):
            gateway.run(self.root, stopped, Path('unused'))
        self.assertTrue(worker_stop.is_set())
        self.assertTrue(alert_stop.is_set())
        http.shutdown.assert_called_once()
        http.server_close.assert_called_once()


if __name__ == '__main__': unittest.main()
