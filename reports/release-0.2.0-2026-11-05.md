# TradePilot 0.2.0 local release

Version 0.2.0, build 2, was signed, installed and launched on the USB-connected iPhone 16 on November 5, 2026. Existing pairing and application data were retained. The user chose to keep the local development installation rather than pursue distribution signing now.

## Changes

- Overview, Holdings and Accounts lead to real provider connections. Fictional balances and demo controls are inside labeled disclosures; paper trading remains a separate saved simulation.
- Webull balances use named rows with an explicitly supplied currency. Missing or invalid provider fields do not become invented values; raw provider details remain available.
- Coinbase balances use vertical asset cards and an optional zero-balance filter. The filter preserves tiny nonzero amounts, amounts on hold and malformed values rather than hiding them.
- Coinbase permissions and order history are available without opening transaction controls. Review/confirmation availability requires matching production portfolio, supported portfolio type, provider grants and gateway enablement. Server enforcement remains unchanged.
- Accounts → Gateway connection & AI contains saved connection controls, setup status and AI selection. Coinbase configuration is reported separately; configuration does not imply successful provider access. Old gateways without the Coinbase setup field remain compatible. Connection changes clear stale setup results.
- The connection guide, current status and remaining-work documents reflect the implemented app rather than old installation/authentication blockers.

## Verification

The final full gate passed: 13 deterministic core tests, 205 backend tests (one optional cryptography/signing test skipped under the default interpreter), 41 script tests, Swift 6 typechecking, journal/connection smoke checks and native paper fixtures. The 205 backend tests, including signing, also passed under the deployed interpreter during the preceding Coinbase setup; no backend source changed in this release.

New fixture checks cover the provider/gateway permission matrix, portfolio binding/types, precise zero filtering, explicit-currency Webull summaries and legacy/current setup decoding. The first gate attempt overlapped a source edit and failed with “input file was modified during the build”; the final gate ran against stable source and passed.

Local gate evidence: `.toolkit-runs/20261106T024642.945385Z.log`. Signed device build: `.toolkit-runs/20261106T024652.633504Z.log`. `devicectl` confirmed installation and launch of `com.louisbrailey.TradePilot` on the existing USB phone.

Direct iPhone Mirroring checks verified:

- New home, account navigation and real/sample holdings separation.
- Retained private gateway pairing and successful authenticated connection check, including Coinbase configuration and disabled Webull order submission.
- Webull account selection, refreshed balances with five labeled USD rows, and the empty-holdings state.
- Coinbase balance load: 3 nonzero asset accounts out of 26; toggling zero balances shows all 26 and toggling back restores the filtered view.
- Coinbase permissions: View granted, Trade/Transfer absent; server writes disabled. Existing account order history loaded successfully.
- Paper account navigation and its previously saved ledger loaded; no new paper fill or valuation update was requested.

Private screenshots are retained only in ignored `.toolkit-runs/release-020-{home,coinbase,permissions,webull,setup}.png`. Financial balances and credentials are not included in the committed report. No real order, cancellation or transfer was submitted. Local AI, research, strategy and Kronos behavior was previously checked on November 4; those workflows were not represented as freshly re-run by this UI release.

## Operating limits and remaining scope

The current embedded development provisioning profile expires **November 11, 2026 at 00:35:44 America/Los_Angeles**. Refresh signing and reinstall before then (preferably November 10); this is not an App Store/TestFlight installation. The Mac must be awake and reachable on the phone’s LAN. Coinbase read access also depends on its public IPv4 allowlist; local hostname changes require deliberate pairing maintenance.

The supported local read-only/research/manual-paper release is installed. Fidelity, always-on remote hosting, automated prospective strategies, additional strategy/product families and production-qualified live execution remain separate work described in [NEXT-STEPS](../NEXT-STEPS.md). Live submission and transfers remain disabled, and the Coinbase key has no Trade or Transfer permission. No strategy has qualified for live adoption.
