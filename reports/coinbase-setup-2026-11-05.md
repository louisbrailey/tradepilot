# Coinbase read-only setup — November 5, 2026

## Authorization and outcome

The user approved creation and private gateway storage of a View-only ECDSA key for the Primary portfolio. SMS verification completed using the user's iPhone 16 Pro through iPhone Mirroring. The key is restricted to the gateway's current public IPv4. Private material, account identifiers and balances are excluded from this report and Git.

The key and private configuration are owner-only files in the existing `gateway-20260923` deployment. Prior config and the two changed deployed modules were retained in `private/coinbase-setup-backup-20261105`. Only the TradePilot launch agent was restarted. Existing Webull credentials, phone pairing and other services were preserved.

## Routing correction

Default IPv6 egress returned Coinbase HTTP 401 because the key allows only the gateway's public IPv4. A bounded IPv4 read established the cause. `COINBASE_IPV4_ONLY=enabled` now selects a connection-local IPv4 source address for Coinbase, without modifying global DNS or socket behavior. The original hostname is retained for SNI and certificate verification. Proxy routing is disabled for this opt-in transport so a proxy cannot change the allowed egress. No IPv6 fallback or certificate bypass is introduced.

## Verification

- All 18 Coinbase unit tests pass with the gateway interpreter, including real temporary-key signing and new transport tests using fake sockets.
- The full backend suite passes: 205 tests, no skips, using the deployed Python interpreter. Log: `.toolkit-runs/20261106T022328.074041Z.log`.
- The first full run failed on an existing HTTP-error fixture with a null response body under Python 3.9. Replacing that fixture body with `BytesIO` preserves the redaction check and verifies closure. The default Python run also passed 205 tests with one optional signing skip before the fixture correction.
- Authenticated gateway POST requests over verified hostname TLS and exact paired certificate returned HTTP 200 for `/v1/setup`, `/v1/coinbase/state`, and `/v1/coinbase/capabilities`.
- Provider permission metadata confirms View true, Trade false and Transfer false. Gateway trading, cancellation and transfer flags are all false. Account read returned 26 asset accounts.
- Mirroring returned to the USB iPhone 16 with TradePilot installed. Accounts → Coinbase accounts and actions → Load Coinbase accounts displayed the updated asset balances at 6:26 PM. Private screenshot: `.toolkit-runs/coinbase-phone-20261105.png` (excluded from Git).

These were authorized production reads for setup, separate from hermetic tests. No order, cancellation or transfer was submitted. Balances are native asset quantities, not a portfolio valuation. The Mac must stay awake and reachable on the phone's LAN. A changed public IPv4 requires a corresponding key-allowlist update.
