# Kronos in TradePilot

Open **Research → Kronos forecasting lab**. Enter a US stock ticker, choose a 5- or 20-session horizon, then run a historical replay. Save the result to the research journal if useful.

The gateway retrieves complete adjusted daily OHLCV from the existing Massive account, takes 128 input bars immediately preceding the held-out window, and runs the cached `NeoQuasar/Kronos-small` model on the Mac. Only input bars and held-out timestamps enter inference; held-out prices/volume never do. Three seeded paths produce a mean close forecast and a min/max sampling range. This range is not a calibrated confidence interval.

The app plots the predicted close against actual prices and an unchanged-price baseline, and reports mean absolute error for both. These are price errors, not strategy returns. Model pretraining overlap is not verified. A favorable replay is not evidence of future profitability. There is no order recommendation, broker access, automatic trading, or model training in this feature.

## Runtime

The existing local Kronos Python environment is reused; no PyTorch dependency is added to the gateway environment. Defaults:

- Model checkout: `~/my-stack/Kronos`
- Python: `~/my-stack/Kronos/.venv/bin/python`

Optional server-side overrides: `KRONOS_HOME` and `KRONOS_PYTHON` in the private gateway config. Model weights must already be cached. Inference runs offline, on CPU, with a 90-second timeout and a single active replay. Its subprocess receives no gateway token, broker keys, or market-data key. Errors fail closed; there is no simulated prediction fallback.

Authenticated POST endpoints:

- `/v1/kronos/status` with `{}`: installation presence only, not a successful model probe.
- `/v1/kronos/replay` with `{"ticker":"AAPL","horizon":5}`: historical replay (horizon 5 or 20).

## October 1, 2026 verification

- 156 backend tests (including 8 Kronos tests), 36 script tests, 13 core tests, existing native smoke checks and Swift typechecking passed through `scripts/check.sh`.
- Native iOS Simulator build passed and was installed/launched in the iPhone 17 Pro runtime.
- Real AAPL five-session inference succeeded with existing market data and model weights. Evidence: `reports/kronos/real-replay.json`.
- Targeted deployment to the existing private gateway completed. An authenticated HTTPS replay succeeded with TLS certificate verification: `reports/kronos/deployed-replay.json`. Broker config and live-disabled settings were preserved. Original server code backed up under the gateway's private directory.
- Simulator GUI app is missing on this Mac; visual interaction and journal-button behavior have not been verified in the running native UI. Physical iPhone installation was not performed.
- The Mac's own `.local` name resolved to its loopback address during the Python probe, reaching a different existing service on port 8787. Deployment verification used the gateway's LAN address with the original hostname for TLS verification. No DNS or certificate protections were changed. Physical-device routing must be checked separately.

Existing Webull application credentials are present, but authentication failed during the preceding connection check. That is independent of this research feature. No orders were placed.

The unsigned physical-iPhone architecture build also passed (this is not an installation). The deployed 20-session AAPL replay succeeded: `reports/kronos/deployed-replay-20.json`. In that particular replay, Kronos MAE was 16.724 versus 8.996 for the unchanged-close baseline; the model was worse. The five-session replay had MAE 4.481 versus 4.530. Neither isolated result supports trading profitability.
