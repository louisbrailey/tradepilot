"""Prepare a review bundle without installing services or copying private state.

Requires an externally prepared public wheelhouse and official Ollama directory.
Nothing is downloaded or executed by this packager.
"""
import argparse
from email.parser import BytesParser
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import zipfile

FROZEN = {
    'paper_automation.py': '558c9ace7001636b5d4b3435ba3266fcb792129002435433198b5749bf01ee1a',
    'paper_calendar.py': '8c7985676625b2db8bc108f744e0851304a59120522013004de013eb0d47d847',
    'strategies.py': 'a359512ed57acb0a4cbfb2f0ba8e91a3852de470bade1683d13213cc2c000450',
    'research.py': '540b2612afe296779479365f64a0b8f1271adc36c2da9a411a05b39dc5293665',
}


def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def reviewed_wheels(directory, lock, minor):
    """Require exactly one reviewed wheel per pin for CPython/Windows x86_64."""
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    pins = {}
    joined = lock.read_text().replace('\\\n', ' ')
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)\s+((?:--hash=sha256:[0-9a-f]{64}\s*)+)', line)
        if not match: raise ValueError('Unsupported reviewed lock entry')
        name = normalize(match[1])
        if name in pins: raise ValueError('Duplicate reviewed pin')
        pins[name] = (match[2], set(re.findall(r'sha256:([0-9a-f]{64})', match[3])))
    result, seen = [], set()
    for p in sorted(directory.iterdir()):
        if p.suffix != '.whl' or not p.is_file() or p.is_symlink():
            raise ValueError('Wheelhouse must contain only ordinary wheels')
        fields = p.stem.split('-')
        if len(fields) not in (5, 6): raise ValueError('Invalid wheel filename')
        name, version = normalize(fields[0]), fields[1]
        if name in seen or name not in pins: raise ValueError('Duplicate or extra wheel')
        if version != pins[name][0] or sha(p) not in pins[name][1]:
            raise ValueError('Wheel version/hash differs from reviewed lock')
        python, abi, platform = fields[-3:]
        compatible = False
        for py in python.split('.'):
            for tag in abi.split('.'):
                for target in platform.split('.'):
                    if target not in ('any', 'win_amd64'): continue
                    pure = py in ('py3', f'py3{minor}') and tag == 'none'
                    native = py == f'cp3{minor}' and tag in (f'cp3{minor}', 'none') and target == 'win_amd64'
                    stable = re.fullmatch(r'cp3\d+', py) and 2 <= int(py[3:]) <= minor and tag == 'abi3' and target == 'win_amd64'
                    compatible |= bool(pure or native or stable)
        if not compatible: raise ValueError('Wheel incompatible with reviewed CPython/Windows target')
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
            if len(names) != 1: raise ValueError('Ambiguous wheel metadata')
            metadata = BytesParser().parsebytes(z.read(names[0]))
        if normalize(metadata['Name']) != name or metadata['Version'] != version:
            raise ValueError('Wheel metadata/filename mismatch')
        seen.add(name)
        result.append((p, f"{name}=={version} --hash=sha256:{sha(p)}"))
    if not pins or seen != set(pins): raise ValueError('Missing reviewed wheels')
    return result


def package(source, wheels, ollama, output, kronos_source, kronos_wheels):
    if output.exists(): raise ValueError('Use a new bundle destination')
    gateway_wheels = reviewed_wheels(wheels, source / 'deploy/windows/requirements.lock', 14)
    model_wheels = reviewed_wheels(kronos_wheels, source / 'deploy/windows/kronos.lock', 12)
    for name, expected in FROZEN.items():
        if sha(source / 'server' / name) != expected: raise ValueError('Frozen bytes changed')
    # Only code/deployment assets, not repository history or runtime folders.
    files = list((source / 'server').glob('*.py'))
    files += [source / 'scripts/remote-gateway.py', source / 'BACKTEST-SUMMARY.json', source / 'deploy/remote/cache-models.py']
    files += [p for p in (source / 'deploy/windows').iterdir() if p.suffix in ('.py', '.ps1', '.md', '.lock', '.in')]
    output.mkdir(parents=True)
    for p in files:
        if p.is_symlink(): raise ValueError('Source link rejected')
        dest = output / 'source' / p.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dest)
    requirements = []
    for p, requirement in gateway_wheels:
        requirements.append(requirement)
        dest = output / 'wheelhouse' / p.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(p, dest)
    if not requirements: raise ValueError('Public wheelhouse required')
    (output / 'requirements.offline.txt').write_text('\n'.join(requirements) + '\n')
    kronos_pin = '67b630e67f6a18c9e9be918d9b4337c960db1e9a'
    names = subprocess.check_output(['git', '-C', str(kronos_source), 'ls-tree', '-r', '--name-only', kronos_pin], text=True).splitlines()
    for name in names:
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or ':' in name:
            raise ValueError('Unsafe Kronos source path')
        dest = output / 'kronos' / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(subprocess.check_output(['git', '-C', str(kronos_source), 'show', kronos_pin + ':' + name]))
    model_requirements = []
    for p, requirement in model_wheels:
        model_requirements.append(requirement)
        dest = output / 'kronos-wheelhouse' / p.name
        dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(p, dest)
    if not model_requirements: raise ValueError('Kronos public wheelhouse required')
    (output / 'kronos.offline.txt').write_text('\n'.join(model_requirements) + '\n')
    if not (ollama / 'ollama.exe').is_file(): raise ValueError('Official Ollama distribution required')
    for p in ollama.rglob('*'):
        if p.is_symlink() or (getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Reparse distribution member')
        if p.is_file():
            dest = output / 'ollama' / p.relative_to(ollama)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
    manifest = {'version': 1, 'ollama_version': '0.40.15', 'files': [
        {'path': str(p.relative_to(output)).replace('\\', '/'), 'sha256': sha(p)}
        for p in sorted(output.rglob('*')) if p.is_file()]}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return sha(output / 'manifest.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'wheels', 'ollama', 'output', 'kronos-source', 'kronos-wheels'): parser.add_argument('--' + name, type=Path, required=True)
    a = parser.parse_args()
    print(package(a.source, a.wheels, a.ollama, a.output, a.kronos_source, a.kronos_wheels))
