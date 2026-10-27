# Remaining work

See LATEST-STATUS.md for completed evidence.

External dependencies: the iPhone is paired with Xcode but Developer Mode must be turned on on the phone before `scripts/install-iphone.sh` can build to it; the Mac must be on the home LAN (a private IPv4 on en0) for the deployed gateway to start, after which the phone imports the 2026-10-26 `TradePilotPairing.json`; the existing Webull account must complete authenticated mobile API access. These cannot be replaced by running another model or an Android VM. Source and installation helper are ready when those conditions change.

Then verify real read-only portfolio and provider preview, perform prospective paper execution/reconciliation, and assess evidence before enabling real submissions. Do not treat mocked broker tests or historical returns as live verification.

Further implementation: Coinbase/Fidelity account adapters, tested strategies beyond the current SMA, continuous prospective paper ledger, and remote hosting if required. Current Mac gateway requires awake Mac and same LAN. No background trading or strategy promotion is enabled.
