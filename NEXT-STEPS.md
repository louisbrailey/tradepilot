# Release scope and remaining work

See [LATEST-STATUS.md](LATEST-STATUS.md) for dated verification and [tasks/todo.md](tasks/todo.md) for the acceptance checklist. Earlier device, Developer Mode, LAN pairing, Webull authentication and Coinbase authentication blockers have been resolved.

## Supported local app

- Physical iPhone installation with a certificate-pinned private Mac gateway.
- Webull account holdings/balances and Coinbase View-only asset balances.
- Explicitly confirmed paper trading with a durable ledger and journal.
- Local AI, Massive research, fixed strategy comparisons and Kronos historical replay.
- Sample portfolio and demo assistant kept visibly separate from real account data.

Broker write functionality in source is not production-qualified by these read-only checks. Live trading, cancellation and transfers remain disabled in the current deployment. The Coinbase key has no Trade or Transfer grants. No strategy has qualified for live adoption.

## Operational requirements

The Mac must remain awake and reachable on the phone's LAN. A changing public IPv4 requires an update to the Coinbase key allowlist. A changing local hostname requires deliberate TLS re-pairing. The user chose to keep the local development app. Its current signing profile expires November 11, 2026 at 00:35 Pacific; refresh signing and reinstall before then. The gateway TLS certificate also has finite validity and needs renewal before expiration. See [LOCAL-SERVICE.md](LOCAL-SERVICE.md), [COINBASE-SETUP.md](COINBASE-SETUP.md) and the latest release report.

## Further product scope

These are separate features or external integrations, not completed by installing this release:

| Work | What remains |
| --- | --- |
| Fidelity account data | Supported provider integration, entitlement and separately approved account connection. No retail trading endpoint is invented. |
| Always-on remote access | Hosting/network design and a reviewed deployment; the current gateway is local to the Mac. |
| Automated prospective paper strategies | Explicit strategy/schedule, independent data-quality gates and prospective evaluation. The existing paper account is manually confirmed. |
| Additional strategy families | Appropriate dividend, FX, intraday or options data plus preregistered evaluation; no tuning observed holdouts into a success claim. |
| Live crypto/options/short execution | Product-specific contracts, provider entitlement, risk controls and independently verified execution evidence before any enablement. |
| App Store/TestFlight distribution | Distribution signing and the applicable Apple account/review requirements. Current installation is a signed development build. |

Do not substitute mocked tests, historical returns or a successful login for these acceptance criteria.
