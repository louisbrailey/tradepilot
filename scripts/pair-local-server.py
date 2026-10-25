"""Create private TLS and iPhone pairing files. Run with the backend virtualenv."""
from __future__ import annotations

import argparse
import base64
import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import tempfile


def certificate_material(address, hostname: str | None) -> tuple[bytes, bytes, bytes]:
    """Generate material in memory so dependency or signing failures write nothing."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise SystemExit("Run pairing with the backend virtualenv Python; cryptography is required.") from None
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TradePilot private gateway")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=90))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(address)] + ([x509.DNSName(hostname)] if hostname else [])), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()),
            cert.public_bytes(serialization.Encoding.PEM), cert.public_bytes(serialization.Encoding.DER))


def create_pairing(private_dir: str, address: str, hostname: str | None = None) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        raise SystemExit("Use a literal private local-network address.") from None
    if ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_multicast or not ip.is_private:
        raise SystemExit("Use a specific private local-network address.")
    if hostname:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.local", hostname, re.IGNORECASE):
            raise SystemExit("Use a single-label .local hostname.")
        hostname = hostname.lower()
    root = Path(private_dir).expanduser()
    if not root.is_absolute():
        raise SystemExit("Private directory must be an absolute path.")
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise SystemExit("Private directory must be an ordinary directory.")
    if root.exists() and root.stat().st_mode & 0o077:
        raise SystemExit("Existing private directory must be owner-only (chmod 700) before pairing.")
    root = root.resolve()
    configfile = root / "config.json"
    keyfile, certfile, pairfile = (root / name for name in ("server.key", "server.pem", "TradePilotPairing.json"))
    # Refuse reruns before reading or rewriting existing private configuration.
    if any(path.exists() or path.is_symlink() for path in (keyfile, certfile, pairfile)):
        raise SystemExit("TLS or pairing files already exist. Preserve them; renew and re-pair deliberately.")
    if configfile.is_symlink() or (configfile.exists() and not configfile.is_file()):
        raise SystemExit("Private config must be an ordinary file.")
    if configfile.exists() and configfile.stat().st_mode & 0o077:
        raise SystemExit("Existing private config must be owner-only (chmod 600) before pairing.")
    try:
        config = json.loads(configfile.read_text()) if configfile.exists() else {}
        if not isinstance(config, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in config.items()):
            raise ValueError("invalid config")
    except (OSError, ValueError):
        raise SystemExit("Private config must be a JSON object containing string values.") from None
    config.setdefault("APP_ACCESS_TOKEN", secrets.token_urlsafe(48))
    if len(config["APP_ACCESS_TOKEN"]) < 32:
        raise SystemExit("Existing APP_ACCESS_TOKEN must contain at least 32 characters; it was not changed.")
    config.setdefault("WEBULL_LIVE_TRADING", "disabled")
    config.setdefault("TRADEPILOT_RUNTIME", str(root / "runtime"))
    key, cert, der = certificate_material(ip, hostname)
    host = hostname or (f"[{ip}]" if ip.version == 6 else str(ip))
    pair = {"endpoint": f"https://{host}:8787", "token": config["APP_ACCESS_TOKEN"],
            "certificate": base64.b64encode(der).decode()}
    old_umask = os.umask(0o077)
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path, content in ((keyfile, key), (certfile, cert), (pairfile, json.dumps(pair).encode())):
            # Exclusive creation refuses both existing files and dangling symlinks.
            with path.open("xb") as handle:
                handle.write(content)
        fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=root)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(config, handle, indent=2)
            os.replace(temporary, configfile)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    finally:
        os.umask(old_umask)
    print("Created private TLS and device-pairing files. Keep the directory outside source archives.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--hostname", help="Optional stable mDNS hostname, such as My-Mac.local")
    args = parser.parse_args()
    create_pairing(args.private_dir, args.address, args.hostname)


if __name__ == "__main__":
    main()
