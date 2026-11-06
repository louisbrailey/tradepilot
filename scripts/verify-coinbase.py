#!/usr/bin/env python3
"""Verify the read-only Coinbase accounts call using the private gateway config.

Usage: <gateway venv python> scripts/verify-coinbase.py /path/to/private/config.json
Prints a summary only. It never prints key names, private keys or tokens.
"""
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from coinbase_service import CoinbaseAdapter, CoinbaseError  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("usage: verify-coinbase.py CONFIG_JSON", file=sys.stderr)
        return 2
    config = Path(sys.argv[1])
    if config.stat().st_mode & 0o077:
        print("FAIL: config must have permissions 600", file=sys.stderr)
        return 2
    values = json.loads(config.read_text())
    # Match the gateway's egress choice; an IP-allowlisted key fails over IPv6.
    os.environ["COINBASE_IPV4_ONLY"] = values.get("COINBASE_IPV4_ONLY", "")
    adapter = CoinbaseAdapter(values.get("COINBASE_API_KEY_NAME"), values.get("COINBASE_API_PRIVATE_KEY"))
    if not adapter.configured:
        print("FAIL: COINBASE_API_KEY_NAME / COINBASE_API_PRIVATE_KEY not set in config")
        return 1
    try:
        state = adapter.state()
    except CoinbaseError as exc:
        print(f"FAIL: {exc.code}: {exc}")
        return 1
    accounts = state["accounts"]
    funded = [a for a in accounts if Decimal(a["total"]) != 0]
    print(f"OK: authenticated read-only call succeeded; {len(accounts)} accounts, {len(funded)} with a balance")
    for a in sorted(funded, key=lambda a: a["currency"]):
        print(f"  {a['currency']:<8} total={a['total']} available={a['available']} hold={a['hold']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
