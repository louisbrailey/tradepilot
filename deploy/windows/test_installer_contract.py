"""Exercise installer manifest and path checks against owned scratch input.

Only manifest blocks and NoReparse run. No installer, elevation, ACL,
SCM, executable payload or production directory is invoked.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell contract')
class InstallerManifestTests(unittest.TestCase):
    def exercise(self, *, bad_approval=False, corrupt_destination=False):
        source = Path(__file__).with_name('Install-Candidate.ps1').read_text()
        read = source[source.index('$approval='):source.index('$bundleRoot=')]
        write_start = source.index('$installedManifestPath=')
        write = source[write_start:source.index('ProtectedTree $install', write_start)]
        # Mutate the untrusted manifest after its one read, before hashing and
        # parsing. The installed receipt must still contain the approved bytes.
        read_line = '$manifestBytes=[IO.File]::ReadAllBytes($manifestPath)'
        self.assertEqual(read.count(read_line), 1)
        read = read.replace(read_line, read_line + '\n'
                            '[IO.File]::WriteAllText($manifestPath,$replacement)')
        if corrupt_destination:
            write_line = '[IO.File]::WriteAllBytes($installedManifestPath,$manifestBytes)'
            self.assertEqual(write.count(write_line), 1)
            write = write.replace(write_line, write_line + '\n'
                                  '[IO.File]::WriteAllText($installedManifestPath,$replacement)')
        original = b'{"version":2,"source_commit":"approved","files":[]}\n'
        replacement = '{"version":2,"source_commit":"replaced","files":[]}'
        approved_hash = '0' * 64 if bad_approval else hashlib.sha256(original).hexdigest()
        with tempfile.TemporaryDirectory(prefix='tradepilot-manifest-') as temporary:
            root = Path(temporary)
            bundle, installed = root / 'input', root / 'installed'
            bundle.mkdir()
            installed.mkdir()
            (bundle / 'manifest.json').write_bytes(original)
            approval = root / 'allow.json'
            approval.write_text(json.dumps({'decision': 'ALLOW', 'manifest_sha256': approved_hash}))
            command = (
                "$ErrorActionPreference='Stop';\n"
                # The full installer already uses Get-FileHash in its preceding
                # payload checks. Load its module for these isolated blocks.
                'Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop;\n'
                f'$Bundle={quote(bundle)}; $install={quote(installed)};\n'
                f'$replacement={quote(replacement)};\n'
                f'$GatekeeperAllow={quote(approval)};\n'
                'try {\n' + read + '\n' + write + '\n'
                '[pscustomobject]@{source_commit=$manifest.source_commit;hash=$manifestHash} | ConvertTo-Json -Compress\n'
                '} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }'
            )
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            environment = os.environ.copy()
            # Let Windows PowerShell discover its own modules instead of an
            # inherited PowerShell 7 module path from the command runner.
            environment.pop('PSModulePath', None)
            result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                                    capture_output=True, text=True, timeout=15, env=environment)
            manifest = installed / 'bundle-manifest.json'
            saved = manifest.read_bytes() if manifest.exists() else None
            self.assertEqual((bundle / 'manifest.json').read_text(), replacement)
            return result, saved, original

    def test_source_replacement_cannot_change_parsed_or_installed_manifest(self):
        result, saved, original = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt['source_commit'], 'approved')
        self.assertEqual(receipt['hash'], hashlib.sha256(original).hexdigest())
        self.assertEqual(saved, original)

    def test_wrong_approval_hash_rejects_without_writing_receipt(self):
        result, saved, _ = self.exercise(bad_approval=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ALLOW must bind this exact bundle manifest', result.stderr)
        self.assertIsNone(saved)

    def test_changed_installed_bytes_fail_post_write_verification(self):
        result, _, _ = self.exercise(corrupt_destination=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Installed manifest checksum mismatch', result.stderr)


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell contract')
class InstallerHiddenPathTests(unittest.TestCase):
    def exercise(self, junction=False):
        source = Path(__file__).with_name('Install-Candidate.ps1').read_text()
        function = source[source.index('function NoReparse('):source.index('function ProtectedTree(')]
        with tempfile.TemporaryDirectory(prefix='tradepilot-hidden-path-') as temporary:
            root = Path(temporary)
            hidden = root / 'hidden ordinary ancestor'
            hidden.mkdir()
            target = root / 'owned junction target'
            target.mkdir()
            command = (
                "$ErrorActionPreference='Stop';\n"
                "if($PSVersionTable.PSVersion.Major -ne 5){throw 'Windows PowerShell 5 required'}\n"
                f'$hidden={quote(hidden)};\n'
                '$item=Get-Item -LiteralPath $hidden -Force;\n'
                '$item.Attributes=$item.Attributes -bor [IO.FileAttributes]::Hidden;\n'
                "if(-not ((Get-Item -LiteralPath $hidden -Force).Attributes -band [IO.FileAttributes]::Hidden)){throw 'Hidden fixture required'}\n"
                + function + '\n'
            )
            if junction:
                link = hidden / 'owned junction'
                command += (
                    f'New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null;\n'
                    f'NoReparse {quote(link / "uncreated child")}\n'
                )
            else:
                command += f'NoReparse $hidden; NoReparse {quote(hidden / "uncreated child")}\n'
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            environment = os.environ.copy()
            environment.pop('PSModulePath', None)
            return subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-Command', command],
                                  capture_output=True, text=True, timeout=15, env=environment)

    def test_hidden_ordinary_directory_and_ancestor_are_accepted(self):
        result = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_junction_under_hidden_ancestor_remains_rejected(self):
        result = self.exercise(junction=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Reparse ancestor rejected', result.stderr)


if __name__ == '__main__':
    unittest.main()
