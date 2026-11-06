# Automated prospective paper strategies

Version `prospective-paper-v1` is fixed before activation. It runs the existing trend SMA20/50, 20-session breakout and 2%-below-SMA20 mean-reversion rules on **SPY**, without selecting a winner or tuning parameters from these observations. Each experiment starts with an independent $10,000 simulated account. It cannot call a broker or mutate the manual paper account.

## Start, schedule and stop

Open **Overview → Automated paper strategies**, or the link in Paper trading. Review the fixed protocol and start the three experiments. Starting explicitly authorizes their future paper fills without per-order prompts. Real broker and manual paper confirmation rules are unchanged. The gateway’s background worker checks every minute; the phone app can be closed. Keep the Mac awake and the gateway running.

Each session is evaluated at or after **20:15 America/New_York**, with a window ending at midnight. This uses the pinned [NYSE 2026–2028 calendar](https://www.nyse.com/trade/hours-calendars), including holidays. Early-close sessions are also evaluated at 20:15. Unsupported calendar years fail closed. An unexpected market closure or missing bar halts rather than fabricating an observation.

The first observation only saves a signal for the next session. A signal is durably recorded before that next session begins. The corresponding simulated fill is recorded after that session, using its unadjusted daily-bar open plus modeled costs. Signal recording time, reference session and settlement observation time are distinct. These are delayed daily references, not verified exchange auction quotes or actual executions. No decision is retrospectively generated for a missed session.

The existing three rules operate on the last 50 validated closes. The next-session entry budget is fixed when the decision is recorded: at most 25% of the prior closing equity and $2,500, further limited by available cash at settlement. Shares round down to eight decimal places. There is no leverage or shorting. A holding is retained until the rule exits; the budget cap is not continuous portfolio rebalancing, and exposure can drift. Buys add and sales subtract **10 bps** from the reference price as a combined cost assumption. This is not a provider fee quote. Dividends, cash interest, taxes, borrow, impact and real liquidity are excluded.

At **10% observed peak-to-trough drawdown**, the experiment stops with recorded holdings retained. The stop is evaluated at daily observations and is not a guaranteed loss limit or simulated stop-loss liquidation. User Stop also cancels pending intentions and freezes the recorded ledger; it does not sell holdings. To continue, start a new experiment after all active ones stop. Previous protocols and history remain intact. Runs are not silently resumed across discontinuities. There is a limit of 30 preserved experiments pending a reviewed archiving policy.

## Data and persistence controls

- Only server-owned [Massive daily bars](https://massive.com/docs/rest/stocks/aggregates/custom-bars) and [split checks](https://massive.com/docs/rest/stocks/corporate-actions/splits) are requested. No client prices, arbitrary tickers, paths or broker account identifiers are accepted.
- Exactly 50 expected sessions must be present, ascending, with one midnight-ET bar per session, positive volume and consistent finite OHLC values. Symbol and unadjusted basis must match; incomplete pages are refused.
- Any split in the signal window stops the run. Split-query entitlement is required. Unavailable data retries at most once per 15 minutes within the same session window. Missing/invalid data or missed sessions stop the run without catch-up fills.
- Later data cannot rewrite previously observed overlapping OHLC bars. A correction halts the experiment for review. Original inputs and hashes stay in private evidence storage.
- Separate `automated-paper.sqlite3` stores immutable session observations, protocol/code hashes, pending decisions, ledger balances and event history. Protocol/code changes halt old runs; new behavior needs a new experiment.
- Short SQLite transactions and revision checks protect pause/start/settlement across multiple workers. Fetching never holds a write lock. Unique run/session keys prevent repeat settlement after restart. Crash recovery waits out a bounded lease.
- Authenticated API: `POST /v1/paper/automation/state` and `/check` accept `{}`; `/start` accepts exactly `{client_id: UUID, approved: true}`; `/pause` accepts exactly `{id: savedRunID | "all"}`. Start retries with the same UUID return the original group. `/check` obeys the normal time window and never forces a historical fill.

The app shows worker heartbeat, session counts, last marked date, equity, quantities, modeled costs, realized result, drawdown, next intent and recent events. A current heartbeat alone does not prove good data or strategy performance; inspect each run’s status and last session. Halted balances are frozen observations.

## Evidence boundaries

These are forward-recorded experiments, not live-adoption candidates. They do not train the model, optimize a strategy, select a profitable result, or demonstrate that live fills are achievable. A complete prospective cycle requires future sessions; synthetic tests prove accounting and control behavior only. Historical backtests and the existing manual paper ledger remain separately labeled.

Tests use fake market data and independent services sharing a temporary SQLite file. They cover first-day/no-lookahead behavior, next-session costed entry/exit, cash conservation, source revisions, missing history, split/adjustment/identity gates, holidays/DST, concurrent workers, restart idempotency, stop-during-fetch, late data, bounded retries and drawdown stops.
