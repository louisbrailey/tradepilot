# Exploratory daily strategy comparison

Already-observed history; this is not a fresh holdout, a recommendation, or evidence of deployability. No parameters were optimized. The first 60% supplies warm-up only, followed by 20% validation and 20% final descriptive periods. Each starts in cash independently. Costs are 0, 10, 25 and 50 bps per side. The table uses 10 bps.

| Symbol | Fixed strategy | Validation return % | Final return % | Final benchmark % | Final drawdown % | Final fills |
|---|---|---:|---:|---:|---:|---:|
| SPY | trend_sma_20_50 | 7.56 | 8.50 | 13.85 | 5.07 | 4 |
| SPY | breakout_20 | 16.20 | -2.72 | 13.85 | 7.37 | 12 |
| SPY | mean_reversion_20 | 2.79 | 5.23 | 13.85 | 5.79 | 8 |
| QQQ | trend_sma_20_50 | 15.57 | 11.07 | 17.63 | 7.88 | 8 |
| QQQ | breakout_20 | 24.19 | 0.45 | 17.63 | 13.75 | 10 |
| QQQ | mean_reversion_20 | -0.07 | 15.24 | 17.63 | 6.66 | 16 |
| IWM | trend_sma_20_50 | 12.82 | -1.85 | 17.51 | 9.62 | 6 |
| IWM | breakout_20 | 3.98 | -1.56 | 17.51 | 10.51 | 10 |
| IWM | mean_reversion_20 | -7.72 | 3.39 | 17.51 | 6.19 | 12 |
| TLT | trend_sma_20_50 | -0.11 | -8.87 | -9.95 | 11.19 | 6 |
| TLT | breakout_20 | -13.76 | -8.26 | -9.95 | 9.94 | 10 |
| TLT | mean_reversion_20 | -2.16 | -0.57 | -9.95 | 3.75 | 8 |
| GLD | trend_sma_20_50 | 31.43 | 12.29 | 11.44 | 19.47 | 4 |
| GLD | breakout_20 | 9.70 | 7.14 | 11.44 | 20.31 | 8 |
| GLD | mean_reversion_20 | 11.95 | -2.98 | 11.44 | 14.53 | 18 |
| AAPL | trend_sma_20_50 | 0.46 | 5.19 | 30.21 | 18.29 | 8 |
| AAPL | breakout_20 | 12.81 | 5.21 | 30.21 | 14.52 | 10 |
| AAPL | mean_reversion_20 | 23.24 | 5.52 | 30.21 | 12.71 | 12 |
| MSFT | trend_sma_20_50 | 14.72 | -15.24 | -4.34 | 21.52 | 6 |
| MSFT | breakout_20 | 11.67 | 5.80 | -4.34 | 20.46 | 8 |
| MSFT | mean_reversion_20 | 4.03 | -9.07 | -4.34 | 19.58 | 16 |

Input hashes, source retrieval times, implementation hashes, dates, rules and all cost scenarios are in SUMMARY.json. Original reports and cache are unchanged. Legacy adjustment flags are unknown; no envelope metadata has been invented. Raw licensed bars are excluded.

Daily price returns omit dividends and therefore cannot evaluate dividend optimization. No short/borrow, options, FX, crypto, intraday, taxes, cash interest, volume/market-impact model or news strategy is tested. Surviving securities and correlated assets limit inference. Prospective paper observation remains necessary.
