# TradePilot 0.4.0 — interface rebuild and review fixes

Version 0.4.0 (build 4), November 6, 2026. Presentation-layer rebuild of the iPhone app plus fixes from an independent review of the work landed since October 26. Order confirmation, duplicate prevention, account binding and live-disabled defaults are unchanged.

## App

- **Four tabs.** Home (connection status, practice account, recent orders), Accounts (Live: Webull, Coinbase · Paper: paper account, automated strategies · Practice · Settings), Research (strategy lab, forecast replay, market research, recorded backtest) and Journal. The assistant opens as a sheet from Home instead of being a tab. The three screens that previously repeated the broker links are gone.
- **Design system** (`iOS/TradePilot/DesignSystem.swift`): one theme (green/red P/L, amber warnings, a red "Live" badge used only for real accounts), spacing scale, `SectionCard`, `MetricTile`, `HeroMetric`, `HoldingRow`, `StatusBadge` (maps gateway states such as `production`/`REVIEW`/`UNKNOWN` to "Live"/"Awaiting confirmation"/"Unconfirmed"), `InlineNotice`, `EmptyState`, primary/secondary buttons and a single `ConfirmationSheet` with a live countdown used by the practice, paper and Webull order flows.
- **Vocabulary.** Practice (sample engine on the phone), Paper (server simulation), Live (real broker; Sandbox where Webull uses it). "Gateway" and "AI" are gone from user-facing copy; the server is "your server", the model is "the assistant".
- **Formatting.** Currency through `NumberFormatter` with the asset's currency code, signed P/L, relative timestamps, strict decimal parsing of every gateway string (`strictDecimal`), decimal keyboards on number fields, Dynamic Type instead of fixed point sizes.
- **Pull to refresh** on every data screen; raw JSON "provider details", snake_case identifiers, session UUIDs and protocol hashes no longer appear in the UI.
- **Settings** edits the server address and token as drafts and commits on Save, so typing no longer changes the live connection or clears other screens. The reject-next-order test toggle is DEBUG-only.

## Defects fixed (from the review)

- Webull: a cancellation review no longer survives a connection change, a new confirmation or the release of the pending-order lock; the client order id is checked before the recovery lock is written (previous force unwrap).
- Coinbase actions: confirm and reconcile replies must carry the saved action's id; a confirmed review can no longer be re-confirmed without a fresh "Review"; the last-action id is recorded at confirmation, not at review; the transfer destination list excludes the source portfolio.
- Paper: a failed account refresh after a successful fill is reported as such instead of telling the user to retry the confirmation.
- Gateway: `AdmissionError` returns 409 with its message instead of a generic 502; the Webull `cancellation_reviews` table is created at startup; reconciling an `UNKNOWN`/`SUBMITTING` Coinbase limit order that the broker positively identifies as open now records it as `ACCEPTED` so it can be cancelled from the app (test `test_identified_open_order_becomes_accepted_and_cancellable`); `scripts/verify-coinbase.py` honours `COINBASE_IPV4_ONLY` and compares balances numerically; dead `CoinbaseAccess.balance` removed.
- App error messages now show the gateway's `{"error": …}` text and HTTP status instead of fixed strings; `scripts/connection-smoke.swift` no longer crashes when run without a fixtures directory.

## Verification

13 core checks, 223 backend tests (all pass under the gateway interpreter, including signing), 50 script tests, Swift 6 typecheck and both smoke binaries pass (`scripts/check.sh`). Simulator build succeeded and the app was exercised on the iPhone 17 Pro simulator: Home, Accounts, Research, Journal, Webull (error state, since the Mac is off the home LAN), the assistant sheet and a practice order through the new confirmation sheet.

## Deployment

`server/` in `gateway-20260923` now matches this commit (previous files in `private/code-backup-20261106`). The Mac deployment had been left behind the repository: the November 5 shared-inference-lock change to `server.py` and `kronos_service.py` and the `inference_guard.py` module it needs were not on the Mac, so they are deployed now as well; the deployed tree imports cleanly under the gateway interpreter and picks up the change on its next start. The phone still runs 0.3.0; install 0.4.0 with `scripts/install-iphone.sh` when the phone is connected.

## Not verified here

Live Webull and Coinbase screens with real data (no LAN during this session), the physical-phone install of 0.4.0, and the unverified Webull SDK response shapes noted in the review (`settled['commission']`/`fees` fields that release a production admission hold, and `commission_detail_total` in Coinbase previews). Those need a session against the real providers.
