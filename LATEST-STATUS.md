# November 8, 2026 — options-chain review (0.5.1)

Version 0.5.1 (build 7) finishes the read-only options chain and fixes expiration substitution, an unnecessary pagination request, standard/adjusted contracts overwriting one another at the same strike, and the assumption that every contract represents 100 shares. Contract terms and quote timestamps are visible, missing activity stays unavailable, and stale requests cannot replace a newer selection. See [release evidence](reports/release-0.5.1-2026-11-08.md).

The full gate passed with 13 Core, 276 backend and 68 script tests plus Swift checks. After one additional malformed-provider regression fix, all 277 backend tests passed under the deployed Python 3.9.6. Signed simulator and signed device builds succeeded. The simulator rendered separate standard/adjusted series, unavailable activity, the appropriate premium estimate, expiration changes and calls/puts using isolated synthetic data. A read-only live source check returned 94 AAPL and 330 SPY contracts. The USB phone has 0.5.1 build 7 installed; iOS blocked launch while it was locked, so a fresh physical-device check is pending.

The reviewed gateway code (`90cae8d`) was deployed at 10:41 PT with `scripts/update-local-gateway.py apply`; backup `code-backup-update-20261108-104125` is retained. Pinned TLS setup, alerts and Markets checks passed. The deployed options route returned 94 AAPL contracts with verified standard terms and rejected invalid/unavailable expirations with HTTP 400. All three paper runs retained their IDs, running state, balances, two observations each, existing fill counts and next session of November 9. Live trading remains disabled.

The home PC is currently offline and its Codex host is disconnected. The Mac remains the active paper-ledger writer; the local-PC migration is still pending.

# November 6, 2026 — Markets, price alerts and current paper prices (0.5.0)

A new Markets tab adds the market session, index ETFs with sparklines, a watchlist saved on the iPhone, large-cap movers and symbol search. Quote pages have an interactive chart for eight ranges, the after-hours price, key statistics, day and 52-week ranges, the paper position, dividends, a company profile and headlines; paper and Webull holdings open them. Price alerts set from a quote page are checked by the gateway about once a minute during trading sessions; the app posts a local notification for each trigger through iOS background refresh (no push service without a paid developer account) and when Markets is open. Alerts never place orders. Paper orders now use the current session's consolidated price instead of the prior close. `scripts/update-local-gateway.py` updates the running gateway with a backup, restart and pinned health check. See [Markets](MARKETS.md) and the [release notes](reports/release-0.5.0-2026-11-06.md).

The gate passed with 13 Core, 262 backend (also under the gateway's Python 3.9.6) and 56 script tests plus Swift checks; simulator and unsigned device builds succeeded. XCUITests in the simulator created an alert through the composer, granted notification permission, showed the system banner for a recorded trigger, and searched for and opened a quote page. A read-only smoke against the real Massive key and simulator checks against an isolated gateway rendered live markets, a quote page and alerts. **Live on the Mac gateway:** with the owner's approval the gateway code was deployed at 20:09 PT with `scripts/update-local-gateway.py apply` (backup `private/code-backup-update-20261106-200945`); the pinned health check passed, the alerts and market routes answered, real quotes were served and all three automated paper runs remained running. 0.5.0 (build 6) is installed on the USB iPhone 16; iOS refused to launch it until the developer profile is trusted on the phone (Settings → General → VPN & Device Management), the same block that stopped 0.4.1. The commits are pushed to `main` and the repository checks passed. A launch agent (`com.tradepilot.keep-signed`) renews the seven-day development signing and reinstalls when the iPhone is reachable, but renewal needs an Apple ID signed into Xcode, and none is (the agent notifies daily until one is). Overnight the iPhone 16 updated itself to iOS 27.2 and waited on its setup screens, so iOS refused every app launch with "Device setup is not yet complete". On November 7 at 15:07 PT, as soon as setup finished, `devicectl` launched TradePilot 0.5.0 on the phone: iOS now accepts its signing. With the owner's permission the app was brought to the front at 15:15 and captured on the physical iPhone: the 0.5.0 Home rendered with the Markets card and the five-tab bar, and reported the server and market data as unavailable, which is correct because the Mac was on an IPv6-only link (CLAT address 192.0.0.2) that the gateway deliberately does not serve. In-app data checks on the phone need the Mac and iPhone on the same home LAN. The gateway moved to the home LAN (10.0.0.166) on its own and passed the pinned health check there. Owner actions: finish the iOS setup on the iPhone, trust the developer profile if iOS asks, and sign in to Xcode before November 11. Later that night Coinbase balances gained USD values, an estimated total and 24-hour changes through a new read-only `/v1/market/crypto` route (checked in the simulator with sample balances and live prices); the owner then approved deploying it and future code-only gateway updates through `scripts/update-local-gateway.py`; it was deployed on November 7 at 14:57 PT (backup `code-backup-update-20261107-145721`), passed the pinned health check and priced BTC, ETH and USD on the live gateway.

# November 6, 2026 — portfolio interface and paper scheduler (0.4.1)

Home shows the saved paper portfolio, including an equity chart and the age of its oldest reference price. Practice balances and orders follow the selected sample account. Webull puts balances and positions ahead of orders, and Coinbase shows asset units and amounts on hold. Paper order review keeps the account, reference close, modeled fill, and confirmation in view. The app follows the phone’s light or dark appearance.

The repository gate passed with 13 Core tests, 224 backend tests, 50 script tests, and Swift smoke checks. The optional signing tests also passed under the gateway Python. Simulator checks with an isolated TLS gateway verified the paper fill, Practice review and cancel, Webull account selection and disabled order entry, and Coinbase zero-balance filtering. The signed 0.4.1 build 5 installed over USB. iOS rejected launch with a signing or profile-trust error, so the updated app’s physical operation remains unverified.

The Mac gateway now binds to local TLS while the paired LAN is unavailable and resumes its LAN listener when a private IPv4 address returns. The scheduler recorded all three November 6 observations, including the first simulated mean-reversion fill. The next scheduled session is November 9. The [home PC migration runbook](HOME-PC.md) is ready for when the Windows host comes online.

# November 6, 2026 — 0.4.0 interface rebuild and review fixes

The iPhone app was rebuilt at the presentation layer: four tabs (Home, Accounts, Research, Journal), the assistant as a sheet, a shared design system with status badges, metric tiles and one confirmation sheet for practice, paper and Webull orders, consistent Practice/Paper/Live vocabulary, currency and relative-time formatting, pull to refresh, and user-facing copy without gateway jargon or raw server strings. Safety flows are unchanged. An independent review of the October 26 to November 5 work found no auth or live-trading gaps; its defects (stale Webull cancellation state, unverified Coinbase confirm/reconcile replies, misleading paper refresh message, generic 502 for admission errors, lazily created cancellation table, reconcile never promoting an identified open order) are fixed with tests. Gates: 13 core, 223 backend, 50 script tests, Swift smoke checks, simulator build. Server changes are deployed to the Mac gateway; the phone still runs 0.3.0. Open items that need the real providers: the Webull settlement fields that release a production hold, and the Coinbase preview commission field. See [release notes](reports/release-0.4.0-2026-11-06.md).

# November 5, 2026 — remote hosting prepared; Mac still active

Prepared an Ubuntu 24.04 deployment for the private Tailscale gateway, paper scheduler, smaller local Qwen3.5:4b assistant and the existing pinned Kronos models. After the user requested lower cost, the selected plan is OVHcloud VPS-2 2027 in Canada East: 4 shared vCores, 8 GB RAM, 75 GB NVMe, $10/month plus $2.20/month for seven-day backups, before tax, with monthly billing and no long-term commitment. This replaces the earlier $57.60/month DigitalOcean proposal. No account/server has been created, no charge incurred and no private state transferred. The current Mac deployment and phone pairing remain unchanged.

Added private-node/pairing preflight, read-only broker enforcement, restart fencing for migration, shared AI/Kronos request serialization, service resource limits, consistent per-database SQLite backups, a staged installer and a single-writer cutover/recovery runbook. Full checks pass: 13 core, 222 backend (one optional signing skip), 50 script tests and Swift smoke/typechecks. Nine new remote tests and systemd unit validation also pass in an isolated Ubuntu 24.04 container. Linux model installation, actual VPS performance, migration, reboot recovery and cellular iPhone verification remain pending; local tests do not prove them. See [hosting plan and deployment steps](REMOTE-SETUP.md).

# November 5, 2026 — automated paper strategies started (0.3.0)

Version 0.3.0 (build 3) adds three fixed prospective SPY experiments with separate $10,000 simulated accounts, scheduled by the Mac gateway after 20:15 Eastern on market sessions. Immutable protocol/code hashes, precommitted next-session intentions, costed decimal accounting, stop controls, drawdown/data holds and restart/concurrency protection are implemented. Manual paper and real broker accounts remain separate; no broker writes are enabled.

The gateway is deployed and the phone app installed. The three experiments were started from the physical iPhone and the background worker recorded their first November 5 observation with real, complete Massive data. Each has one observation and zero fills, with its next intent saved for November 6. This is initial forward-recording evidence; the first future-session settlement remains unobserved. See [protocol and controls](AUTOMATED-PAPER.md) and [release evidence](reports/automated-paper-2026-11-05.md).

Final full checks passed: 13 core, 219 backend (one optional signing skip under default Python), 41 script tests and Swift smoke/typechecks. All 219 backend tests also passed under the deployed Python, including signing. The signed native build passed. Keep the Mac awake; the existing local-development signing expiry remains November 11 at 00:35 Pacific.

# November 5, 2026 — version 0.2.0 installed and checked

TradePilot 0.2.0 (build 2) is installed and running on the USB iPhone 16. Overview, Holdings and Accounts now lead to real Webull/Coinbase connections, with sample data in clearly labeled disclosures. Webull has labeled currency balances; Coinbase has readable asset cards, exact zero-balance filtering and read-only order history. Action availability requires both provider grants and gateway controls. Connection settings have their own screen and report Coinbase configuration without claiming provider verification.

Physical checks confirmed the new navigation, retained pairing, authenticated setup, Webull balances, Coinbase balances/permissions/order history and the saved paper account. No new orders, cancellations or transfers were submitted. The full gate passes (13 core, 205 backend with one optional signing skip, 41 script tests and Swift smoke checks), and the signed native build passes. See [release evidence and operational limits](reports/release-0.2.0-2026-11-05.md).

The user chose to keep the local development installation. Its current signing profile expires **November 11, 2026 at 00:35 Pacific**; refresh signing and reinstall before then. The Mac must remain awake on the phone’s LAN. Live trading/transfers remain disabled. Broader future product scope is retained in [NEXT-STEPS.md](NEXT-STEPS.md).

# November 5, 2026 — Coinbase read-only connection verified on the phone

Created the explicitly approved View-only ECDSA key for the Primary portfolio after SMS verification on the iPhone 16 Pro. Stored it in the gateway's owner-only private configuration. Coinbase confirms View enabled and Trade/Transfer disabled. The gateway's authenticated, certificate-pinned account and capability routes returned HTTP 200; 26 asset accounts were returned and balances rendered in TradePilot on the physical USB iPhone. Trading, cancellations and transfers remain disabled; no transactions were performed.

Added and deployed opt-in `COINBASE_IPV4_ONLY` routing because the key's IPv4 allowlist rejected the default IPv6 egress. TLS hostname/certificate verification remains enabled. All 205 backend tests pass under the deployed interpreter, including signing. The first full run exposed an existing Python 3.9-incompatible HTTP-error fixture; giving it a real in-memory response body fixed the fixture and added response-closure verification. See [Coinbase setup and operational limits](COINBASE-SETUP.md) and [evidence](reports/coinbase-setup-2026-11-05.md).

# November 4, 2026 — Webull account connected on the phone

At the user’s request, loaded the existing production Webull connection from TradePilot on the USB iPhone, selected the authorized Individual Cash account, and refreshed its portfolio. Current balance details and an empty holdings table rendered successfully. This is direct read-access verification, not a fake-provider test. Credentials and existing authorization stayed on the gateway; no trading flag was changed and no order, cancellation or transfer was performed. See [Webull setup](WEBULL-SETUP.md).

# November 4, 2026 — physical app paths checked and gateway aligned

Direct checks on the USB iPhone verified Overview, Holdings, demo confirmation, persistent paper fill/journal, Massive research, strategy comparison, five-session Kronos replay and local AI. Coinbase/Webull disconnected controls rendered; real accounts were not used as tests. The matching merged gateway routes are now deployed with the existing runtime and configuration retained. A local AI failure was traced to Lima shadowing IPv4 Ollama; explicit IPv6 loopback routing restored the configured native model, and the phone AI request succeeded. Live trading remains disabled.

See [phone verification, exact simulated ledger changes and remaining limits](reports/phone-verification-2026-11-04.md). The full gate passed before this fix; all 202 backend tests pass afterward (one optional signing test skipped).

# November 4, 2026 — physical iPhone installed

Signed build succeeded and TradePilot 0.1.0 (build 1) was installed on the USB-connected iPhone 16 (`00008140-0010646A1413801C`). Developer Mode is enabled. The pairing file was copied successfully. After the user trusted the developer profile, `devicectl` launched the app successfully. The process remained running, and app preferences copied back from the physical device confirm the paired endpoint and pinned origin are `https://louiss-macbook-pro-8.local:8787`. Device Hub remained at “Connecting display”. The user then ran Accounts → Check connection & setup on the physical phone and confirmed that connection/setup details appeared, establishing phone-to-gateway connectivity. Other app screens and broker workflows have not been verified on this phone.

The Mac is back on the LAN at `192.168.68.56`. The gateway was deliberately re-paired for the current hostname `louiss-macbook-pro-8.local`; previous pairing/config files are preserved in `private/previous-pairing-20261104`, and the access token is unchanged. A certificate-verified, authenticated `/v1/setup` request returned HTTP 200 over the LAN address. The new pairing was copied to the phone and imported by the app. Setup reports local Ollama and market data configured, with live trading disabled. This check did not contact a broker. The phone was subsequently updated to source `8ea2d2d`, including merged PR #1. Build/install evidence: `.toolkit-runs/20261104T083815.217395Z.log` (overall exit 1 because the initial launch preceded developer-profile trust); a subsequent standalone launch succeeded.

# October 26, 2026 — Claude review

Claude independently reviewed the source and fixed four issues:

- A filled paper order could be confirmed again.
- An idle TCP peer could stall the TLS gateway.
- Paper orders were refused the day after a Monday holiday.
- Double-tap guards were added to Webull confirmation.

All gates pass: 13 core, 159 backend and 36 script tests, the Swift smoke checks, and both native builds. Commits `2b05e15` and `7ab6207` are deployed in place to the private gateway; the previous code is kept in `private/code-backup-20261026`. The gateway is waiting for a LAN address and has not served a request since deployment. The gateway was later re-paired the same day for `louiss-macbook-pro-7.local`. That produced a new certificate, valid until 2027-01-24; the access token is unchanged. The old pairing files are kept in `private/previous-pairing-20261026`. The phone must receive the new `TradePilotPairing.json`. See the [October 26 review](reports/review-2026-10-26/REVIEW.md) and [release notes](reports/review-2026-10-26/RELEASE-NOTES.md).

Later the same day the iPhone 16 Pro was connected over USB-C, trusted and paired. Xcode now recognises it, which resolves the September device-discovery blocker, but the phone has Developer Mode off, so the signed build cannot target it, and the team has no registered device yet because the app has never been installed on it. `scripts/install-iphone.sh` now checks this first and stops with instructions instead of waiting on `xcodebuild`. The remaining steps need the user: turn on Developer Mode on the phone, put the Mac on home Wi-Fi so the gateway can start, then run the installer. See [DEVICE-CONNECTION-REPORT.md](DEVICE-CONNECTION-REPORT.md).

# October 1, 2026 — Kronos feature

Added the native Kronos research lab and deployed its authenticated gateway endpoint. Real model and market-data replay passed; simulator build installed and launched. Simulator GUI and physical iPhone verification remain unavailable. No automatic trading enabled. See [Kronos evidence and limitations](KRONOS.md).

# TradePilot — source reviewed September 23, 2026

The current source is `/Users/louisbrailey/tradepilot`. The latest independent review fixed order-state races, fill-regression handling, iPhone request/account binding, gateway parsing, research provenance and private setup. The combined gate passes 148 tests plus Swift smoke checks; both native architecture builds pass. An offline replay and 119 independent accounting checks reproduce the existing backtest without changing its results. No candidate both passed validation and beat its final benchmark.

Claude Code was actually invoked but returned a sign-in error; Claude has not reviewed this revision. Physical iPhone installation, production brokerage authentication and the broader multi-broker/strategy scope remain unfinished. Source changes have not been deployed. See the [September 23 review, evidence and remaining work](reports/review-2026-09-23/REVIEW.md) and [Claude handoff](reports/review-2026-09-23/CLAUDE-HANDOFF.md).

The September 12 observations below describe the previously tested runtime. They have not all been reverified on September 23 and must not be read as current deployment status.

## Previous runtime verification — September 12, 2026

## Working now

- Native SwiftUI iPhone app installed, launched, and paired in Apple’s iOS 26.5 simulator. Signed simulator and unsigned physical-iPhone architecture builds pass.
- Local AI uses the installed Ollama alias `qwen3.8-local:latest`; its reported model family is `qwen35`, 27.3B, Q4_K_M. The alias is not verification of a Qwen 3.8 release. No OpenAI API key is needed in this configuration.
- Actual AI response verified through the authenticated TLS gateway and the installed app. Gateway test took 6.97 seconds, with setup responding in 0.018 seconds during inference. No model execution tools or remote fallback.
- Private launch-at-login gateway is running outside Documents. It retains credentials, broker records, and certificate pairing in owner-only storage. Mac must remain awake on the same LAN; an IP change still requires re-pairing.
- Real Massive daily history, options samples, dividends and Benzinga research. Recorded results are available inside Research.
- Exact Webull stock-order preview/confirmation workflow, durable submission and execution evidence, and account/environment binding are implemented and tested with fake broker responses. Production account authentication is not verified.
- Journal records demo and broker-related actions separately, links reflections, exports history, and supplies optional AI context. Retrieval does not retrain the model.

## Backtest evidence

Seven symbols, 1,177 daily bars each, from 2022-01-03 through 2026-09-11. Frozen training, validation and final periods; four cost scenarios; independent accounting and temporal-leakage tests; exact offline replay. No symbol both passed validation and beat its final benchmark. This SMA experiment does not justify live strategy adoption. See BACKTEST-REPORT.md and BACKTESTING.md. No parameters were tuned after final outcomes were seen.

## Verification

13 core tests, 90 backend tests, 17 script tests, plus Swift journal, connection, order-review and evaluation smoke checks pass. Both native builds pass. Simulator verified setup, local assistant response, recorded evaluation and exact 3-share AAPL demo review. Manual demo confirmation was not counted: the UI tool’s automatic approval check timed out; automated confirmation tests passed. No real orders or transfers were performed. Live order submission remains disabled.

## External blockers and unimplemented scope

Physical iPhone installation remains blocked: Xcode reports no devices, and iPhone Mirroring requires unlocking the phone. A simulator does not install software on the physical iPhone.

Webull account read returned HTTP409 authentication failure. The website’s saved sign-in requires a Mac password, and API authentication requires Webull’s mobile verification. The existing production keys were preserved; no new brokerage account or access was created. A new account would not remove those requirements.

Coinbase/Fidelity integrations, live crypto/options/short execution, autonomous strategy promotion, continuous paper performance tracking, broader strategy backtests, and an always-online hosted service are not completed. The app is a functioning local development build with the scope above, not a fully operational multi-broker live-trading service.
