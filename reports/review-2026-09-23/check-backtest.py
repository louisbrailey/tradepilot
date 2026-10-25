#!/usr/bin/env python3
"""Independent accounting audit of saved results. Reads private bars; emits no bars."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def reconcile(rows, window, begin, end, bps):
    # An exposure-return recurrence independent of the simulator's cash/share ledger.
    cost = bps / 10000
    targets = [rows[i-1]["c"] > math.fsum(r["c"] for r in rows[i-window:i])/window
               for i in range(begin, end)]
    wealth, marks, was_long, fills = 1.0, [1.0], False, 0
    for i, target in zip(range(begin, end), targets):
        if target and was_long:
            growth = rows[i]["c"] / rows[i-1]["c"]
        elif target:
            growth = rows[i]["c"] / rows[i]["o"] / (1+cost)
            fills += 1
        elif was_long:
            growth = rows[i]["o"] / rows[i-1]["c"] * (1-cost)
            fills += 1
        else:
            growth = 1.0
        wealth *= growth
        marks.append(wealth)
        was_long = target
    if was_long:
        wealth *= 1-cost
        marks.append(wealth)
        fills += 1
    benchmark_marks = [1.0] + [r["c"] / rows[begin]["o"] / (1+cost) for r in rows[begin:end]]
    benchmark_marks.append(benchmark_marks[-1] * (1-cost))
    def drawdown(values):
        peak, worst = values[0], 0.0
        for value in values:
            peak = max(peak, value)
            worst = max(worst, (peak-value)/peak)
        return worst * 100
    return {"return_pct": (wealth-1)*100, "max_drawdown_pct": drawdown(marks),
            "benchmark_price_return_pct": (benchmark_marks[-1]-1)*100,
            "benchmark_max_drawdown_pct": drawdown(benchmark_marks), "fills": fills}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--original", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = json.loads(Path(args.report).read_text())
    original = json.loads(Path(args.original).read_text())
    protocol = report["protocol"]
    audit = {"method": "independent daily exposure-return recurrence and running peak drawdown",
             "raw_bars_included": False, "symbols": {}, "all_checks_passed": True}
    for symbol, result in report["results"].items():
        source, ev = result["source"], result["evaluation"]
        payload = json.loads((Path(args.cache_dir) / f"{symbol}-{protocol['requested_start']}-{protocol['requested_end']}.json").read_text())
        rows = payload["rows"]
        assert digest(rows) == source["raw_rows_sha256"]
        expected_selection, candidate_means, maximum_error, runs = None, {}, 0.0, 0
        boundaries = ev["training"]["fold_boundaries"]
        for window in protocol["windows"]:
            returns = []
            for i, stored in enumerate(ev["training"]["candidates"][str(window)]["folds"]):
                expected = reconcile(rows, window, boundaries[i], boundaries[i+1], 10)
                for metric, value in expected.items():
                    maximum_error = max(maximum_error, abs(stored[metric]-value))
                    assert math.isclose(stored[metric], value, rel_tol=1e-10, abs_tol=1e-8), (symbol, metric)
                returns.append(expected["return_pct"])
                runs += 1
            candidate_means[window] = math.fsum(returns)/len(returns)
        expected_selection = max(candidate_means, key=lambda n: (candidate_means[n], -n))
        assert expected_selection == ev["training"]["selected_window"]
        for stage_name in ("validation", "final_holdout"):
            stage = ev[stage_name]
            for bps in protocol["costs_bps_per_side"]:
                expected = reconcile(rows, expected_selection, stage["start_index"], stage["stop_index_exclusive"], bps)
                observed = stage["cost_sensitivity"][str(bps)]
                for metric, value in expected.items():
                    maximum_error = max(maximum_error, abs(observed[metric]-value))
                    assert math.isclose(observed[metric], value, rel_tol=1e-10, abs_tol=1e-8), (symbol, stage_name, bps, metric)
                runs += 1
        audit["symbols"][symbol] = {"independent_runs": runs,
            "maximum_metric_error": maximum_error, "selected_window_reconciled": expected_selection,
            "original_evaluation_identical": ev == original["results"][symbol]["evaluation"],
            "original_input_hash_identical": source["used_ohlc_sha256"] == original["results"][symbol]["source"]["used_ohlc_sha256"],
            "previously_observed": source["final_holdout_previously_observed"]}
        assert all(audit["symbols"][symbol][key] for key in ("original_evaluation_identical", "original_input_hash_identical", "previously_observed"))
    audit["total_independent_runs"] = sum(r["independent_runs"] for r in audit["symbols"].values())
    audit["all_protocol_hashes_identical"] = report["protocol_sha256"] == original["protocol_sha256"]
    assert audit["all_protocol_hashes_identical"]
    Path(args.output).write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"all_checks_passed": True, "symbols": len(audit["symbols"]),
                      "independent_runs": audit["total_independent_runs"],
                      "maximum_metric_error": max(row["maximum_metric_error"] for row in audit["symbols"].values())}))


if __name__ == "__main__":
    main()
