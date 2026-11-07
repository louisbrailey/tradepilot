# TradePilot

A native iPhone assistant for reviewing portfolios, preparing explicitly confirmed trades, and keeping research and a trade journal together.

**Current verified status:** version 0.5.0 adds Markets (watchlist, movers, search, quote pages with charts and statistics), price alerts and current-session paper prices; it passed the full gate, a read-only live data smoke and simulator checks. It is not yet deployed to the Mac gateway or installed on the iPhone; see [latest status](LATEST-STATUS.md). The phone still has 0.4.1, which iOS refused to launch at the developer-trust check. Webull and Coinbase read access, local AI, Massive research and Kronos replay have prior physical-phone verification. The Mac scheduler is recording three automated SPY paper experiments. Live trading and transfers are disabled. See [the paper protocol](AUTOMATED-PAPER.md).

Kronos is available under **Research → Kronos forecasting lab** for local historical forecasts and baseline comparisons. See [Kronos setup and verification](KRONOS.md).

## Included

- Automated prospective paper strategies with a private scheduler, separate portfolios and explicit stop/data gates.
- SwiftUI app with five tabs. Home shows paper equity and links to practice, automated strategies and broker accounts. Markets has the session status, index ETFs, a watchlist, large-cap movers, symbol search and a quote page with an interactive chart, key statistics and headlines; see [Markets](MARKETS.md). Accounts groups the broker connections and settings. Research hosts strategy comparison, forecast replay, market research and recorded backtests. Journal keeps activity and notes. The practice assistant opens from Home. A shared design system supplies the theme, metric tiles, and order confirmation sheet.
- Paper orders priced at the current session's consolidated price, or the last close when none exists, with modeled slippage.
- Local Ollama inference or optional OpenAI, strict structured proposals, independent order validation, and separate confirmation.
- Webull long-stock DAY market/limit order adapter with durable no-duplicate submission and execution evidence.
- Real Massive/Benzinga research and reproducible multi-stage historical evaluation with results in the app.
- Private TLS pairing, Keychain access token, and a per-user Mac gateway. The planned always-on host is the [home PC](HOME-PC.md).

See [confirmed broker access, supported scope and safety controls](BROKER-ACCESS.md) for the Coinbase action screen and Webull cancellation flow. The matching gateway routes are deployed. Read-only access has been verified; this does not qualify or enable live submissions.

## Run and install

Open `iOS/TradePilot.xcodeproj` in Xcode. Select TradePilot and an installed iPhone simulator to run. A physical installation requires Apple signing and a trusted, paired iPhone with Developer Mode turned on; see [WEBULL-SETUP.md](WEBULL-SETUP.md) and `scripts/install-iphone.sh`.

Phone connection checks and the assistant toggle are under **Accounts → Settings** (also the gear on Home). The current development profile expires November 11, 2026; refresh signing and reinstall before expiry.

The already-deployed local gateway is described in [LOCAL-SERVICE.md](LOCAL-SERVICE.md). Configure inference with [LOCAL-AI.md](LOCAL-AI.md). Credentials and private runtime files are deliberately excluded from the source ZIP.

## Evidence and limits

[Verification](VERIFICATION.md) · [Backtest report](BACKTEST-REPORT.md) · [Reproduce backtests](BACKTESTING.md) · [Order integrity review](TRADE-INTEGRITY-REVIEW.md) · [Learning design](LEARNING-DESIGN.md)

The tested SMA strategy did not qualify for live adoption. Research profiles are not validated trading systems. Journaling provides retrieved context, not automatic model training. Demo prices and account balances are fictional and clearly labeled in the app.
