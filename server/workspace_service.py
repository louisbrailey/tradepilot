"""Authenticated workspace features. No client-supplied prices or broker execution."""
import os
from private_storage import ensure_private_directory, runtime_path
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path
from research import Massive, validated_daily_bars
from paper_service import PaperService
from paper_automation import AutomationService
from coinbase_service import CoinbaseAdapter, CoinbaseError
from strategies import compare_strategies
from webull_service import BrokerError
from market_service import service as market_data

AUTOMATION_ROUTES = ("/v1/paper/automation/state", "/v1/paper/automation/start", "/v1/paper/automation/pause", "/v1/paper/automation/check")
WORKSPACE_ROUTES = AUTOMATION_ROUTES + ("/v1/paper/state", "/v1/paper/review", "/v1/paper/confirm", "/v1/paper/note", "/v1/paper/mark", "/v1/coinbase/state", "/v1/strategies")
_services = {}
_automation_services = {}
_lock = threading.Lock()


def paper():
    runtime = runtime_path(os.environ.get("TRADEPILOT_RUNTIME", "runtime"))
    with _lock:
        if runtime not in _services:
            ensure_private_directory(runtime)
            _services[runtime] = PaperService(runtime / "paper.sqlite3")
        return _services[runtime]


def automation():
    runtime = runtime_path(os.environ.get("TRADEPILOT_RUNTIME", "runtime"))
    with _lock:
        if runtime not in _automation_services:
            ensure_private_directory(runtime)
            _automation_services[runtime] = AutomationService(runtime / "automated-paper.sqlite3")
        return _automation_services[runtime]


def ticker(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", value):
        raise BrokerError("Use an uppercase US stock symbol")
    return value


def recent_bars(symbol, days, adjusted):
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days)
    result = Massive().get(f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}",
                           {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": 50000})
    if not result.get("available") or result.get("partial_page") or result.get("adjusted") is not adjusted:
        raise BrokerError("Complete market data with confirmed price adjustment is unavailable")
    return validated_daily_bars(result.get("results"), minimum=1, start=str(start), end=str(end), require_ohlc=True)


def live_reference(symbol):
    """Current-session consolidated price from the market data service, or None."""
    try:
        reference = market_data().reference_price(symbol)
    except Exception:
        return None
    if not reference:
        return None
    price = Decimal(str(reference["price"]))
    if not price.is_finite() or price <= 0:
        return None
    label = "official close" if reference["session_close"] else "latest consolidated price"
    return {"symbol": symbol, "price": format(price, "f"), "as_of": reference["as_of"],
            "source": f"Massive snapshot {label} (may be delayed; not an executable quote)", "delayed": True}


def paper_quote(symbol):
    # Prefer the current session's consolidated price; otherwise the latest completed unadjusted
    # close. Either is an explicitly delayed simulation reference, never an executable quote.
    live = live_reference(ticker(symbol))
    if live:
        return live
    row = recent_bars(ticker(symbol), 7, False)[-1]
    day = datetime.fromtimestamp(row["t"] / 1000, timezone.utc).date()
    close = datetime.combine(day, datetime.min.time(), ZoneInfo("America/New_York")).replace(hour=16)
    return {"symbol": symbol, "price": format(Decimal(str(row["c"])), "f"),
            "as_of": close.timestamp(), "source": "Massive completed daily bar (unadjusted close; timestamp is 16:00 ET on bar date)", "delayed": True}


def workspace_request(path, payload):
    if not isinstance(payload, dict):
        raise BrokerError("Expected an object")
    if path in AUTOMATION_ROUTES:
        try:
            if path.endswith(("/state", "/check")) and payload:
                raise ValueError("Expected an empty scheduler request")
            service = automation()
            if path.endswith("/state"): return service.state()
            if path.endswith("/start"): return service.start(payload)
            if path.endswith("/pause"): return service.pause(payload)
            return service.tick()
        except ValueError as error:
            raise BrokerError(str(error)) from None
    if path in ("/v1/paper/state", "/v1/paper/mark", "/v1/coinbase/state") and payload:
        raise BrokerError("Expected an empty request")
    if path == "/v1/coinbase/state":
        try:
            return CoinbaseAdapter(os.environ.get("COINBASE_API_KEY_NAME"), os.environ.get("COINBASE_API_PRIVATE_KEY")).state()
        except CoinbaseError as error:
            raise BrokerError(str(error)) from None
    if path == "/v1/strategies":
        if set(payload) != {"ticker"}:
            raise BrokerError("Expected only a ticker")
        symbol = ticker(payload["ticker"])
        result = compare_strategies(recent_bars(symbol, 1500, True))
        return {**result, "ticker": symbol, "source": "Massive split-adjusted daily bars", "retrieved_at": time.time()}
    service = paper()
    try:
        if path == "/v1/paper/state":
            return service.state()
        if path == "/v1/paper/review":
            if set(payload) != {"symbol", "side", "quantity", "client_id"}:
                raise BrokerError("Expected symbol, side, quantity and client_id only")
            return service.create_review(payload, paper_quote(ticker(payload["symbol"])))
        if path == "/v1/paper/confirm":
            return service.confirm(payload)
        if path == "/v1/paper/note":
            return service.add_note(payload)
        if path == "/v1/paper/mark":
            symbols = [row["symbol"] for row in service.state()["positions"]]
            return service.mark_quotes([paper_quote(symbol) for symbol in symbols])
    except ValueError as error:
        raise BrokerError(str(error)) from None
    raise BrokerError("Unknown workspace operation")
