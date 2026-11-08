#!/usr/bin/env python3
"""Remote service entrypoint. Private Tailscale bind only; never public TLS bypass."""
import argparse
import base64
from contextlib import closing
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import sys

STATE = Path('/var/lib/tradepilot')


def private_file(path):
    if os.name == "nt":
        from windows_runtime import private_path
        return private_path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('Expected ordinary owner-only file: ' + path.name)
    return path


def private_directory(path):
    if os.name == "nt":
        from windows_runtime import private_path
        return private_path(path, directory=True)
    if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
        raise ValueError('Expected ordinary owner-only directory: ' + path.name)
    return path


def read_settings(root=STATE):
    private_directory(root)
    settings = json.loads(private_file(root/'remote.json').read_text())
    if not isinstance(settings, dict) or set(settings) != {'address', 'hostname'} or any(not isinstance(v, str) for v in settings.values()):
        raise ValueError('Remote network settings must contain address and hostname only')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.ts\.net', settings['hostname']):
        raise ValueError('Expected a full Tailscale MagicDNS hostname')
    address = ipaddress.ip_address(settings['address'])
    if address not in ipaddress.ip_network('100.64.0.0/10'):
        raise ValueError('Bind only to the assigned Tailscale IPv4 address')
    return settings


def command(root=STATE, tailscale_status=None):
    settings = read_settings(root)
    private_directory(root/'private')
    private_directory(root/'private/runtime')
    if tailscale_status is None:
        result = subprocess.run(['/usr/bin/tailscale', 'status', '--json'], check=True, capture_output=True, text=True, timeout=15)
        tailscale_status = json.loads(result.stdout)
    me = tailscale_status.get('Self') or {}
    if (tailscale_status.get('BackendState') != 'Running' or me.get('Online') is not True or
            settings['address'] not in me.get('TailscaleIPs', []) or
            me.get('DNSName', '').rstrip('.') != settings['hostname']):
        raise ValueError('Remote pairing does not match this online Tailscale node')
    config = json.loads(private_file(root/'private/config.json').read_text())
    if config.get('GATEWAY_DISABLED') != 'disabled':
        raise ValueError('Remote gateway has not been activated')
    if (config.get('WEBULL_LIVE_TRADING') != 'disabled' or config.get('COINBASE_LIVE_TRADING') != 'disabled' or
            config.get('COINBASE_TRANSFERS') != 'disabled' or config.get('BROKER_KILL_SWITCH') != 'enabled'):
        raise ValueError('Remote deployment requires broker trading and transfers disabled')
    if config.get('TRADEPILOT_RUNTIME') != str(root/'private/runtime'):
        raise ValueError('Remote runtime must use this persistent state directory')
    if (config.get('AI_PROVIDER') != 'ollama' or config.get('OLLAMA_LOOPBACK_HOST') != '127.0.0.1'
            or config.get('LOCAL_AI_KEEP_ALIVE') != '0' or config.get('OLLAMA_MODEL') != 'qwen3.5:4b'):
        raise ValueError('Remote AI must use the reviewed local model and release memory after requests')
    pair = json.loads(private_file(root/'private/TradePilotPairing.json').read_text())
    if (not isinstance(config.get('APP_ACCESS_TOKEN'), str) or len(config['APP_ACCESS_TOKEN']) < 32
            or pair.get('endpoint') != 'https://' + settings['hostname'] + ':8787' or pair.get('token') != config.get('APP_ACCESS_TOKEN')):
        raise ValueError('Pairing and remote configuration disagree')
    certificate = private_file(root/'private/server.pem')
    if base64.b64decode(pair.get('certificate', ''), validate=True) != ssl.PEM_cert_to_DER_cert(certificate.read_text()):
        raise ValueError('Pairing certificate does not match the server certificate')
    script = Path(__file__).resolve().parent.parent/'server/server.py'
    return [sys.executable, str(script), '--config', str(root/'private/config.json'),
            '--market-env', str(private_file(root/'private/market.env')),
            '--bind', settings['address'], '--tls-cert', str(private_file(root/'private/server.pem')),
            '--tls-key', str(private_file(root/'private/server.key'))]


def sqlite_backup(source, target):
    private_file(source)
    if target.exists() or target.is_symlink():
        raise ValueError('Refusing to overwrite a backup')
    # Create exclusively and privately before SQLite opens it, even with a loose caller umask.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite backup integrity check failed')
    target.chmod(0o600)


def backup(root=STATE):
    read_settings(root)
    private_directory(root/'private')
    runtime = private_directory(root/'private/runtime')
    databases = sorted(runtime.glob('*.sqlite3'))
    if not databases:
        raise ValueError('No ledgers found; refusing an empty backup')
    parent = root/'backups'
    if parent.is_symlink(): raise ValueError('Backup directory must not be a symlink')
    parent.mkdir(mode=0o700, exist_ok=True)
    if parent.stat().st_mode & 0o077: raise ValueError('Backup directory must be private')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = parent/stamp
    out.mkdir(mode=0o700)
    for path in databases:
        sqlite_backup(path, out/path.name)
    admission = root/'Library/Application Support/BrokerAccess/admission.sqlite3'
    if admission.exists(): sqlite_backup(admission, out/'admission.sqlite3')
    # No automatic deletion of evidence. Monitor disk and review retention explicitly.
    # Written last: partial backups must never be mistaken for completed snapshots.
    manifest = out/'complete.json'
    manifest.write_text(json.dumps({'created_at': stamp, 'databases': sorted(p.name for p in out.glob('*.sqlite3'))}))
    manifest.chmod(0o600)
    print('Private ledger backup created (each database consistent):', stamp)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', action='store_true')
    args = parser.parse_args()
    try:
        if args.backup: backup()
        else:
            argv = command()
            os.execv(argv[0], argv)
    except Exception as error:
        print('Remote gateway preflight failed:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
