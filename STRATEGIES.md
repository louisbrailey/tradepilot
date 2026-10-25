# Fixed daily strategy experiments

`server/strategies.py` exposes `compare_strategies(rows)` for validated daily OHLC rows. It compares three fixed long/cash rules: SMA20 above SMA50, a prior-close breakout of the preceding 20 closes with a 20-close low exit, and a 2% below SMA20 mean-reversion entry with an exit at the mean. Breakout excludes the signal close from its reference range; moving averages include that prior close. Rules never inspect the execution day's close to make its opening decision.

All entries and exits occur at the following daily open, with forced liquidation at the final period close. Each stage starts independently with $10,000 cash, fractional shares and no leverage. Fees/slippage are modeled as 0/10/25/50 bps on each side; the baseline is 10. Benchmark is same-symbol buy-and-hold over identical opens/closes and costs. Drawdown uses daily closing marks, starting capital, and final liquidation costs; it does not represent intraday drawdown.

The earliest 60% is warm-up only, next 20% validation and final 20% final descriptive comparison. These are already-observed dates. Results are explicitly exploratory; no winner selection, parameter tuning, new unseen holdout or automatic promotion is claimed. Original SMA evaluation and its frozen reports are unchanged.

Reproduce without credentials or network requests:

```sh
python3 scripts/compare-strategies.py --cache-dir '/Users/louisbrailey/Documents/Codex/2026-09-10/i-w/work/private/backtest-cache' --output-dir reports/strategy-comparison-2026-09-23
```

The command reads owner-only cached records with verified raw hashes, and writes derived metrics, source timestamps/hashes and implementation hashes. It does not alter cache or observation records, publish raw licensed bars or submit orders. Current evidence is in [the comparison report](reports/strategy-comparison-2026-09-23/REPORT.md).

This is daily equity/ETF price research. Dividend optimization needs total-return/corporate-action data; shorts need borrow and financing; options need historical chains and realistic fills; FX, crypto and intraday approaches need their own data and execution assumptions. Those strategies are not implemented by relabeling these results. No future-profitability or deployment recommendation follows from this comparison.
