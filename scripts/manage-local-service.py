#!/usr/bin/env python3
"""Deploy and manage the per-user TradePilot launchd agent.

Private deployment preserves credentials without printing their contents.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import plistlib
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
from typing import NoReturn
from pathlib import Path

LABEL = "com.tradepilot.private-gateway"


_TIMESTAMP_ERRORS = False  # serve() turns this on so the launchd log shows when each start failed


def fail(message: str) -> "NoReturn":
    if _TIMESTAMP_ERRORS:
        message = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}"
    raise SystemExit(f"error: {message}")


def absolute_path(value: str, kind: str, *, directory: bool = False, resolve: bool = True) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        fail(f"{kind} must be an absolute path")
    if resolve:
        path = path.resolve()
    if directory:
        if not path.is_dir():
            fail(f"{kind} directory does not exist: {path}")
    elif not path.is_file():
        fail(f"{kind} file does not exist: {path}")
    return path


def validate_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        fail("address must be a literal private IPv4 or IPv6 address")
    if address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast or not address.is_private:
        fail("address must be a specific private LAN address (wildcard/public binds are refused)")
    return str(address)


def check_private_mode(path: Path, description: str) -> None:
    if path.stat().st_mode & 0o077:
        fail(f"{description} is accessible to group/other users; chmod 600 it first: {path}")


def validate_hostname(value: str) -> str:
    if not value or len(value) > 253 or value.endswith("."):
        fail("hostname must be a non-empty DNS name")
    labels = value.split(".")
    if any(not label or len(label) > 63 or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
           for label in labels):
        fail("hostname contains an invalid DNS label")
    return value.lower()


def validate_interface(value: str) -> str:
    # Must match server.py and network_watch.py, which accept only en0-en99.
    if not re.fullmatch(r"en[0-9]{1,2}", value):
        fail("interface must be a macOS en0 through en99 interface")
    return value


def validate_inputs(args: argparse.Namespace) -> dict[str, Path | str]:
    private_dir = absolute_path(args.private_dir, "private-dir", directory=True)
    if private_dir.stat().st_mode & 0o077:
        fail(f"private-dir must be owner-only (mode 700 or stricter): {private_dir}")
    market_env = absolute_path(args.market_env, "market-env")
    # Preserve the supplied venv path. Resolving it can bypass a venv shim and
    # make launchd invoke the system interpreter instead.
    python = absolute_path(args.python, "python executable", resolve=False)
    if not os.access(python, os.X_OK):
        fail(f"python executable is not executable: {python}")
    config = private_dir / "config.json"
    cert = private_dir / "server.pem"
    key = private_dir / "server.key"
    for path, description in ((config, "private config"), (cert, "TLS certificate"), (key, "TLS private key")):
        if path.is_symlink() or not path.is_file():
            fail(f"{description} must be an ordinary file: {path}")
    check_private_mode(config, "private config")
    check_private_mode(key, "TLS private key")
    raw_address = getattr(args, "address", None)
    raw_hostname = getattr(args, "hostname", None)
    address = validate_address(raw_address) if raw_address else None
    hostname = validate_hostname(raw_hostname) if raw_hostname else None
    if bool(address) == bool(hostname):
        fail("provide exactly one of --address or --hostname")
    if hostname and not getattr(args, "interface", None):
        fail("--interface is required with --hostname")
    validate_tls_material(cert, key)
    if hostname:
        validate_cert_san(cert, hostname=hostname)
    else:
        validate_cert_san(cert, address=address)
    return {"private_dir": private_dir, "market_env": market_env, "python": python,
            "config": config, "cert": cert, "key": key, "address": address or "", "hostname": hostname or "",
            "interface": validate_interface(getattr(args, "interface", None)) if getattr(args, "interface", None) else ""}


def validate_tls_material(cert: Path, key: Path) -> None:
    """Reject unusable TLS material before replacing a running launch agent."""
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # A password callback prevents an encrypted key from prompting unattended.
        context.load_cert_chain(str(cert), str(key), password=lambda: "")
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-dates"],
            check=True, capture_output=True, text=True, timeout=10,
        )
        dates = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        now = time.time()
        if not ssl.cert_time_to_seconds(dates["notBefore"]) <= now < ssl.cert_time_to_seconds(dates["notAfter"]):
            fail("TLS certificate is expired or not yet valid; renew and re-pair deliberately")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        fail("TLS certificate/key are invalid, mismatched, encrypted, or could not be inspected")


def validate_cert_san(cert: Path, address: str | None = None, hostname: str | None = None) -> None:
    """Require the requested IP or DNS SAN, using the system openssl."""
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-text"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        fail("could not inspect TLS certificate with openssl")
    if result.returncode != 0:
        fail("TLS certificate could not be parsed")
    if address:
        wanted = ipaddress.ip_address(address)
        for item in re.findall(r"IP Address:([^,\s]+)", result.stdout):
            try:
                if ipaddress.ip_address(item.strip()) == wanted:
                    return
            except ValueError:
                continue
        fail(f"TLS certificate SAN does not contain address {address}")
    wanted_name = hostname.lower()
    names = [item.lower().rstrip(".") for item in re.findall(r"DNS:([^,\s]+)", result.stdout)]
    if wanted_name.rstrip(".") in names:
        return
    fail(f"TLS certificate SAN does not contain hostname {hostname}")


def protected_location(path: Path) -> bool:
    """Do not make a background daemon depend on Files & Folders protected paths."""
    home = Path.home().resolve()
    actual = path.resolve()
    return any(root == actual or root in actual.parents
               for root in (home / "Documents", home / "Desktop", home / "Downloads"))


def assert_launch_paths_accessible(values: dict[str, Path | str], script_dir: Path) -> None:
    required = [Path(values[key]) for key in ("private_dir", "market_env", "python")]
    required.append(script_dir)
    if any(protected_location(path) for path in required):
        fail("launchd paths include Documents/Desktop/Downloads; use the deploy command to copy the gateway into Application Support first")


def launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def plist_for(values: dict[str, Path | str], script_dir: Path) -> dict:
    private_dir = values["private_dir"]
    log = Path(private_dir) / "server.log"
    if values["hostname"]:
        arguments = [str(values["python"]), str(script_dir / "manage-local-service.py"), "serve",
                     "--private-dir", str(private_dir), "--hostname", str(values["hostname"]),
                     "--interface", str(values["interface"]), "--market-env", str(values["market_env"]),
                     "--python", str(values["python"])]
    else:
        arguments = [str(values["python"]), str(script_dir.parent / "server" / "server.py"),
                     "--config", str(values["config"]), "--market-env", str(values["market_env"]),
                     "--bind", str(values["address"]), "--tls-cert", str(values["cert"]),
                     "--tls-key", str(values["key"])]
    return {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(script_dir.parent),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "Umask": 0o077,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def print_sanitized(plist: dict, destination: Path) -> None:
    print(f"label: {LABEL}")
    print(f"plist: {destination}")
    print("program arguments:")
    for argument in plist["ProgramArguments"]:
        print(f"  {argument}")
    print(f"logs: {plist['StandardOutPath']} (owner-only)")
    print("keepalive: restart after failure, throttled to one start per 30 seconds")


def discover_interface_address(interface: str) -> str:
    try:
        result = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", interface], check=False,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        fail(f"could not inspect interface {interface}")
    if result.returncode:
        fail(f"interface {interface} has no IPv4 address (Mac not on the paired LAN?); launchd will retry")
    return validate_address(result.stdout.strip())


def serve(args: argparse.Namespace) -> None:
    global _TIMESTAMP_ERRORS
    _TIMESTAMP_ERRORS = True
    values = validate_inputs(args)
    # Hostname mode validates the DNS SAN and discovers only the bind address.
    address = str(values["address"]) or discover_interface_address(str(values["interface"]))
    server = Path(__file__).resolve().parent.parent / "server" / "server.py"
    arguments = [str(values["python"]), str(server), "--config", str(values["config"]),
                 "--market-env", str(values["market_env"]), "--bind", address,
                 "--tls-cert", str(values["cert"]), "--tls-key", str(values["key"])]
    if values["hostname"]:
        arguments += ["--interface", str(values["interface"])]
    os.execv(str(values["python"]), arguments)


def install(args: argparse.Namespace) -> None:
    values = validate_inputs(args)
    destination = launch_agent_path()
    script_dir = Path(__file__).resolve().parent
    if not args.dry_run:
        assert_launch_paths_accessible(values, script_dir)
    plist = plist_for(values, script_dir)
    private_dir = values["private_dir"]
    for name in ("server.log",):
        log = Path(private_dir) / name
        if log.is_symlink() or (log.exists() and not log.is_file()):
            fail("server log must be an ordinary file")
        log.touch(exist_ok=True, mode=0o600)
        log.chmod(0o600)
    if args.dry_run:
        review_path = Path(private_dir) / f".{LABEL}.dry-run.plist"
        if review_path.is_symlink() or (review_path.exists() and not review_path.is_file()):
            fail("review plist must be an ordinary file")
        review_path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=False))
        review_path.chmod(0o600)
        print_sanitized(plist, review_path)
        return
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        backup = destination.with_suffix(destination.suffix + ".bak")
        counter = 1
        while backup.exists():
            backup = destination.with_suffix(destination.suffix + f".bak{counter}")
            counter += 1
        shutil.copy2(destination, backup)
        backup.chmod(0o600)
        print(f"backup: {backup}")
    fd, temporary = tempfile.mkstemp(prefix=f".{LABEL}.", suffix=".plist", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=False))
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)], check=False)
    if result.returncode:
        fail("plist written but launchctl bootstrap failed")
    print(f"installed and loaded: {destination}")


def status(_args: argparse.Namespace) -> None:
    try:
        result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], check=False,
                                capture_output=True, text=True)
    except OSError:
        print(f"{LABEL}: launchctl unavailable (this host is not macOS)")
        return
    if result.returncode:
        print(f"{LABEL}: not loaded")
        return
    # launchctl output is operational metadata and contains no config/token content.
    print(f"{LABEL}: loaded")
    for line in result.stdout.splitlines():
        if line.strip().startswith(("state =", "pid =", "last exit code =", "runs =")):
            print(line.strip())


def remove(_args: argparse.Namespace) -> None:
    destination = launch_agent_path()
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if destination.exists():
        backup = destination.with_suffix(destination.suffix + ".removed")
        counter = 1
        while backup.exists():
            backup = destination.with_suffix(destination.suffix + f".removed{counter}")
            counter += 1
        os.replace(destination, backup)
        backup.chmod(0o600)
        print(f"unloaded; plist moved to recoverable backup: {backup}")
    else:
        print(f"{LABEL}: no installed plist")



def inspect_python(python: Path) -> dict:
    code = "import sysconfig,json;print(json.dumps({'purelib':sysconfig.get_path('purelib'),'platlib':sysconfig.get_path('platlib')}))"
    try:
        result = subprocess.run([str(python), "-c", code], check=True, capture_output=True, text=True, timeout=30)
        paths = json.loads(result.stdout)
        if not isinstance(paths, dict) or set(paths) != {"purelib", "platlib"}:
            raise ValueError("unexpected Python paths")
        for path in paths.values():
            absolute_path(path, "Python packages", directory=True)
        return paths
    except (OSError, ValueError, subprocess.SubprocessError):
        fail("could not inspect the source Python environment")


def secure_tree(root: Path) -> None:
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_symlink():
            fail("private runtime must not contain symbolic links")
        if path.is_dir():
            path.chmod(0o700)
        elif path.is_file():
            path.chmod(0o600)
        else:
            fail("private runtime contains an unsupported file type")


def selected_market_env(path: Path) -> str:
    # Keep only data-provider assignments. Do not copy unrelated Signal Forge keys.
    accepted = {"MASSIVE_API_KEY", "POLYGON_API_KEY", "MARKET_DATA_PROVIDER", "MARKET_DATA_API_KEY"}
    selected = []
    for raw in path.read_text().splitlines():
        line = raw.strip().removeprefix("export ")
        name, sep, value = line.partition("=")
        if sep and name.strip() in accepted:
            selected.append(name.strip() + "=" + value)
    return "\n".join(selected) + "\n"


def copy_runtime(source: Path, destination: Path) -> None:
    if not source.exists():
        destination.mkdir(mode=0o700)
        return
    for path in [source, *source.rglob("*")]:
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            fail("runtime must contain only ordinary files and directories")
    shutil.copytree(source, destination, copy_function=shutil.copyfile)
    secure_tree(destination)


def evaluation_artifact(project: Path) -> bytes:
    """Read only the sanitized frozen summary, never a bar cache or private file."""
    artifact = project / "BACKTEST-SUMMARY.json"
    if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size > 5_000_000:
        fail("BACKTEST-SUMMARY.json must be an ordinary JSON file below 5 MB")
    try:
        content = artifact.read_bytes()
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("protocol"), dict) or not isinstance(parsed.get("results"), dict):
            raise ValueError("invalid evaluation summary")
        if not isinstance(parsed.get("evaluated_at"), str):
            raise ValueError("missing evaluation date")
    except (OSError, ValueError):
        fail("BACKTEST-SUMMARY.json is not a valid frozen evaluation summary")
    return content


def deploy(args: argparse.Namespace) -> None:
    """Copy a stopped gateway into a private, launchd-accessible deployment.

    Every deployment gets a new destination. A failed attempt is retained there
    for inspection; the source remains untouched and nothing is started.
    """
    values = validate_inputs(args)
    destination = Path(args.destination).expanduser()
    if not destination.is_absolute():
        fail("destination must be an absolute path")
    destination = destination.resolve()
    if protected_location(destination):
        fail("deployment destination cannot be inside Documents/Desktop/Downloads")
    if destination.exists():
        fail("destination already exists; use a new deployment directory to preserve the current runtime")
    if not args.source_stopped and not args.dry_run:
        fail("stop the source gateway, then pass --source-stopped so journals and authentication files remain consistent")
    source_python = Path(values["python"])
    base_python = source_python.resolve()
    if protected_location(base_python):
        fail("the base Python interpreter is in a protected folder; use an interpreter installed outside Documents/Desktop/Downloads")
    package_paths = inspect_python(source_python)
    project = Path(__file__).resolve().parent.parent
    source_private = Path(values["private_dir"])
    frozen_evaluation = evaluation_artifact(project)
    try:
        config = json.loads(Path(values["config"]).read_text())
        if not isinstance(config, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in config.items()):
            raise ValueError("invalid configuration")
        runtime = Path(config.get("TRADEPILOT_RUNTIME", str(source_private / "runtime"))).expanduser()
        if not runtime.is_absolute():
            fail("TRADEPILOT_RUNTIME must be absolute before deployment")
    except (OSError, ValueError):
        fail("could not read the private gateway configuration")
    for source in [runtime.resolve(), source_private.resolve(), *(Path(path).resolve() for path in package_paths.values())]:
        if source == destination or source in destination.parents:
            fail("destination must be separate from the source private runtime and Python package directories")
    if args.dry_run:
        print(f"deployment: {destination}")
        print("copy: gateway Python sources, manager, pinned requirements, frozen BACKTEST-SUMMARY.json, private config/TLS/pairing, and stopped runtime")
        print("market environment: only Massive/Polygon assignments will be copied")
        print("Python: new local virtual environment with existing installed packages; no downloads")
        print("source preserved; credentials and certificates preserved; service not installed or started")
        return
    old_umask = os.umask(0o077)
    try:
        destination.mkdir(parents=True, mode=0o700)
        server = destination / "server"
        server.mkdir(mode=0o700)
        for path in project.joinpath("server").iterdir():
            if path.name == "requirements.txt" or (path.suffix == ".py" and not path.name.startswith("test_")):
                shutil.copyfile(path, server / path.name)
        scripts = destination / "scripts"
        scripts.mkdir(mode=0o700)
        shutil.copyfile(Path(__file__), scripts / "manage-local-service.py")
        shutil.copyfile(project / "LOCAL-SERVICE.md", destination / "LOCAL-SERVICE.md")
        (destination / "BACKTEST-SUMMARY.json").write_bytes(frozen_evaluation)
        private = destination / "private"
        private.mkdir(mode=0o700)
        config["TRADEPILOT_RUNTIME"] = str(private / "runtime")
        (private / "config.json").write_text(json.dumps(config, indent=2))
        for name in ("server.key", "server.pem", "TradePilotPairing.json"):
            if (source_private / name).is_file():
                if (source_private / name).is_symlink():
                    fail("private input files cannot be symbolic links")
                shutil.copyfile(source_private / name, private / name)
        (private / "market.env").write_text(selected_market_env(Path(values["market_env"])))
        copy_runtime(runtime, private / "runtime")
        secure_tree(private)
        venv = destination / "venv"
        try:
            subprocess.run([str(base_python), "-m", "venv", "--without-pip", str(venv)],
                           check=True, capture_output=True, text=True, timeout=90)
            deployed_python = venv / "bin" / "python"
            deployed_paths = inspect_python(deployed_python)
            seen = set()
            for kind in ("purelib", "platlib"):
                pair = (package_paths[kind], deployed_paths[kind])
                if pair not in seen:
                    shutil.copytree(pair[0], pair[1], dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                    seen.add(pair)
            subprocess.run([str(deployed_python), "-c", "from webull.core.client import ApiClient; from webull.trade.trade_client import TradeClient; import ssl"],
                           check=True, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            fail("deployed Python dependency check failed; source is unchanged, and the partial deployment is retained for inspection")
        deployed_values = dict(values, private_dir=private, config=private / "config.json",
                               cert=private / "server.pem", key=private / "server.key",
                               market_env=private / "market.env", python=deployed_python)
        assert_launch_paths_accessible(deployed_values, scripts)
        review = private / f".{LABEL}.dry-run.plist"
        review.write_bytes(plistlib.dumps(plist_for(deployed_values, scripts), fmt=plistlib.FMT_XML, sort_keys=False))
        review.chmod(0o600)
    finally:
        os.umask(old_umask)
    print(f"deployed and dependency-checked: {destination}")
    print(f"review plist: {review}")
    print("Nothing started. Install using this deployment's scripts/manage-local-service.py and private/ paths.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the opt-in TradePilot private gateway launch agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    install_parser = sub.add_parser("install", help="validate and install the per-user launch agent")
    install_parser.add_argument("--private-dir", required=True)
    endpoint = install_parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--address")
    endpoint.add_argument("--hostname")
    install_parser.add_argument("--interface", help="interface to inspect when --hostname is used")
    install_parser.add_argument("--market-env", required=True)
    install_parser.add_argument("--python", required=True)
    install_parser.add_argument("--dry-run", action="store_true", help="write a temporary review plist only")
    install_parser.set_defaults(handler=install)
    deploy_parser = sub.add_parser("deploy", help="copy a stopped gateway to a private launchd-accessible directory")
    deploy_parser.add_argument("--destination", required=True)
    deploy_parser.add_argument("--private-dir", required=True)
    deploy_endpoint = deploy_parser.add_mutually_exclusive_group(required=True)
    deploy_endpoint.add_argument("--address")
    deploy_endpoint.add_argument("--hostname")
    deploy_parser.add_argument("--interface")
    deploy_parser.add_argument("--market-env", required=True)
    deploy_parser.add_argument("--python", required=True)
    deploy_parser.add_argument("--source-stopped", action="store_true")
    deploy_parser.add_argument("--dry-run", action="store_true")
    deploy_parser.set_defaults(handler=deploy)
    serve_parser = sub.add_parser("serve", help="discover a concrete interface address and exec the gateway")
    serve_parser.add_argument("--private-dir", required=True)
    serve_endpoint = serve_parser.add_mutually_exclusive_group(required=True)
    serve_endpoint.add_argument("--address")
    serve_endpoint.add_argument("--hostname")
    serve_parser.add_argument("--interface", help="required with --hostname")
    serve_parser.add_argument("--market-env", required=True)
    serve_parser.add_argument("--python", required=True)
    serve_parser.set_defaults(handler=serve)
    sub.add_parser("status", help="show load state and safe operational metadata").set_defaults(handler=status)
    remove_parser = sub.add_parser("remove", aliases=["uninstall"], help="unload and move this agent plist to a recoverable backup")
    remove_parser.set_defaults(handler=remove)
    args = parser.parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
