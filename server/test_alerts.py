import json
import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import alerts_service
from alerts_service import AlertError, AlertService, check_alerts
from market_service import MarketDataError, MarketService
from test_market import FRIDAY_2PM, SATURDAY_NOON, FakeProvider, et, snapshot


def request(symbol="AAPL", direction="above", target="350", client_id="alert-0001"):
    return {"symbol": symbol, "direction": direction, "target": target, "client_id": client_id}


class AlertServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = [FRIDAY_2PM]
        self.service = AlertService(Path(self.folder.name) / "alerts.sqlite3", clock=lambda: self.now[0])

    def tearDown(self):
        self.folder.cleanup()

    def test_create_is_idempotent_and_refuses_reused_ids(self):
        first = self.service.create(request(target="350.50"))
        self.assertEqual(self.service.create(request(target="350.5")), first)
        with self.assertRaisesRegex(AlertError, "different alert"):
            self.service.create(request(target="351"))
        with self.assertRaisesRegex(AlertError, "already have"):
            self.service.create(request(target="350.5", client_id="alert-0002"))
        self.assertEqual((first["status"], first["target"], first["direction"]), ("active", "350.5", "above"))
        self.assertEqual(self.service.state()["active"], 1)

    def test_invalid_requests_are_rejected(self):
        for payload in ({}, request(symbol="aapl"), request(direction="sideways"), request(target="0"),
                        request(target="-5"), request(target="1e3"), request(target="12.123456789"),
                        request(client_id="short"), {**request(), "extra": True}, []):
            with self.subTest(payload=payload), self.assertRaises(AlertError):
                self.service.create(payload)

    def test_active_alerts_are_capped(self):
        for index in range(alerts_service.MAX_ACTIVE):
            self.service.create(request(target=str(100 + index), client_id=f"alert-{index:04d}"))
        with self.assertRaisesRegex(AlertError, "up to 50"):
            self.service.create(request(target="999", client_id="alert-9999"))

    def test_only_prices_after_creation_reach_the_level(self):
        above = self.service.create(request(direction="above", target="350"))
        below = self.service.create(request(direction="below", target="300", client_id="alert-0002"))
        self.assertEqual(self.service.evaluate({"AAPL": (Decimal("360"), FRIDAY_2PM - 60)}), [])
        self.assertEqual(self.service.evaluate({"AAPL": (Decimal("349.99"), FRIDAY_2PM + 60)}), [])
        self.now[0] += 120
        hit = self.service.evaluate({"AAPL": (Decimal("350"), FRIDAY_2PM + 90)})
        self.assertEqual([item["id"] for item in hit], [above["id"]])
        self.assertEqual((hit[0]["status"], hit[0]["triggered_price"], hit[0]["triggered_at"]),
                         ("triggered", "350", FRIDAY_2PM + 120))
        self.assertEqual(self.service.evaluate({"AAPL": (Decimal("400"), FRIDAY_2PM + 100)}), [])
        state = self.service.state()
        self.assertEqual([item["id"] for item in state["alerts"]], [above["id"], below["id"]])
        self.assertEqual((state["active"], state["triggered"]), (1, 1))
        self.assertEqual([item["id"] for item in self.service.evaluate({"AAPL": (Decimal("299"), FRIDAY_2PM + 200)})], [below["id"]])

    def test_cancel_removes_active_and_clears_triggered(self):
        active = self.service.create(request(target="400"))
        fired = self.service.create(request(target="300", client_id="alert-0002"))
        self.service.evaluate({"AAPL": (Decimal("320"), FRIDAY_2PM + 1)})
        self.assertEqual(self.service.cancel({"id": active["id"]})["active"], 0)
        self.assertEqual(self.service.cancel({"id": fired["id"]})["alerts"], [])
        for payload in ({"id": active["id"]}, {"id": "missing"}, {"id": 5}, {}):
            with self.subTest(payload=payload), self.assertRaises(AlertError):
                self.service.cancel(payload)
        self.assertEqual(self.service.symbols(), [])

    def test_clear_removes_only_triggered_alerts(self):
        self.service.create(request(target="300"))
        self.service.create(request(target="999", client_id="alert-0002"))
        self.service.evaluate({"AAPL": (Decimal("320"), FRIDAY_2PM + 1)})
        state = self.service.clear({})
        self.assertEqual([(item["target"], item["status"]) for item in state["alerts"]], [("999", "active")])
        with self.assertRaises(AlertError):
            self.service.clear({"all": True})

    def test_concurrent_evaluations_trigger_once(self):
        self.service.create(request(target="300"))
        results = []
        def run():
            other = AlertService(Path(self.folder.name) / "alerts.sqlite3", clock=lambda: FRIDAY_2PM + 5)
            results.append(other.evaluate({"AAPL": (Decimal("320"), FRIDAY_2PM + 1)}))
        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(len(result) for result in results), 1)


class AlertCheckTests(unittest.TestCase):
    def market(self, status, rows, clock=FRIDAY_2PM):
        routes = {"/v1/marketstatus/now": {"market": status},
                  "/v2/snapshot/locale/us/markets/stocks/tickers": rows}
        return MarketService(FakeProvider(routes), clock=lambda: clock)

    def test_checks_run_only_while_trading_and_use_after_hours_prices(self):
        with tempfile.TemporaryDirectory() as folder:
            service = AlertService(Path(folder) / "alerts.sqlite3", clock=lambda: et(2026, 11, 6, 16, 30))
            service.create(request(target="736"))
            late = snapshot("SPY", 735.29, 733.0, updated=et(2026, 11, 6, 17))
            late["ticker"] = "AAPL"
            late["min"] = {"c": 736.53, "t": int(et(2026, 11, 6, 17) * 1000)}
            self.assertEqual(check_alerts(service, self.market("closed", {"tickers": [late]}, SATURDAY_NOON)), [])
            hit = check_alerts(service, self.market("extended-hours", {"tickers": [late]}, et(2026, 11, 6, 17)))
            self.assertEqual(hit[0]["triggered_price"], "736.53")

    def test_provider_outage_skips_the_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            service = AlertService(Path(folder) / "alerts.sqlite3", clock=lambda: FRIDAY_2PM - 60)
            service.create(request(target="100"))
            self.assertEqual(check_alerts(service, self.market("open", MarketDataError("down"))), [])
            self.assertEqual(service.state()["active"], 1)
            no_day_bar = {"tickers": [{"ticker": "AAPL", "day": {"c": 0}, "prevDay": {"c": 340}, "updated": int(FRIDAY_2PM * 1e9)}]}
            self.assertEqual(check_alerts(service, self.market("open", no_day_bar)), [])


class AlertRouteTests(unittest.TestCase):
    def test_routes_use_the_private_runtime_and_require_exact_bodies(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(alerts_service.os.environ, {"TRADEPILOT_RUNTIME": folder}):
            created = alerts_service.alerts_request("/v1/alerts/create", request())
            state = alerts_service.alerts_request("/v1/alerts/state", {})
            self.assertEqual(state["alerts"][0]["id"], created["id"])
            self.assertTrue((Path(folder) / "alerts.sqlite3").exists())
            with self.assertRaises(AlertError):
                alerts_service.alerts_request("/v1/alerts/state", {"x": 1})
            self.assertEqual(alerts_service.alerts_request("/v1/alerts/cancel", {"id": created["id"]})["active"], 0)
            self.assertNotIn("order", json.dumps(state["alerts"]))


class AlertGatewayTests(unittest.TestCase):
    def test_alert_routes_require_auth_and_return_readable_errors(self):
        import io
        from email.message import Message
        import server

        def post(path, payload, authorized=True):
            handler = server.Handler.__new__(server.Handler)
            handler.path, handler.headers = path, Message()
            if authorized:
                handler.headers["Authorization"] = "Bearer " + "x" * 32
            data = json.dumps(payload).encode()
            handler.headers["Content-Type"] = "application/json"
            handler.headers["Content-Length"] = str(len(data))
            handler.rfile = io.BytesIO(data)
            replies = []
            handler.reply = lambda status, result: replies.append((status, result))
            handler.do_POST()
            return replies[0]
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32, "TRADEPILOT_RUNTIME": folder}):
            self.assertEqual(post("/v1/alerts/state", {}, authorized=False)[0], 401)
            status, created = post("/v1/alerts/create", request())
            self.assertEqual((status, created["symbol"]), (200, "AAPL"))
            self.assertEqual(post("/v1/alerts/create", request(target="0", client_id="alert-0009")),
                             (400, {"error": "Enter a positive price with up to 8 decimal places."}))


if __name__ == "__main__":
    unittest.main()
