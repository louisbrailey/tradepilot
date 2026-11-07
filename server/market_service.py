"""Read-only market data for the Markets tab.

Quotes, market status, symbol search, company details, key statistics, price
history and headlines from Massive (Polygon-compatible) REST endpoints. Nothing
here can trade, read brokerage accounts or follow a URL other than the provider.
Every figure carries the provider's timestamp; none is an executable quote.
Standard library only and Python 3.9 compatible, like the deployed gateway.
"""
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener

from paper_calendar import ET, next_session, session as is_session
from research import NoRedirects

MARKET_ROUTES = ("/v1/market/overview", "/v1/market/quotes", "/v1/market/search",
                 "/v1/market/symbol", "/v1/market/chart", "/v1/market/crypto")
SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,14}")
CURRENCY = re.compile(r"[A-Z0-9]{2,10}")
MAX_CURRENCIES = 60
QUERY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .&'\-]{0,39}")
RANGES = ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "5Y")
MAX_SYMBOLS = 40
MAX_RESPONSE = 4 * 1024 * 1024
INDEX_PROXIES = (("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("DIA", "Dow Jones"), ("IWM", "Russell 2000"))
# Widely held, liquid US large caps. Movers are ranked within this list only, so a
# thinly traded warrant or penny stock can never headline the overview.
MOVER_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "BRK.B", "JPM",
    "V", "LLY", "UNH", "XOM", "MA", "JNJ", "PG", "HD", "COST", "ABBV",
    "MRK", "CVX", "KO", "PEP", "BAC", "WMT", "NFLX", "ADBE", "CRM", "AMD",
    "ORCL", "CSCO", "INTC", "QCOM", "TXN", "DIS", "MCD", "NKE", "PFE", "T",
    "VZ", "WFC", "GS", "MS", "CAT", "BA", "GE", "IBM", "UBER", "PLTR",
)
EXCHANGES = {"XNAS": "Nasdaq", "XNYS": "NYSE", "ARCX": "NYSE Arca", "XASE": "NYSE American",
             "BATS": "Cboe BZX", "XCBO": "Cboe", "IEXG": "IEX"}
TYPES = {"CS": "Stock", "ETF": "ETF", "ETN": "ETN", "ETV": "ETF", "ADRC": "ADR", "PFD": "Preferred",
         "WARRANT": "Warrant", "RIGHT": "Right", "UNIT": "Unit", "FUND": "Fund", "OS": "Stock", "SP": "Note"}
SEARCH_RANK = {"CS": 0, "ETF": 0, "ADRC": 1, "ETN": 2, "ETV": 2, "OS": 2, "FUND": 3, "PFD": 4}
# NYSE 1:00 p.m. ET early closes. The provider's live status stays authoritative.
EARLY_CLOSES = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}
OPEN_MINUTE, CLOSE_MINUTE, EARLY_CLOSE_MINUTE = 9 * 60 + 30, 16 * 60, 13 * 60
_MISSING = object()


class MarketDataError(Exception):
    """The provider is unreachable, rate limited or not entitled. The message is user-facing."""


class MarketRequestError(ValueError):
    """The app sent an unusable market request. The message is user-facing."""


class MassiveClient:
    base = "https://api.massive.com"

    def __init__(self, key=None):
        self.key = key or os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
        if not self.key:
            raise MarketDataError("Market data isn't set up on your server.")
        self.opener = build_opener(NoRedirects())

    def get(self, path, params=None):
        """Decoded JSON object for one provider path, or None when the provider has no such item."""
        url = self.base + path + ("?" + urlencode(params) if params else "")
        request = Request(url, headers={"Authorization": "Bearer " + self.key, "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=12) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as error:
            error.close()
            if error.code == 404:
                return None
            if error.code in (401, 403):
                raise MarketDataError("Your market data plan doesn't include this information.") from None
            if error.code == 429:
                raise MarketDataError("Market data is busy. Try again in a minute.") from None
            raise MarketDataError("The market data provider returned an error.") from None
        except Exception:
            raise MarketDataError("Couldn't reach the market data provider.") from None
        if len(raw) > MAX_RESPONSE:
            raise MarketDataError("The market data response was too large.")
        try:
            body = json.loads(raw)
        except ValueError:
            raise MarketDataError("The market data response was unreadable.") from None
        if not isinstance(body, dict):
            raise MarketDataError("The market data response was unreadable.")
        if body.get("status") in ("ERROR", "NOT_AUTHORIZED"):
            raise MarketDataError("Your market data plan doesn't include this information.")
        return body


class TTLCache:
    """Small thread-safe cache. A stale value can stand in briefly when the provider fails."""

    def __init__(self, clock, limit=600):
        self.clock, self.limit = clock, limit
        self.items, self.lock = {}, threading.Lock()

    def fetch(self, key, fresh_for, stale_for, load):
        now = self.clock()
        with self.lock:
            entry = self.items.get(key)
        if entry and entry[0] > now:
            return entry[2]
        try:
            value = load()
        except MarketDataError:
            if entry and entry[1] > now:
                return entry[2]
            raise
        with self.lock:
            if len(self.items) >= self.limit:
                for old in [k for k, item in self.items.items() if item[1] <= now]:
                    del self.items[old]
                while len(self.items) >= self.limit:
                    del self.items[min(self.items, key=lambda k: self.items[k][1])]
            self.items[key] = (now + fresh_for, now + fresh_for + stale_for, value)
        return value


# MARK: - Validation and number helpers

def _dict(value):
    return value if isinstance(value, dict) else {}


def _number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e15 or (positive and value <= 0):
        return None
    return value


def _round(value, digits=4):
    return None if value is None else round(value, digits)


def _epoch(value, scale):
    # Provider timestamps arrive in milliseconds or nanoseconds, beyond _number's magnitude bound.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    seconds = value / scale
    return seconds if 946684800 <= seconds <= time.time() + 86400 else None


def _text(value, limit):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] if value else None


def _published(value):
    if not isinstance(value, str):
        return None
    for layout in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, layout).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _https(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == "https" and parts.netloc and not parts.username else None


def valid_symbol(value):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        raise MarketRequestError("Use an uppercase US stock symbol such as AAPL.")
    return value


def _exact(payload, required, optional=()):
    if not isinstance(payload, dict):
        raise MarketRequestError("Expected an object.")
    keys = set(payload)
    if not set(required) <= keys or keys - set(required) - set(optional):
        raise MarketRequestError("Unexpected market data request fields.")


def _trading_day(day):
    try:
        return is_session(day)
    except ValueError:
        return day.weekday() < 5


def _close_minute(day):
    return EARLY_CLOSE_MINUTE if day.isoformat() in EARLY_CLOSES else CLOSE_MINUTE


# MARK: - Normalisation

def quote_from_snapshot(row, name=None):
    """One quote from a provider snapshot row. Change is measured against the previous close."""
    if not isinstance(row, dict) or not isinstance(row.get("ticker"), str) or not SYMBOL.fullmatch(row["ticker"]):
        return None
    day, previous = _dict(row.get("day")), _dict(row.get("prevDay"))
    trade, minute, book = _dict(row.get("lastTrade")), _dict(row.get("min")), _dict(row.get("lastQuote"))
    previous_close = _number(previous.get("c"), positive=True)
    price = _number(day.get("c"), positive=True)
    # The provider clears the day bar overnight; until trading resumes show the last close without a change.
    current = price is not None
    if price is None:
        price = previous_close
    if price is None:
        return None
    change = percent = None
    if current and previous_close:
        change = price - previous_close
        percent = change / previous_close * 100
    stamps = [stamp for stamp in (_epoch(row.get("updated"), 1e9), _epoch(trade.get("t"), 1e9),
                                  _epoch(minute.get("t"), 1e3)) if stamp]
    result = {
        "symbol": row["ticker"], "name": name, "price": _round(price), "change": _round(change),
        "change_percent": _round(percent), "previous_close": _round(previous_close),
        "open": _round(_number(day.get("o"), True)) if current else None,
        "high": _round(_number(day.get("h"), True)) if current else None,
        "low": _round(_number(day.get("l"), True)) if current else None,
        "volume": _number(day.get("v"), True) if current else None,
        "vwap": _round(_number(day.get("vw"), True)) if current else None,
        "updated": max(stamps) if stamps else None,
    }
    bid, ask = _number(book.get("p"), True), _number(book.get("P"), True)
    if bid and ask and ask >= bid:
        result["bid"], result["ask"] = _round(bid), _round(ask)
    # The day bar keeps the official close; later minute bars carry after-hours trading.
    late, late_at = _number(minute.get("c"), True), _epoch(minute.get("t"), 1e3)
    if current and late and late_at:
        at = datetime.fromtimestamp(late_at, ET)
        if _close_minute(at.date()) <= at.hour * 60 + at.minute < 20 * 60:
            result["extended"] = {"session": "after_hours", "price": _round(late), "change": _round(late - price),
                                  "change_percent": _round((late - price) / price * 100), "at": late_at}
    return result


def display_name(value):
    """Provider security names without listing boilerplate; all-caps names in title case."""
    name = _text(value, 120)
    if not name:
        return None
    name = re.sub(r"\s+(Class [A-Z] )?(Common Stock|Ordinary Shares|Common Shares|Capital Stock)$",
                  lambda match: " " + match.group(1).strip() if match.group(1) else "", name, flags=re.I)
    name = re.sub(r"\s+American Depositary Shares?\b.*$", " ADR", name, flags=re.I)
    shouting = [word for word in name.split() if len(word) >= 4 and word.isalpha() and word.isupper()]
    if len(shouting) >= 2:  # e.g. "BERKSHIRE HATHAWAY"; a lone brand such as "NVIDIA" stays as written
        name = " ".join(word.capitalize() if word in shouting else word for word in name.split())
    return name.strip() or None


def _any_epoch(value):
    """Provider timestamps in seconds, milliseconds, microseconds or nanoseconds."""
    for scale in (1e9, 1e6, 1e3, 1):
        stamp = _epoch(value, scale)
        if stamp:
            return stamp
    return None


def crypto_quote(row):
    """USD price for one crypto pair snapshot: the latest trade, else the day's close; change from the prior day."""
    if not isinstance(row, dict):
        return None
    trade, day, previous = _dict(row.get("lastTrade")), _dict(row.get("day")), _dict(row.get("prevDay"))
    price = _number(trade.get("p"), True) or _number(day.get("c"), True) or _number(_dict(row.get("min")).get("c"), True)
    if price is None:
        return None
    prior = _number(previous.get("c"), True)
    stamps = [stamp for stamp in (_any_epoch(row.get("updated")), _any_epoch(trade.get("t"))) if stamp]
    return {"price": round(price, 10), "change_percent": _round((price - prior) / prior * 100) if prior else None,
            "updated": max(stamps) if stamps else None}


def _bar(row, daily):
    if not isinstance(row, dict):
        return None
    stamp = _epoch(row.get("t"), 1e3)
    prices = [_number(row.get(field), True) for field in ("o", "h", "l", "c")]
    if stamp is None or None in prices:
        return None
    o, h, l, c = prices
    if l > min(o, c) or h < max(o, c):
        return None
    when = datetime.fromtimestamp(stamp, timezone.utc).date() if daily else datetime.fromtimestamp(stamp, ET)
    return {"t": stamp, "o": _round(o), "h": _round(h), "l": _round(l), "c": _round(c),
            "v": _number(row.get("v"), True) or 0, "_when": when}


def _clean_bars(rows, daily):
    bars, seen = [], set()
    for row in rows if isinstance(rows, list) else []:
        bar = _bar(row, daily)
        if bar and bar["t"] not in seen:
            seen.add(bar["t"])
            bars.append(bar)
    return sorted(bars, key=lambda bar: bar["t"])


def _regular_sessions(bars, sessions):
    """Bars inside 9:30 ET to the close for the latest `sessions` dates with at least two bars."""
    by_day = {}
    for bar in bars:
        at = bar["_when"]
        minute = at.hour * 60 + at.minute
        if OPEN_MINUTE <= minute < _close_minute(at.date()):
            by_day.setdefault(at.date(), []).append(bar)
    days = sorted(day for day, rows in by_day.items() if len(rows) >= 2)[-sessions:]
    return [bar for day in days for bar in by_day[day]], days


def _public(bars):
    return [{key: value for key, value in bar.items() if key != "_when"} for bar in bars]


# MARK: - Service

class MarketService:
    def __init__(self, provider=None, clock=time.time):
        self._provider, self.clock = provider, clock
        self.cache = TTLCache(clock)

    @property
    def provider(self):
        if self._provider is None:
            self._provider = MassiveClient()
        return self._provider

    def _get(self, path, params, fresh_for, stale_for=600):
        key = path + "?" + urlencode(sorted((params or {}).items()))
        return self.cache.fetch(key, fresh_for, stale_for, lambda: self.provider.get(path, params))

    # Provider datasets

    def _snapshots(self, symbols):
        body = self._get("/v2/snapshot/locale/us/markets/stocks/tickers",
                         {"tickers": ",".join(sorted(symbols))}, 10, 900)
        rows = _dict(body).get("tickers")
        return {row.get("ticker"): row for row in rows if isinstance(row, dict)} if isinstance(rows, list) else {}

    def _details(self, ticker):
        body = self._get("/v3/reference/tickers/" + quote(ticker, safe=""), None, 86400, 7 * 86400)
        return _dict(_dict(body).get("results"))

    def _name(self, ticker):
        try:
            return display_name(self._details(ticker).get("name"))
        except MarketDataError:
            return None

    def _names(self, symbols):
        with ThreadPoolExecutor(max_workers=8) as pool:
            return dict(zip(symbols, pool.map(self._name, symbols)))

    def _bars(self, ticker, multiplier, timespan, start, end, fresh_for):
        body = self._get(f"/v2/aggs/ticker/{quote(ticker, safe='')}/range/{multiplier}/{timespan}/{start}/{end}",
                         {"adjusted": "true", "sort": "asc", "limit": 50000}, fresh_for, 3600)
        return _clean_bars(_dict(body).get("results"), timespan in ("day", "week"))

    def _today(self):
        return datetime.fromtimestamp(self.clock(), ET).date()

    def _sparkline(self, ticker):
        today = self._today()
        try:
            bars = self._bars(ticker, 15, "minute", today - timedelta(days=7), today, 120)
        except MarketDataError:
            return None
        points, _ = _regular_sessions(bars, 1)
        return [bar["c"] for bar in points] if len(points) >= 2 else None

    def latest_prices(self, symbols):
        """{symbol: (Decimal price, as_of)} for price alerts: after-hours trades count, cleared day bars don't."""
        from decimal import Decimal
        prices = {}
        for ticker, row in self._snapshots([valid_symbol(item) for item in symbols]).items():
            current = quote_from_snapshot(row)
            if not current or current["change"] is None or not current["updated"]:
                continue
            extended = current.get("extended")
            price, as_of = (extended["price"], extended["at"]) if extended else (current["price"], current["updated"])
            prices[ticker] = (Decimal(str(price)), as_of)
        return prices

    def reference_price(self, ticker):
        """Latest consolidated price in the current or just-finished session, for paper simulations.

        Returns None when the provider has no current day bar (overnight reset, unknown symbol or
        outage) so callers can fall back to a completed daily close.
        """
        try:
            row = _dict(self._snapshots([valid_symbol(ticker)]).get(ticker))
        except MarketDataError:
            return None
        day, minute = _dict(row.get("day")), _dict(row.get("min"))
        price = _number(day.get("c"), positive=True)
        stamps = [stamp for stamp in (_epoch(row.get("updated"), 1e9), _epoch(_dict(row.get("lastTrade")).get("t"), 1e9),
                                      _epoch(minute.get("t"), 1e3)) if stamp]
        if price is None or not stamps:
            return None
        as_of = min(max(stamps), self.clock())
        at = datetime.fromtimestamp(as_of, ET)
        close = datetime.combine(at.date(), datetime.min.time(), ET) + timedelta(minutes=_close_minute(at.date()))
        # After the close the day bar holds the official close; date it at the close, not at later updates.
        if at >= close:
            as_of = close.timestamp()
        return {"price": price, "as_of": as_of, "session_close": at >= close}

    # Routes

    def status(self):
        now = self.clock()
        at = datetime.fromtimestamp(now, ET)
        today, minute = at.date(), at.hour * 60 + at.minute
        try:
            body = _dict(self._get("/v1/marketstatus/now", None, 30, 600))
        except MarketDataError:
            body = {}
        market = body.get("market")
        if market == "open":
            state = "open"
        elif market == "extended-hours" or body.get("earlyHours") or body.get("afterHours"):
            state = "pre_market" if minute < OPEN_MINUTE else "after_hours"
        elif market == "closed":
            state = "closed"
        else:  # Provider status unavailable: fall back to the pinned calendar, flagged as an estimate.
            trading = _trading_day(today)
            if trading and OPEN_MINUTE <= minute < _close_minute(today):
                state = "open"
            elif trading and 4 * 60 <= minute < OPEN_MINUTE:
                state = "pre_market"
            elif trading and _close_minute(today) <= minute < 20 * 60:
                state = "after_hours"
            else:
                state = "closed"
        result = {"state": state, "as_of": now, "estimated": market not in ("open", "closed", "extended-hours")}
        if state == "open":
            close = datetime.combine(today, datetime.min.time(), ET) + timedelta(minutes=_close_minute(today))
            result["closes_at"] = close.timestamp()
        else:
            try:
                day = today if (_trading_day(today) and minute < OPEN_MINUTE) else next_session(today)
                result["opens_at"] = (datetime.combine(day, datetime.min.time(), ET)
                                      + timedelta(minutes=OPEN_MINUTE)).timestamp()
            except ValueError:
                pass
        return result

    def quotes(self, payload):
        _exact(payload, ("symbols",), ("sparklines",))
        requested = payload["symbols"]
        sparklines = payload.get("sparklines", False)
        if not isinstance(requested, list) or not 0 < len(requested) <= MAX_SYMBOLS or not isinstance(sparklines, bool):
            raise MarketRequestError(f"Request between 1 and {MAX_SYMBOLS} symbols.")
        symbols = list(dict.fromkeys(valid_symbol(item) for item in requested))
        return self._quotes(symbols, sparklines)

    def _quotes(self, symbols, sparklines):
        snapshots = self._snapshots(symbols)
        names = self._names(symbols)
        quotes = [quote_from_snapshot(snapshots.get(item), names.get(item)) for item in symbols]
        quotes = [item for item in quotes if item]
        if sparklines:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for item, line in zip(quotes, pool.map(self._sparkline, [item["symbol"] for item in quotes])):
                    item["sparkline"] = line
        found = {item["symbol"] for item in quotes}
        return {"quotes": quotes, "missing": [item for item in symbols if item not in found],
                "source": "Massive", "as_of": self.clock()}

    def overview(self, payload):
        _exact(payload, ())
        indices = self._quotes([ticker for ticker, _ in INDEX_PROXIES], True)
        labels = dict(INDEX_PROXIES)
        for item in indices["quotes"]:
            item["label"] = labels[item["symbol"]]
        universe = self._snapshots(MOVER_UNIVERSE)
        movers = [quote_from_snapshot(universe.get(ticker)) for ticker in MOVER_UNIVERSE]
        movers = [item for item in movers if item and item["change_percent"] is not None]
        ranked = sorted(movers, key=lambda item: item["change_percent"])
        names = self._names(list(dict.fromkeys(
            [item["symbol"] for item in ranked[-5:] + ranked[:5]] +
            [item["symbol"] for item in sorted(movers, key=lambda q: -(q["volume"] or 0) * q["price"])[:5]])))
        for item in movers:
            item["name"] = names.get(item["symbol"])
        return {
            "status": self.status(), "indices": indices["quotes"],
            "gainers": [item for item in reversed(ranked[-5:]) if item["change_percent"] > 0],
            "losers": [item for item in ranked[:5] if item["change_percent"] < 0],
            "active": sorted(movers, key=lambda q: -(q["volume"] or 0) * q["price"])[:5],
            "universe": "50 widely held US large caps", "source": "Massive", "as_of": self.clock(),
        }

    def search(self, payload):
        _exact(payload, ("query",))
        query = payload["query"].strip() if isinstance(payload["query"], str) else None
        if not query or not QUERY.fullmatch(query):
            raise MarketRequestError("Search with letters, numbers or a company name.")
        body = self._get("/v3/reference/tickers", {"search": query, "active": "true", "market": "stocks",
                                                    "limit": 40}, 3600, 86400)
        upper, results = query.upper(), []
        for row in _dict(body).get("results") or []:
            row = _dict(row)
            ticker, name = row.get("ticker"), display_name(row.get("name"))
            if not isinstance(ticker, str) or not SYMBOL.fullmatch(ticker) or not name:
                continue
            kind = row.get("type") if isinstance(row.get("type"), str) else ""
            rank = (0 if ticker == upper else 1 if ticker.startswith(upper) else 2,
                    SEARCH_RANK.get(kind, 5), len(ticker), ticker)
            results.append((rank, {"symbol": ticker, "name": name, "type": TYPES.get(kind, kind or "Security"),
                                   "exchange": EXCHANGES.get(row.get("primary_exchange"), row.get("primary_exchange"))}))
        results.sort(key=lambda pair: pair[0])
        return {"query": query, "results": [item for _, item in results[:15]], "source": "Massive"}

    def symbol(self, payload):
        _exact(payload, ("symbol",))
        ticker = valid_symbol(payload["symbol"])
        today = self._today()
        jobs = {
            "snapshot": lambda: self._snapshots([ticker]).get(ticker),
            "details": lambda: self._details(ticker),
            "ratios": lambda: _dict(self._get("/stocks/financials/v1/ratios", {"ticker": ticker, "limit": 1},
                                              21600, 86400)).get("results"),
            "dividends": lambda: _dict(self._get("/stocks/v1/dividends", {"ticker": ticker, "limit": 4,
                                                 "sort": "ex_dividend_date.desc"}, 43200, 86400)).get("results"),
            "news": lambda: _dict(self._get("/v2/reference/news", {"ticker": ticker, "limit": 8,
                                            "order": "desc", "sort": "published_utc"}, 300, 3600)).get("results"),
            "year": lambda: self._bars(ticker, 1, "day", today - timedelta(days=372), today, 3600),
        }
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {key: pool.submit(job) for key, job in jobs.items()}
            data, failures = {}, []
            for key, future in futures.items():
                try:
                    data[key] = future.result()
                except MarketDataError:
                    data[key], failures = None, failures + [key]
        details = _dict(data["details"])
        name = display_name(details.get("name"))
        current = quote_from_snapshot(data["snapshot"], name)
        if current is None and not details:
            if "snapshot" in failures or "details" in failures:
                raise MarketDataError("Market data for this symbol is unavailable right now.")
            raise MarketRequestError("No US-listed security uses that symbol.")
        ratios = _dict(data["ratios"][0]) if isinstance(data["ratios"], list) and data["ratios"] else {}
        year = [bar for bar in data["year"] or [] if bar["_when"] >= today - timedelta(days=365)]
        stats = {
            "open": current and current["open"], "high": current and current["high"],
            "low": current and current["low"], "previous_close": current and current["previous_close"],
            "volume": current and current["volume"], "vwap": current and current["vwap"],
            "average_volume": _number(ratios.get("average_volume"), True),
            "market_cap": _number(ratios.get("market_cap"), True) or _number(details.get("market_cap"), True),
            "pe_ratio": _round(_number(ratios.get("price_to_earnings"), True), 2),
            "eps": _round(_number(ratios.get("earnings_per_share")), 2),
            "dividend_yield": _round(_number(ratios.get("dividend_yield")) * 100, 2)
            if _number(ratios.get("dividend_yield")) is not None else None,
            "price_to_book": _round(_number(ratios.get("price_to_book"), True), 2),
            "week52_high": _round(max(bar["h"] for bar in year)) if year else None,
            "week52_low": _round(min(bar["l"] for bar in year)) if year else None,
            "shares_outstanding": _number(details.get("share_class_shares_outstanding"), True),
        }
        return {
            "symbol": ticker, "name": name, "quote": current,
            "profile": {
                "description": _text(details.get("description"), 1500),
                "homepage": _https(details.get("homepage_url")),
                "employees": _number(details.get("total_employees"), True),
                "industry": _text(details.get("sic_description"), 80).title()
                if _text(details.get("sic_description"), 80) else None,
                "listed": details.get("list_date") if isinstance(details.get("list_date"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", details["list_date"]) else None,
                "exchange": EXCHANGES.get(details.get("primary_exchange"), _text(details.get("primary_exchange"), 12)),
                "type": TYPES.get(details.get("type"), _text(details.get("type"), 12)),
            },
            "stats": stats, "dividend": self._dividend(data["dividends"]),
            "news": self._news(data["news"], ticker), "unavailable": failures,
            "status": self.status(), "source": "Massive", "as_of": self.clock(),
        }

    @staticmethod
    def _dividend(rows):
        for row in rows if isinstance(rows, list) else []:
            row = _dict(row)
            amount = _number(row.get("cash_amount"), True)
            ex_date = row.get("ex_dividend_date")
            if amount and isinstance(ex_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ex_date):
                pay = row.get("pay_date")
                frequency = {1: "Annual", 2: "Semiannual", 4: "Quarterly", 12: "Monthly"}.get(row.get("frequency"))
                return {"amount": _round(amount), "ex_date": ex_date, "frequency": frequency,
                        "pay_date": pay if isinstance(pay, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", pay) else None,
                        "currency": row.get("currency") if row.get("currency") in ("USD",) else "USD"}
        return None

    @staticmethod
    def _news(rows, ticker):
        items = []
        for row in rows if isinstance(rows, list) else []:
            row = _dict(row)
            title, url = _text(row.get("title"), 300), _https(row.get("article_url"))
            published = _published(row.get("published_utc"))
            if published is None:
                continue
            if not title or not url:
                continue
            sentiment = None
            for insight in row.get("insights") or []:
                insight = _dict(insight)
                if insight.get("ticker") == ticker and insight.get("sentiment") in ("positive", "negative", "neutral"):
                    sentiment = insight["sentiment"]
            items.append({"id": _text(row.get("id"), 128) or url, "title": title, "url": url,
                          "publisher": _text(_dict(row.get("publisher")).get("name"), 80),
                          "published": published, "summary": _text(row.get("description"), 400),
                          "sentiment": sentiment})
        return items[:8]

    def crypto(self, payload):
        """USD prices for crypto balances. USD itself is priced at par; unknown pairs are reported missing."""
        _exact(payload, ("currencies",))
        requested = payload["currencies"]
        if not isinstance(requested, list) or not 0 < len(requested) <= MAX_CURRENCIES:
            raise MarketRequestError(f"Request between 1 and {MAX_CURRENCIES} currencies.")
        if not all(isinstance(item, str) and CURRENCY.fullmatch(item) for item in requested):
            raise MarketRequestError("Use currency codes such as BTC.")
        currencies = list(dict.fromkeys(requested))
        pairs = sorted(f"X:{currency}USD" for currency in currencies if currency != "USD")
        rows = {}
        if pairs:
            body = self._get("/v2/snapshot/locale/global/markets/crypto/tickers", {"tickers": ",".join(pairs)}, 15, 900)
            rows = {row.get("ticker"): row for row in _dict(body).get("tickers") or [] if isinstance(row, dict)}
        prices, missing = [], []
        for currency in currencies:
            if currency == "USD":
                prices.append({"currency": "USD", "price": 1.0, "change_percent": 0.0, "updated": None})
                continue
            quote = crypto_quote(rows.get(f"X:{currency}USD"))
            if quote:
                prices.append({"currency": currency, **quote})
            else:
                missing.append(currency)
        return {"prices": prices, "missing": missing, "source": "Massive", "as_of": self.clock()}

    def chart(self, payload):
        _exact(payload, ("symbol", "range"))
        ticker, span = valid_symbol(payload["symbol"]), payload["range"]
        if span not in RANGES:
            raise MarketRequestError("Unsupported chart range.")
        today = self._today()
        if span in ("1D", "1W", "1M"):
            minutes, lookback, sessions = {"1D": (5, 7, 1), "1W": (30, 14, 5), "1M": (30, 45, 21)}[span]
            bars = self._bars(ticker, minutes, "minute", today - timedelta(days=lookback), today,
                              60 if span == "1D" else 300)
            points, days = _regular_sessions(bars, sessions)
            daily = self._bars(ticker, 1, "day", today - timedelta(days=lookback + 10), today, 3600)
            before = [bar for bar in daily if days and bar["_when"] < days[0]]
            baseline = before[-1]["c"] if before else (points[0]["o"] if points else None)
            interval = f"{minutes} min"
        else:
            start = {"3M": today - timedelta(days=92), "6M": today - timedelta(days=183),
                     "YTD": date(today.year, 1, 1), "1Y": today - timedelta(days=366),
                     "5Y": today - timedelta(days=5 * 366)}[span]
            timespan = "week" if span == "5Y" else "day"
            bars = self._bars(ticker, 1, timespan, start - timedelta(days=14), today, 3600)
            points = [bar for bar in bars if bar["_when"] >= start]
            before = [bar for bar in bars if bar["_when"] < start]
            baseline = before[-1]["c"] if before else (points[0]["o"] if points else None)
            interval = "1 week" if span == "5Y" else "1 day"
        return {"symbol": ticker, "range": span, "interval": interval, "points": _public(points),
                "baseline": baseline, "regular_hours_only": span in ("1D", "1W", "1M"),
                "source": "Massive", "as_of": self.clock()}


_service = None
_service_lock = threading.Lock()


def service():
    global _service
    with _service_lock:
        if _service is None:
            _service = MarketService()
        return _service


def market_request(path, payload):
    current = service()
    if path == "/v1/market/overview":
        return current.overview(payload)
    if path == "/v1/market/quotes":
        return current.quotes(payload)
    if path == "/v1/market/search":
        return current.search(payload)
    if path == "/v1/market/symbol":
        return current.symbol(payload)
    if path == "/v1/market/chart":
        return current.chart(payload)
    if path == "/v1/market/crypto":
        return current.crypto(payload)
    raise MarketRequestError("Unknown market route.")
