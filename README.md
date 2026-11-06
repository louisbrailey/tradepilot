# TradePilot

A native iPhone assistant for reviewing portfolios, preparing explicitly confirmed trades, and keeping research and a trade journal together.

**Current verified status:** version 0.3.0 is installed on the physical iPhone with verified Webull and Coinbase read access. Real account screens are separate from sample portfolios and paper trading. Three fixed automated SPY paper experiments are running; see [the protocol](AUTOMATED-PAPER.md). Local AI, Massive research, strategy comparison and Kronos replay have prior physical-phone verification. See [latest status](LATEST-STATUS.md), [0.3.0 automation checks](reports/automated-paper-2026-11-05.md) and [research/paper checks](reports/phone-verification-2026-11-04.md). Live trading and transfers are disabled.

Kronos is available under **Research → Kronos forecasting lab** for local historical forecasts and baseline comparisons. See [Kronos setup and verification](KRONOS.md).

## Included

- Automated prospective paper strategies with a private scheduler, separate portfolios and explicit stop/data gates.
- SwiftUI account overview, Webull/Coinbase balances, paper trading, demo portfolio, assistant and research/journal screens.
- Local Ollama inference or optional OpenAI, strict structured proposals, independent order validation, and separate confirmation.
- Webull long-stock DAY market/limit order adapter with durable no-duplicate submission and execution evidence.
- Real Massive/Benzinga research and reproducible multi-stage historical evaluation with results in the app.
- Private TLS pairing, Keychain access token, and a per-user Mac gateway. [Always-on remote hosting](REMOTE-SETUP.md) is prepared but not yet deployed.

See [confirmed broker access, supported scope and safety controls](BROKER-ACCESS.md) for the Coinbase action screen and Webull cancellation flow. The matching gateway routes are deployed. Read-only access has been verified; this does not qualify or enable live submissions.

## Run and install

Open `iOS/TradePilot.xcodeproj` in Xcode. Select TradePilot and an installed iPhone simulator to run. A physical installation requires Apple signing and a trusted, paired iPhone with Developer Mode turned on; see [WEBULL-SETUP.md](WEBULL-SETUP.md) and `scripts/install-iphone.sh`.

Phone connection checks and the AI toggle are under **Accounts → Gateway connection & AI**. The current development profile expires November 11, 2026; refresh signing and reinstall before expiry.

The already-deployed local gateway is described in [LOCAL-SERVICE.md](LOCAL-SERVICE.md). Configure inference with [LOCAL-AI.md](LOCAL-AI.md). Credentials and private runtime files are deliberately excluded from the source ZIP.

## Evidence and limits

[Verification](VERIFICATION.md) · [Backtest report](BACKTEST-REPORT.md) · [Reproduce backtests](BACKTESTING.md) · [Order integrity review](TRADE-INTEGRITY-REVIEW.md) · [Learning design](LEARNING-DESIGN.md)

The tested SMA strategy did not qualify for live adoption. Research profiles are not validated trading systems. Journaling provides retrieved context, not automatic model training. Demo prices and account balances are fictional and clearly labeled in the app.
