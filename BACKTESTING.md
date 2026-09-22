# Reproduce TradePilot's strategy evaluation

The evaluator exercises the same daily-bar strategy engine used by the Research tab. It never calls a broker and cannot trade. It covers a predeclared universe of SPY, QQQ, IWM, TLT, GLD, AAPL and MSFT, with SMA windows of 10, 20 and 50 bars. It does not implement or validate short, dividend, intraday, option, crypto, FX or news strategies.

From this source directory, run with Python 3.9 or later:

```sh
python3 scripts/evaluate-strategies.py \
  --market-env /path/to/private/market.env \
  --cache-dir /path/to/private/backtest-cache \
  --start 2022-01-01 --end 2026-09-11
```

The environment file can contain `MASSIVE_API_KEY` or the existing Signal Forge market-data settings; it is parsed without executing shell commands. Never put a key in a command argument. The cache must be owned by the current user and mode 700; cached files are mode 600. Do not distribute the cache. Public outputs are `BACKTEST-REPORT.md` and `BACKTEST-SUMMARY.json`, containing derived metrics and provenance hashes, not raw vendor bars.

Replay the exact cached dataset without network access:

```sh
python3 scripts/evaluate-strategies.py \
  --cache-dir /path/to/private/backtest-cache \
  --start 2022-01-01 --end 2026-09-11 --offline
```

The recorded implementation hashes and input hashes must match for an exact code/data replay. The evaluation timestamp and cache/repeated-observation flags will change. Never delete observation records to present a previously evaluated holdout as unseen. The local ledger can only record runs performed by this evaluator; it cannot establish that no person or other tool has seen the historical data.

The protocol is persisted before data acquisition. The first 60% of daily bars are training history; its latter half contains three chronological candidate-scoring folds. The next 20% is validation; the final 20% is a separate final test. Warmup closes come from preceding bars only. Training selects the window by mean fold return; validation decides only whether the fixed research screen passes. The final test evaluates all selected windows, including those that failed validation. Cost stress of 0, 10, 25 and 50 bps per side never changes the selected window.

The screen is fixed in advance: positive excess return against the same-symbol price benchmark, no greater drawdown than that benchmark, and at least two fills at 10 bps per side. This is a research filter, not a guarantee, statistically established edge, or live-trading approval. A final holdout is consumed once observed; repeating it verifies reproducibility and does not create new evidence. Any changed hypothesis needs a new, prospective evaluation period.

All positions are fractional and long/cash, enter at a subsequent daily open, and close at the final daily close if still open. Each run starts with $10,000 independently. Returns are not combined across symbols or stages. Closing-equity drawdown excludes intraday troughs. Split-adjusted bars do not include dividend income; the evaluator therefore cannot establish dividend or income performance.

Automated checks reject short/partial/unordered/duplicate/nonfinite/out-of-range data, test future-price mutation invariance, and independently reconcile round-trip and benchmark return calculations. A partial or denied provider response produces an unavailable result, never simulated substitute data. Exit code 1 means at least one expected symbol was unavailable; the report retains all failures. The JSON reports cross-symbol date-set agreement, but an authoritative exchange calendar is still needed to conclusively identify missing sessions.

Run the meaningful checks without fetching market data:

```sh
python3 -m unittest discover -s scripts -p 'test_evaluate_strategies.py' -v
```

The full project check script includes these tests. Source interpretation is based on [Massive Custom Bars](https://massive.com/docs/rest/stocks/aggregates) and [Massive's adjustment explanation](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends).
