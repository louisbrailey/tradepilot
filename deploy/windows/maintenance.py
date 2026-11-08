"""Explicit offline backup/restore; never stops, starts or activates a service."""
import argparse
from pathlib import Path
from snapshots import backup, restore


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
