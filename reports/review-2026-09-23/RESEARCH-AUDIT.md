# TradePilot research and backtest audit — September 23, 2026

**Share with caveats. Completeness: partial source verification; assigned software and offline-replay review complete.** Five confirmed defect families were repaired. The frozen strategy, parameters and original published report were preserved. The newly generated replay is a verification of already observed history, not a new prospective test.

[Refreshed backtest report](refreshed-replay/BACKTEST-REPORT.md) · [Refreshed machine-readable results](refreshed-replay/BACKTEST-SUMMARY.json) · [Independent calculations](INDEPENDENT-CHECK.json) · [Reproducible independent checker](check-backtest.py)

Seven symbols each contain 1,177 daily bars from January 3, 2022 through September 11, 2026. The requested bounds remain January 1, 2022 through September 11, 2026. Training ends October 23, 2024; validation is October 24, 2024 through October 2, 2025; the final period is October 3, 2025 through September 11, 2026. The initial replay matched the frozen implementation hashes. Both the initial and corrected replays matched every original numerical evaluation, raw/used input hash, and protocol hash. All final periods remain marked previously observed.

One symbol passed the validation screen (IWM), two beat the same-symbol benchmark in the final period (GLD and MSFT), and none did both. No return or drawdown was improved by the audit. This experiment supplies no basis for live strategy adoption.

## Checked scope

The audit covered `server/research.py`, `server/evaluation.py`, their tests, `scripts/evaluate-strategies.py`, its tests, the frozen public artifacts and the existing private cache. It inspected signals, warmup, train/validation/final separation, next-open fills, final-close liquidation, cost application, capital resets, drawdown, selection, result projection, private-cache checks and observation provenance. Other agents own the app UI, order flow, AI, deployment and broader integration checks.

The independent checker derives daily equity returns from changes in long/cash exposure, separate from the production cash/share ledger. It reconciled 119 runs: nine training candidate folds plus eight validation/final cost scenarios for each of seven symbols. Selected windows, returns, fill counts, benchmark returns and closing-equity drawdowns all agree; maximum numerical difference is 2.203e-13 percentage points. All simulated capital is independent by symbol, stage and fold; it is not a seven-asset portfolio return.

Totals below are scoped inventory counts, not percentages of complete verification. Zero observed defects does not establish that every possible source error or future behavior is ruled out.

## Report usefulness and quality

| Category | Observed defects | Assessment |
|---|---:|---|
| Usefulness and completeness | 0 / 2 | Frozen replay and independent calculation artifacts answer reproducibility and accounting questions; prospective performance remains outside these artifacts. |
| Analytical clarity | 0 / 2 | Both refreshed artifacts distinguish historical simulation, price returns, independent capital and already observed final periods. |
| Visual and interaction consistency | N/A | This review covers code and Markdown/JSON artifacts; app rendering is assigned separately. |

## Analytical correctness and robustness

| Category | Observed defects | Assessment |
|---|---:|---|
| Source authority and confidence | 7 / 7 | All legacy caches lack the discarded provider response's adjustment flag. The requested adjustment and frozen code/data replay are verified; actual response-envelope confirmation cannot be reconstructed. The refreshed output explicitly records null instead of inventing a confirmation. |
| Value accuracy | 0 / 119 | Independent exposure-based accounting reconciles returns, benchmark, fill count and closing-equity drawdown for all selected runs. |
| Within-chart agreement | N/A | No charts were authored. |
| Complete source details | 7 / 7 | Input hashes, requested query, retrieval time and stage dates remain intact; the seven legacy adjustment envelopes are unavailable. |
| Cross-artifact consistency | 0 / 7 | Each corrected evaluation matches its original frozen numerical results and used-input hash. |
| Data-quality controls | 0 / 7 | Every cached dataset passes strict finite positive OHLC, bounds, ascending timestamp and unique daily-date checks. Exchange-session completeness is not independently established by an exchange calendar. |
| Conclusion support | 0 / 1 | The statement that no symbol passed validation and beat its final benchmark is reproduced. It is not a statement of statistical significance or universal strategy performance. |

## Prioritized problems and fixes

1. **Research accepted invalid daily bars.** Boolean/numeric-string prices and two timestamps on one date could produce an available experiment; a malformed row in the evaluator could abort the all-symbol run with an uncaught attribute error. **Fixed:** shared strict daily validation rejects non-object rows, invalid numeric types, extreme timestamps and duplicate dates. Provider research additionally checks OHLC and requested bounds. Failure remains unavailable rather than substituted data.

2. **Requested adjustment was mistaken for confirmed adjustment.** The provider adapter dropped the response's `adjusted` value. A response reporting `false` could therefore be evaluated under split-adjusted assumptions. **Fixed for new observations:** both research and acquisition require actual boolean `true`, retain it in new caches and expose it as `provider_adjusted`. **Remaining provenance limitation:** legacy cached envelopes were not retained; they remain unknown and are clearly labeled. They were not re-downloaded or relabeled. Massive states that aggregate bars adjust splits, exclude dividends, and may change after later splits; the response envelope identifies the returned adjustment. [Official adjustment documentation](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends).

3. **Cache records and the frozen protocol had inconsistent validation.** Existing protocol JSON was reused without checking its contents; cache checks did not establish that every record was an owned regular file. **Fixed:** reads reject symlinks, nonregular files, public permissions, other owners, malformed JSON and non-object payloads. Existing protocol content must match its digest-named expected protocol. Raw-row hashes remain mandatory.

4. **Concurrent final observations could both appear new.** A controlled concurrent reproduction produced two false previously-observed flags for overlapping date ranges. **Fixed:** an owner-only file lock serializes observation scanning and creation. The concurrent regression now returns exactly one first observation and one previously observed result. The ledger still establishes only this evaluator's local observations; it cannot prove that no analyst or other software has seen the history.

5. **The app projection accepted inconsistent evaluation provenance.** Changing SPY's selected SMA from 20 to 50 was accepted without changing the saved locked-selection digest. **Fixed:** projection verifies that digest, exact stage index splits, metric dates, source adjustment request and full 10 bps baseline consistency. Tampered selection, stage boundaries, timestamps, fills and adjustment requests are rejected; the original frozen report still projects successfully.

A final resource-cleanup correction closes HTTP error responses before returning the unavailable result. The denied-entitlement regression uses a real in-memory response body and verifies that both the body and HTTP error are closed. It preserves the safe HTTP 403 reason without producing data or exposing provider content.

## Verification evidence

Focused regression suites pass: 15 research tests, 6 recorded-evaluation projection tests and 14 evaluator tests. The final research suite also passes with `ResourceWarning` treated as an error and emits no warnings. No broker or market-data API requests, new credentials, live orders or deployed-service mutations were used. The only network verification was public provider documentation. Parent review owns the final combined project gate.

Relevant complete local logs in `.toolkit-runs/`:

- `20260923T074605.740982Z.log`: initial exact replay.
- `20260923T074946.281459Z.log`: six projection tests.
- `20260923T080022.370645Z.log`: final research tests with resource warnings treated as errors.
- `20260923T075449.417405Z.log`: final evaluator tests.
- `20260923T080209.049899Z.log`: final corrected offline replay, including the finalized research implementation hash.
- `20260923T080209.420544Z.log`: 119 independent reconciliations against the finalized corrected report.

Reproduce the independent check with the same private cache without printing or publishing raw bars:

```sh
python3 reports/review-2026-09-23/check-backtest.py \
  --cache-dir /path/to/private/backtest-cache \
  --report reports/review-2026-09-23/refreshed-replay/BACKTEST-SUMMARY.json \
  --original BACKTEST-SUMMARY.json \
  --output /path/to/sanitized-independent-check.json
```

Only the existing SMA long/cash strategy is implemented. Research profiles are not separate backtested strategies. Options, shorts, dividend-income, intraday, news, crypto and FX strategies, prospective paper tracking, authoritative calendar completeness, dividend cash flows, taxes, interest, borrow, intraday liquidity and actual execution remain outside the evidence. Survivorship, correlated assets, one historical path and already observed outcomes limit inference.
