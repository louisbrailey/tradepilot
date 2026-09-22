#!/usr/bin/env python3
"""Read-only, reproducible stock-strategy evaluation. Never places orders.

Source bars stay in an owner-only cache; public artifacts contain derived metrics
and hashes. A previously observed final holdout is never called unseen again.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from research import Massive, load_market_env, simulate

VERSION = "sma-multistage-v1"
SYMBOLS = ("SPY", "QQQ", "IWM", "TLT", "GLD", "AAPL", "MSFT")
WINDOWS = (10, 20, 50)
COSTS = (0, 10, 25, 50)
MIN_BARS = 500


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def iso_day(timestamp):
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()


def protocol(symbols, start, end):
    return {
        "version": VERSION, "symbols": list(symbols), "requested_start": start,
        "requested_end": end, "windows": list(WINDOWS), "costs_bps_per_side": list(COSTS),
        "split": [0.6, 0.2, 0.2], "minimum_bars": MIN_BARS,
        "selection": "Highest mean return across three contiguous folds in the latter half of training; ties prefer shorter window. No validation or holdout selection.",
        "validation_gate": "Excess price return > 0, drawdown <= same-symbol benchmark drawdown, and at least two fills at 10 bps per side. Research screening only.",
        "final_holdout": "Evaluate every train-selected window once, even when validation fails; do not tune from final results. Replay is labeled previously observed.",
        "capital": "Independent $10,000 start per symbol/stage/fold/scenario; fractional long/cash positions, no leverage or interest.",
        "execution": "Previous close versus SMA of preceding closes; next daily bar open; forced liquidation at final close; fixed cost on both sides.",
        "benchmark": "Same-symbol buy-and-hold price return, identical initial/final dates and per-side costs; dividends excluded.",
    }


def validated_bars(rows, start, end):
    if not isinstance(rows, list) or len(rows) < MIN_BARS:
        raise ValueError("At least 500 daily bars are required; no smaller fallback is evaluated")
    clean, previous, days = [], -1, set()
    for row in rows:
        timestamp = row.get("t")
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp) or timestamp <= previous):
            raise ValueError("Daily timestamps must be finite, unique and ascending")
        day = iso_day(timestamp)
        if day in days or not start <= day <= end:
            raise ValueError("Duplicate daily date or bar outside requested date range")
        prices = {}
        for key in ("o", "h", "l", "c"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError("OHLC prices must be finite positive numbers")
            prices[key] = float(value)
        if prices["l"] > min(prices["o"], prices["c"]) or prices["h"] < max(prices["o"], prices["c"]):
            raise ValueError("OHLC prices violate high/low bounds")
        clean.append(dict(t=timestamp, **prices))
        days.add(day)
        previous = timestamp
    return clean


def compact(run):
    return {key: value for key, value in run.items() if key != "fill_log"}


def select_training(bars, train_stop):
    first = train_stop // 2
    boundaries = [first + (train_stop - first) * i // 3 for i in range(4)]
    candidates = {}
    for window in WINDOWS:
        folds = [compact(simulate(bars, window, boundaries[i], boundaries[i + 1], 10)) for i in range(3)]
        candidates[str(window)] = {"folds": folds,
            "mean_fold_return_pct": statistics.mean(row["return_pct"] for row in folds),
            "worst_fold_drawdown_pct": max(row["max_drawdown_pct"] for row in folds)}
    selected = max(WINDOWS, key=lambda n: (candidates[str(n)]["mean_fold_return_pct"], -n))
    return {"selected_window": selected, "candidates": candidates,
            "fold_boundaries": boundaries, "training_stop_exclusive": train_stop}


def stage(bars, window, start, stop):
    base = compact(simulate(bars, window, start, stop, 10))
    base["excess_return_pct"] = base["return_pct"] - base["benchmark_price_return_pct"]
    return {"start_index": start, "stop_index_exclusive": stop,
            "start_date": iso_day(bars[start]["t"]), "end_date": iso_day(bars[stop - 1]["t"]),
            "baseline": base, "cost_sensitivity": {
                str(cost): compact(simulate(bars, window, start, stop, cost)) for cost in COSTS}}


def mutated_after(bars, index):
    result = [dict(row) for row in bars]
    for i in range(index, len(result)):
        value = 3.0 if i % 2 else 3000.0
        result[i].update(o=value, h=value, l=value, c=value)
    return result


def independent_return(bars, window, start, stop, cost_bps):
    """Independent multiplicative round-trip accounting, not the cash engine."""
    factor, entry = 1.0, None
    cost = cost_bps / 10000
    for i in range(start, stop):
        signal = bars[i - 1]["c"] > statistics.mean(row["c"] for row in bars[i - window:i])
        if signal and entry is None:
            entry = bars[i]["o"]
        elif not signal and entry is not None:
            factor *= bars[i]["o"] * (1 - cost) / (entry * (1 + cost))
            entry = None
    if entry is not None:
        factor *= bars[stop - 1]["c"] * (1 - cost) / (entry * (1 + cost))
    return (factor - 1) * 100


def evaluate(bars):
    train_stop, validation_stop = len(bars) * 3 // 5, len(bars) * 4 // 5
    training = select_training(bars, train_stop)
    window = training["selected_window"]
    validation = stage(bars, window, train_stop, validation_stop)
    base = validation["baseline"]
    validation["screen_passed"] = (base["excess_return_pct"] > 0
        and base["max_drawdown_pct"] <= base["benchmark_max_drawdown_pct"] and base["fills"] >= 2)
    # Lock training/validation outputs before any final-stage computation.
    selection_sha = digest({"training": training, "validation": validation})
    final = stage(bars, window, validation_stop, len(bars))
    train_mutated = select_training(mutated_after(bars, train_stop), train_stop)
    final_mutated = mutated_after(bars, validation_stop)
    validation_replay = stage(final_mutated, window, train_stop, validation_stop)
    validation_replay["screen_passed"] = validation["screen_passed"]
    first = simulate(bars, window, validation_stop, len(bars), 10)["fill_log"]
    first_changed = simulate(mutated_after(bars, validation_stop), window, validation_stop, len(bars), 10)["fill_log"]
    # Fill prices change when the current open changes; compare same-bar buy decision only.
    initial_decision = bool(first and first[0]["index"] == validation_stop and first[0]["side"] == "buy")
    changed_decision = bool(first_changed and first_changed[0]["index"] == validation_stop and first_changed[0]["side"] == "buy")
    errors, reconciliation = [], []
    for label, begin, stop, result in (("validation", train_stop, validation_stop, validation),
                                     ("final_holdout", validation_stop, len(bars), final)):
        for cost in COSTS:
            expected = independent_return(bars, window, begin, stop, cost)
            observed = result["cost_sensitivity"][str(cost)]["return_pct"]
            errors.append(abs(expected - observed))
            reconciliation.append(math.isclose(expected, observed, rel_tol=1e-10, abs_tol=1e-8))
            expected_benchmark = (bars[stop - 1]["c"] * (1 - cost / 10000)
                                  / (bars[begin]["o"] * (1 + cost / 10000)) - 1) * 100
            observed_benchmark = result["cost_sensitivity"][str(cost)]["benchmark_price_return_pct"]
            errors.append(abs(expected_benchmark - observed_benchmark))
            reconciliation.append(math.isclose(expected_benchmark, observed_benchmark, rel_tol=1e-10, abs_tol=1e-8))
    checks = {
        "training_invariant_to_all_future_prices": train_mutated == training,
        "validation_invariant_to_holdout_prices": validation_replay == validation,
        "first_holdout_decision_invariant_to_current_and_future_prices": initial_decision == changed_decision,
        "chronological_nonoverlap": 50 < train_stop < validation_stop < len(bars),
        "independent_return_and_benchmark_reconciliation": all(reconciliation),
    }
    if not all(checks.values()):
        raise ValueError("Evaluation integrity checks failed")
    return {"training": training, "validation": validation, "final_holdout": final,
            "locked_selection_sha256": selection_sha, "integrity_checks": checks,
            "maximum_reconciliation_error_percentage_points": max(errors)}


def private_directory(path):
    path = Path(path).expanduser()
    if path.is_symlink():
        raise ValueError("Private cache must not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Private cache must be owner-only (mode 700)")
    return path


def private_json(path, payload):
    # Refuse overwrite/symlink following. A run never replaces cached observations.
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(payload, stream, sort_keys=True, allow_nan=False)


def mark_observation(cache, ticker, first, last, protocol_sha, timestamp):
    """Track overlapping final-date ranges, including protocol/date-bound changes."""
    seen = False
    for path in cache.glob("observed-*.json"):
        if path.is_symlink():
            raise ValueError("Observation ledger must not contain symlinks")
        previous = json.loads(path.read_text())
        if previous.get("ticker") == ticker and previous["start"] <= last and previous["end"] >= first:
            seen = True
    path = cache / ("observed-" + digest({"ticker": ticker, "start": first, "end": last}) + ".json")
    if not path.exists():
        private_json(path, {"first_observed_at": timestamp, "ticker": ticker,
                           "start": first, "end": last, "protocol_sha256": protocol_sha})
    return seen


def acquire(client, ticker, start, end, cache, offline):
    cache_file = cache / (ticker + "-" + start + "-" + end + ".json")
    if cache_file.exists():
        if cache_file.is_symlink() or cache_file.stat().st_mode & 0o077:
            raise ValueError("Cached bars must be an owner-only regular file")
        payload = json.loads(cache_file.read_text())
        if (payload.get("ticker"), payload.get("start"), payload.get("end")) != (ticker, start, end):
            raise ValueError("Cache source metadata mismatch")
        if digest(payload["rows"]) != payload.get("raw_rows_sha256"):
            raise ValueError("Cache content hash mismatch")
        payload["cache_replay"] = True
        return payload
    if offline:
        raise ValueError("No exact private cache available for offline evaluation")
    response = client.get(f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                          {"adjusted": "true", "sort": "asc", "limit": 50000})
    if not response["available"]:
        raise ValueError(response["reason"])
    if response["partial_page"]:
        raise ValueError("Provider returned a partial page; evaluation refused")
    rows = response["results"]
    validated_bars(rows, start, end)
    payload = {"ticker": ticker, "start": start, "end": end, "rows": rows,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "raw_rows_sha256": digest(rows), "provider_request_id": response.get("request_id"),
        "cache_replay": False}
    private_json(cache_file, payload)
    return payload


def markdown(report):
    valid = [r for r in report["results"].values() if r["available"]]
    both = sum(r["evaluation"]["validation"]["screen_passed"] and r["evaluation"]["final_holdout"]["baseline"]["excess_return_pct"] > 0 for r in valid)
    assessment = ("The current SMA experiment does not support live adoption: none of the evaluated symbols both passed validation and beat its final-period benchmark."
                  if valid and not both else "Historical results are research evidence only and do not establish readiness for live trading.")
    lines = ["# TradePilot backtest report", "", "**" + assessment + "**", "",
        f"Evaluation: {report['evaluated_at']}. Protocol: `{report['protocol_sha256']}`.",
        f"Requested market history: {report['protocol']['requested_start']} through {report['protocol']['requested_end']}.", "",
        "This evaluates the existing long/cash SMA strategy across seven predeclared US-listed stocks and ETFs. Each symbol selects one of 10, 20 or 50 bars from three training folds, locks it, checks a separate validation period, then observes the final holdout. The 60/20/20 split uses each symbol's daily bar count. Final results are now observed and cannot serve as an unseen test for later changes.", "",
        "Returns below are simulated price returns at 10 bps cost per side. The benchmark buys and holds the same symbol over exactly the same stage. Dividends are excluded, materially limiting income and bond ETF comparisons. Each run resets to $10,000; these are independent experiments, not a combined portfolio.", "",
        "| Symbol | Bars | SMA | Validation excess (pp) | Validation screen | Final return | Final benchmark | Final excess (pp) | Final drawdown |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|"]
    for ticker, row in report["results"].items():
        if not row["available"]:
            lines.append(f"| {ticker} | unavailable | — | — | {row['reason']} | — | — | — | — |")
            continue
        val, final = row["evaluation"]["validation"], row["evaluation"]["final_holdout"]
        b = final["baseline"]
        lines.append(f"| {ticker} | {row['source']['bar_count']} | {row['evaluation']['training']['selected_window']} | {val['baseline']['excess_return_pct']:+.2f} | {'Pass' if val['screen_passed'] else 'Fail'} | {b['return_pct']:+.2f}% | {b['benchmark_price_return_pct']:+.2f}% | {b['excess_return_pct']:+.2f} | {b['max_drawdown_pct']:.2f}% |")
    available = [r for r in report["results"].values() if r["available"]]
    passed = sum(r["evaluation"]["validation"]["screen_passed"] for r in available)
    beaten = sum(r["evaluation"]["final_holdout"]["baseline"]["excess_return_pct"] > 0 for r in available)
    lines += ["", f"{len(available)}/{len(report['results'])} symbols produced valid datasets; {passed} passed the fixed validation screen; {beaten} beat their benchmark in the final period. A passing screen is a research filter, not statistical significance or an instruction to trade.", "",
        "## Cost stress and date boundaries", "",
        "Windows stay fixed in every scenario. Costs are assumptions, not confidence intervals. Drawdown uses daily close marks and final liquidation; intraday drawdowns and executable opening liquidity are not observed.", "",
        "| Symbol | Training through | Validation dates | Final dates | Final at 0 bps | 10 bps | 25 bps | 50 bps | Final fills |",
        "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for ticker, row in report["results"].items():
        if not row["available"]:
            continue
        ev = row["evaluation"]; val = ev["validation"]; final = ev["final_holdout"]
        stress = " | ".join(f"{final['cost_sensitivity'][str(c)]['return_pct']:+.2f}%" for c in COSTS)
        lines.append(f"| {ticker} | {row['source']['training_end_date']} | {val['start_date']}–{val['end_date']} | {final['start_date']}–{final['end_date']} | {stress} | {final['baseline']['fills']} |")
    lines += ["", "## Integrity and interpretation", "",
        "Every accepted dataset passed finite positive OHLC, high/low consistency, ascending unique timestamps, unique daily dates, requested-date bounds, minimum-history and full-page checks. Missing exchange sessions cannot be conclusively identified without a separately sourced exchange calendar; cross-symbol date-set agreement is reported in the JSON. No missing bar is filled or invented.", "",
        "Mutation checks verify that changing all future prices leaves training selection unchanged, changing final-holdout prices leaves validation unchanged, and current/future prices cannot alter the first holdout entry decision. Independent round-trip accounting reconciles strategy and benchmark returns for both validation and final stages at every cost assumption. These checks cover this daily-bar algorithm, not every possible source revision or modeling bias.", "",
        "The fixed validation screen requires positive benchmark excess, no greater drawdown than benchmark, and at least two fills at 10 bps per side. The final period is evaluated even for failed screens to avoid hiding adverse results. No parameter was changed in response to these outcomes. This is a computational separation of historical data; it cannot establish that no analyst or earlier tool has ever observed that history.", "",
        "The seven symbols were chosen before this run for equity, bond ETF and gold ETF coverage. They are surviving, well-known securities, not a point-in-time universe. Correlated assets, one history, model selection and survivorship bias limit inference. Split-adjusted prices can be revised; input hashes preserve the exact cached snapshot. No dividends, taxes, cash interest, borrow, market impact, intraday strategies, shorts, options, FX, crypto, news signals or execution reliability are tested. Prospective paper evaluation is still required before reconsidering any strategy for actual use.", "",
        "## Reproduce and inspect", "",
        "`scripts/evaluate-strategies.py` freezes the protocol before fetching data and stores exact raw daily bars only in an owner-only private cache. `BACKTEST-SUMMARY.json` includes source request metadata, input hashes, implementation hashes, per-fold metrics, stage dates, checks and fixed cost scenarios. It contains no API credentials or raw bars. The private observation ledger labels a repeated final test as previously observed; changing a protocol does not erase that fact.", "",
        "Run using the private paths documented in `BACKTESTING.md`. An offline replay must use the same cache, date range and code; a fresh vendor download may change after data corrections. This report is ready for review within its daily-bar research scope and must be shared with these limitations.", "",
        "Source: [Massive Custom Bars documentation](https://massive.com/docs/rest/stocks/aggregates). Its `adjusted` flag adjusts for splits. [Massive adjustment explanation](https://massive.com/knowledge-base/article/is-massives-stock-data-adjusted-for-splits-or-dividends) distinguishes split adjustment from dividends.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-env")
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default=(datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    parser.add_argument("--output-dir", default=str(ROOT))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start >= end or end >= datetime.now(timezone.utc).date():
        parser.error("Use a chronological historical range ending before today (UTC)")
    cache = private_directory(args.cache_dir)
    frozen = protocol(SYMBOLS, args.start, args.end)
    protocol_sha = digest(frozen)
    frozen_file = cache / ("protocol-" + protocol_sha + ".json")
    if not frozen_file.exists():
        private_json(frozen_file, {"frozen_at": datetime.now(timezone.utc).isoformat(), "protocol": frozen})
    if args.market_env:
        load_market_env(args.market_env)
    client = None if args.offline else Massive()
    report = {"schema_version": 1, "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": frozen, "protocol_sha256": protocol_sha,
        "implementation_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), ROOT / "server" / "research.py")}, "results": {}}
    date_sets = []
    for ticker in SYMBOLS:
        try:
            payload = acquire(client, ticker, args.start, args.end, cache, args.offline)
            bars = validated_bars(payload["rows"], args.start, args.end)
            # Mark source-date holdout exposure independently of protocol so retuning
            # cannot reset its status. Mark before evaluation for conservative retries.
            seen = mark_observation(cache, ticker, iso_day(bars[len(bars) * 4 // 5]["t"]),
                                    iso_day(bars[-1]["t"]), protocol_sha, report["evaluated_at"])
            result = evaluate(bars)
            date_sets.append({iso_day(row["t"]) for row in bars})
            report["results"][ticker] = {"available": True, "source": {
                "provider": "Massive", "path": f"/v2/aggs/ticker/{ticker}/range/1/day/{args.start}/{args.end}",
                "query": {"adjusted": True, "sort": "asc", "limit": 50000},
                "retrieved_at": payload["retrieved_at"], "request_id": payload["provider_request_id"],
                "bar_count": len(bars), "first_date": iso_day(bars[0]["t"]), "last_date": iso_day(bars[-1]["t"]),
                "training_end_date": iso_day(bars[result["training"]["training_stop_exclusive"] - 1]["t"]),
                "raw_rows_sha256": payload["raw_rows_sha256"], "used_ohlc_sha256": digest(bars),
                "cache_replay": payload["cache_replay"], "final_holdout_previously_observed": seen}, "evaluation": result}
        except (ValueError, KeyError, TypeError, OSError) as error:
            # Avoid including arbitrary payloads, file paths or credential-bearing exceptions.
            safe = str(error) if isinstance(error, ValueError) else type(error).__name__
            report["results"][ticker] = {"available": False, "reason": safe}
    report["cross_symbol_date_sets_identical"] = bool(date_sets) and all(days == date_sets[0] for days in date_sets)
    report["all_expected_symbols_evaluated"] = all(row["available"] for row in report["results"].values())
    out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    (out / "BACKTEST-SUMMARY.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (out / "BACKTEST-REPORT.md").write_text(markdown(report))
    print(json.dumps({"protocol_sha256": protocol_sha, "evaluated_symbols": sum(r["available"] for r in report["results"].values()),
                      "expected_symbols": len(SYMBOLS), "outputs": ["BACKTEST-REPORT.md", "BACKTEST-SUMMARY.json"]}))
    return 0 if report["all_expected_symbols_evaluated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
