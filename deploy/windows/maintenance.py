"""Explicit offline backup/restore; never stops, starts or activates a service."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid
from snapshots import backup, restore
from windows_runtime import admin_control_file, private_directory, private_path


def service_run(root):
    """Admin request, actual gateway identity, fenced offline backup/restore only."""
    from service_preflight import service_identity
    from snapshots import fenced
    root=Path(root)
    service_identity(); fenced(root)
    request=json.loads(admin_control_file(root/'maintenance-request.json').read_text(encoding='utf-8-sig'))
    if set(request) != {'version','action','nonce','snapshot','manifest_sha256'} or request['version'] != 1:
        raise ValueError('Invalid maintenance request')
    if str(uuid.UUID(request['nonce'])) != request['nonce']: raise ValueError('Invalid maintenance nonce')
    receipts=private_directory(private_directory(root/'private/maintenance')/request['nonce'])
    if (receipts/'receipt.json').exists(): raise ValueError('Maintenance nonce already used')
    report={'nonce':request['nonce'],'action':request['action'],'production_started':False,'restored_into_runtime':False}
    try:
        if request['action']=='backup' and request['snapshot'] is None and request['manifest_sha256'] is None:
            result=backup(root)
        elif request['action']=='restore-isolated':
            if str(uuid.UUID(request['snapshot'])) != request['snapshot']: raise ValueError('Invalid snapshot ID')
            snapshot=private_path(root/'backups'/request['snapshot'],directory=True)
            marker=private_path(snapshot/'complete.json')
            if hashlib.sha256(marker.read_bytes()).hexdigest()!=request['manifest_sha256']:
                raise ValueError('Snapshot completion hash differs from reviewed request')
            parent=private_directory(root/'private/restores')
            result=restore(root,snapshot,parent/request['nonce'])
        else: raise ValueError('Unsupported offline maintenance action')
        report.update(status='passed',result=str(result.relative_to(root)))
    except BaseException as error:
        report.update(status='failed',error=type(error).__name__)
        raise
    finally:
        temp=receipts/'receipt.tmp';temp.write_text(json.dumps(report,indent=2)+'\n');temp.replace(receipts/'receipt.json')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    command = p.add_subparsers(dest='command', required=True)
    command.add_parser('backup')
    r = command.add_parser('restore')
    r.add_argument('--snapshot', type=Path, required=True)
    r.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    result = backup(args.root) if args.command == 'backup' else restore(args.root, args.snapshot, args.destination)
    print(result)
