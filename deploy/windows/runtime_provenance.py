"""Exact attested model runtime; never accepts arbitrary unsigned interpreters."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ARCHIVE_SHA256 = '1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149'
WORKFLOW = 'https://github.com/astral-sh/python-build-standalone/.github/workflows/release.yml@refs/heads/main'
PYTHON_SHA256 = '246221b571e7a692a8b26818b628cac4c163e836de9897812eaebc2a8e1efa90'
VERSION = '3.12.16'


def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def safe_member(name):
    p = PurePosixPath(name)
    devices = {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    if not p.parts or p.parts[0] != 'python' or p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe runtime archive path')
    if any(x.endswith(('.', ' ')) or x.split('.')[0].upper() in devices for x in p.parts):
        raise ValueError('Windows archive alias')
    return p


def extract(archive, receipt, destination):
    archive, receipt, destination = map(Path, (archive, receipt, destination))
    # This receipt is included in the exact gatekeeper-approved bundle. The archive
    # hash is compiled into reviewed source, not supplied by an arbitrary receipt.
    r = json.loads(receipt.read_text())
    if (sha(archive) != ARCHIVE_SHA256 or r.get('archive_sha256') != ARCHIVE_SHA256
        or r.get('identity') != WORKFLOW or r.get('attestation_verification_exit') != 0
        or r.get('predicate') != 'https://slsa.dev/provenance/v1'):
        raise ValueError('Runtime provenance does not match the reviewed release')
    if destination.exists(): raise ValueError('Runtime destination must be fresh')
    members, names = [], set()
    with tarfile.open(archive, 'r:gz') as tar:
        for m in tar.getmembers():
            p = safe_member(m.name)
            if not (m.isfile() or m.isdir()) or str(p).casefold() in names:
                raise ValueError('Duplicate or non-ordinary runtime member')
            names.add(str(p).casefold()); members.append((m,p))
        destination.mkdir()
        files = {}
        for m,p in members:
            if len(p.parts) == 1 or '__pycache__' in p.parts or p.suffix == '.pyc': continue
            out = destination.joinpath(*p.parts[1:])
            if m.isdir(): out.mkdir(parents=True, exist_ok=True); continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as source, out.open('xb') as target:
                data = source.read(); target.write(data)
            files[out.relative_to(destination).as_posix()] = hashlib.sha256(data).hexdigest()
    if files.get('python.exe') != PYTHON_SHA256: raise ValueError('Unexpected runtime executable')
    manifest = {'version':VERSION, 'architecture':'x86_64', 'archive_sha256':ARCHIVE_SHA256,
                'bytecode':'Excluded; runtime uses dont_write_bytecode', 'files':files}
    (destination/'installed-members.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest


def verify_installed(directory):
    from windows_runtime import admin_control_file, ordinary_path
    directory = ordinary_path(Path(directory))
    record = json.loads(admin_control_file(directory/'installed-members.json').read_text())
    if record.get('archive_sha256') != ARCHIVE_SHA256 or record.get('version') != VERSION or record.get('architecture') != 'x86_64':
        raise ValueError('Unexpected installed model runtime receipt')
    for relative, expected in record['files'].items():
        p = safe_member('python/'+relative)
        file = admin_control_file(directory.joinpath(*p.parts[1:]))
        if sha(file) != expected: raise ValueError('Installed runtime member changed')
    if sha(directory/'python.exe') != PYTHON_SHA256: raise ValueError('Installed interpreter differs')
    return {'version': VERSION, 'architecture':'x86_64', 'files_verified':len(record['files']), 'archive_sha256':ARCHIVE_SHA256}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for name in ('archive','receipt','destination'): parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args(); extract(a.archive,a.receipt,a.destination)
