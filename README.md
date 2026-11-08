# TradePilot

A native iPhone assistant for reviewing portfolios, preparing explicitly confirmed trades, and keeping research and a trade journal together.

**Current verified status:** the USB iPhone connects to the Mac gateway and displays the paper portfolio, Markets, a quote chart and live read-only options, including contract details and expiration changes. Version 0.5.2 (build 8) is signed, installed and physically verified: strategy values fit cleanly and drawdown/entry percentages are readable. See [latest status](LATEST-STATUS.md). Webull and Coinbase read access, local AI, Massive research and Kronos replay have prior physical-phone verification. The Mac scheduler is recording three automated SPY paper experiments. Live trading and transfers are disabled. See [the paper protocol](AUTOMATED-PAPER.md).

Kronos is available under **Research → Kronos forecasting lab** for local historical forecasts and baseline comparisons. See [Kronos setup and verification](KRONOS.md).

## Included

- Automated prospective paper strategies with a private scheduler, separate portfolios and explicit stop/data gates.
- SwiftUI app with five tabs. Home shows paper equity and links to practice, automated strategies and broker accounts. Markets has the session status, index ETFs, a watchlist, large-cap movers, symbol search and a quote page with an interactive chart, key statistics and headlines; see [Markets](MARKETS.md). Accounts groups the broker connections and settings. Research hosts strategy comparison, forecast replay, market research and recorded backtests. Journal keeps activity and notes. The practice assistant opens from Home. A shared design system supplies the theme, metric tiles, and order confirmation sheet.
- Paper orders priced at the current session's consolidated price, or the last close when none exists, with modeled slippage.
- Coinbase balances valued in USD with an estimated total and 24-hour changes (read-only; prices can be delayed).
- Read-only options chains on quote pages: expirations, calls and puts by strike, implied volatility and Greeks.
- Local Ollama inference or optional OpenAI, strict structured proposals, independent order validation, and separate confirmation.
- Webull long-stock DAY market/limit order adapter with durable no-duplicate submission and execution evidence.
- Real Massive/Benzinga research and reproducible multi-stage historical evaluation with results in the app.
- Private TLS pairing, Keychain access token, and a per-user Mac gateway. The planned always-on host is the [home PC](HOME-PC.md).

See [confirmed broker access, supported scope and safety controls](BROKER-ACCESS.md) for the Coinbase action screen and Webull cancellation flow. The matching gateway routes are deployed. Read-only access has been verified; this does not qualify or enable live submissions.

## Run and install

Open `iOS/TradePilot.xcodeproj` in Xcode. Select TradePilot and an installed iPhone simulator to run. A physical installation requires Apple signing and a trusted, paired iPhone with Developer Mode turned on; see [WEBULL-SETUP.md](WEBULL-SETUP.md) and `scripts/install-iphone.sh`.

Phone connection checks and the assistant toggle are under **Accounts → Settings** (also the gear on Home).

Free development signing expires every seven days. The `com.tradepilot.keep-signed` launch agent (`scripts/keep-iphone-signed.py`) checks hourly and, within two days of expiry, rebuilds the committed `main` branch with a fresh profile and installs it whenever the iPhone is reachable over USB or Wi-Fi. It never copies pairing data or launches the app. Renewal needs the Apple ID for team ANWNGW59GP signed in under Xcode → Settings → Accounts; as of November 6 none is signed in, and the agent posts a macOS notification once a day until one is. `renew` asks Apple for a new profile without the phone. Check it with `python3 scripts/keep-iphone-signed.py status`; remove it with `python3 scripts/keep-iphone-signed.py remove`. Its log is in `~/Library/Application Support/TradePilot/keep-signed/`.

The already-deployed local gateway is described in [LOCAL-SERVICE.md](LOCAL-SERVICE.md). Configure inference with [LOCAL-AI.md](LOCAL-AI.md). Credentials and private runtime files are deliberately excluded from the source ZIP.

## Evidence and limits

[Verification](VERIFICATION.md) · [Backtest report](BACKTEST-REPORT.md) · [Reproduce backtests](BACKTESTING.md) · [Order integrity review](TRADE-INTEGRITY-REVIEW.md) · [Learning design](LEARNING-DESIGN.md)

The tested SMA strategy did not qualify for live adoption. Research profiles are not validated trading systems. Journaling provides retrieved context, not automatic model training. Demo prices and account balances are fictional and clearly labeled in the app.
