# TradePilot Claude review — October 26, 2026

This is the independent Claude review requested in [the September 23 handoff](../review-2026-09-23/CLAUDE-HANDOFF.md). It covers the source at `3f0aa5f`. Two read-only reviewers looked at the code: one at the gateway (`server/`, the service and strategy scripts), the other at the iOS app and `Core/`. Every confirmed finding was reproduced against fake data, then fixed and covered by a regression test. Each new test fails against the unfixed code. No broker, real account or deployed gateway was contacted.

## Fixed

1. **A filled paper order could be shown and confirmed again.** Requesting a review again with a `client_id` that was already confirmed returned the stored review with `status: REVIEW` and a live token. The app reused the same `client_id` when a confirmation response was lost and the sheet was then swiped away. The user would see a fresh confirmation, the app would journal a second `paper_fill`, and the ledger would not change.
   - **Gateway:** `paper_service.create_review` now refuses a confirmed `client_id`.
   - **App:** `WorkspaceViews` now generates a new `client_id` when the sheet is dismissed and when a confirmation is attempted. Retries still use the review's id and token.
2. **One idle TCP connection could stall the TLS gateway.** The listening socket did TLS handshakes inside `accept()` on the serve thread, with no timeout. One silent LAN peer could block every request and the network-change restart (`shutdown()`).
   - **Fix:** `server.enable_tls` defers the handshake (`do_handshake_on_connect=False`). `Handler.setup` then performs it on the request thread, under the 45-second timeout. `GatewayHTTPServer.handle_error` drops routine `OSError` handshake failures from the log.
3. **Paper orders were refused all day after a Monday holiday.** `paper_quote` timestamped each bar at midnight, so on Tuesday after Labor Day, Friday's close was 106 hours old, which is beyond the 96-hour freshness limit.
   - **Fix:** the bar is now timestamped at its 16:00 America/New_York close, about 90 hours old in the same case. The window itself is unchanged.
4. **Webull confirmation double-tap hardening.** `WebullView.run` now ignores calls while busy, and `confirm` ignores calls after an attempt. The server was already idempotent, so the only previous effect was duplicate journal entries.

## Checked without finding a defect

- **Paper accounting:** decimal precision, average-cost exits, cash and holdings limits, stale-mark guard, idempotent concurrent confirmation.
- **Webull duplicate prevention:** the state-gated update is committed before `place()`, there is no resubmission from UNKNOWN or SUBMITTING, the live gate is checked at confirm time, and orders are bound to account and environment.
- **Execution ledger monotonicity.**
- **Gateway authentication:** constant-time bearer check on every route, strict request framing, and no client prices or file paths.
- **Strategy no-lookahead:** signals use closes `[i-50, i)` and fills happen at the open of bar `i`.
- **Coinbase:** JWT claims and pagination guards are correct. The ES256 test passes with the gateway's interpreter.
- **Kronos:** isolation and holdout boundaries hold.
- **iOS:**
  - TLS leaf pinning holds.
  - Each response is tied to the connection that requested it.
  - Swift 6 actor isolation holds.
  - Live trading stays off by default.

## Open, not fixed (low impact or needs a decision)

- **Webull MARKET confirmations may be refused.** `webull_service.confirm` compares `estimated_cost` for exact equality against a fresh preview. While the market is open, MARKET confirmations may therefore usually be refused. This fails safe, but it needs a real sandbox preview to decide.
- **Splits are not modeled.** A split between a paper buy and a mark would show a false drawdown, because marks use unadjusted closes. This limitation is already documented.

## Follow-up fixes (same day)

- **Connection binding:** the demo `askAI` reply and the `JournalView` research text are now discarded if the connection changed during the request. Research text is cleared when the connection changes.
- **Strict quantities:** AI-proposed quantities must match `^[0-9]+(\.[0-9]+)?$` before decimal parsing.
- **Interface names:** `manage-local-service.py` now accepts only `en0`–`en99`, matching `server.py`.

## Verification

| Check | Result |
|---|---|
| `scripts/check.sh` | 13 core, 159 backend (1 signing test skipped on system Python), 36 script tests; all Swift smoke checks pass. Log: `.toolkit-runs/20261026T230327.747172Z.log` |
| Coinbase ES256 signing with gateway venv interpreter | 15/15 pass |
| `xcodebuild` iOS Simulator and unsigned `generic/platform=iOS` | Both succeed |

## Deployment state observed (read-only)

- **Gateway is down.** The deployed gateway at `~/Library/Application Support/TradePilot/gateway-20260923` matched the source before these fixes. It has been restarting repeatedly (about 1,800 launchd runs) because `en0` has no usable private IPv4 address. The Mac is currently on a network that gives only `192.0.0.2`.
- **The pairing hostname is stale.** The iPhone pairing targets `louiss-macbook-pro-6.local`, but macOS now names the Mac `louiss-MacBook-Pro-7`. The app cannot reach the gateway until the hostname is restored or the app is re-paired.
- **Fixes deployed later the same day.** The deployed `server/` and `scripts/manage-local-service.py` files now match `7ab6207`; the previous code is in `private/code-backup-20261026`. The repository's backend tests pass against the deployed modules with the gateway's interpreter. Six evaluation tests could not run outside the repository layout because they need `BACKTEST-SUMMARY.json`. No live request has been served yet, because the Mac has no LAN address.
