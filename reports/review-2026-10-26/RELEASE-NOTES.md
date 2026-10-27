# TradePilot — October 26, 2026 release notes

Source range `3f0aa5f..` on `main`. Full detail in [REVIEW.md](REVIEW.md).

## Fixed

- A filled paper order could be shown and confirmed again after a lost confirmation response; the gateway now refuses a confirmed `client_id` and the app rotates its id.
- One idle TCP connection could stall the TLS gateway; handshakes now run on the request thread under a timeout.
- Paper orders were refused the day after a Monday holiday; bars are now stamped at the 16:00 ET close.
- Webull confirmation ignores double taps.
- Demo and research replies are discarded if the connection changed while they were in flight.
- AI-proposed quantities must match `^[0-9]+(\.[0-9]+)?$`.
- `manage-local-service.py` accepts only `en0`–`en99`, matching the gateway.
- `scripts/install-iphone.sh` checks the phone with `devicectl` first (physical device, Developer Mode on) and refuses a pairing file that is a symlink or readable by other users. Launchd serve-path errors are timestamped.

## Verification

13 core checks, 160 backend tests (one Coinbase ES256 signing test skipped on system Python; passes with the gateway venv), 40 script tests, Swift smoke checks, both native builds. Simulator end-to-end paper flow passed against an isolated gateway running the deployed code.

## Deployment

Deployed in place to `gateway-20260923` (matches `7ab6207`; previous code in `private/code-backup-20261026`). Re-paired for `louiss-macbook-pro-7.local`, certificate valid until 2027-01-24, token unchanged. No live request has been served yet: the Mac is not on the home LAN.

## Not included

Physical iPhone install (phone paired; Developer Mode off), real Webull or Coinbase access, live order submission (still disabled by default), Webull MARKET cost-tolerance decision.
