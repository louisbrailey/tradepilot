#!/usr/bin/env python3
"""Update the running Mac gateway's code in place, with a backup and a health check.

  plan      list the runtime files that differ from this checkout (default; writes nothing)
  apply     back up replaced files, install changed and new files atomically, restart, verify
  verify    authenticated, certificate-pinned health check of the running gateway
  rollback  restore a backup made by apply, remove the files it added, restart, verify

Only gateway runtime code moves: non-test modules in server/ and scripts the deployment
already has. The private directory (credentials, pairing, ledgers) is never written, and
secrets are never printed. Run it with the deployment's own Python, for example:

  "$HOME/Library/Application Support/TradePilot/gateway-20260923/venv/bin/python" scripts/update-local-gateway.py apply
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import plistlib
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

LABEL = "com.tradepilot.private-gateway"
REPO = Path(__file__).resolve().parent.parent
BACKUP_PREFIX = "code-backup-update-"


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def launch_arguments() -> list[str]:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    if not plist.is_file():
        fail(f"{plist} not found; install the gateway first or pass --deployment")
    arguments = plistlib.loads(plist.read_bytes()).get("ProgramArguments", [])
    if len(arguments) < 2:
        fail("launch agent has no program arguments")
    return [str(item) for item in arguments]


def option(arguments: list[str], name: str) -> str | None:
    return arguments[arguments.index(name) + 1] if name in arguments and arguments.index(name) + 1 < len(arguments) else None


def deployment_root(value: str | None) -> Path:
    root = Path(value).expanduser().resolve() if value else Path(launch_arguments()[1]).resolve().parent.parent
    if not (root / "server" / "server.py").is_file() or not (root / "private").is_dir():
        fail(f"{root} is not a TradePilot gateway deployment")
    repo = REPO.resolve()
    if root == repo or repo in root.parents:
        fail("refusing to treat this checkout as the deployment")
    return root


def runtime_files(root: Path, repo: Path = REPO) -> list[str]:
    names = sorted(f"server/{path.name}" for path in (repo / "server").glob("*.py") if not path.name.startswith("test_"))
    names += sorted(f"scripts/{path.name}" for path in (repo / "scripts").iterdir()
                    if path.is_file() and (root / "scripts" / path.name).exists() and not path.name.startswith("test_"))
    return names


def plan(root: Path, repo: Path = REPO) -> tuple[list[str], list[str]]:
    changed, added = [], []
    for name in runtime_files(root, repo):
        target = root / name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            fail(f"{target} is not an ordinary file")
        if not target.exists():
            added.append(name)
        elif target.read_bytes() != (repo / name).read_bytes():
            changed.append(name)
    return changed, added


def write_atomic(source: Path, target: Path) -> None:
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".update-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(source.read_bytes())
        mode = 0o700 if os.access(source, os.X_OK) and target.parent.name == "scripts" else 0o600
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def restart() -> None:
    result = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"], check=False,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        fail("launchctl could not restart the gateway; check `manage-local-service.py status`")


def apply(root: Path, repo: Path = REPO, restart_service=restart, check=None) -> Path | None:
    changed, added = plan(root, repo)
    if not changed and not added:
        print("Already up to date.")
        return None
    backup = root / "private" / (BACKUP_PREFIX + datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(mode=0o700)
    for name in changed:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(root / name, saved)
        saved.chmod(0o600)
    commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (backup / "MANIFEST.json").write_text(json.dumps({"source_commit": commit, "replaced": changed, "added": added,
                                                      "created_at": time.time()}, indent=2))
    (backup / "MANIFEST.json").chmod(0o600)
    for name in changed + added:
        write_atomic(repo / name, root / name)
    print(f"Installed {len(changed)} changed and {len(added)} new files from {commit[:12] or 'this checkout'}.")
    print(f"Backup: {backup}")
    restart_service()
    (check or verify)(root)
    return backup


def rollback(root: Path, name: str, restart_service=restart, check=None) -> None:
    backup = (root / "private" / name).resolve()
    if backup.parent != (root / "private").resolve() or not backup.name.startswith(BACKUP_PREFIX):
        fail("choose a backup directory created by this tool")
    manifest = json.loads((backup / "MANIFEST.json").read_text())
    for item in manifest["replaced"]:
        write_atomic(backup / item, root / item)
    for item in manifest["added"]:
        (root / item).unlink(missing_ok=True)
    print(f"Restored {len(manifest['replaced'])} files and removed {len(manifest['added'])} added files.")
    restart_service()
    (check or verify)(root)


def private_config(root: Path) -> dict:
    config = root / "private" / "config.json"
    if config.stat().st_mode & 0o077:
        fail("private config must be owner-only")
    return json.loads(config.read_text())


def post(host: str, port: int, server_name: str, cert: Path, token: str, path: str, timeout: float = 20) -> tuple[int, dict]:
    context = ssl.create_default_context(cafile=str(cert))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as secure:
            connection = http.client.HTTPConnection(server_name, port, timeout=timeout)
            connection.sock = secure
            connection.request("POST", path, body=b"{}", headers={"Authorization": f"Bearer {token}",
                                                                     "Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(2_000_000)
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            return response.status, payload if isinstance(payload, dict) else {}


def endpoints(arguments: list[str]) -> list[tuple[str, str]]:
    """(connect address, certificate name) pairs to try, most specific first."""
    hostname, address, interface = option(arguments, "--hostname"), option(arguments, "--address"), option(arguments, "--interface")
    name = hostname or address or "localhost"
    candidates = []
    if address:
        candidates.append((address, name))
    if interface:
        found = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", interface], capture_output=True, text=True).stdout.strip()
        if found:
            candidates.append((found, name))
    candidates.append(("::1", name))
    return candidates


def verify(root: Path, attempts: int = 30) -> None:
    arguments = launch_arguments()
    token = private_config(root).get("APP_ACCESS_TOKEN", "")
    cert = root / "private" / "server.pem"
    if len(token) < 32 or not cert.is_file():
        fail("gateway token or certificate missing from the private directory")
    last = "no response"
    for _ in range(attempts):
        for host, name in endpoints(arguments):
            try:
                status, _ = post(host, 8787, name, cert, token, "/v1/setup")
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last = type(error).__name__
                continue
            if status == 200:
                failures = []
                for path in ("/v1/alerts/state", "/v1/market/overview"):
                    try:
                        code, _ = post(host, 8787, name, cert, token, path, timeout=60)
                        detail = "ok" if code == 200 else f"HTTP {code}"
                    except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                        detail = type(error).__name__
                    if detail != "ok":
                        failures.append(f"{path}: {detail}")
                    print(f"  {path}: {detail}")
                if failures:
                    fail("gateway capability checks failed (" + "; ".join(failures) + ")")
                print(f"Gateway healthy at {host} (pinned certificate for {name}).")
                return
            last = f"HTTP {status}"
        time.sleep(2)
    fail(f"gateway did not pass its health check ({last}); see private/server.log or roll back")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="plan", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--deployment", help="Deployment directory (default: the installed launch agent's)")
    parser.add_argument("--backup", help="Backup directory name inside private/, for rollback")
    args = parser.parse_args()
    root = deployment_root(args.deployment)
    if args.command == "plan":
        changed, added = plan(root)
        print(f"Deployment: {root}")
        for name in changed: print(f"  update {name}")
        for name in added: print(f"  add    {name}")
        print("Up to date." if not changed and not added else "Run `apply` to install, back up and restart.")
    elif args.command == "apply":
        apply(root)
    elif args.command == "verify":
        verify(root)
    else:
        if not args.backup:
            fail("rollback needs --backup NAME")
        rollback(root, args.backup)


if __name__ == "__main__":
    main()
