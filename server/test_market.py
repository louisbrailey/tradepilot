import io
import json
import unittest
from datetime import datetime, timedelta
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

import market_service as market
import server
from market_service import ET, MarketDataError, MarketRequestError, MarketService, TTLCache


def et(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET).timestamp()


FRIDAY_2PM = et(2026, 11, 6, 14)
SATURDAY_NOON = et(2026, 11, 7, 12)


def snapshot(ticker, close, previous, volume=1_000_000, updated=FRIDAY_2PM):
    return {"ticker": ticker, "todaysChange": 999, "updated": int(updated * 1e9),
            "day": {"o": previous, "h": max(close, previous) + 1, "l": min(close, previous) - 1,
                    "c": close, "v": volume, "vw": close},
            "prevDay": {"c": previous}, "lastTrade": {"p": close, "t": int((updated - 5) * 1e9)},
            "lastQuote": {"p": close - 0.01, "P": close + 0.01}, "min": {"c": close, "t": int(updated * 1e3)}}


def intraday(day, minutes, start=(4, 0), end=(20, 0), base=100.0):
    rows, at = [], datetime(day.year, day.month, day.day, *start, tzinfo=ET)
    stop = datetime(day.year, day.month, day.day, *end, tzinfo=ET)
    while at < stop:
        price = base + at.hour + at.minute / 100
        rows.append({"t": int(at.timestamp() * 1000), "o": price, "h": price + 0.5, "l": price - 0.5,
                     "c": price, "v": 1000})
        at += timedelta(minutes=minutes)
    return rows


def daily(days, base=100.0):
    return [{"t": int(datetime(day.year, day.month, day.day, tzinfo=ET).timestamp() * 1000),
             "o": base + i, "h": base + i + 2, "l": base + i - 2, "c": base + i + 1, "v": 10}
            for i, day in enumerate(days)]


class FakeProvider:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        for prefix, result in self.routes.items():
            if path.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return result(path, params or {}) if callable(result) else result
        return None


class QuoteNormalisationTests(unittest.TestCase):
    def test_change_is_measured_from_previous_close_not_provider_field(self):
        quote = market.quote_from_snapshot(snapshot("AAPL", 110.0, 100.0), "Apple Inc.")
        self.assertEqual((quote["price"], quote["change"], quote["change_percent"]), (110.0, 10.0, 10.0))
        self.assertEqual(quote["name"], "Apple Inc.")
        self.assertEqual((quote["bid"], quote["ask"]), (109.99, 110.01))
        self.assertAlmostEqual(quote["updated"], FRIDAY_2PM)

    def test_nanosecond_and_millisecond_timestamps_are_both_read(self):
        row = snapshot("AAPL", 110.0, 100.0, updated=FRIDAY_2PM)
        row.pop("min")
        self.assertAlmostEqual(market.quote_from_snapshot(row)["updated"], FRIDAY_2PM, places=3)
        row["updated"] = int((FRIDAY_2PM + 9) * 1e9)
        self.assertAlmostEqual(market.quote_from_snapshot(row)["updated"], FRIDAY_2PM + 9, places=3)
        self.assertIsNone(market._epoch(float("inf"), 1e9))
        self.assertIsNone(market._epoch(True, 1e3))

    def test_overnight_cleared_day_bar_shows_last_close_without_change(self):
        row = snapshot("AAPL", 110.0, 100.0)
        row["day"] = {"o": 0, "h": 0, "l": 0, "c": 0, "v": 0}
        quote = market.quote_from_snapshot(row)
        self.assertEqual(quote["price"], 100.0)
        self.assertIsNone(quote["change"])
        self.assertIsNone(quote["open"])

    def test_malformed_rows_and_crossed_books_are_rejected(self):
        for row in (None, {}, {"ticker": "aapl"}, {"ticker": "AAPL", "day": {"c": float("nan")}, "prevDay": {}},
                    {"ticker": "AAPL", "day": {"c": True}, "prevDay": {"c": -1}}):
            with self.subTest(row=row):
                self.assertIsNone(market.quote_from_snapshot(row))
        row = snapshot("AAPL", 110.0, 100.0)
        row["lastQuote"] = {"p": 111, "P": 109}
        self.assertNotIn("bid", market.quote_from_snapshot(row))


class PresentationTests(unittest.TestCase):
    def test_after_hours_line_comes_from_late_minute_bars_only(self):
        row = snapshot("SPY", 735.29, 733.0, updated=et(2026, 11, 6, 20))
        row["min"] = {"c": 736.53, "t": int(et(2026, 11, 6, 19, 59) * 1000)}
        extended = market.quote_from_snapshot(row)["extended"]
        self.assertEqual((extended["session"], extended["price"], extended["change"]), ("after_hours", 736.53, 1.24))
        row["min"] = {"c": 736.53, "t": int(et(2026, 11, 6, 15, 59) * 1000)}
        self.assertNotIn("extended", market.quote_from_snapshot(row))
        row["day"] = {"c": 0}
        row["min"] = {"c": 736.53, "t": int(et(2026, 11, 6, 19, 59) * 1000)}
        self.assertNotIn("extended", market.quote_from_snapshot(row))

    def test_display_names_drop_listing_boilerplate(self):
        cases = {"Tesla, Inc. Common Stock": "Tesla, Inc.",
                 "Palantir Technologies Inc. Class A Common Stock": "Palantir Technologies Inc. Class A",
                 "BERKSHIRE HATHAWAY Class B": "Berkshire Hathaway Class B",
                 "Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares (each representing 5)": "Taiwan Semiconductor Manufacturing Company Ltd. ADR",
                 "SPDR S&P 500 ETF Trust": "SPDR S&P 500 ETF Trust", "  ": None, None: None}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(market.display_name(raw), expected)


class QuoteRouteTests(unittest.TestCase):
    def service(self, extra=None, clock=FRIDAY_2PM):
        friday = datetime.fromtimestamp(FRIDAY_2PM, ET).date()
        routes = {
            "/v2/snapshot/locale/us/markets/stocks/tickers": lambda path, params: {"tickers": [
                snapshot(item, 110.0, 100.0) for item in params["tickers"].split(",") if item != "ZZZZ"]},
            "/v3/reference/tickers/": lambda path, params: {"results": {"name": path.rsplit("/", 1)[1] + " Corp"}},
            "/v2/aggs/ticker/": {"results": intraday(friday - timedelta(days=1), 15) + intraday(friday, 15)},
            "/v1/marketstatus/now": {"market": "open"},
        }
        routes.update(extra or {})
        provider = FakeProvider(routes)
        return MarketService(provider, clock=lambda: clock), provider

    def test_quotes_keep_requested_order_report_missing_and_add_names(self):
        service, _ = self.service()
        result = service.quotes({"symbols": ["MSFT", "ZZZZ", "AAPL", "MSFT"]})
        self.assertEqual([q["symbol"] for q in result["quotes"]], ["MSFT", "AAPL"])
        self.assertEqual(result["missing"], ["ZZZZ"])
        self.assertEqual(result["quotes"][0]["name"], "MSFT Corp")
        self.assertNotIn("sparkline", result["quotes"][0])

    def test_sparkline_uses_only_the_latest_regular_session(self):
        service, _ = self.service()
        line = service.quotes({"symbols": ["AAPL"], "sparklines": True})["quotes"][0]["sparkline"]
        self.assertEqual(len(line), 26)  # 9:30 through 15:45 in 15-minute bars
        self.assertEqual(line[0], 109.3)
        self.assertEqual(line[-1], 115.45)

    def test_invalid_quote_requests_are_refused_before_the_provider_is_called(self):
        service, provider = self.service()
        for payload in ({}, {"symbols": []}, {"symbols": ["aapl"]}, {"symbols": "AAPL"},
                        {"symbols": ["AAPL"], "sparklines": "yes"}, {"symbols": ["AAPL"], "extra": 1},
                        {"symbols": ["A"] * 41}, {"symbols": ["AAPL; DROP"]}, []):
            with self.subTest(payload=payload), self.assertRaises(MarketRequestError):
                service.quotes(payload)
        self.assertEqual(provider.calls, [])

    def test_cached_quotes_stand_in_briefly_when_the_provider_fails(self):
        now = [FRIDAY_2PM]
        service, provider = self.service()
        service.clock = service.cache.clock = lambda: now[0]
        service.quotes({"symbols": ["AAPL"]})
        provider.routes["/v2/snapshot/locale/us/markets/stocks/tickers"] = MarketDataError("down")
        now[0] += 60
        self.assertEqual(service.quotes({"symbols": ["AAPL"]})["quotes"][0]["price"], 110.0)
        now[0] += 3600
        with self.assertRaisesRegex(MarketDataError, "down"):
            service.quotes({"symbols": ["AAPL"]})


class OverviewTests(unittest.TestCase):
    def test_movers_come_only_from_the_large_cap_universe(self):
        changes = {ticker: (index - 25) for index, ticker in enumerate(market.MOVER_UNIVERSE)}

        def snapshots(path, params):
            tickers = params["tickers"].split(",")
            rows = [snapshot(t, 100 + changes.get(t, 0), 100.0, volume=1000 + changes.get(t, 0)) for t in tickers]
            return {"tickers": rows + [snapshot("JUNKW", 0.02, 0.01)]}
        provider = FakeProvider({"/v2/snapshot/locale/us/markets/stocks/tickers": snapshots,
                                 "/v3/reference/tickers/": {"results": {"name": "Fixture"}},
                                 "/v2/aggs/ticker/": {"results": []},
                                 "/v1/marketstatus/now": {"market": "closed"}})
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).overview({})
        self.assertEqual([q["symbol"] for q in result["indices"]], ["SPY", "QQQ", "DIA", "IWM"])
        self.assertEqual(result["indices"][0]["label"], "S&P 500")
        self.assertEqual([q["symbol"] for q in result["gainers"]], list(reversed(market.MOVER_UNIVERSE[-5:])))
        self.assertEqual([q["symbol"] for q in result["losers"]], list(market.MOVER_UNIVERSE[:5]))
        self.assertNotIn("JUNKW", json.dumps(result))
        self.assertTrue(all(q["change_percent"] > 0 for q in result["gainers"]))
        self.assertEqual(result["status"]["state"], "closed")
        self.assertEqual(result["gainers"][0]["name"], "Fixture")
        with self.assertRaises(MarketRequestError):
            MarketService(provider).overview({"unexpected": True})

    def test_status_maps_provider_sessions_and_next_open(self):
        cases = [({"market": "open"}, FRIDAY_2PM, "open"),
                 ({"market": "extended-hours", "earlyHours": True}, et(2026, 11, 6, 8), "pre_market"),
                 ({"market": "extended-hours", "afterHours": True}, et(2026, 11, 6, 17), "after_hours"),
                 ({"market": "closed"}, SATURDAY_NOON, "closed")]
        for body, clock, state in cases:
            with self.subTest(state=state):
                status = MarketService(FakeProvider({"/v1/marketstatus/now": body}), clock=lambda: clock).status()
                self.assertEqual(status["state"], state)
                self.assertFalse(status["estimated"])
        open_status = MarketService(FakeProvider({"/v1/marketstatus/now": {"market": "open"}}),
                                    clock=lambda: FRIDAY_2PM).status()
        self.assertEqual(open_status["closes_at"], et(2026, 11, 6, 16))
        weekend = MarketService(FakeProvider({"/v1/marketstatus/now": {"market": "closed"}}),
                                clock=lambda: SATURDAY_NOON).status()
        self.assertEqual(weekend["opens_at"], et(2026, 11, 9, 9, 30))
        thanksgiving_eve = MarketService(FakeProvider({"/v1/marketstatus/now": {"market": "closed"}}),
                                         clock=lambda: et(2026, 11, 25, 18)).status()
        self.assertEqual(thanksgiving_eve["opens_at"], et(2026, 11, 27, 9, 30))
        early = MarketService(FakeProvider({"/v1/marketstatus/now": {"market": "open"}}),
                              clock=lambda: et(2026, 11, 27, 10)).status()
        self.assertEqual(early["closes_at"], et(2026, 11, 27, 13))

    def test_status_falls_back_to_the_calendar_and_says_so(self):
        provider = FakeProvider({"/v1/marketstatus/now": MarketDataError("down")})
        status = MarketService(provider, clock=lambda: FRIDAY_2PM).status()
        self.assertEqual(status["state"], "open")
        self.assertTrue(status["estimated"])
        holiday = MarketService(provider, clock=lambda: et(2026, 11, 26, 11)).status()
        self.assertEqual(holiday["state"], "closed")


class SearchTests(unittest.TestCase):
    def test_exact_symbols_rank_first_and_warrants_last(self):
        rows = [{"ticker": "APLEW", "name": "Apple Warrant", "type": "WARRANT", "primary_exchange": "XNAS"},
                {"ticker": "APLE", "name": "Apple Hospitality REIT", "type": "CS", "primary_exchange": "XNYS"},
                {"ticker": "AAPL", "name": "Apple Inc.", "type": "CS", "primary_exchange": "XNAS"},
                {"ticker": "bad", "name": "Lowercase"}, {"ticker": "NONAME"}]
        provider = FakeProvider({"/v3/reference/tickers": {"results": rows}})
        result = MarketService(provider).search({"query": "aapl"})
        self.assertEqual([r["symbol"] for r in result["results"]], ["AAPL", "APLE", "APLEW"])
        self.assertEqual(result["results"][0]["exchange"], "Nasdaq")
        self.assertEqual(result["results"][0]["type"], "Stock")
        self.assertEqual(provider.calls[0][1]["search"], "aapl")

    def test_queries_are_bounded(self):
        provider = FakeProvider({})
        for query in ("", "   ", "a" * 41, "<script>", "AA\nPL", 5, None):
            with self.subTest(query=query), self.assertRaises(MarketRequestError):
                MarketService(provider).search({"query": query})
        self.assertEqual(provider.calls, [])


class SymbolTests(unittest.TestCase):
    def routes(self):
        today = datetime.fromtimestamp(FRIDAY_2PM, ET).date()
        year = [today - timedelta(days=offset) for offset in range(400, -1, -1)]
        bars = daily(year)
        bars[0]["h"] = 10_000  # older than 52 weeks: must not set the high
        return {
            "/v2/snapshot/locale/us/markets/stocks/tickers": {"tickers": [snapshot("AAPL", 110.0, 100.0)]},
            "/v3/reference/tickers/AAPL": {"results": {
                "name": "Apple Inc.", "description": "Makes  phones.\n", "homepage_url": "http://apple.com",
                "total_employees": 167000, "sic_description": "ELECTRONIC COMPUTERS", "list_date": "1980-12-12",
                "primary_exchange": "XNAS", "type": "CS", "market_cap": 1.0}},
            "/stocks/financials/v1/ratios": {"results": [{"price_to_earnings": 37.844, "earnings_per_share": 9.1,
                                                          "dividend_yield": 0.0031, "market_cap": 5e12,
                                                          "average_volume": 44e6, "price_to_book": 44.62}]},
            "/stocks/v1/dividends": {"results": [{"cash_amount": 0.27, "ex_dividend_date": "2026-11-12",
                                                  "pay_date": "2026-11-16", "frequency": 4, "currency": "USD"}]},
            "/v2/reference/news": {"results": [
                {"id": "1", "title": "Apple ships", "article_url": "https://example.com/a",
                 "published_utc": "2026-11-06T18:00:00Z", "publisher": {"name": "Wire"},
                 "insights": [{"ticker": "MSFT", "sentiment": "negative"}, {"ticker": "AAPL", "sentiment": "positive"}]},
                {"id": "2", "title": "Plain link", "article_url": "http://example.com/b", "published_utc": "2026-11-06T18:00:00Z"},
                {"id": "3", "title": "Bad date", "article_url": "https://example.com/c", "published_utc": "yesterday"}]},
            "/v2/aggs/ticker/AAPL/range/1/day/": {"results": bars},
            "/v1/marketstatus/now": {"market": "open"},
        }

    def test_symbol_page_combines_quote_profile_stats_dividend_and_news(self):
        result = MarketService(FakeProvider(self.routes()), clock=lambda: FRIDAY_2PM).symbol({"symbol": "AAPL"})
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertEqual(result["quote"]["price"], 110.0)
        profile, stats = result["profile"], result["stats"]
        self.assertEqual(profile["description"], "Makes phones.")
        self.assertIsNone(profile["homepage"])  # only https links reach the phone
        self.assertEqual((profile["industry"], profile["exchange"], profile["type"]), ("Electronic Computers", "Nasdaq", "Stock"))
        self.assertEqual((stats["pe_ratio"], stats["eps"], stats["dividend_yield"], stats["market_cap"]), (37.84, 9.1, 0.31, 5e12))
        self.assertLess(stats["week52_high"], 10_000)
        self.assertEqual(result["dividend"], {"amount": 0.27, "ex_date": "2026-11-12", "frequency": "Quarterly",
                                              "pay_date": "2026-11-16", "currency": "USD"})
        self.assertEqual([item["title"] for item in result["news"]], ["Apple ships"])
        self.assertEqual(result["news"][0]["sentiment"], "positive")
        self.assertEqual(result["unavailable"], [])

    def test_partial_provider_failures_are_reported_not_hidden(self):
        routes = self.routes()
        routes["/stocks/financials/v1/ratios"] = MarketDataError("plan")
        routes["/v2/reference/news"] = MarketDataError("busy")
        result = MarketService(FakeProvider(routes), clock=lambda: FRIDAY_2PM).symbol({"symbol": "AAPL"})
        self.assertEqual(sorted(result["unavailable"]), ["news", "ratios"])
        self.assertIsNone(result["stats"]["pe_ratio"])
        self.assertEqual(result["news"], [])

    def test_unknown_symbol_and_total_outage_are_distinguished(self):
        unknown = FakeProvider({"/v1/marketstatus/now": {"market": "open"}})
        with self.assertRaisesRegex(MarketRequestError, "No US-listed security"):
            MarketService(unknown, clock=lambda: FRIDAY_2PM).symbol({"symbol": "ZZZZ"})
        down = FakeProvider({"/": MarketDataError("Couldn't reach the market data provider.")})
        with self.assertRaisesRegex(MarketDataError, "unavailable right now"):
            MarketService(down, clock=lambda: FRIDAY_2PM).symbol({"symbol": "AAPL"})


class ChartTests(unittest.TestCase):
    def test_one_day_chart_is_regular_hours_with_previous_close_baseline(self):
        friday = datetime.fromtimestamp(FRIDAY_2PM, ET).date()
        thursday = friday - timedelta(days=1)
        routes = {"/v2/aggs/ticker/AAPL/range/5/minute/": {"results": intraday(thursday, 5) + intraday(friday, 5, end=(14, 0))},
                  "/v2/aggs/ticker/AAPL/range/1/day/": {"results": daily([thursday - timedelta(days=1), thursday, friday])}}
        result = MarketService(FakeProvider(routes), clock=lambda: FRIDAY_2PM).chart({"symbol": "AAPL", "range": "1D"})
        times = [datetime.fromtimestamp(point["t"], ET) for point in result["points"]]
        self.assertTrue(all(t.date() == friday for t in times))
        self.assertEqual((times[0].hour, times[0].minute), (9, 30))
        self.assertEqual((times[-1].hour, times[-1].minute), (13, 55))
        self.assertEqual(result["baseline"], 102.0)  # Thursday's daily close
        self.assertTrue(result["regular_hours_only"])

    def test_daily_ranges_use_the_close_before_the_range_as_baseline(self):
        today = datetime.fromtimestamp(FRIDAY_2PM, ET).date()
        days = [today - timedelta(days=offset) for offset in range(400, -1, -1)]
        provider = FakeProvider({"/v2/aggs/ticker/AAPL/range/1/day/": {"results": daily(days)}})
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).chart({"symbol": "AAPL", "range": "1Y"})
        start = today - timedelta(days=366)
        self.assertGreaterEqual(datetime.fromtimestamp(result["points"][0]["t"], ET).date(), start - timedelta(days=1))
        self.assertEqual(result["baseline"], daily(days)[days.index(start) - 1]["c"])
        self.assertNotIn("_when", result["points"][0])
        self.assertIn("/range/1/day/", provider.calls[0][0])
        five = MarketService(FakeProvider({"/v2/aggs/ticker/AAPL/range/1/week/": {"results": []}})).chart(
            {"symbol": "AAPL", "range": "5Y"})
        self.assertEqual((five["points"], five["baseline"], five["interval"]), ([], None, "1 week"))

    def test_bad_bars_and_requests_are_rejected(self):
        rows = [{"t": 1793975400000, "o": 10, "h": 9, "l": 8, "c": 10},  # high below open
                {"t": 1793975400000, "o": 10, "h": 11, "l": 9, "c": float("inf")},
                {"t": "x", "o": 1, "h": 1, "l": 1, "c": 1}]
        self.assertEqual(market._clean_bars(rows, daily=False), [])
        for payload in ({"symbol": "AAPL"}, {"symbol": "AAPL", "range": "2D"}, {"symbol": "aapl", "range": "1D"}):
            with self.subTest(payload=payload), self.assertRaises(MarketRequestError):
                MarketService(FakeProvider({})).chart(payload)


class CryptoTests(unittest.TestCase):
    def test_crypto_prices_use_latest_trade_par_usd_and_report_missing(self):
        rows = {"tickers": [
            {"ticker": "X:BTCUSD", "lastTrade": {"p": 76078.93, "t": int(FRIDAY_2PM * 1000)}, "day": {"c": 76054.4},
             "prevDay": {"c": 75731.04}, "updated": int(FRIDAY_2PM * 1e9)},
            {"ticker": "X:SHIBUSD", "day": {"c": 0.0000123456789}, "prevDay": {"c": 0.00001}},
            {"ticker": "X:BADUSD", "lastTrade": {"p": -1}}]}
        provider = FakeProvider({"/v2/snapshot/locale/global/markets/crypto/tickers": rows})
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).crypto({"currencies": ["BTC", "USD", "SHIB", "BAD", "BTC", "ZZZ"]})
        prices = {item["currency"]: item for item in result["prices"]}
        self.assertEqual(prices["BTC"]["price"], 76078.93)
        self.assertAlmostEqual(prices["BTC"]["change_percent"], 0.4596, places=3)
        self.assertAlmostEqual(prices["BTC"]["updated"], FRIDAY_2PM, places=3)
        self.assertEqual(prices["USD"]["price"], 1.0)
        self.assertEqual(prices["SHIB"]["price"], 0.0000123457)
        self.assertEqual(result["missing"], ["BAD", "ZZZ"])
        self.assertEqual(provider.calls[0][1]["tickers"], "X:BADUSD,X:BTCUSD,X:SHIBUSD,X:ZZZUSD")

    def test_usd_only_needs_no_provider_and_requests_are_validated(self):
        provider = FakeProvider({})
        self.assertEqual(MarketService(provider).crypto({"currencies": ["USD"]})["prices"][0]["price"], 1.0)
        self.assertEqual(provider.calls, [])
        for payload in ({}, {"currencies": []}, {"currencies": ["btc"]}, {"currencies": ["B"]},
                        {"currencies": ["BTC", 5]}, {"currencies": ["X" * 11]}, {"currencies": ["A1"] * 61},
                        {"currencies": ["BTC"], "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(MarketRequestError):
                MarketService(provider).crypto(payload)


def option_row(kind, strike, expiration="2026-11-13", bid=1.0, ask=1.2, underlying=342.79):
    code = f"O:AAPL{expiration.replace('-', '')[2:]}{'C' if kind == 'call' else 'P'}{int(strike * 1000):08d}"
    return {"details": {"contract_type": kind, "strike_price": strike, "expiration_date": expiration, "ticker": code, "shares_per_contract": 100},
            "last_quote": {"bid": bid, "ask": ask, "last_updated": int(FRIDAY_2PM * 1e9)},
            "last_trade": {"price": (bid + ask) / 2, "sip_timestamp": int((FRIDAY_2PM - 5) * 1e9)},
            "greeks": {"delta": 0.5 if kind == "call" else -0.5, "gamma": 0.05, "theta": -0.6, "vega": 0.1},
            "implied_volatility": 0.2855, "open_interest": 1734, "day": {"volume": 4756, "change_percent": 1.5},
            "break_even_price": strike + 1.1, "underlying_asset": {"ticker": "AAPL", "price": underlying}}


class OptionsTests(unittest.TestCase):
    def provider(self, chain_pages):
        contracts = {"results": [{"expiration_date": day} for day in ("2026-11-13", "2026-11-09", "2026-11-13", "2026-11-20", "bad")]}
        contracts["results"].extend(row["details"] for page in chain_pages for row in page.get("results", []))
        routes = {"/v3/reference/options/contracts": contracts}
        pages = iter(chain_pages)
        routes["/v3/snapshot/options/AAPL"] = lambda path, params: next(pages)
        return FakeProvider(routes)

    def test_chain_pairs_calls_and_puts_by_strike_for_the_nearest_expiration(self):
        provider = self.provider([{"results": [option_row("call", 340, "2026-11-09"), option_row("put", 340, "2026-11-09"),
                                               option_row("call", 345, "2026-11-09"), option_row("call", 350, "2026-11-13")]}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL"})
        self.assertEqual(result["expirations"], ["2026-11-09", "2026-11-13", "2026-11-20"])
        self.assertEqual(result["expiration"], "2026-11-09")
        self.assertEqual(result["underlying"], 342.79)
        self.assertEqual([row["strike"] for row in result["strikes"]], [340, 345])
        self.assertIsNone(result["strikes"][1]["put"])
        call = result["strikes"][0]["call"]
        self.assertEqual((call["bid"], call["ask"], call["implied_volatility"], call["open_interest"]), (1.0, 1.2, 28.55, 1734))
        self.assertEqual(provider.calls[-1][1]["expiration_date"], "2026-11-09")

    def test_explicit_expiration_and_bad_dates(self):
        provider = self.provider([{"results": [option_row("put", 345, "2026-11-20")]}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": "2026-11-20"})
        self.assertEqual((result["expiration"], len(result["strikes"])), ("2026-11-20", 1))
        for payload in ({"symbol": "AAPL", "expiration": "Nov 20"}, {"symbol": "AAPL", "expiration": 5},
                        {"symbol": "aapl"}, {"symbol": "AAPL", "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(MarketRequestError):
                MarketService(FakeProvider({})).options(payload)

    def test_pages_follow_only_provider_links(self):
        provider = self.provider([
            {"results": [option_row("call", 340, "2026-11-09")],
             "next_url": "https://api.massive.com/v3/snapshot/options/AAPL?cursor=abc%3D%3D"},
            {"results": [option_row("call", 345, "2026-11-09")], "next_url": "https://evil.example/steal?cursor=x"},
            {"results": [option_row("call", 999, "2026-11-09")]}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL"})
        self.assertEqual([row["strike"] for row in result["strikes"]], [340, 345])
        self.assertEqual(provider.calls[-1][1], {"cursor": "abc=="})

    def test_unusable_contracts_are_dropped_and_crossed_quotes_cleared(self):
        self.assertIsNone(market.option_quote({"details": {"contract_type": "swap", "strike_price": 1, "ticker": "O:X"}}))
        self.assertIsNone(market.option_quote({"details": {"contract_type": "call", "strike_price": -1, "ticker": "O:X"}}))
        crossed = market.option_quote(option_row("call", 340, bid=2.0, ask=1.0))
        self.assertEqual((crossed["bid"], crossed["ask"]), (None, None))

    def test_symbol_without_options_returns_an_empty_chain(self):
        provider = FakeProvider({"/v3/reference/options/contracts": {"results": []}})
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "BRK.A"})
        self.assertEqual((result["expirations"], result["strikes"], result["expiration"]), ([], [], None))

    def test_page_limit_does_not_fetch_a_page_that_will_be_discarded(self):
        path = "/v3/reference/options/contracts"
        provider = FakeProvider({path: {"results": [{"expiration_date": "2026-11-13"}],
                                       "next_url": "https://api.massive.com" + path + "?cursor=unused"}})
        result = MarketService(provider)._paged(path, {}, 3600, pages=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(provider.calls), 1)

    def test_invalid_or_unavailable_expiration_is_never_replaced_by_another(self):
        for expiration in ("2026-99-99", "2026-02-30", "2026-11-12"):
            with self.subTest(expiration=expiration):
                provider = self.provider([{"results": []}])
                with self.assertRaises(MarketRequestError):
                    MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": expiration})
                self.assertFalse(any("/snapshot/" in path for path, _ in provider.calls))

    def test_adjusted_and_standard_contracts_at_one_strike_are_kept_separate(self):
        standard, adjusted = option_row("call", 340), option_row("call", 340)
        adjusted["details"].update(ticker=adjusted["details"]["ticker"].replace("AAPL", "AAPL1"), shares_per_contract=10)
        provider = self.provider([{"results": [standard, adjusted, option_row("put", 340)]}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": "2026-11-13"})
        self.assertEqual([row["series"] for row in result["strikes"]], ["AAPL", "AAPL1"])
        first, second = result["strikes"]
        self.assertTrue(first["call"]["standard_contract"])
        self.assertIsNotNone(first["put"])
        self.assertFalse(second["call"]["standard_contract"])
        self.assertEqual(second["call"]["shares_per_contract"], 10)
        self.assertIsNone(second["put"])

    def test_contracts_with_extra_deliverables_are_not_priced_as_standard(self):
        row = option_row("call", 340)
        provider = self.provider([{"results": [row]}])
        provider.routes["/v3/reference/options/contracts"]["results"][-1] = dict(row["details"], additional_underlyings=[{"type": "cash", "amount": 12}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": "2026-11-13"})
        self.assertFalse(result["strikes"][0]["call"]["standard_contract"])

    def test_unknown_contract_size_and_missing_activity_remain_unknown(self):
        row = option_row("call", 340)
        row["details"].pop("shares_per_contract")
        row.pop("open_interest")
        row["day"]["volume"] = -1
        provider = self.provider([{"results": [row]}])
        result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": "2026-11-13"})
        contract = result["strikes"][0]["call"]
        self.assertIsNone(contract["standard_contract"])
        self.assertIsNone(contract["shares_per_contract"])
        self.assertIsNone(contract["volume"])
        self.assertIsNone(contract["open_interest"])

    def test_contract_identity_must_agree_with_the_quoted_terms(self):
        for field, value in (("contract_type", "put"), ("strike_price", 345), ("expiration_date", "2026-11-20")):
            row = option_row("call", 340)
            row["details"][field] = value
            with self.subTest(field=field):
                self.assertIsNone(market.option_quote(row))

    def test_conflicting_contract_sizes_do_not_produce_a_standard_premium(self):
        row = option_row("call", 340)
        reference = dict(row["details"], shares_per_contract=10)
        contract = market.option_quote(row, reference)
        self.assertIsNone(contract["shares_per_contract"])
        self.assertIsNone(contract["standard_contract"])

    def test_malformed_contract_identifiers_are_ignored(self):
        for identifier in ([], {}, None):
            with self.subTest(identifier=identifier):
                row = option_row("call", 340)
                row["details"]["ticker"] = identifier
                provider = self.provider([{"results": [row]}])
                result = MarketService(provider, clock=lambda: FRIDAY_2PM).options({"symbol": "AAPL", "expiration": "2026-11-13"})
                self.assertEqual(result["strikes"], [])

    def test_zero_ask_does_not_become_a_free_contract_premium(self):
        for bid in (0, 1):
            contract = market.option_quote(option_row("call", 340, bid=bid, ask=0))
            self.assertEqual((contract["bid"], contract["ask"]), (None, None))
        quoted = market.option_quote(option_row("call", 340, bid=0, ask=1))
        self.assertEqual((quoted["bid"], quoted["ask"]), (0, 1))


class CacheAndClientTests(unittest.TestCase):
    def test_cache_expires_and_evicts(self):
        now = [0.0]
        cache = TTLCache(lambda: now[0], limit=2)
        calls = []
        load = lambda value: (lambda: calls.append(value) or value)
        self.assertEqual(cache.fetch("a", 10, 0, load(1)), 1)
        self.assertEqual(cache.fetch("a", 10, 0, load(2)), 1)
        now[0] = 11
        self.assertEqual(cache.fetch("a", 10, 0, load(3)), 3)
        cache.fetch("b", 10, 0, load(4)); cache.fetch("c", 10, 0, load(5))
        self.assertLessEqual(len(cache.items), 2)

    def test_client_maps_provider_failures_to_user_messages(self):
        client = market.MassiveClient(key="fixture-key")

        class Opener:
            def __init__(self, outcome): self.outcome, self.requests = outcome, []
            def open(self, request, timeout):
                self.requests.append(request)
                if isinstance(self.outcome, Exception): raise self.outcome
                return self.outcome

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()

        def http(code):
            return HTTPError("https://api.massive.com/x", code, "fixture", Message(), io.BytesIO(b"{}"))

        client.opener = Opener(http(404))
        self.assertIsNone(client.get("/v3/reference/tickers/ZZZZ"))
        self.assertEqual(client.opener.requests[0].get_header("Authorization"), "Bearer fixture-key")
        for outcome, message in ((http(403), "plan"), (http(429), "busy"), (http(500), "returned an error"),
                                 (http(302), "returned an error"), (OSError("dns"), "Couldn't reach"),
                                 (Response(b"[]"), "unreadable"), (Response(b"{oops"), "unreadable"),
                                 (Response(b'{"status": "NOT_AUTHORIZED"}'), "plan")):
            with self.subTest(message=message):
                client.opener = Opener(outcome)
                with self.assertRaisesRegex(MarketDataError, message):
                    client.get("/v1/marketstatus/now")
        client.opener = Opener(Response(b'{"status": "OK", "results": []}'))
        self.assertEqual(client.get("/x", {"a": "b"}), {"status": "OK", "results": []})
        self.assertEqual(client.opener.requests[0].full_url, "https://api.massive.com/x?a=b")
        with patch.dict(market.os.environ, {}, clear=True), self.assertRaisesRegex(MarketDataError, "isn't set up"):
            market.MassiveClient()


class GatewayRouteTests(unittest.TestCase):
    def post(self, path, payload, authorized=True):
        handler = server.Handler.__new__(server.Handler)
        handler.path = path
        handler.headers = Message()
        if authorized:
            handler.headers["Authorization"] = "Bearer " + "x" * 32
        data = json.dumps(payload).encode()
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = str(len(data))
        handler.rfile = io.BytesIO(data)
        responses = []
        handler.reply = lambda status, result: responses.append((status, result))
        handler.do_POST()
        return responses[0]

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_market_routes_require_auth_and_map_errors(self):
        with patch.object(server, "market_request", return_value={"quotes": []}) as route:
            self.assertEqual(self.post("/v1/market/quotes", {"symbols": ["AAPL"]}, authorized=False)[0], 401)
            route.assert_not_called()
            self.assertEqual(self.post("/v1/market/quotes", {"symbols": ["AAPL"]}), (200, {"quotes": []}))
            route.assert_called_once_with("/v1/market/quotes", {"symbols": ["AAPL"]})
        with patch.object(server, "market_request", side_effect=MarketDataError("Market data is busy.")):
            self.assertEqual(self.post("/v1/market/overview", {}), (503, {"error": "Market data is busy."}))
        with patch.object(server, "market_request", side_effect=MarketRequestError("Unsupported chart range.")):
            self.assertEqual(self.post("/v1/market/chart", {}), (400, {"error": "Unsupported chart range."}))
        self.assertEqual(self.post("/v1/market/unknown", {})[0], 404)

    def test_route_dispatch_reaches_each_service_method(self):
        calls = []

        class Stub:
            def __getattr__(self, name):
                return lambda payload: calls.append(name) or name
        with patch.object(market, "service", return_value=Stub()):
            for path in market.MARKET_ROUTES:
                self.assertEqual(market.market_request(path, {}), path.rsplit("/", 1)[1])
            with self.assertRaises(MarketRequestError):
                market.market_request("/v1/market/other", {})
        self.assertEqual(calls, ["overview", "quotes", "search", "symbol", "chart", "crypto", "options"])


if __name__ == "__main__":
    unittest.main()
