# Resume TradePilot

Start with [LATEST-STATUS.md](LATEST-STATUS.md), [NEXT-STEPS.md](NEXT-STEPS.md) and the repository instructions. Canonical source is `/Users/louisbrailey/Projects/tradepilot`; the private repository is `louisbrailey/tradepilot`.

The app is installed on the USB-connected iPhone 16 named “louis’s iPhone.” The separate iPhone 16 Pro named “my iphone” receives the Coinbase verification SMS. Verify device identity before installing or using Mirroring. Both Webull and Coinbase read access have been verified on the installed app. Coinbase is View-only; broker writes remain disabled.

The deployed gateway is `/Users/louisbrailey/Library/Application Support/TradePilot/gateway-20260923`, managed by `com.tradepilot.private-gateway`. Credentials, pairing and authoritative ledgers live in its private directory, outside Git. Do not start a second gateway or replace current durable state with an older copy. Coinbase uses the optional IPv4 route to match its key allowlist. Native Ollama uses the configured IPv6 loopback route.

Use `devkit context` and `devkit run -- bash scripts/check.sh`. Build signed iPhone artifacts into `/private/tmp` to avoid cloud-file metadata. `scripts/install-iphone.sh DEVICE_ID` updates the app without changing pairing; supply the owner-only pairing file only when importing or deliberately re-pairing. Use `scripts/manage-local-service.py status` to inspect the launch agent.

Preserve unrelated untracked `.worktrees/` and `scripts/verify-coinbase.py`. Logs and private screenshots belong in ignored `.toolkit-runs/`, never commits. Separate real setup reads from fake-provider automated tests. Historical strategy results do not authorize live trading.
