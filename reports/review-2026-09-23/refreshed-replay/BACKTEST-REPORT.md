# TradePilot backtest report

**The current SMA experiment does not support live adoption: none of the evaluated symbols both passed validation and beat its final-period benchmark.**

Evaluation: 2026-09-23T08:02:09.101603+00:00. Protocol: `1420f3748daedcd5f892d4d4a4be404ceb2959795094ab511fd10277bb9b2cf0`.
Requested market history: 2022-01-01 through 2026-09-11.

This evaluates the existing long/cash SMA strategy across seven predeclared US-listed stocks and ETFs. Each symbol selects one of 10, 20 or 50 bars from three training folds, locks it, checks a separate validation period, then observes the final holdout. The 60/20/20 split uses each symbol's daily bar count. Final results are now observed and cannot serve as an unseen test for later changes.

Returns below are simulated price returns at 10 bps cost per side. The benchmark buys and holds the same symbol over exactly the same stage. Dividends are excluded, materially limiting income and bond ETF comparisons. Each run resets to $10,000; these are independent experiments, not a combined portfolio.

| Symbol | Bars | SMA | Validation excess (pp) | Validation screen | Final return | Final benchmark | Final excess (pp) | Final drawdown |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| SPY | 1177 | 20 | -9.98 | Fail | -2.64% | +13.85% | -16.49 | 11.77% |
| QQQ | 1177 | 20 | -9.62 | Fail | -11.31% | +17.63% | -28.94 | 19.65% |
| IWM | 1177 | 50 | +7.96 | Pass | +4.72% | +17.51% | -12.79 | 10.05% |
| TLT | 1177 | 10 | -7.38 | Fail | -13.38% | -9.95% | -3.42 | 14.77% |
| GLD | 1177 | 50 | -17.96 | Fail | +20.03% | +11.44% | +8.59 | 15.37% |
| AAPL | 1177 | 20 | -12.51 | Fail | +23.25% | +30.21% | -6.97 | 10.91% |
| MSFT | 1177 | 50 | -12.31 | Fail | -3.04% | -4.34% | +1.30 | 16.48% |

7/7 symbols produced valid datasets; 1 passed the fixed validation screen; 2 beat their benchmark in the final period. A passing screen is a research filter, not statistical significance or an instruction to trade.

## Cost stress and date boundaries

Windows stay fixed in every scenario. Costs are assumptions, not confidence intervals. Drawdown uses daily close marks and final liquidation; intraday drawdowns and executable opening liquidity are not observed.

| Symbol | Training through | Validation dates | Final dates | Final at 0 bps | 10 bps | 25 bps | 50 bps | Final fills |
|---|---|---|---|---:|---:|---:|---:|---:|
| SPY | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | +1.13% | -2.64% | -8.04% | -16.37% | 38 |
| QQQ | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | -7.32% | -11.31% | -16.97% | -25.62% | 44 |
| IWM | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | +6.62% | +4.72% | +1.93% | -2.55% | 18 |
| TLT | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | -8.94% | -13.38% | -19.64% | -29.08% | 50 |
| GLD | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | +20.51% | +20.03% | +19.31% | +18.12% | 4 |
| AAPL | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | +25.73% | +23.25% | +19.60% | +13.77% | 20 |
| MSFT | 2024-10-23 | 2024-10-24–2025-10-02 | 2025-10-03–2026-09-11 | -1.67% | -3.04% | -5.05% | -8.32% | 14 |

## Integrity and interpretation

New downloads require the provider response to confirm split adjustment. Legacy cached snapshots retain an unknown provider-adjustment flag; their frozen request and exact replay are verified, but the discarded response envelope cannot be reconstructed.

Every accepted dataset passed finite positive OHLC, high/low consistency, ascending unique timestamps, unique daily dates, requested-date bounds, minimum-history and full-page checks. Missing exchange sessions cannot be conclusively identified without a separately sourced exchange calendar; cross-symbol date-set agreement is reported in the JSON. No missing bar is filled or invented.

Mutation checks verify that changing all future prices leaves training selection unchanged, changing final-holdout prices leaves validation unchanged, and current/future prices cannot alter the first holdout entry decision. Independent round-trip accounting reconciles strategy and benchmark returns for both validation and final stages at every cost assumption. These checks cover this daily-bar algorithm, not every possible source revision or modeling bias.

The fixed validation screen requires positive benchmark excess, no greater drawdown than benchmark, and at least two fills at 10 bps per side. The final period is evaluated even for failed screens to avoid hiding adverse results. No parameter was changed in response to these outcomes. This is a computational separation of historical data; it cannot establish that no analyst or earlier tool has ever observed that history.

The seven symbols were chosen before this run for equity, bond ETF and gold ETF coverage. They are surviving, well-known securities, not a point-in-time universe. Correlated assets, one history, model selection and survivorship bias limit inference. Split-adjusted prices can be revised; input hashes preserve the exact cached snapshot. No dividends, taxes, cash interest, borrow, market impact, intraday strategies, shorts, options, FX, crypto, news signals or execution reliability are tested. Prospective paper evaluation is still required before reconsidering any strategy for actual use.

## Reproduce and inspect

`scripts/evaluate-strategies.py` freezes the protocol before fetching data and stores exact raw daily bars only in an owner-only private cache. `BACKTEST-SUMMARY.json` includes source request metadata, input hashes, implementation hashes, per-fold metrics, stage dates, checks and fixed cost scenarios. It contains no API credentials or raw bars. The private observation ledger labels a repeated final test as previously observed; changing a protocol does not erase that fact.

Run using the private paths documented in `BACKTESTING.md`. An offline replay must use the same cache, date range and code; a fresh vendor download may change after data corrections. This report is ready for review within its daily-bar research scope and must be shared with these limitations.

Source: [Massive Custom Bars documentation](https://massive.com/docs/rest/stocks/aggregates). Its `adjusted` flag adjusts for splits. [Massive adjustment explanation](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends) distinguishes split adjustment from dividends.
