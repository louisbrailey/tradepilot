# TradePilot 0.5.1 — options-chain review

The read-only options chain is included with corrections found while reviewing the unpublished options feature. No options execution is introduced.

## Corrections

- A requested expiration must be a real date and remain available. The server reports an error instead of substituting the nearest expiration, and the app checks that a response matches the selected date.
- Pagination stops before fetching a page it would discard. Provider cursor queries use the standard URL parser.
- Standard and adjusted option series at the same strike retain separate identities. Contract codes must agree with the reported expiration, side and strike. Malformed identifiers are ignored.
- The contract sheet displays share count and the quote's own timestamp. Missing or negative volume/open interest stays unavailable. A zero ask is treated as unavailable, so it cannot generate a free-contract midpoint estimate. Midpoint contract-premium estimates require matching reference data confirming 100 shares with no additional deliverables; conflicting or unknown terms produce no estimate.
- A newer request owns the loading/error state. A cancelled or late request cannot overwrite a subsequent selection. Refresh reloads expiration choices.

## Verification

- Full repository gate: 13 Core tests, 276 backend tests, 68 script tests, Swift typechecking, journal/connection smoke checks and project validation passed. Log: `.toolkit-runs/20261108T181515.770040Z.log`.
- Later malformed-provider identifier and zero-ask guards add backend regressions: all 278 backend tests passed under the deployed Python 3.9.6. Logs: `.toolkit-runs/20261108T182007.082679Z.log`, `.toolkit-runs/20261108T185307.008474Z.log`.
- The regression cases failed before the implementation changes. The first expanded full gate found two throwing expressions inside nonthrowing Swift test assertions; the assertions were corrected and the full gate passed. Logs: `.toolkit-runs/20261108T180901.798396Z.log`, `.toolkit-runs/20261108T181331.550122Z.log`.
- Read-only source smoke with real market data: AAPL returned 15 upcoming expiration choices and 94 contracts; SPY returned seven choices and 330 contracts. These counts describe that snapshot, not complete historical coverage. The system Python probe could not reach the provider; the deployed Python probe succeeded without weakening TLS. Private result: `.toolkit-runs/options-review-20261108/live-source-smoke.json`.
- Signed simulator build and Device Hub checks: separate adjusted/standard rows, adjusted share count, unavailable activity and premium estimate, standard premium estimate, expiration switching and put selection. The gateway was isolated on loopback with synthetic fixtures and no broker routes or real credentials. An earlier unsigned build displayed the unconfigured-server state; the later signed build loaded the pairing and passed the screen checks. Build log: `.toolkit-runs/20261108T183015.613280Z.log`.
- Signed physical-device build and installation succeeded. Device inventory confirms version 0.5.1, build 7. The install script then exited 1 because iOS refused launch while the phone was locked; installation alone does not verify the new app on the phone. Log: `.toolkit-runs/20261108T182513.085587Z.log`.
- The four frozen automated-paper protocol modules remain byte-identical to the active gateway. Broker confirmation, account binding and live-disabled defaults are preserved.

## Deployment and remaining checks

The gateway update from `90cae8d` was deployed November 8 at 10:41 PT with the approved code-only updater. Backup: `private/code-backup-update-20261108-104125`. Pinned TLS setup, alerts and Markets checks passed. The deployed options route returned HTTP 200 with 94 AAPL contracts carrying the new terms, and returned HTTP 400 for invalid and unavailable expiration dates. Before/after snapshots confirm the same three running paper IDs, balances, observation/fill counts and November 9 next sessions, with live trading disabled. Deployment log: `.toolkit-runs/20261108T184125.038429Z.log`; private checks: `deployed-options-smoke.json`, `before-deployment.json`, `after-deployment.json` under `.toolkit-runs/options-review-20261108/`.

The zero-ask follow-up (`bcc9e18`) was deployed at 10:54 PT, retaining backup `private/code-backup-update-20261108-105416`. Pinned setup, alerts and Markets checks passed again; a final before/after comparison retained all paper state. Log: `.toolkit-runs/20261108T185416.204167Z.log`.

The physical-phone check subsequently passed after repairing the stale paired hostname. Device Hub showed the real Home portfolio, Markets/watchlist, AAPL chart, calls/puts, a 100-share contract's premium and quote timestamp, an expiration change from November 9 to November 11, and three active automated-paper strategies. The resulting display fixes and operational evidence are in [0.5.2](release-0.5.2-2026-11-08.md). The Mac remains the sole paper-ledger writer. Home-PC staging is underway, but no cloud server or ledger cutover was performed. Development signing still expires November 11 at 00:35 PT; automatic renewal requires an Apple ID signed into Xcode.

Provider field references: [option-chain snapshot](https://massive.com/docs/rest/options/snapshots/option-chain-snapshot), [contract reference](https://massive.com/docs/rest/options/contracts/contract-overview). Share count alone does not establish additional deliverables; the implementation requires matching contract-reference data before estimating a standard premium.
