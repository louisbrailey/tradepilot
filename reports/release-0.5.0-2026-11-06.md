# TradePilot 0.5.0 — Markets, price alerts and current paper prices

November 6, 2026. Source `main` at the commit that adds this report. Built and checked by Claude in an isolated worktree, then merged with Codex's `0da625b` (assistant reply constraints).

## What changed

**Markets tab.** A new tab between Home and Accounts shows the market session (open, pre-market, after hours or closed, with the next open or today's close), S&P 500, Nasdaq 100, Dow Jones and Russell 2000 through their ETFs with intraday sparklines, a watchlist of up to 40 symbols saved on the iPhone, large-cap gainers, losers and most active, and symbol search by ticker or company name. Details and data limits: [MARKETS.md](../MARKETS.md).

**Quote pages.** Every US-listed stock or ETF has a quote page with an interactive chart (press and hold, then drag) for 1D, 1W, 1M, 3M, 6M, YTD, 1Y and 5Y; the after-hours price; key statistics including market cap, P/E, EPS, dividend yield, bid/ask and VWAP; day and 52-week range bars; the paper position; the latest or upcoming dividend; a company profile; and headlines with the provider's sentiment. **Trade on paper** and **Forecast lab** open the existing screens with the symbol filled in; those screens keep their own review and confirmation. Paper and Webull stock holdings open the same page.

**Price alerts.** A bell on each quote page sets an alert above or below a price. The gateway checks active alerts about once a minute during pre-market, regular and after-hours trading, and only prices observed after the alert was set can trigger it. Markets shows triggered alerts and a bell with their count; a list screen removes alerts or clears triggered ones. Alerts never create or place orders. The app posts a local notification for each new trigger, badges its icon with the triggered count and opens the symbol when the notification is tapped. Development signing has no push service, so iOS background refresh checks the gateway while the iPhone is unlocked (the gateway token keeps its unlocked-only Keychain protection), and Markets or the alert list check whenever they are open.

**Paper prices.** Paper reviews and marks now use the provider's consolidated price for the current or just-finished session (the official close after 4:00 p.m. ET), falling back to the latest completed daily close when no current day bar exists. Previously a paper order placed mid-session filled at the prior day's close. Freshness, no-regression and confirmation rules are unchanged; see [PAPER-TRADING.md](../PAPER-TRADING.md).

**Operations.** `scripts/update-local-gateway.py` updates the running Mac gateway in place: `plan` lists differing runtime files, `apply` backs them up, installs atomically, restarts the launch agent and runs an authenticated, certificate-pinned health check, and `rollback` restores a backup. It never writes the private directory.

**Fixes found while building.** Market quotes ignored nanosecond provider timestamps because a magnitude guard rejected them; fixed with a regression test. The Debug configuration never defines `DEBUG`, so `#if DEBUG` code (the practice "reject next order" toggle and the screen selector) is compiled out of Debug builds, including the phone build. This was left unchanged on purpose; simulator QA passes the flag on the command line.

## Verification

| Check | Result |
| --- | --- |
| `scripts/check.sh` (Core, backend, scripts, Swift typecheck and smoke checks, project lint) | Passed: 13 Core, 262 backend (1 optional signing skip), 56 script tests |
| Backend suite under the deployed gateway Python 3.9.6 | 262 passed, including signing |
| New tests | 25 market data, 11 alerts, 2 paper reference price, 6 gateway update |
| Native builds | iOS Simulator (arm64) and unsigned generic iOS device build succeeded |
| Live provider smoke (read-only, real Massive key) | Overview, quotes, search, symbol page and all eight chart ranges returned plausible data; unknown symbol rejected |
| XCUITest in the simulator against the isolated gateway | Passed: quote page → bell → composer → create → allow notifications → alert listed; a recorded trigger produced the system banner "AAPL rose above $359.49 · Reached $360.12" and no duplicate on the next check; Markets loaded live indices, search found NVDA and its quote page drew the 1Y chart |
| Simulator, isolated gateway on loopback with a temporary ledger and no broker credentials | Markets with live data, quote page, alert creation, triggered-alert banner and badge rendered; screenshots in `.toolkit-runs/markets-qa-20261106/` (private, not committed) |

The Mac was heavily loaded during checks (load average above 500 from staging VMs and other jobs). The new simulator's trust daemon stalled until it was restarted; that affected only the QA simulator.

## Deployment and remaining steps

- **Gateway deployment: done.** Claude's first attempt was blocked by the Claude Code permission policy for production changes; the owner then approved it. `scripts/update-local-gateway.py apply` installed 2 changed and 2 new files from `89d2274` at 20:09 PT, backed up the replaced files to `private/code-backup-update-20261106-200945`, restarted the launch agent and passed the pinned health check (alerts and market routes answered). Afterwards the gateway served real quotes and all three automated paper runs were still running. Roll back with `scripts/update-local-gateway.py rollback --backup code-backup-update-20261106-200945` if needed.
- **Phone launch.** `scripts/install-iphone.sh` built, signed and installed 0.5.0 (build 6) on the USB iPhone 16 (`devicectl` reports version 0.5.0, bundle version 6). iOS refused to launch it: the developer profile has not been explicitly trusted on the phone, as with 0.4.1. On the iPhone open Settings → General → VPN & Device Management, choose the Apple Development profile and trust or verify it (the phone needs an internet connection), then open TradePilot. The development signing profile expires November 11, 2026 at 00:35 Pacific. With the owner's approval the `com.tradepilot.keep-signed` launch agent is installed: it checks hourly and, within two days of expiry, rebuilds `main` with a fresh profile and installs it when the iPhone is reachable (backing off if Apple returns the same profile). A renewal attempt (`keep-iphone-signed.py renew`) found that **Xcode has no Apple account signed in** (`No Accounts`), so no new profile can be issued until the owner signs in under Xcode → Settings → Accounts with the Apple ID for team ANWNGW59GP; the existing profile was restored untouched. The agent now posts a macOS notification once a day until that is done. The signing certificate itself is valid until September 10, 2027 and passed Apple's OCSP revocation check, so the iPhone's launch refusal is the on-device trust step, not a revoked certificate.
- **Push notifications** need a paid Apple Developer membership and an APNs key; until then alerts appear when the app is open.
- The GitHub repository is public by the owner's choice; gitleaks and trufflehog found no secrets in its history. The commits were pushed to `main` (`cc6f6bc..89d2274`) and the repository checks passed.
