# TradePilot 0.5.2 — physical connection and strategy display

The USB iPhone now reaches the Mac gateway and displays live market data. Physical checks exposed an outdated hostname in the existing pairing and a strategy-card layout that wrapped monetary values and printed raw drawdown decimals.

## Changes

- Strategy metrics use a responsive grid with more room per value. Shared metric values stay on one line with bounded scaling; accessibility text sizes retain a single-column grid.
- Drawdown is displayed to two decimal places. The entry fraction is shown as a percentage, fill/session counts use the appropriate singular/plural form, and labels use the app's existing US spelling.
- Scheduler help refers to the server, so the wording remains accurate when the gateway moves to the home PC.
- App version is 0.5.2, build 8. Execution, confirmation, connection trust and frozen strategy calculations are unchanged.

## Physical and operational evidence

On November 8, Device Hub connected to the correct USB phone with TradePilot foregrounded. Build 7 initially launched but showed a server connection failure. The Mac's hostname had changed; the old name resolved to a USB link-local address instead of the gateway's Wi-Fi listener. An equivalent pairing refresh retained the existing token and exact private configuration, backed up the previous certificate/key/pairing and updated the launch agent's hostname. No broker account was accessed and no order or strategy control was submitted during these checks.

The first launchd reload returned bootstrap error 5; rollback restored the previous running service. A subsequent unload, registration wait and bounded load retry succeeded. Logs: `.toolkit-runs/20261108T193400.350205Z.log` (failed and rolled back), `.toolkit-runs/20261108T193445.848631Z.log` (successful repair). Private backup: `previous-pairing-20261108-113445` under the gateway's private directory. The new certificate and existing token were imported on the phone over USB.

Pinned setup, alerts and Markets checks succeeded. Private before/after snapshots under `.toolkit-runs/options-review-20261108/` confirm identical paper IDs, balances, quantities, observations, fills and next-session state across the repair. All four frozen paper modules remain byte-identical to the active gateway. Trading and transfers remain disabled.

Device Hub then directly showed the real Home paper portfolio, market indices and watchlist, the AAPL intraday chart, live calls/puts and contract details with 100 shares, midpoint premium and the quote's own Friday 3:59 PM ET timestamp. Selecting November 11 instead of November 9 changed the expiration and quotes. The automated screen showed a current scheduler heartbeat, three active strategies and one simulated fill. These observations establish phone-to-gateway operation; they do not establish options execution or strategy performance.

## Build and remaining verification

The final signed native build passed: `.toolkit-runs/20261108T194744.245778Z.log`. It compiles the changed shared presentation components for the physical device. Build 8 was installed and launched successfully with the existing pairing retained; private receipts are `.toolkit-runs/phone-review-20261108/final-install.json` and `final-launch.json`. After the owner unlocked the Mac, Device Hub verified the final screen at 12:31–12:32 PT: currency fits in two columns, drawdown is 0.01%, the entry limit is 25%, the singular fill label is correct, and the detail page preserves costs, quantities and the next November 9 decision. No strategy controls were used. No new backend code changed, so the previously passing 278 backend tests and 68 script tests are prior-release evidence, not reruns for this presentation change. Repository CI passed for `7108bee`: [run 42517057160](https://github.com/louisbrailey/tradepilot/actions/runs/42517057160).

Development signing still expires November 11 at 00:35 PT. The renewal agent is loaded; renewal still needs a usable Apple ID in Xcode. The home PC's native Windows deployment candidate is being staged separately and has not been activated or accepted under its service identity. The Mac remains the sole paper-ledger writer.
