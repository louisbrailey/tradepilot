# TradePilot

A native iPhone assistant for reviewing portfolios, preparing explicitly confirmed trades, and keeping research and a trade journal together.

**Current verified status:** see [LATEST-STATUS.md](LATEST-STATUS.md). The app is installed and verified on a physical iPhone with local AI, Massive research, paper execution, strategy comparison and Kronos replay. See [physical-phone checks](reports/phone-verification-2026-11-04.md). Real broker access remains separately gated. Live trading is disabled.

Kronos is available under **Research → Kronos forecasting lab** for local historical forecasts and baseline comparisons. See [Kronos setup and verification](KRONOS.md).

## Included

- SwiftUI overview, portfolio table, assistant, research/journal, and Webull account screens.
- Local Ollama inference or optional OpenAI, strict structured proposals, independent order validation, and separate confirmation.
- Webull long-stock DAY market/limit order adapter with durable no-duplicate submission and execution evidence.
- Real Massive/Benzinga research and reproducible multi-stage historical evaluation with results in the app.
- Private TLS pairing, Keychain access token, and a per-user Mac gateway.

See [confirmed broker access, supported scope and safety controls](BROKER-ACCESS.md) for the new Coinbase action screen and Webull cancellation flow. The matching gateway routes are deployed; this does not establish real broker access or enable live submissions.

## Run and install

Open `iOS/TradePilot.xcodeproj` in Xcode. Select TradePilot and an installed iPhone simulator to run. A physical installation requires Apple signing and a trusted, paired iPhone with Developer Mode turned on; see [WEBULL-SETUP.md](WEBULL-SETUP.md) and `scripts/install-iphone.sh`.

The already-deployed local gateway is described in [LOCAL-SERVICE.md](LOCAL-SERVICE.md). Configure inference with [LOCAL-AI.md](LOCAL-AI.md). Credentials and private runtime files are deliberately excluded from the source ZIP.

## Evidence and limits

[Verification](VERIFICATION.md) · [Backtest report](BACKTEST-REPORT.md) · [Reproduce backtests](BACKTESTING.md) · [Order integrity review](TRADE-INTEGRITY-REVIEW.md) · [Learning design](LEARNING-DESIGN.md)

The tested SMA strategy did not qualify for live adoption. Research profiles are not validated trading systems. Journaling provides retrieved context, not automatic model training. Demo prices and account balances are fictional and clearly labeled in the app.
