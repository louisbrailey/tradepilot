#!/usr/bin/env python3
"""Keep the development-signed TradePilot app installable on the owner's iPhone.

Free Apple development signing expires after seven days. Installed as a per-user launch
agent, this checks hourly and, when the TradePilot provisioning profile is within two days
of expiring (or has expired) and the iPhone is reachable over USB or Wi-Fi, builds the
committed `main` branch with a fresh profile and installs it. It never copies a pairing
file, never touches gateway data, and does not launch the app.

  install --device UDID   write and load the launch agent
  remove                  unload it and keep its log and state
  status                  show the agent, the profile expiry and the last install
  run [--force]           one check now (the agent runs this hourly)
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

LABEL = "com.tradepilot.keep-signed"
BUNDLE_ID = "com.louisbrailey.TradePilot"
REPO = Path(__file__).resolve().parent.parent
STATE_DIR = Path.home() / "Library" / "Application Support" / "TradePilot" / "keep-signed"
PROFILES = Path.home() / "Library" / "Developer" / "Xcode" / "UserData" / "Provisioning Profiles"
REFRESH_WITHIN = 48 * 3600
DEVELOPER_DIR = "/Applications/Xcode.app/Contents/Developer"
BUILD_ROOT = Path("/private/tmp")  # outside synced folders, as for manual iPhone builds


def log(message: str) -> None:
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", flush=True)


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def read_profile(path: Path) -> dict | None:
    result = subprocess.run(["security", "cms", "-D", "-i", str(path)], capture_output=True, timeout=30)
    if result.returncode:
        return None
    try:
        return plistlib.loads(result.stdout)
    except Exception:
        return None


def app_profiles(directory: Path | None = None) -> list[tuple[Path, float]]:
    """TradePilot development profiles with their expiry as epoch seconds, latest expiry first."""
    directory = PROFILES if directory is None else directory
    found = []
    for path in directory.glob("*.mobileprovision") if directory.is_dir() else []:
        data = read_profile(path)
        identifier = (data or {}).get("Entitlements", {}).get("application-identifier", "")
        expires = (data or {}).get("ExpirationDate")
        if identifier.endswith("." + BUNDLE_ID) and isinstance(expires, datetime):
            found.append((path, expires.replace(tzinfo=expires.tzinfo or timezone.utc).timestamp()))
    return sorted(found, key=lambda item: -item[1])


def device_reachable(device: str) -> bool:
    result = subprocess.run(["xcrun", "devicectl", "list", "devices"], capture_output=True, text=True, timeout=120)
    return any(device in line and " connected " in f" {line} " and "physical" in line for line in result.stdout.splitlines())


def needs_refresh(expiry: float | None, now: float) -> bool:
    return expiry is None or expiry - now <= REFRESH_WITHIN


def load_state() -> dict:
    try:
        return json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = STATE_DIR / "state.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2))
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def export_main(destination: Path) -> str:
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "main"], capture_output=True, text=True,
                            check=True).stdout.strip()
    archive = subprocess.run(["git", "-C", str(REPO), "archive", "--format=tar", commit], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive.stdout, check=True)
    return commit


def build_and_install(device: str, source: Path, derived: Path) -> Path:
    environment = {**os.environ, "DEVELOPER_DIR": os.environ.get("DEVELOPER_DIR", DEVELOPER_DIR)}
    build = subprocess.run(["xcodebuild", "-project", str(source / "iOS" / "TradePilot.xcodeproj"), "-scheme", "TradePilot",
                            "-destination", f"id={device}", "-derivedDataPath", str(derived),
                            "-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration", "build"],
                           capture_output=True, text=True, env=environment, timeout=3600)
    if build.returncode:
        raise RuntimeError("xcodebuild failed: " + (build.stdout + build.stderr)[-1500:])
    app = derived / "Build" / "Products" / "Debug-iphoneos" / "TradePilot.app"
    if not app.is_dir():
        raise RuntimeError("build finished without TradePilot.app")
    install = subprocess.run(["xcrun", "devicectl", "device", "install", "app", "--device", device, str(app)],
                             capture_output=True, text=True, env=environment, timeout=900)
    if install.returncode:
        raise RuntimeError("install failed: " + (install.stdout + install.stderr)[-1500:])
    return app


def run(device: str, force: bool = False, now: float | None = None) -> str:
    now = time.time() if now is None else now
    profiles = app_profiles()
    expiry = profiles[0][1] if profiles else None
    if not force and not needs_refresh(expiry, now):
        return "profile valid for another %.1f days; nothing to do" % ((expiry - now) / 86400)
    retry_after = load_state().get("retry_after", 0)
    if not force and expiry is not None and expiry > now and now < retry_after:
        return "Apple returned the current profile last time; waiting to retry"
    if not device_reachable(device):
        return "iPhone not reachable over USB or Wi-Fi; will retry"
    backup = STATE_DIR / "profile-backup"
    backup.mkdir(mode=0o700, parents=True, exist_ok=True)
    moved = []
    for path, _ in profiles:  # Xcode requests a new profile when no local copy remains.
        target = backup / path.name
        shutil.move(str(path), str(target))
        moved.append((target, path))
    with tempfile.TemporaryDirectory(prefix="tradepilot-sign-", dir=BUILD_ROOT if BUILD_ROOT.is_dir() else None) as folder:
        source, derived = Path(folder) / "source", Path(folder) / "derived"
        source.mkdir()
        try:
            commit = export_main(source)
            build_and_install(device, source, derived)
        except Exception:
            for saved, original in moved:
                if not original.exists():
                    shutil.move(str(saved), str(original))
            raise
    for saved, _ in moved:
        saved.unlink(missing_ok=True)
    renewed = app_profiles()
    new_expiry = renewed[0][1] if renewed else None
    # If Apple handed back the same profile, retry in 12 hours (or right after it expires).
    unchanged = new_expiry is not None and expiry is not None and new_expiry <= expiry + 60
    save_state({"device": device, "installed_commit": commit, "installed_at": now,
                "profile_expires_at": new_expiry, "previous_expiry": expiry,
                "retry_after": min(expiry, now + 12 * 3600) if unchanged else 0})
    when = datetime.fromtimestamp(new_expiry).astimezone().strftime("%b %d %H:%M %Z") if new_expiry else "unknown"
    return f"installed {commit[:12]}; profile now expires {when}"


def plist(device: str) -> dict:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(Path(__file__).resolve()), "run", "--device", device],
        "StartInterval": 3600, "RunAtLoad": True, "ProcessType": "Background", "LowPriorityIO": True,
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "DEVELOPER_DIR": DEVELOPER_DIR},
        "StandardOutPath": str(STATE_DIR / "keep-signed.log"), "StandardErrorPath": str(STATE_DIR / "keep-signed.log"),
    }


def install(device: str) -> None:
    destination = agent_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(plistlib.dumps(plist(device)))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    result = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(destination)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit("error: launchctl bootstrap failed: " + result.stderr.strip())
    print(f"Loaded {LABEL}; it checks hourly. Log: {STATE_DIR / 'keep-signed.log'}")


def remove() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    if agent_path().exists():
        agent_path().rename(agent_path().with_suffix(".plist.removed"))
    print(f"Unloaded {LABEL}; log and state kept in {STATE_DIR}")


def status() -> None:
    loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True).returncode == 0
    profiles = app_profiles()
    state = load_state()
    print(f"{LABEL}: {'loaded' if loaded else 'not loaded'}")
    if profiles:
        print("profile expires:", datetime.fromtimestamp(profiles[0][1]).astimezone().strftime("%Y-%m-%d %H:%M %Z"))
    if state:
        print("last install:", state.get("installed_commit", "")[:12],
              datetime.fromtimestamp(state["installed_at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("install", "remove", "status", "run"))
    parser.add_argument("--device", help="iPhone UDID from `xcrun devicectl list devices`")
    parser.add_argument("--force", action="store_true", help="refresh even if the profile is not close to expiry")
    args = parser.parse_args()
    if args.command in ("install", "run") and not args.device:
        parser.error("--device is required")
    if args.command == "install":
        install(args.device)
    elif args.command == "remove":
        remove()
    elif args.command == "status":
        status()
    else:
        try:
            log(run(args.device, force=args.force))
        except Exception as error:
            log(f"refresh failed: {error}")
            sys.exit(1)


if __name__ == "__main__":
    main()
