"""Full synthetic backend suite with outbound traffic and external commands fenced."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'server'))
from windows_runtime import create_scratch_root

OriginalTemporaryDirectory = tempfile.TemporaryDirectory


class PrivateTemporaryDirectory(OriginalTemporaryDirectory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = self.name
        self.name = str(create_scratch_root(Path(self.container) / 'private-fixture'))

    def __enter__(self):
        return self.name

    def cleanup(self):
        self.name = self.container
        super().cleanup()


def main():
    # Every disposable fixture uses a genuine private DACL, including .name users.
    connect, bind, run = socket.socket.connect, socket.socket.bind, subprocess.run
    def safe_connect(sock, address):
        if address[0] not in ('127.0.0.1', '::1'): raise AssertionError('Outbound network forbidden')
        return connect(sock, address)
    def safe_bind(sock, address):
        if address[0] not in ('127.0.0.1', '::1') or address[1] != 0:
            raise AssertionError('Only ephemeral loopback test listeners permitted')
        return bind(sock, address)
    def safe_run(argv, *args, **kwargs):
        if argv[:2] != ['openssl', 'req']:
            raise AssertionError('Unmocked external command forbidden')
        executable = Path(r'C:\Program Files\Git\usr\bin\openssl.exe')
        if not executable.exists(): raise unittest.SkipTest('OpenSSL test prerequisite absent')
        return run([str(executable), *argv[1:]], *args, **kwargs)
    env = {k: os.environ[k] for k in ('SystemRoot','WINDIR','TEMP','TMP','PATH') if k in os.environ}
    with patch.dict(os.environ, env, clear=True), patch.object(socket.socket, 'connect', safe_connect), \
         patch.object(socket.socket, 'bind', safe_bind), patch.object(subprocess, 'run', safe_run), \
         patch.object(tempfile, 'TemporaryDirectory', PrivateTemporaryDirectory):
        suite = unittest.defaultTestLoader.discover(str(SOURCE / 'server'), pattern='test_*.py')
        return unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()


if __name__ == '__main__': raise SystemExit(0 if main() else 1)
