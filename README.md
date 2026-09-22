# TradePilot

A native iPhone assistant for reviewing portfolios, preparing explicitly confirmed trades, and keeping research and a trade journal together.

**Current verified status:** see [LATEST-STATUS.md](LATEST-STATUS.md). The app runs in Apple’s iPhone simulator with working local AI and real Massive research. Physical-phone installation and Webull account authorization remain blocked. Live trading is disabled.

## Included

- SwiftUI overview, portfolio table, assistant, research/journal, and Webull account screens.
- Local Ollama inference or optional OpenAI, strict structured proposals, independent order validation, and separate confirmation.
- Webull long-stock DAY market/limit order adapter with durable no-duplicate submission and execution evidence.
- Real Massive/Benzinga research and reproducible multi-stage historical evaluation with results in the app.
- Private TLS pairing, Keychain access token, and a per-user Mac gateway.

## Run and install

Open `iOS/TradePilot.xcodeproj` in Xcode. Select TradePilot and an installed iPhone simulator to run. A physical installation requires Apple signing and an available trusted device; see [WEBULL-SETUP.md](WEBULL-SETUP.md) and `scripts/install-iphone.sh`.

The already-deployed local gateway is described in [LOCAL-SERVICE.md](LOCAL-SERVICE.md). Configure inference with [LOCAL-AI.md](LOCAL-AI.md). Credentials and private runtime files are deliberately excluded from the source ZIP.

## Evidence and limits

[Verification](VERIFICATION.md) · [Backtest report](BACKTEST-REPORT.md) · [Reproduce backtests](BACKTESTING.md) · [Order integrity review](TRADE-INTEGRITY-REVIEW.md) · [Learning design](LEARNING-DESIGN.md)

The tested SMA strategy did not qualify for live adoption. Research profiles are not validated trading systems. Journaling provides retrieved context, not automatic model training. Demo prices and account balances are fictional and clearly labeled in the app.
