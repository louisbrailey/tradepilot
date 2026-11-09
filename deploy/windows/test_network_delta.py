"""Execute only the delta's pure manifest planner in real PS5, no installer."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5')
class NetworkDeltaTests(unittest.TestCase):
    def exercise(self, mutation=None):
        before = {'version': 2, 'files': [{'path':'server-preserved.py','sha256':'a'*64}]}
        names = ['network_status.py','configure_recovery.py','Update-NetworkStatus.ps1','service_host.py','gateway.py','service_preflight.py']
        after = {'version':2, 'files': [dict(row) for row in before['files']] + [{'path':'source/deploy/windows/'+n,'sha256':'b'*64} for n in names]}
        if mutation: mutation(before, after)
        source = Path(__file__).with_name('Update-NetworkStatus.ps1').read_text()
        function = source[source.index('function PlanNetworkDelta('):source.index('function RequireStoppedDisabled')]
        with tempfile.TemporaryDirectory(prefix='tradepilot-delta-plan-') as temp:
            root = Path(temp)
            for name, data in [('before',before),('after',after)]: (root/(name+'.json')).write_text(json.dumps(data))
            quote=lambda p:"'"+str(p).replace("'","''")+"'"
            script = "$ErrorActionPreference='Stop';if($PSVersionTable.PSVersion.Major -ne 5){throw 'PS5 required'};\n" + function
            script += '\n$b=Get-Content -Raw -LiteralPath '+quote(root/'before.json')+' | ConvertFrom-Json;'
            script += '$a=Get-Content -Raw -LiteralPath '+quote(root/'after.json')+' | ConvertFrom-Json;'
            script += '@(PlanNetworkDelta $b $a) | ConvertTo-Json -Compress'
            env = os.environ.copy();env.pop('PSModulePath',None)
            return subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                '-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,text=True,timeout=15)

    def test_only_allowlisted_new_payload_is_planned(self):
        result=self.exercise();self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(json.loads(result.stdout)),6)

    def test_runtime_or_backend_change_rejected(self):
        result=self.exercise(lambda b,a:a['files'][0].update(sha256='c'*64))
        # Separate copied rows so an attacker cannot mutate the comparison fixture too.
        self.assertNotEqual(result.returncode,0)

    def test_deletion_rejected(self):
        result=self.exercise(lambda b,a:a['files'].pop(0));self.assertNotEqual(result.returncode,0)

    def test_path_escape_duplicate_and_extra_file_rejected(self):
        for path in ('../outside','C:/absolute','source/deploy/windows/../x','source/deploy/windows/other.py','SOURCE/DEPLOY/WINDOWS/network_status.py'):
            result=self.exercise(lambda b,a:a['files'].append({'path':path,'sha256':'d'*64}))
            with self.subTest(path=path):self.assertNotEqual(result.returncode,0)
