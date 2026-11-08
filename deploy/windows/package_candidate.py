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


def reviewed_wheels(directory, lock, minor, build_receipt=None):
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
        digest = sha(p)
        built = False
        if build_receipt is not None and name == 'paho-mqtt' and version == '1.6.1':
            r = json.loads(Path(build_receipt).read_text())
            source = '2a8291c81623aec00372b5a85558a372c747cbca8e9934dfe218638b8eefc26f'
            expected = 'd47a551aec8466d86e7924aa75e1afbf92979142c48a18955db4fea417db28b6'
            tools = {(x['package'],x['version'],x['sha256']) for x in r.get('build_tools',[])}
            built = (digest == expected and source in pins[name][1] and r.get('source',{}).get('upstream_sha256') == source
                and r.get('source_sha256_after') == source and r.get('byte_identical') is True
                and r.get('independent_fresh_source_builds') == 2 and r.get('source_date_epoch') == '315532800'
                and r.get('python_hash_seed') == '0' and r.get('build_network_and_child_process_audit_guard') is True
                and len(r.get('wheels',[])) == 2 and all(w['sha256'] == expected for w in r['wheels'])
                and tools == {('setuptools','80.9.0','062d34222ad13e0cc312a4c02d73f059e86a4acbfbdea8f8f76b28c99f306922'),
                              ('wheel','0.45.1','708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248')})
        if version != pins[name][0] or (digest not in pins[name][1] and not built):
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
            names = [n for n in z.namelist() if n.endswith('.dist-info/METADATA') and n.count('/') == 1]
            if len(names) != 1: raise ValueError('Ambiguous wheel metadata')
            metadata = BytesParser().parsebytes(z.read(names[0]))
        if normalize(metadata['Name']) != name or metadata['Version'] != version:
            raise ValueError('Wheel metadata/filename mismatch')
        seen.add(name)
        result.append((p, f"{name}=={version} --hash=sha256:{sha(p)}"))
    if not pins or seen != set(pins): raise ValueError('Missing reviewed wheels')
    return result


def package(source, wheels, ollama, output, kronos_source, kronos_wheels, runtime_inputs, model_cache, paho_build):
    if output.exists(): raise ValueError('Use a new bundle destination')
    if subprocess.check_output(['git','-C',str(source),'status','--porcelain']).strip():
        raise ValueError('Commit reviewed source before packaging')
    head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    build_receipt=paho_build/'reproducible-wheel-receipt.json'
    gateway_wheels = reviewed_wheels(wheels, source / 'deploy/windows/requirements.lock', 14, build_receipt)
    model_wheels = reviewed_wheels(kronos_wheels, source / 'deploy/windows/kronos.lock', 12)
    for name, expected in FROZEN.items():
        if sha(source / 'server' / name) != expected: raise ValueError('Frozen bytes changed')
    # Only code/deployment assets, not repository history or runtime folders.
    files = list((source / 'server').glob('*.py'))
    files += [source / 'scripts/remote-gateway.py', source / 'BACKTEST-SUMMARY.json', source / 'deploy/remote/cache-models.py']
    files += [p for p in (source / 'deploy/windows').iterdir() if p.suffix in ('.py', '.ps1', '.md', '.lock', '.in')]
    files += list((source/'deploy/windows/reports').glob('*.json'))
    output.mkdir(parents=True)
    for p in files:
        if p.is_symlink(): raise ValueError('Source link rejected')
        dest = output / 'source' / p.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(subprocess.check_output(['git','-C',str(source),'show',head+':'+p.relative_to(source).as_posix()]))
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
    def copy_public(p, relative, expected=None):
        p=Path(p)
        if not p.is_file() or any(x.is_symlink() or (x.exists() and getattr(x.lstat(),'st_file_attributes',0)&0x400) for x in (p,*p.parents)):
            raise ValueError('Public input must have ordinary ancestors')
        digest=sha(p)
        if expected is not None and digest != expected: raise ValueError('Public input checksum mismatch')
        dest=output/relative; dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists(): raise ValueError('Duplicate bundle member')
        shutil.copyfile(p,dest)
        if sha(dest)!=digest: raise ValueError('Copied input mismatch')
    inputs=ollama.parent
    distribution=json.loads((inputs/'ollama-provenance.json').read_text())
    signature=json.loads((inputs/'ollama-authenticode.json').read_text(encoding='utf-8-sig'))
    if distribution.get('archive_sha256')!='9ca74a7ab66ec86870b1eecac7df160df08dc4e3a291ab5d2d59bcf9310221c6' or distribution.get('official_checksum_agrees') is not True or signature.get('status')!='Valid' or not signature.get('subject','').startswith('CN=Ollama Inc.,'):
        raise ValueError('Official Ollama provenance required')
    for entry in distribution['files']:
        rel=Path(entry['path'])
        if rel.is_absolute() or '..' in rel.parts or ':' in str(rel): raise ValueError('Distribution path escape')
        copy_public(ollama/rel,Path('ollama')/rel,entry['sha256'])
    copy_public(inputs/'ollama-provenance.json','provenance/ollama.json')
    copy_public(inputs/'ollama-authenticode.json','provenance/ollama-authenticode.json')
    from runtime_provenance import ARCHIVE_SHA256, WORKFLOW
    runtime=json.loads((runtime_inputs/'python31216-provenance-summary.json').read_text())
    if runtime.get('identity')!=WORKFLOW or runtime.get('attestation_verification_exit')!=0 or runtime.get('archive_sha256')!=ARCHIVE_SHA256:
        raise ValueError('Reviewed runtime attestation receipt required')
    copy_public(runtime_inputs/'cpython-3.12.16+20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz','runtime/model-python.tar.gz',ARCHIVE_SHA256)
    copy_public(runtime_inputs/'python31216-provenance-summary.json','runtime/model-provenance.json')
    copy_public(runtime_inputs/'python31216.sigstore.jsonl','runtime/model-attestation.jsonl')
    copy_public(runtime_inputs/'python31216-verification.json','runtime/model-verification.json')
    copy_public(runtime_inputs/'python-3.14.10-amd64.exe','runtime/python-3.14.10-amd64.exe','92480239264744fe0386a1bd8275786fefa126e3129e56a68e22b52c73329965')
    copy_public(runtime_inputs/'python31410-provenance.json','runtime/gateway-provenance.json')
    copy_public(build_receipt,'provenance/paho-build.json')
    copy_public(paho_build/'wheel-validation-receipt.json','provenance/paho-wheel-validation.json')
    copy_public(paho_build/'paho-mqtt-1.6.1.tar.gz','provenance/paho-mqtt-1.6.1.tar.gz','2a8291c81623aec00372b5a85558a372c747cbca8e9934dfe218638b8eefc26f')
    for tool in json.loads(build_receipt.read_text())['build_tools']:
        name=tool['url'].rsplit('/',1)[-1]
        copy_public(paho_build/'build-tool-wheels'/name,Path('provenance/build-tools')/name,tool['sha256'])
    # Only the exact public HF configs/weights and pinned refs, never HF tokens,
    # private profile files, whole cache trees, unrelated models or locks.
    metadata=json.loads((inputs/'hf-public-metadata.json').read_text())
    pins={'Kronos-small':'901c26c1332695a2a8f243eb2f37243a37bea320','Kronos-Tokenizer-base':'0e0117387f39004a9016484a186a908917e22426'}
    for name,ref in pins.items():
        cache_name='models--NeoQuasar--'+name
        cached=model_cache/'huggingface/hub'/cache_name
        if (cached/'refs/main').read_text().strip()!=ref or metadata[name].get('sha')!=ref: raise ValueError('Unpinned public HF cache')
        for filename in ('config.json','model.safetensors'):
            entry=next(x for x in metadata[name]['siblings'] if x['rfilename']==filename)
            p=cached/'snapshots'/ref/filename
            if filename=='config.json':
                data=p.read_bytes()
                if hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()!=entry['blobId']: raise ValueError('HF config differs from upstream Git blob')
            expected=entry.get('lfs',{}).get('sha256')
            copy_public(p,Path('public-models/huggingface/hub')/cache_name/'snapshots'/ref/filename,expected)
        target=output/'public-models/huggingface/hub'/cache_name/'refs/main'
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(ref)
    copy_public(inputs/'hf-public-metadata.json','provenance/hf-public-metadata.json')
    models=model_cache/'ollama'
    relative=Path('manifests/registry.ollama.ai/library/qwen3.5/4b')
    raw=json.loads((models/relative).read_text())
    expected_model='d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04'
    refs=[raw['config'],*raw['layers']]
    if not any(x['digest']=='sha256:'+expected_model for x in refs): raise ValueError('Unexpected 4B digest')
    copy_public(models/relative,Path('public-models/ollama')/relative)
    for row in refs:
        digest=row['digest']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}',digest): raise ValueError('Unsafe model digest')
        name=digest.replace(':','-')
        copy_public(models/'blobs'/name,Path('public-models/ollama/blobs')/name,digest[7:])
    manifest = {'version': 2, 'source_commit':head, 'ollama_version': '0.40.15',
                'gateway_python':'3.14.10','model_python':'3.12.16','ollama_model_digest':expected_model,
                'kronos_source':kronos_pin,'hf_refs':pins, 'files': [
        {'path': str(p.relative_to(output)).replace('\\', '/'), 'sha256': sha(p)}
        for p in sorted(output.rglob('*')) if p.is_file()]}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return sha(output / 'manifest.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'wheels', 'ollama', 'output', 'kronos-source', 'kronos-wheels','runtime-inputs','model-cache','paho-build'): parser.add_argument('--' + name, type=Path, required=True)
    a = parser.parse_args()
    print(package(a.source, a.wheels, a.ollama, a.output, a.kronos_source, a.kronos_wheels,a.runtime_inputs,a.model_cache,a.paho_build))
