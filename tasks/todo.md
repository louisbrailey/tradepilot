# Remaining work acceptance checklist

- [x] Paper ledger: durable accounting, explicit confirmation, retry/concurrency safety, quote provenance and valuation history verified.
- [x] Strategy comparison: three fixed families, no-lookahead and accounting checks, real-cache report with known-history label.
- [x] Coinbase: strict read-only account API and native table; malformed responses/pagination/signature tested.
- [x] Gateway routes: authenticated exact payloads, no client-price or arbitrary-file access, connection-bound native responses.
- [x] iOS: paper review/history and strategy results accessible; native builds pass and simulator launches. (Builds and simulator end-to-end paper flow re-verified 2026-10-26.)
- [x] Private gateway deploy preserves authoritative state; authenticated health check succeeds. (Matching production source deployed November 4; old code retained, pinned-TLS authenticated setup HTTP 200 and phone connection verified.)
- [x] Saved release notes, installation status and continuity checkpoint. (reports/review-2026-10-26/RELEASE-NOTES.md, DEVICE-CONNECTION-REPORT.md, codex-recall checkpoint 2026-10-26.)
- [x] October 26 baseline independently reviewed by Claude; see reports/review-2026-10-26/REVIEW.md. Later changes have their own dated validation; this is not a claim of an independent review of every subsequent revision.
- [x] Physical iPhone signed, installed, launched and paired. (USB iPhone 16, Developer Mode enabled; direct Mirroring checks November 4 documented in reports/phone-verification-2026-11-04.md.)
- [x] Real Webull account connectivity: physical iPhone account list, portfolio and balances loaded November 4 using existing production authorization; live trading remains disabled.
- [x] Real Coinbase account connectivity: View-only provider permissions, authenticated pinned-TLS gateway reads and physical-phone balances verified November 5. See reports/coinbase-setup-2026-11-05.md.
- [x] Version 0.2.0 account screens, connection status and demo separation rebuilt, installed and checked on the physical iPhone. See reports/release-0.2.0-2026-11-05.md.

- [x] Automated paper version 1: three frozen SPY protocols, independent simulated accounts, background scheduling, data/drawdown stops, durable evidence, phone controls and first forward observation verified November 5.
- [x] Observe the first future-session settlement. All three runs recorded November 6, 2026. The mean reversion strategy settled its first simulated fill and the other two remained in cash.
- [x] Markets tab, quote pages, price alerts and current-session paper prices (0.5.0): full gate, live read-only data smoke and simulator checks. See reports/release-0.5.0-2026-11-06.md.
- [x] Deploy 0.5.0 gateway code to the Mac with `scripts/update-local-gateway.py apply` (owner-approved; backup `code-backup-update-20261106-200945`; health check passed).
- [x] Install 0.5.0 (build 6) on the USB iPhone 16 (devicectl confirms the version).
- [x] iOS 27.2 setup finished on the iPhone; TradePilot 0.5.0 launched there on November 7, 15:07 PT (iOS accepts the signing).
- [ ] With the Mac and iPhone on the same Wi-Fi, open TradePilot on the phone and check Markets, a quote page, an alert notification and Coinbase values on the device.
- [ ] Sign in to Xcode (Settings → Accounts) with the Apple ID for team ANWNGW59GP so `com.tradepilot.keep-signed` can renew signing before November 11, 00:35 PT.
- [x] Deploy the Coinbase USD pricing route (`/v1/market/crypto`) with `scripts/update-local-gateway.py apply` (owner-approved; deployed November 7, 14:57 PT).
- [ ] Accumulate enough prospective observations to evaluate each frozen paper strategy.
- [ ] Stage and verify the gateway on the home PC, then move the active ledger and pair the iPhone. See [home PC setup](../HOME-PC.md).

Follow-on product scope retained explicitly: Fidelity supported data access, live crypto/options/short execution, dividend/FX/intraday strategy implementations with appropriate data, broader/custom strategy automation, prospective evaluation, and remote always-on infrastructure. Do not mark these complete from exploratory research or a manual paper ledger.
