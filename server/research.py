"""Read-only Massive data and a small chronological strategy experiment.

This module cannot trade. Backtests are price-return experiments, not evidence of
future profits. Snapshot/news data never enters the historical backtest.
"""
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_market_env(path):
    """Read only market-key assignments, without executing .env as shell code."""
    accepted = {"MASSIVE_API_KEY", "POLYGON_API_KEY", "MARKET_DATA_PROVIDER", "MARKET_DATA_API_KEY"}
    selected = {}
    with open(path) as stream:
        for line in stream:
            line = line.strip().removeprefix("export ")
            name, sep, value = line.partition("=")
            name = name.strip()
            if sep and name in accepted:
                value = value.strip()
                if value[:1] in ("'", '"') and value[-1:] == value[:1]:
                    value = value[1:-1]
                else:
                    value = value.split(" #", 1)[0].strip()
                if value:
                    selected[name] = value
    for name in ("MASSIVE_API_KEY", "POLYGON_API_KEY"):
        if selected.get(name):
            os.environ.setdefault(name, selected[name])
    if selected.get("MARKET_DATA_PROVIDER", "").lower() in ("massive", "polygon") and selected.get("MARKET_DATA_API_KEY"):
        os.environ.setdefault("MASSIVE_API_KEY", selected["MARKET_DATA_API_KEY"])


class Massive:
    def __init__(self, key=None):
        self.key = key or os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
        if not self.key:
            raise RuntimeError("Massive API key is not configured")

    def get(self, path, params):
        request = Request("https://api.massive.com" + path + "?" + urlencode(params),
                          headers={"Authorization": "Bearer " + self.key})
        try:
            with build_opener(NoRedirects()).open(request, timeout=15) as response:
                result = json.load(response)
            if result.get("status") in ("ERROR", "NOT_AUTHORIZED"):
                return {"available": False, "reason": "Provider denied this dataset"}
            return {"available": True, "results": result.get("results", []),
                    "partial_page": bool(result.get("next_url")), "request_id": result.get("request_id")}
        except HTTPError as error:
            return {"available": False, "reason": "Provider HTTP " + str(error.code)}
        except Exception:
            return {"available": False, "reason": "Provider connection failed"}

    def research(self, ticker):
        if not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", ticker):
            raise ValueError("Use a US stock ticker such as AAPL")
        end = datetime.now(timezone.utc).date() - timedelta(days=1)
        start = end - timedelta(days=400)
        queries = {
            "daily_bars": (f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}", {"adjusted": "true", "sort": "asc", "limit": 50000}),
            "options_sample": (f"/v3/snapshot/options/{ticker}", {"limit": 20, "sort": "ticker", "order": "asc"}),
            "dividends": ("/stocks/v1/dividends", {"ticker": ticker, "limit": 20, "sort": "ex_dividend_date.desc"}),
            "benzinga_news": ("/benzinga/v2/news", {"tickers": ticker, "limit": 8, "sort": "published.desc"}),
        }
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {key: pool.submit(self.get, path, params) for key, (path, params) in queries.items()}
            datasets = {key: future.result() for key, future in futures.items()}
        # Preserve provenance/timestamps, omit full article bodies and images.
        news = datasets["benzinga_news"]
        if news["available"]:
            news["results"] = [{k: row.get(k) for k in ("benzinga_id", "title", "published", "last_updated", "url", "tickers")} for row in news["results"]]
        bars = datasets["daily_bars"]
        experiment = {"available": False, "reason": "Insufficient or unavailable bars"}
        if bars["available"] and not bars["partial_page"]:
            try:
                experiment = walk_forward(bars["results"])
            except (ValueError, KeyError, TypeError) as error:
                experiment = {"available": False,
                              "reason": "Historical bars failed validation: " + str(error)}
        return {
            "ticker": ticker, "source": "Massive", "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "freshness": "Historical daily bars through yesterday. Options Developer snapshots are 15-minute delayed; news carries its own published/updated times. Actual entitlements must be verified.",
            "scope": "US stock research. Options are a limited current chain sample, not a complete chain or historical options backtest. No FX or crypto data access has been assumed.",
            "datasets": datasets, "experiment": experiment,
        }


def simulate(bars, lookback, start, stop, cost_bps=10):
    """Prior-close SMA signal, next-bar open fill, long/cash, daily close marks.

    All-in fractional positions; 10 bps combined cost/slippage per side by default.
    End liquidates at the final close with another cost. No dividends or taxes.
    """
    if not (1 <= lookback <= start < stop <= len(bars)) or not 0 <= cost_bps < 10000:
        raise ValueError("Invalid simulation parameters")
    cash, shares, peak, drawdown, fills = 10000.0, 0.0, 10000.0, 0.0, []
    cost = cost_bps / 10000
    for i in range(start, stop):
        average = sum(float(b["c"]) for b in bars[i-lookback:i]) / lookback
        wants_long = float(bars[i-1]["c"]) > average
        price = float(bars[i]["o"])
        if wants_long and shares == 0:
            shares = cash / (price * (1 + cost)); cash = 0
            fills.append({"index": i, "time": bars[i]["t"], "side": "buy", "price": price})
        elif not wants_long and shares > 0:
            cash = shares * price * (1 - cost); shares = 0
            fills.append({"index": i, "time": bars[i]["t"], "side": "sell", "price": price})
        equity = cash + shares * float(bars[i]["c"])
        peak = max(peak, equity); drawdown = max(drawdown, 1 - equity / peak)
    if shares > 0:
        cash = shares * float(bars[stop-1]["c"]) * (1 - cost)
        fills.append({"index": stop-1, "time": bars[stop-1]["t"], "side": "sell_at_end", "price": float(bars[stop-1]["c"])})
        drawdown = max(drawdown, 1 - cash / peak)
    benchmark_shares = 10000.0 / (float(bars[start]["o"]) * (1 + cost))
    benchmark_peak, benchmark_drawdown = 10000.0, 0.0
    for i in range(start, stop):
        benchmark_equity = benchmark_shares * float(bars[i]["c"])
        benchmark_peak = max(benchmark_peak, benchmark_equity)
        benchmark_drawdown = max(benchmark_drawdown, 1 - benchmark_equity / benchmark_peak)
    benchmark_cash = benchmark_shares * float(bars[stop-1]["c"]) * (1 - cost)
    benchmark_drawdown = max(benchmark_drawdown, 1 - benchmark_cash / benchmark_peak)
    benchmark = benchmark_cash / 10000.0 - 1
    return {"return_pct": (cash / 10000 - 1) * 100, "max_drawdown_pct": drawdown * 100,
            "benchmark_price_return_pct": benchmark * 100,
            "benchmark_max_drawdown_pct": benchmark_drawdown * 100,
            "fills": len(fills), "fill_log": fills,
            "from": bars[start]["t"], "to": bars[stop-1]["t"]}


def _aggregate_fold_results(results):
    """Summarize independent $10,000 fold runs without compounding across folds."""
    count = len(results)
    return {
        "return_pct": sum(row["return_pct"] for row in results) / count,
        "max_drawdown_pct": max(row["max_drawdown_pct"] for row in results),
        "benchmark_price_return_pct": sum(row["benchmark_price_return_pct"] for row in results) / count,
        "benchmark_max_drawdown_pct": max(row["benchmark_max_drawdown_pct"] for row in results),
        "fills": sum(row["fills"] for row in results),
        "fill_log": [fill for row in results for fill in row["fill_log"]],
        "from": results[0]["from"], "to": results[-1]["to"],
        "folds": count, "capital_policy": "Each fold starts with $10,000 cash; returns are arithmetic means, not compounded",
        "excess_return_pct": (sum(row["return_pct"] for row in results)
                              - sum(row["benchmark_price_return_pct"] for row in results)) / count,
        "profitable_folds": sum(row["return_pct"] > 0 for row in results),
        "benchmark_beaten_folds": sum(row["return_pct"] > row["benchmark_price_return_pct"]
                                      for row in results),
    }


def walk_forward(bars):
    if len(bars) < 160:
        raise ValueError("At least 160 daily bars required")
    previous = -1
    for row in bars:
        if (not isinstance(row["t"], (int, float)) or isinstance(row["t"], bool)
                or not math.isfinite(row["t"]) or row["t"] <= previous):
            raise ValueError("Bars must have unique ascending timestamps")
        previous = row["t"]
        for field in ("o", "c"):
            if not math.isfinite(float(row[field])) or float(row[field]) <= 0:
                raise ValueError("Invalid prices")
    candidates = [10, 20, 50]
    split = len(bars) // 2
    remaining = len(bars) - split
    fold_sizes = [remaining // 3 + (1 if i < remaining % 3 else 0) for i in range(3)]
    folds, test_start = [], split
    first_training = None
    for fold_number, size in enumerate(fold_sizes, 1):
        test_stop = test_start + size
        training = {n: simulate(bars, n, 50, test_start) for n in candidates}
        selected = max(candidates, key=lambda n: (training[n]["return_pct"], -n))
        testing = simulate(bars, selected, test_start, test_stop)
        if first_training is None:
            first_training = training
            legacy_selected = selected
        folds.append({
            "fold": fold_number, "train_start_index": 50, "train_stop_index": test_start,
            "test_start_index": test_start, "test_stop_index": test_stop,
            "selected_window": selected,
            "training": {str(n): {k: v for k, v in result.items() if k != "fill_log"}
                         for n, result in training.items()},
            "holdout": testing,
        })
        test_start = test_stop
    baseline_results = [fold["holdout"] for fold in folds]
    aggregate = _aggregate_fold_results(baseline_results)
    cost_sensitivity = {}
    for cost_bps in (0, 10, 25):
        scenario = [simulate(bars, fold["selected_window"], fold["test_start_index"],
                             fold["test_stop_index"], cost_bps=cost_bps) for fold in folds]
        cost_sensitivity[str(cost_bps)] = _aggregate_fold_results(scenario)
    return {"available": True, "version": "sma-long-cash-v2", "candidate_windows": candidates,
            "selected_window": legacy_selected,
            "selection": "Each fold independently selects the highest-return SMA window using only its preceding expanding training history",
            "training": {str(n): {k: v for k, v in result.items() if k != "fill_log"}
                         for n, result in first_training.items()},
            "holdout": aggregate, "split_index": split, "cost_bps_per_side": 10,
            "folds": folds, "cost_sensitivity": cost_sensitivity,
            "evaluation": "Three chronological, non-overlapping out-of-sample folds with expanding training windows; capital resets each fold",
            "limitations": ["Only three folds from one ticker; estimates remain noisy and are not a validated trading strategy",
                "Parameters are reselected using preceding history only; earlier test folds enter the training history of later folds",
                "Each fold resets to $10,000 cash; aggregate returns are arithmetic means and are not a compounded portfolio path",
                "Price returns only: dividends, tax, borrow, market impact and intraday liquidity are not modeled",
                "Split-adjusted daily bars are not a point-in-time constituent universe; selection/survivorship bias remains",
                "No short, option, FX, crypto or news strategy is backtested here",
                "Not a recommendation or proof of future profitability"]}


def summarize(report):
    lines = [f"Market research: {report['ticker']}", f"Retrieved: {report['retrieved_at']}", report["freshness"], ""]
    for name, dataset in report["datasets"].items():
        status = (f"{len(dataset['results'])} records" + (" · partial page" if dataset["partial_page"] else "")) if dataset["available"] else dataset["reason"]
        lines.append(f"{name.replace('_', ' ').title()}: {status}")
    experiment = report["experiment"]
    if experiment.get("available"):
        h = experiment["holdout"]
        lines += ["", "Historical experiment · SMA long/cash",
                  f"Mean fold return: {h['return_pct']:.2f}%", f"Mean fold benchmark return: {h['benchmark_price_return_pct']:.2f}%",
                  f"Worst fold drawdown: {h['max_drawdown_pct']:.2f}%", f"Total fold fills: {h['fills']}",
                  f"Worst benchmark fold drawdown: {h['benchmark_max_drawdown_pct']:.2f}%",
                  f"Mean excess return versus benchmark: {h['excess_return_pct']:.2f} percentage points; benchmark beaten in {h['benchmark_beaten_folds']}/{h['folds']} folds",
                  "Expanding-window folds (window selected solely from preceding training history):"]
        for fold in experiment["folds"]:
            fold_holdout = fold["holdout"]
            lines.append(f"Fold {fold['fold']}: {fold['selected_window']}-bar SMA · return {fold_holdout['return_pct']:.2f}% · benchmark {fold_holdout['benchmark_price_return_pct']:.2f}%")
        lines.append("Cost sensitivity (same training-selected window per fold):")
        for cost_bps in (0, 10, 25):
            scenario = experiment["cost_sensitivity"][str(cost_bps)]
            lines.append(f"{cost_bps} bps/side: mean return {scenario['return_pct']:.2f}% · mean benchmark {scenario['benchmark_price_return_pct']:.2f}%")
        lines.append("Each fold starts with $10,000 cash; fold returns are averaged, not compounded. Dividends and taxes excluded.")
    else:
        lines += ["", "Historical experiment unavailable: " + experiment.get("reason", "Missing data")]
    news = report["datasets"]["benzinga_news"]
    if news["available"]:
        lines += ["", "Recent Benzinga headlines:"]
        for item in news["results"]:
            lines.append(f"{item.get('published', '')} · {item.get('title', '')}\n{item.get('url', '')}")
    lines += ["", report["scope"]]
    return "\n".join(lines)
