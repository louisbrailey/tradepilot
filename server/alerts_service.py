"""Price alerts watched by the private gateway.

An alert only records that a symbol's price reached a level. It never creates,
reviews or submits an order. Active alerts are checked about once a minute while
US equities trade (pre-market, regular and after hours) with the same read-only
market data as the Markets tab, and only prices observed after an alert was set
can trigger it. Triggered alerts stay listed until the user clears them.
"""
from contextlib import contextmanager
import os
from private_storage import ensure_private_directory, runtime_path
import re
import sqlite3
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

from market_service import MarketDataError, SYMBOL
from paper_service import decimal

ALERT_ROUTES = ("/v1/alerts/state", "/v1/alerts/create", "/v1/alerts/cancel", "/v1/alerts/clear")
MAX_ACTIVE = 50
MAX_LISTED = 200
CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
TRADING = ("open", "pre_market", "after_hours")


class AlertError(ValueError):
    """The request can't be applied. The message is user-facing."""


def _exact(payload, keys):
    if not isinstance(payload, dict) or set(payload) != set(keys):
        raise AlertError("Unexpected alert request fields.")


class AlertService:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS price_alerts (
                id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, symbol TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('above', 'below')), target TEXT NOT NULL,
                created_at REAL NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'triggered', 'cancelled')),
                triggered_at REAL, triggered_price TEXT, price_as_of REAL,
                cleared INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS price_alerts_status ON price_alerts(status, symbol);
            ''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _public(row):
        return {key: row[key] for key in ("id", "symbol", "direction", "target", "created_at", "status",
                                          "triggered_at", "triggered_price", "price_as_of")}

    def state(self):
        with self._db() as db:
            rows = db.execute('''SELECT * FROM price_alerts WHERE cleared = 0 AND status != 'cancelled'
                                 ORDER BY CASE status WHEN 'triggered' THEN 0 ELSE 1 END,
                                          COALESCE(triggered_at, created_at) DESC LIMIT ?''', (MAX_LISTED,)).fetchall()
        alerts = [self._public(row) for row in rows]
        return {"alerts": alerts, "active": sum(item["status"] == "active" for item in alerts),
                "triggered": sum(item["status"] == "triggered" for item in alerts),
                "notice": "Alerts record price levels only. They never place orders.", "as_of": self.clock()}

    def create(self, payload):
        _exact(payload, ("symbol", "direction", "target", "client_id"))
        symbol, direction, client_id = payload["symbol"], payload["direction"], payload["client_id"]
        if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            raise AlertError("Use an uppercase US stock symbol such as AAPL.")
        if direction not in ("above", "below"):
            raise AlertError("Choose whether to alert above or below the price.")
        if not isinstance(client_id, str) or not CLIENT_ID.fullmatch(client_id):
            raise AlertError("Invalid alert request.")
        try:
            target = format(decimal(payload["target"], "alert price").normalize(), "f")
        except ValueError:
            raise AlertError("Enter a positive price with up to 8 decimal places.") from None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM price_alerts WHERE client_id = ?", (client_id,)).fetchone()
            if existing:
                if (existing["symbol"], existing["direction"], Decimal(existing["target"])) != (symbol, direction, Decimal(target)):
                    raise AlertError("This request was already used for a different alert.")
                return self._public(existing)
            duplicate = db.execute("""SELECT * FROM price_alerts WHERE status = 'active' AND symbol = ?
                                      AND direction = ? AND target = ?""", (symbol, direction, target)).fetchone()
            if duplicate:
                raise AlertError(f"You already have an alert for {symbol} {direction} this price.")
            if db.execute("SELECT COUNT(*) FROM price_alerts WHERE status = 'active'").fetchone()[0] >= MAX_ACTIVE:
                raise AlertError(f"You can keep up to {MAX_ACTIVE} active alerts. Remove one first.")
            alert_id = str(uuid.uuid4())
            db.execute("""INSERT INTO price_alerts(id, client_id, symbol, direction, target, created_at, status)
                          VALUES(?, ?, ?, ?, ?, ?, 'active')""", (alert_id, client_id, symbol, direction, target, self.clock()))
            return self._public(db.execute("SELECT * FROM price_alerts WHERE id = ?", (alert_id,)).fetchone())

    def cancel(self, payload):
        """Remove an active alert, or clear a triggered one from the list."""
        _exact(payload, ("id",))
        if not isinstance(payload["id"], str) or len(payload["id"]) > 64:
            raise AlertError("Alert not found.")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM price_alerts WHERE id = ? AND cleared = 0", (payload["id"],)).fetchone()
            if not row or row["status"] == "cancelled":
                raise AlertError("Alert not found. It may already be removed.")
            if row["status"] == "active":
                db.execute("UPDATE price_alerts SET status = 'cancelled' WHERE id = ?", (row["id"],))
            else:
                db.execute("UPDATE price_alerts SET cleared = 1 WHERE id = ?", (row["id"],))
        return self.state()

    def clear(self, payload):
        _exact(payload, ())
        with self._db() as db:
            db.execute("UPDATE price_alerts SET cleared = 1 WHERE status = 'triggered'")
        return self.state()

    def symbols(self):
        with self._db() as db:
            return [row[0] for row in db.execute(
                "SELECT DISTINCT symbol FROM price_alerts WHERE status = 'active' ORDER BY symbol")]

    def evaluate(self, prices):
        """Record alerts reached by prices {symbol: (Decimal price, as_of epoch)}. Returns the new triggers."""
        triggered = []
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT * FROM price_alerts WHERE status = 'active'").fetchall():
                observed = prices.get(row["symbol"])
                if not observed:
                    continue
                price, as_of = observed
                if as_of < row["created_at"]:
                    continue  # Only prices seen after the alert was set can trigger it.
                target = Decimal(row["target"])
                if (row["direction"] == "above" and price >= target) or (row["direction"] == "below" and price <= target):
                    db.execute("""UPDATE price_alerts SET status = 'triggered', triggered_at = ?, triggered_price = ?,
                                  price_as_of = ? WHERE id = ? AND status = 'active'""",
                               (self.clock(), format(price, "f"), as_of, row["id"]))
                    triggered.append(self._public(db.execute("SELECT * FROM price_alerts WHERE id = ?", (row["id"],)).fetchone()))
        return triggered


def check_alerts(service, market):
    """One pass: during trading sessions, read latest prices for symbols with active alerts."""
    symbols = service.symbols()
    if not symbols or market.status()["state"] not in TRADING:
        return []
    try:
        prices = market.latest_prices(symbols)
    except MarketDataError:
        return []
    return service.evaluate(prices)


def start_alert_worker(service_factory, market_factory, interval=60):
    stopped = threading.Event()

    def run():
        while not stopped.wait(interval):
            try:
                check_alerts(service_factory(), market_factory())
            except Exception:  # A failed pass must not stop later checks; the next pass retries.
                continue

    worker = threading.Thread(target=run, name="price-alerts", daemon=True)
    worker.start()
    return stopped, worker


_services = {}
_lock = threading.Lock()


def alerts():
    runtime = runtime_path(os.environ.get("TRADEPILOT_RUNTIME", "runtime"))
    with _lock:
        if runtime not in _services:
            ensure_private_directory(runtime)
            _services[runtime] = AlertService(runtime / "alerts.sqlite3")
        return _services[runtime]


def alerts_request(path, payload):
    service = alerts()
    if path == "/v1/alerts/state":
        _exact(payload, ())
        return service.state()
    if path == "/v1/alerts/create":
        return service.create(payload)
    if path == "/v1/alerts/cancel":
        return service.cancel(payload)
    if path == "/v1/alerts/clear":
        return service.clear(payload)
    raise AlertError("Unknown alert route.")
