"""Read-only projection of the recorded historical evaluation for the iPhone."""
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
import re

REPORT_PATH = Path(__file__).resolve().parents[1] / "BACKTEST-SUMMARY.json"


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid evaluation metric")
    return value


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("Invalid evaluation date")
    return value


def project_evaluation(report):
    try:
        if report["schema_version"] != 1 or report["protocol"]["version"] != "sma-multistage-v1":
            raise ValueError("Unsupported evaluation version")
        protocol = report["protocol"]
        encoded = json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if hashlib.sha256(encoded).hexdigest() != report["protocol_sha256"]:
            raise ValueError("Evaluation protocol hash mismatch")
        if protocol["windows"] != [10, 20, 50] or protocol["costs_bps_per_side"] != [0, 10, 25, 50] or protocol["split"] != [0.6, 0.2, 0.2]:
            raise ValueError("Unsupported evaluation protocol")
        symbols = protocol["symbols"]
        if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 30 or len(set(symbols)) != len(symbols)
                or not all(isinstance(s, str) and re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols)
                or set(report["results"]) != set(symbols)):
            raise ValueError("Invalid evaluation universe")
        timestamp = report["evaluated_at"]
        if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
            raise ValueError("Missing evaluation timestamp")
        rows, unavailable = [], []
        for symbol in symbols:
            item = report["results"][symbol]
            if type(item["available"]) is not bool:
                raise ValueError("Invalid availability marker")
            if not item["available"]:
                unavailable.append(symbol)
                continue
            source, ev = item["source"], item["evaluation"]
            validation, holdout = ev["validation"], ev["final_holdout"]
            v, h = validation["baseline"], holdout["baseline"]
            if source["provider"] != "Massive" or type(source["bar_count"]) is not int or source["bar_count"] < 500:
                raise ValueError("Invalid evaluation source")
            dates = [day(source["first_date"]), day(source["training_end_date"]), day(validation["start_date"]),
                     day(validation["end_date"]), day(holdout["start_date"]), day(holdout["end_date"]), day(source["last_date"])]
            if not (dates[0] <= dates[1] < dates[2] <= dates[3] < dates[4] <= dates[5] <= dates[6]):
                raise ValueError("Overlapping evaluation stages")
            for metrics in (v, h):
                for field in ("return_pct", "benchmark_price_return_pct", "excess_return_pct", "max_drawdown_pct", "benchmark_max_drawdown_pct"):
                    number(metrics[field])
                if not math.isclose(metrics["return_pct"] - metrics["benchmark_price_return_pct"], metrics["excess_return_pct"], rel_tol=1e-10, abs_tol=1e-8):
                    raise ValueError("Inconsistent evaluation excess")
                if not 0 <= metrics["max_drawdown_pct"] <= 100 or not 0 <= metrics["benchmark_max_drawdown_pct"] <= 100:
                    raise ValueError("Invalid drawdown")
                if type(metrics["fills"]) is not int or metrics["fills"] < 0:
                    raise ValueError("Invalid fill count")
            expected_pass = v["excess_return_pct"] > 0 and v["max_drawdown_pct"] <= v["benchmark_max_drawdown_pct"] and v["fills"] >= 2
            if type(validation["screen_passed"]) is not bool or validation["screen_passed"] != expected_pass:
                raise ValueError("Inconsistent evaluation screening result")
            checks = ev["integrity_checks"]
            required = {"training_invariant_to_all_future_prices", "validation_invariant_to_holdout_prices",
                        "first_holdout_decision_invariant_to_current_and_future_prices", "chronological_nonoverlap",
                        "independent_return_and_benchmark_reconciliation"}
            if set(checks) != required or any(value is not True for value in checks.values()):
                raise ValueError("Evaluation integrity checks did not pass")
            window = ev["training"]["selected_window"]
            if type(window) is not int or window not in (10, 20, 50):
                raise ValueError("Invalid selected window")
            costs = []
            for cost in (0, 10, 25, 50):
                scenario = holdout["cost_sensitivity"][str(cost)]
                costs.append({"bps_per_side": cost, "return_pct": number(scenario["return_pct"]),
                              "benchmark_return_pct": number(scenario["benchmark_price_return_pct"])})
            if costs[1]["return_pct"] != h["return_pct"] or costs[1]["benchmark_return_pct"] != h["benchmark_price_return_pct"]:
                raise ValueError("Inconsistent baseline cost scenario")
            rows.append({"symbol": symbol, "bar_count": source["bar_count"], "selected_window": window,
                "source_start": dates[0], "source_end": dates[6], "validation_passed": expected_pass,
                "validation_excess_pct": v["excess_return_pct"], "holdout_start": dates[4], "holdout_end": dates[5],
                "holdout_return_pct": h["return_pct"], "benchmark_return_pct": h["benchmark_price_return_pct"],
                "excess_return_pct": h["excess_return_pct"], "max_drawdown_pct": h["max_drawdown_pct"],
                "fills": h["fills"], "cost_sensitivity": costs})
        if not rows:
            raise ValueError("No recorded evaluation is available")
        qualified = sum(row["validation_passed"] and row["excess_return_pct"] > 0 for row in rows)
        return {"schema_version": 1, "historical_only": True, "previously_observed": True,
            "scope": "sma-long-cash", "evaluated_at": timestamp, "protocol_sha256": report["protocol_sha256"],
            "baseline_cost_bps": 10, "source_start": min(row["source_start"] for row in rows),
            "source_end": max(row["source_end"] for row in rows), "expected_symbols": len(symbols),
            "unavailable_symbols": unavailable, "rows": rows,
            "conclusion": ("Current SMA results do not support live adoption: no symbol both passed validation and beat its final-period benchmark."
                           if not qualified else "Historical results are research evidence and do not establish readiness for live trading."),
            "limitations": ["Price returns omit dividends, taxes and cash interest; income strategies are not evaluated.",
                "Each symbol and stage is an independent $10,000 experiment, not a combined portfolio.",
                "Previous-close signals, subsequent daily-open fills, fixed costs and daily-close drawdown are assumptions; actual execution is untested.",
                "Training, validation and final periods are separate. The final period is already observed and cannot be reused as fresh evidence.",
                "Seven surviving stocks and ETFs do not establish performance for other markets. Shorts, options, intraday, crypto and FX strategies are not tested.",
                "This report never activates a strategy or authorizes an order. Prospective paper evaluation is still required."]}
    except (KeyError, TypeError, OverflowError, AttributeError) as error:
        raise ValueError("Invalid recorded evaluation") from error


def load_evaluation():
    try:
        if REPORT_PATH.stat().st_size > 2_000_000:
            raise ValueError("Recorded evaluation is too large")
        return project_evaluation(json.loads(REPORT_PATH.read_text()))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Recorded evaluation is unavailable") from error
