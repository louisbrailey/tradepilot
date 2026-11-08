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
import time
import zipfile
import package_candidate
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

    def test_timeout_kills_grandchild(self):
        import win32api, win32event
        pid_file = self.root / 'grandchild.pid'
        code = ('import subprocess,sys,time;from pathlib import Path;'
                'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
                f'Path({str(pid_file)!r}).write_text(str(p.pid));time.sleep(30)')
        with patch.dict(os.environ, {'TRADEPILOT_RUNTIME':str(self.root)}):
            with self.assertRaises(subprocess.TimeoutExpired):
                wr.run_model([sys.executable,'-c',code],input='',timeout=2,
                             env=wr.child_environment(os.environ),cwd=self.root)
        pid = int(pid_file.read_text())
        try:
            handle = win32api.OpenProcess(0x00100000, False, pid)
        except Exception as error:
            self.assertEqual(error.winerror, 87)  # PID no longer exists; not access denied.
        else:
            try: self.assertEqual(win32event.WaitForSingleObject(handle,5000),win32event.WAIT_OBJECT_0)
            finally: handle.Close()

    def test_output_limit_kills_sleeping_tree_promptly(self):
        import win32api, win32event
        pid_file = self.root / 'noisy-grandchild.pid'
        code = ('import subprocess,sys,time;from pathlib import Path;'
                'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);'
                f'Path({str(pid_file)!r}).write_text(str(p.pid));'
                'sys.stdout.write("x"*2100000);sys.stdout.flush();time.sleep(60)')
        started = time.monotonic()
        with patch.dict(os.environ, {'TRADEPILOT_RUNTIME':str(self.root)}):
            with self.assertRaisesRegex(ValueError, 'output exceeds'):
                wr.run_model([sys.executable,'-c',code],input='',timeout=90,
                             env=wr.child_environment(os.environ),cwd=self.root)
        self.assertLess(time.monotonic()-started, 5)
        self.assertEqual(list((self.root/'model-tmp').iterdir()), [])
        try: handle = win32api.OpenProcess(0x00100000, False, int(pid_file.read_text()))
        except Exception as error: self.assertEqual(error.winerror, 87)
        else:
            try: self.assertEqual(win32event.WaitForSingleObject(handle,1000),win32event.WAIT_OBJECT_0)
            finally: handle.Close()

    def test_packager_rejects_unreviewed_or_wrong_platform_wheels(self):
        wheels = self.root/'wheels'
        wheels.mkdir()
        wheel = wheels/'fixture-1.0-py3-none-any.whl'
        with zipfile.ZipFile(wheel,'w') as z:
            z.writestr('fixture-1.0.dist-info/METADATA','Name: fixture\nVersion: 1.0\n')
        lock = self.root/'reviewed.lock'
        good = f'fixture==1.0 --hash=sha256:{package_candidate.sha(wheel)}\n'
        lock.write_text(good)
        self.assertEqual(len(package_candidate.reviewed_wheels(wheels,lock,14)),1)
        for bad in (good.replace('==1.0','==2.0'), good.replace(package_candidate.sha(wheel),'0'*64),
                    good+'missing==1.0 --hash=sha256:'+'0'*64+'\n',good.replace('fixture==','other==')):
            lock.write_text(bad)
            with self.assertRaises(ValueError): package_candidate.reviewed_wheels(wheels,lock,14)
        lock.write_text(good)
        wrong = wheels/'fixture-1.0-cp312-cp312-win_amd64.whl'
        wheel.rename(wrong)
        with self.assertRaisesRegex(ValueError,'incompatible'): package_candidate.reviewed_wheels(wheels,lock,14)

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

    def test_transport_failure_poison_blocks_subsequent_model(self):
        import server
        lock = InferenceLock()
        with patch.object(server, '_local_ai_lock', lock), patch.object(server, 'build_opener') as opener:
            opener.return_value.open.side_effect = TimeoutError('synthetic timeout')
            with self.assertRaises(TimeoutError):
                server.local_ollama_request('/api/chat', {}, timeout=1)
        self.assertFalse(lock.acquire(False))

    def test_hardlink_private_file_rejected(self):
        original = self.root / 'original'
        original.write_text('synthetic')
        os.link(original, self.root / 'alias')
        with self.assertRaises(ValueError): wr.private_path(original)

    def test_missing_cutover_prevents_all_startup(self):
        with patch.object(gateway, 'remote_module') as remote:
            with self.assertRaises(ValueError):
                gateway.run(self.root, threading.Event(), Path('unused'))
            remote.assert_not_called()

    def test_gateway_shutdown_signals_both_workers_without_network(self):
        self.check_gateway_shutdown(False)

    def test_poison_triggers_drained_supervised_restart(self):
        self.check_gateway_shutdown(True)

    def check_gateway_shutdown(self, poisoned):
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
            if not poisoned: stopped.set()
            return alert_stop, alert
        lock = InferenceLock()
        if poisoned: lock.poison()
        with patch.object(gateway, 'remote_module', return_value=remote), \
             patch.object(gateway, 'tailscale_status', return_value={}), \
             patch.object(gateway, 'ollama_idle'), \
             patch.object(server, 'load_private_config'), patch.object(server, 'require_gateway_enabled'), \
             patch.object(server, 'load_market_env'), patch.object(server, 'enable_tls'), \
             patch.object(server, 'GatewayHTTPServer', return_value=http), \
             patch.object(server, 'automation', return_value=Mock()), \
             patch.object(server, '_local_ai_lock', lock), \
             patch.object(server, 'start_worker', return_value=(worker_stop,worker)), \
             patch.object(server, 'start_alert_worker', side_effect=alerts):
            if poisoned:
                with self.assertRaisesRegex(RuntimeError,'supervised restart'):
                    gateway.run(self.root, stopped, Path('unused'))
            else: gateway.run(self.root, stopped, Path('unused'))
        self.assertTrue(worker_stop.is_set())
        self.assertTrue(alert_stop.is_set())
        http.shutdown.assert_called_once()
        http.server_close.assert_called_once()


if __name__ == '__main__': unittest.main()
