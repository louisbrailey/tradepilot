# Automated paper release 0.3.0 — November 5, 2026

Implemented, deployed and installed the first automated prospective paper feature. The user requested this as the next unfinished feature. The frozen initial protocol is documented in [AUTOMATED-PAPER.md](../AUTOMATED-PAPER.md): three existing fixed SPY rules, independent $10,000 virtual accounts, a 25%/$2,500 entry budget, 10 bps per side and a 10% observed drawdown stop. No rule/parameter selection was performed from the first observations.

## Implemented behavior

A gateway background worker checks the schedule without the phone being open. It saves next-session decisions after 20:15 ET, then records the corresponding daily-open simulated fills after the following session. Missing sessions are not retrospectively filled. Atomic per-session evidence, immutable protocol/code hashes, revision checks, bounded leases and unique keys prevent competing workers or restarts from duplicating fills. Manual paper and real broker execution paths are unchanged.

Data checks require the complete expected session set, explicit symbol and adjustment basis, finite positive OHLC/volume, matching prior observations and complete split coverage. Market-data outages retry within the same session window; gaps, source revisions, splits, missed sessions, protocol changes or drawdown stops preserve history and halt the run. Stop cancels pending simulations and retains recorded holdings; it does not pretend to liquidate them.

The app has start approval, stop-all and individual stops, status/heartbeat, balances, observed drawdown, saved next intent and event history. Its initial layout was compacted after inspecting the physical phone so account results appear sooner.

## Verification

- Final full gate passed: 13 core tests, 219 backend tests (one optional signing skip under the default interpreter), 41 script tests, Swift 6 typechecking and journal/connection/paper fixtures. Log: `.toolkit-runs/20261106T031233.443257Z.log`.
- All 219 backend tests passed under the deployed Python interpreter, including signing. Log: `.toolkit-runs/20261106T031014.016144Z.log`.
- Thirteen new automation tests cover first-observation/no-same-day-fill behavior, precommitted next-session entry, costed exit and cash conservation, drawdown stop, calendar/DST, missing/revised data, provider identity/adjustment/splits, bounded outages, stop during a fetch, concurrent workers, restart idempotency, late response and background operation. Additional route tests preserve service separation and strict payloads; authentication checks cover every new route. Native fixtures verify protocol/account/event decoding.
- Final signed iPhone build passed: `.toolkit-runs/20261106T031234.580665Z.log`. `devicectl` installed and launched 0.3.0 (build 3) on the existing USB iPhone 16, retaining pairing.
- Before deployment, the existing affected gateway modules matched the reviewed Git baseline. Old modules are retained in the gateway’s private `automation-code-backup-20261105`. No private credentials or existing manual/broker ledger were replaced.
- The first Mac-side diagnostic resolved the hostname to a different local listener and failed TLS. Retrying the actual LAN address while retaining hostname validation and exact certificate pinning succeeded. Phone requests also succeeded; no TLS verification was disabled.

## Initial forward observation

The three experiments were started through the physical phone’s explicit paper-only protocol confirmation. The background worker fetched complete Massive daily bars and split coverage, then recorded the November 5 session. An authenticated, hostname-verified and certificate-pinned state request returned HTTP 200 and confirmed:

| Experiment | Observations | Fills | Saved intent for November 6 |
| --- | ---: | ---: | --- |
| Trend SMA20/50 | 1 | 0 | Cash |
| 20-session breakout | 1 | 0 | Cash |
| Mean reversion | 1 | 0 | Long, entry budget $2,500 |

All remain running with $10,000 cash each. These are experimental simulated intentions, not recommendations. The stored protocol hashes match the current source. No broker account requests, real orders or transfers were made for this feature. No new manual paper fill was made.

Sanitized operational evidence: ignored `.toolkit-runs/automation-first-observation.json`. Phone evidence: ignored `.toolkit-runs/automated-paper-030.png`. Raw source bars and full experiment history stay in the gateway’s private automated-paper database.

## Remaining evidence and operating limits

The first actual future-session settlement cannot be verified until November 6 after 20:15 ET (17:15 Pacific), assuming the Mac is awake and complete data is available. Subsequent prospective results are not yet known; synthetic tests do not supply them. Custom universes/schedules, notifications, broader strategy families and performance promotion are outside this first fixed protocol.

The pinned calendar ends in 2028 and fails closed beyond its coverage. The gateway must remain running; no remote hosting or system sleep setting was changed. The user’s chosen local-development installation still needs signing refreshed before November 11 at 00:35 Pacific. Live trading and transfers remain disabled.
