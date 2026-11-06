"""Hermetic remote deployment checks: fake identity/state only, no providers."""
import base64
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import ssl
import tempfile
import unittest
from unittest.mock import patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


REMOTE = module('remote_gateway', 'remote-gateway.py')
PAIR = module('remote_pair', 'pair-local-server.py')
HOST = 'paper.testnet.ts.net'
ADDRESS = '100.100.1.2'


def write(path, value):
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    path.chmod(0o600)


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'private').mkdir(mode=0o700)
        (self.root/'private/runtime').mkdir(mode=0o700)
        self.config = {'GATEWAY_DISABLED': 'disabled', 'WEBULL_LIVE_TRADING': 'disabled',
                       'COINBASE_LIVE_TRADING': 'disabled', 'COINBASE_TRANSFERS': 'disabled',
                       'BROKER_KILL_SWITCH': 'enabled', 'APP_ACCESS_TOKEN': 'fixture-'*8,
                       'TRADEPILOT_RUNTIME': str(self.root/'private/runtime'),
                       'AI_PROVIDER': 'ollama', 'OLLAMA_LOOPBACK_HOST': '127.0.0.1',
                       'LOCAL_AI_KEEP_ALIVE': '0', 'OLLAMA_MODEL': 'qwen3.5:4b'}
        self.settings = {'hostname': HOST, 'address': ADDRESS}
        self.status = {'BackendState': 'Running', 'Self': {'Online': True, 'DNSName': HOST+'.', 'TailscaleIPs': [ADDRESS]}}
        write(self.root/'remote.json', self.settings)
        write(self.root/'private/config.json', self.config)
        write(self.root/'private/server.pem', ssl.DER_cert_to_PEM_cert(b'fixture-certificate'))
        write(self.root/'private/server.key', 'fixture-not-a-real-key')
        write(self.root/'private/market.env', 'MASSIVE_API_KEY=fixture-only')
        self.pair = {'endpoint': 'https://'+HOST+':8787', 'token': self.config['APP_ACCESS_TOKEN'],
                     'certificate': base64.b64encode(b'fixture-certificate').decode()}
        write(self.root/'private/TradePilotPairing.json', self.pair)

    def test_only_verified_private_node_can_start(self):
        argv = REMOTE.command(self.root, self.status)
        self.assertEqual(argv[argv.index('--bind')+1], ADDRESS)
        self.assertNotIn(self.config['APP_ACCESS_TOKEN'], ' '.join(argv))
        for bad in ({}, {'BackendState': 'Stopped'}, {'BackendState': 'Running', 'Self': dict(self.status['Self'], Online=False)},
                    {'BackendState': 'Running', 'Self': dict(self.status['Self'], DNSName='other.testnet.ts.net')},
                    {'BackendState': 'Running', 'Self': dict(self.status['Self'], TailscaleIPs=['100.100.1.3'])}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                REMOTE.command(self.root, bad)

    def test_network_settings_reject_public_lan_and_malformed_hosts(self):
        for settings in ({'address': '0.0.0.0', 'hostname': HOST}, {'address': '8.8.8.8', 'hostname': HOST},
                         {'address': '192.168.1.2', 'hostname': HOST}, {'address': ADDRESS, 'hostname': 'example.com'},
                         {'address': ADDRESS, 'hostname': None}, []):
            write(self.root/'remote.json', json.dumps(settings))
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                REMOTE.read_settings(self.root)

    def test_disabled_and_unsafe_runtime_flags_fail_closed(self):
        for key, value in [('GATEWAY_DISABLED', 'enabled'), ('WEBULL_LIVE_TRADING', 'enabled'),
                           ('COINBASE_LIVE_TRADING', 'enabled'), ('COINBASE_TRANSFERS', 'enabled'),
                           ('BROKER_KILL_SWITCH', 'disabled'), ('TRADEPILOT_RUNTIME', '/tmp/other'),
                           ('AI_PROVIDER', 'openai'), ('LOCAL_AI_KEEP_ALIVE', '5m'),
                           ('OLLAMA_LOOPBACK_HOST', 'example.com'), ('APP_ACCESS_TOKEN', ''),
                           ('OLLAMA_MODEL', 'unknown')]:
            write(self.root/'private/config.json', dict(self.config, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                REMOTE.command(self.root, self.status)
        del self.config['GATEWAY_DISABLED']
        write(self.root/'private/config.json', self.config)
        with self.assertRaises(ValueError): REMOTE.command(self.root, self.status)

    def test_pairing_must_match_host_token_and_certificate(self):
        for key, value in [('endpoint', 'https://other.testnet.ts.net:8787'), ('token', 'wrong'),
                           ('certificate', base64.b64encode(b'other').decode())]:
            write(self.root/'private/TradePilotPairing.json', dict(self.pair, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                REMOTE.command(self.root, self.status)

    def test_private_file_permissions_and_symlinks_are_refused(self):
        path = self.root/'private/config.json'
        path.chmod(0o644)
        with self.assertRaises(ValueError): REMOTE.command(self.root, self.status)
        path.rename(self.root/'original.json')
        path.symlink_to(self.root/'original.json')
        with self.assertRaises(ValueError): REMOTE.command(self.root, self.status)

    def test_symlinked_runtime_cannot_redirect_state(self):
        runtime = self.root/'private/runtime'
        runtime.rmdir()
        runtime.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): REMOTE.command(self.root, self.status)
        with self.assertRaises(ValueError): REMOTE.backup(self.root)

    def test_backup_includes_committed_wal_and_refuses_overwrite(self):
        db = self.root/'private/runtime/automated-paper.sqlite3'
        with closing(sqlite3.connect(db)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE observations (intent TEXT)')
            writer.execute("INSERT INTO observations VALUES ('next-session-intent')")
            writer.commit()
            db.chmod(0o600)
            previous = os.umask(0o022)
            try: output = REMOTE.backup(self.root)
            finally: os.umask(previous)
            with closing(sqlite3.connect(output/db.name)) as restored:
                self.assertEqual(restored.execute('SELECT intent FROM observations').fetchall(), [('next-session-intent',)])
            self.assertEqual((output/db.name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((output/'complete.json').read_text())['databases'], [db.name])
            with self.assertRaises(ValueError): REMOTE.sqlite_backup(db, output/db.name)
            writer.execute("INSERT INTO observations VALUES ('after-backup')")
            writer.commit()

    def test_empty_and_failed_backups_have_no_complete_marker(self):
        with self.assertRaises(ValueError): REMOTE.backup(self.root)
        write(self.root/'private/runtime/bad.sqlite3', 'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError): REMOTE.backup(self.root)
        self.assertEqual(list((self.root/'backups').glob('*/complete.json')), [])

    def test_tailscale_pairing_requires_explicit_network_and_full_private_identity(self):
        target = self.root/'new-pair'
        for address, host, network in [(ADDRESS, HOST, 'lan'), ('8.8.8.8', HOST, 'tailscale'),
                                       (ADDRESS, 'test.local', 'tailscale'), (ADDRESS, None, 'tailscale')]:
            with self.subTest(address=address, host=host), self.assertRaises(SystemExit):
                PAIR.create_pairing(str(target), address, host, network)
        with patch.object(PAIR, 'certificate_material', return_value=(b'fixture', b'fixture', b'fixture')):
            PAIR.create_pairing(str(target), ADDRESS, HOST, 'tailscale')
        self.assertEqual(json.loads((target/'TradePilotPairing.json').read_text())['endpoint'], 'https://'+HOST+':8787')
        with self.assertRaises(SystemExit): PAIR.create_pairing(str(target), ADDRESS, HOST, 'tailscale')


if __name__ == '__main__':
    unittest.main()
