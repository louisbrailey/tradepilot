"""Synthetic status, ACL and child-process failures; no real Tailscale query."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

import network_status as net

STAMP = (datetime(2026, 11, 8, tzinfo=timezone.utc), '12345678-1234-1234-1234-123456789abc', 100000)
RAW = json.dumps({'BackendState': 'Running', 'Self': {'Online': True,
    'TailscaleIPs': ['100.96.0.24', 'fd7a:115c:a1e0::1'], 'DNSName': 'desktop.example.ts.net.'},
    'Peer': {'private-peer': 'never-publish'}, 'User': {'private-user': 'never-publish'}}).encode()


class NetworkStatusTests(unittest.TestCase):
    def test_sanitizes_and_preserves_existing_gateway_identity_shape(self):
        receipt = net.record_status(RAW, STAMP)
        self.assertEqual(set(receipt), net.SCHEMA)
        status = net.validate(receipt, *STAMP)
        self.assertEqual(status, {'BackendState': 'Running', 'Self': {'Online': True,
            'TailscaleIPs': ['100.96.0.24'], 'DNSName': 'desktop.example.ts.net.'}})
        self.assertNotIn('private', json.dumps(receipt))

    def test_stale_future_other_boot_and_clock_jump_rejected(self):
        good = net.record_status(RAW, STAMP)
        for now, boot, tick in [(STAMP[0]+timedelta(seconds=21), STAMP[1], 121000),
                               (STAMP[0]-timedelta(seconds=1), STAMP[1], 99000),
                               (STAMP[0], 'other-boot', 100000),
                               (STAMP[0]+timedelta(seconds=5), STAMP[1], 100000)]:
            with self.subTest(now=now, boot=boot, tick=tick), self.assertRaises(ValueError):
                net.validate(good, now, boot, tick)

    def test_schema_and_types_fail_closed(self):
        for key, value in [('version', True), ('SelfOnline', 1), ('ok', 'yes'), ('IPv4', ['8.8.8.8']),
                           ('DNSName', 'evil.example'), ('uptime_ms', True), ('BackendState', 'invented'),
                           ('published_utc', '2026-11-08'), ('extra', 'private')]:
            receipt = net.record_status(RAW, STAMP); receipt[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): net.validate(receipt, *STAMP)

    def test_unavailable_and_offline_never_imply_online(self):
        with self.assertRaises(ValueError): net.validate(net.record_status(None, STAMP), *STAMP)
        raw = json.loads(RAW); raw['BackendState'] = 'Stopped'; raw['Self']['Online'] = False
        self.assertFalse(net.validate(net.record_status(json.dumps(raw), STAMP), *STAMP)['Self']['Online'])

    def test_oversize_and_duplicate_keys_rejected(self):
        for raw in (b' ' * (net.MAX_BYTES + 1), b'{"version":1,"version":1}'):
            with self.assertRaises(ValueError): net.decode(raw)

    def test_trusted_owner_and_only_administrator_writers(self):
        for owner in net.ADMINS:
            net.validate_acl(owner, [(0, 0, 0x1f01ff, owner), (0, 0, 0x120089, 'gateway')])
        for owner, acl in [('gateway', []), ('S-1-5-18', None),
                           ('S-1-5-18', [(0, 0, 2, 'gateway')]),
                           ('S-1-5-18', [(0, 0, 0x40000, 'users')]),
                           ('S-1-5-18', [(5, 0, 0, 'users')])]:
            with self.subTest(owner=owner, acl=acl), self.assertRaises(ValueError): net.validate_acl(owner, acl)

    def fake_query(self, output=RAW, code=0, stop=False):
        proc = Mock()
        proc.stdout = io.BytesIO(output)
        proc.wait.return_value = code; proc.poll.return_value = code
        stopped = threading.Event()
        if stop: stopped.set()
        with patch.object(net, 'open_checked', return_value=nullcontext()), patch.object(net.subprocess, 'Popen', return_value=proc) as create:
            result = net.query_status(stopped)
            args, kwargs = create.call_args
            self.assertEqual(args[0], [str(net.TAILSCALE), 'status', '--json', '--peers=false'])
            self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
            self.assertNotIn('BROKER_SECRET', kwargs['env'])
            return result

    def test_fixed_command_output_bound_failure_and_stop(self):
        self.assertEqual(self.fake_query(), RAW)
        for kwargs in ({'output': b'x' * (net.MAX_OUTPUT + 1)}, {'code': 1}, {'stop': True}):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises(ValueError): self.fake_query(**kwargs)

    def test_read_failure_is_fixed_error_not_raw_path_or_payload(self):
        with patch.object(net, 'open_checked', side_effect=OSError('sensitive details')):
            with self.assertRaisesRegex(ValueError, '^Trusted fresh network status unavailable$'):
                net.read_status()

    @unittest.skipUnless(os.name == 'nt', 'Windows file SDK')
    def test_reader_bounds_data_and_rejects_stale_receipt(self):
        import win32file
        receipt = net.record_status(RAW, STAMP)
        raw = json.dumps(receipt).encode()
        with patch.object(net, 'open_checked', return_value=nullcontext()), patch.object(win32file, 'GetFileSize', return_value=len(raw)), patch.object(win32file, 'ReadFile', return_value=(0, raw)) as read, patch.object(net, 'clock', return_value=STAMP):
            self.assertTrue(net.read_status()['Self']['Online'])
            self.assertEqual(read.call_args.args[1], net.MAX_BYTES + 1)
        with patch.object(net, 'open_checked', return_value=nullcontext()), patch.object(win32file, 'GetFileSize', return_value=net.MAX_BYTES+1), patch.object(win32file, 'ReadFile') as read:
            with self.assertRaises(ValueError): net.read_status()
            read.assert_not_called()

    def test_timeout_kills_owned_child_and_drains_reader(self):
        released = threading.Event()
        class BlockedPipe:
            def read(self, size):
                released.wait(3)
                return b''
            def close(self): pass
        proc = Mock();proc.stdout=BlockedPipe();proc.poll.return_value=None
        proc.kill.side_effect=released.set
        with patch.object(net, 'open_checked', return_value=nullcontext()), patch.object(net.subprocess, 'Popen', return_value=proc), patch.object(net.time, 'monotonic', side_effect=[0, 9]):
            with self.assertRaises(ValueError): net.query_status(threading.Event())
        proc.kill.assert_called_once()
        self.assertTrue(released.is_set())

    @unittest.skipUnless(os.name == 'nt', 'Windows identity SDK')
    def test_publisher_failure_and_stop_publish_only_unavailable(self):
        import win32security as sec
        stopped=threading.Event();token=Mock();published=[]
        def failed_query(event):
            event.set()
            raise ValueError('synthetic private error must never be persisted')
        with patch.object(sec, 'OpenProcessToken', return_value=token), patch.object(sec, 'GetTokenInformation', return_value=(sec.ConvertStringSidToSid('S-1-5-18'),0)), patch.object(net, 'open_checked', return_value=nullcontext()), patch.object(net, 'query_status', side_effect=failed_query), patch.object(net, 'clock', return_value=STAMP), patch.object(net, 'publish', side_effect=published.append):
            net.run(stopped)
        self.assertEqual(len(published),2)
        self.assertTrue(all(p['ok'] is False and p['SelfOnline'] is False for p in published))
        self.assertNotIn('private',json.dumps(published))

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel')
    def test_kernel_boot_clock_is_stable(self):
        first, second = net.clock(), net.clock()
        self.assertEqual(first[1], second[1]); self.assertGreaterEqual(second[2], first[2])

    @unittest.skipUnless(os.name == 'nt', 'Windows handles')
    def test_real_owned_scratch_file_is_not_an_administrator_receipt(self):
        with tempfile.TemporaryDirectory(prefix='tradepilot-net-untrusted-') as temp:
            path = Path(temp) / 'status.json'; path.write_bytes(b'{}')
            with self.assertRaises(ValueError):
                with net.open_checked(path): pass

    @unittest.skipUnless(os.name == 'nt', 'Windows file SDK')
    def test_real_handle_lifetime_and_security_descriptor(self):
        import win32file, win32security as sec
        with tempfile.TemporaryDirectory(prefix='tradepilot-net-handles-') as temp:
            path = Path(temp) / 'owned.txt';path.write_bytes(b'fixture')
            # Exercise real handles while mocking only the administrator trust
            # decision (ordinary user cannot create SYSTEM-owned test files).
            with patch.object(net, 'validate_acl'):
                with net.open_checked(path) as handle:
                    self.assertEqual(win32file.ReadFile(handle, 20)[1], b'fixture')
                with self.assertRaises(Exception):win32file.ReadFile(handle, 1)
            fake_gateway=sec.ConvertStringSidToSid('S-1-5-21-1-2-3-1001')
            with patch.object(sec, 'LookupAccountName', return_value=(fake_gateway,'synthetic',1)):
                sa=net.receipt_security()
            sd=sa.SECURITY_DESCRIPTOR
            self.assertEqual(sec.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()),'S-1-5-18')
            acl=sd.GetSecurityDescriptorDacl()
            rows=[acl.GetAce(i) for i in range(acl.GetAceCount())]
            reader=next(row for row in rows if row[2]==fake_gateway)
            self.assertEqual(reader[1] & net.WRITE_RIGHTS,0)

    @unittest.skipUnless(os.name == 'nt', 'Windows file SDK')
    def test_real_atomic_publication_and_bounded_read_in_owned_scratch(self):
        with tempfile.TemporaryDirectory(prefix='tradepilot-net-publish-') as temp:
            root=Path(temp)
            # Ordinary-user scratch cannot have SYSTEM ownership. Trust and
            # explicit receipt ACLs are tested separately; retain real Windows
            # file creation, write, flush, replace and pinned-reader operations.
            with patch.object(net, 'ROOT', root), patch.object(net, 'STATUS', root/'status.json'), patch.object(net, 'validate_acl'), patch.object(net, 'receipt_security', return_value=None), patch.object(net, 'clock', return_value=STAMP):
                net.publish(net.record_status(RAW,STAMP))
                self.assertTrue(net.read_status()['Self']['Online'])
                net.publish(net.record_status(None,STAMP))
                with self.assertRaises(ValueError): net.read_status()
                self.assertEqual({p.name for p in root.iterdir()},{'status.json'})

    @unittest.skipUnless(os.name == 'nt', 'SCM module imports only')
    def test_service_host_import_has_no_gateway_or_private_modules(self):
        folder = str(Path(__file__).parent.resolve())
        command = 'import sys;sys.path.insert(0,' + repr(folder) + ');import service_host;assert not any(n in sys.modules for n in ("gateway","server","snapshots","paper_automation","maintenance"))'
        result = subprocess.run([sys.executable, '-I', '-B', '-c', command], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovery_ends_with_no_action(self):
        import configure_recovery
        fake = Mock()
        fake.SC_MANAGER_CONNECT=1;fake.SERVICE_QUERY_STATUS=4;fake.SERVICE_CHANGE_CONFIG=2;fake.SERVICE_START=16
        fake.SERVICE_STOPPED=1;fake.QueryServiceStatus.return_value=(0,1)
        fake.SERVICE_CONFIG_FAILURE_ACTIONS=2;fake.SC_ACTION_RESTART=1;fake.SC_ACTION_NONE=0
        with patch.dict(sys.modules, win32service=fake): configure_recovery.configure()
        self.assertEqual(fake.ChangeServiceConfig2.call_count, 3)
        self.assertEqual(fake.OpenService.call_count, 3)
        for call in fake.OpenService.call_args_list:
            self.assertEqual(call.args[2], fake.SERVICE_QUERY_STATUS | fake.SERVICE_CHANGE_CONFIG | fake.SERVICE_START)
        fake.StartService.assert_not_called()
        for call in fake.ChangeServiceConfig2.call_args_list:
            self.assertEqual(call.args[2]['Actions'], [(1,15000),(1,30000),(1,60000),(0,0)])
