# Release scope and remaining work

See [LATEST-STATUS.md](LATEST-STATUS.md) for dated verification and [tasks/todo.md](tasks/todo.md) for the acceptance checklist. Earlier device, Developer Mode, LAN pairing, Webull authentication and Coinbase authentication blockers have been resolved.

## Supported local app

- Physical iPhone installation with a certificate-pinned private Windows gateway over Tailscale.
- Webull account holdings/balances and Coinbase View-only asset balances.
- Explicitly confirmed manual paper trading with a durable ledger and journal.
- Three fixed automated SPY paper experiments with a separate scheduler, portfolios and data/risk stops; see [AUTOMATED-PAPER.md](AUTOMATED-PAPER.md).
- Local AI, Massive research, fixed strategy comparisons and Kronos historical replay.
- Markets with a watchlist, index ETFs, large-cap movers, symbol search, quote pages and gateway-checked price alerts.
- Sample portfolio and demo assistant kept visibly separate from real account data.

Broker write functionality in source is not production-qualified by these read-only checks. Live trading, cancellation and transfers remain disabled in the current deployment. The Coinbase key has no Trade or Transfer grants. No strategy has qualified for live adoption.

## Operational requirements

The home PC must stay powered and reachable on Tailscale. The Mac can sleep during normal iPhone use. Local development signing renewal still needs the Mac and a reachable iPhone, and the gateway certificate needs renewal before it expires. See [HOME-PC.md](HOME-PC.md) and [LATEST-STATUS.md](LATEST-STATUS.md).

## Further product scope

These are separate features or external integrations, not completed by installing this release:

| Work | What remains |
| --- | --- |
| Fidelity account data | Supported provider integration, entitlement and separately approved account connection. No retail trading endpoint is invented. |
| PC availability before Windows login | The phone is connected to the deployed PC over Tailscale. A controlled startup with no interactive login is still required for pre-login verification. |
| Prospective evaluation and broader automation | The three fixed SPY runs have six observations each and stopped after one missed session. A fresh, explicitly started paper cohort and enough future observations are needed for evaluation. Custom universes and schedules require separate design. |
| Additional strategy families | Appropriate dividend, FX, intraday or options data plus preregistered evaluation; no tuning observed holdouts into a success claim. |
| Live crypto/options/short execution | Product-specific contracts, provider entitlement, risk controls and independently verified execution evidence before any enablement. |
| App Store/TestFlight distribution | Distribution signing and the applicable Apple account/review requirements. Current installation is a signed development build. |

Do not substitute mocked tests, historical returns or a successful login for these acceptance criteria.
