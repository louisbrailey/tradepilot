"""Durable evidence for Webull orders submitted by TradePilot.

This deliberately covers only orders whose client IDs were created by this app.
Broker order history, fees, and realized profit/loss are outside this ledger's scope.

Webull's authoritative field definitions for ``filled_quantity`` (cumulative)
and ``filled_price`` (average transaction price) are documented at:
https://developer.webull.com/apis/docs/reference/order-detail/
"""
import json
import sqlite3
from decimal import Decimal, InvalidOperation


class ExecutionEvidenceError(ValueError):
    pass


def _decimal(value, label, allow_zero=True):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ExecutionEvidenceError("Invalid %s" % label)
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ExecutionEvidenceError("Invalid %s" % label)
    return result


def _text(value):
    value = value.normalize()
    return format(value, "f")


class ExecutionLedger:
    SCOPE = "APP-TRACKED ONLY"
    STATES = {"PENDING", "SUBMITTED", "CANCELLED", "FILLED", "FAILED", "PARTIAL_FILLED"}

    def __init__(self, db, clock):
        self.db, self.clock = db, clock
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS execution_tracked (
                environment TEXT NOT NULL, account_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL, order_id TEXT NOT NULL,
                symbol TEXT NOT NULL, side TEXT NOT NULL,
                ordered_quantity TEXT NOT NULL, currency TEXT NOT NULL,
                order_body TEXT,
                registered_at REAL NOT NULL,
                PRIMARY KEY(environment, account_id, client_order_id),
                UNIQUE(environment, account_id, order_id));
            CREATE TABLE IF NOT EXISTS execution_latest (
                environment TEXT NOT NULL, account_id TEXT NOT NULL,
                client_order_id TEXT NOT NULL, order_id TEXT NOT NULL,
                state TEXT NOT NULL, filled_quantity TEXT NOT NULL,
                average_fill_price TEXT, fill_notional TEXT,
                verification_version INTEGER NOT NULL DEFAULT 2,
                updated_at REAL NOT NULL,
                PRIMARY KEY(environment, account_id, client_order_id));
            CREATE TABLE IF NOT EXISTS execution_evidence (
                id INTEGER PRIMARY KEY, environment TEXT NOT NULL,
                account_id TEXT NOT NULL, client_order_id TEXT NOT NULL,
                order_id TEXT NOT NULL, state TEXT NOT NULL,
                filled_quantity TEXT NOT NULL, average_fill_price TEXT,
                fill_notional TEXT, observed_at REAL NOT NULL,
                normalized_snapshot TEXT NOT NULL,
                UNIQUE(environment, account_id, client_order_id, normalized_snapshot));
            CREATE TABLE IF NOT EXISTS execution_warnings (
                id INTEGER PRIMARY KEY, environment TEXT NOT NULL,
                account_id TEXT NOT NULL, client_order_id TEXT NOT NULL,
                observed_at REAL NOT NULL, warning TEXT NOT NULL);
        """)
        # Preserve the originally reviewed terms for databases created before this
        # column existed. A matching re-registration fills it from the review.
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(execution_tracked)")}
        if "order_body" not in columns:
            self.db.execute("ALTER TABLE execution_tracked ADD COLUMN order_body TEXT")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(execution_latest)")}
        if "verification_version" not in columns:
            self.db.execute("ALTER TABLE execution_latest ADD COLUMN verification_version INTEGER NOT NULL DEFAULT 1")

    def register(self, environment, account_id, body, order_id):
        client_id = body.get("client_order_id")
        if not all(isinstance(v, str) and v for v in
                   (environment, account_id, client_id, order_id, body.get("symbol"), body.get("side"))):
            raise ExecutionEvidenceError("Incomplete submitted order identity")
        qty = _text(_decimal(body.get("quantity"), "ordered quantity", allow_zero=False))
        currency = "USD" if body.get("market") == "US" else None
        if currency is None:
            raise ExecutionEvidenceError("Unsupported order currency")
        if body["side"] not in {"BUY", "SELL"}:
            raise ExecutionEvidenceError("Unsupported submitted order side")
        body_text = json.dumps(body, sort_keys=True, separators=(",", ":"))
        existing = self.db.execute(
            "SELECT * FROM execution_tracked WHERE environment=? AND account_id=? AND client_order_id=?",
            (environment, account_id, client_id)).fetchone()
        values = (order_id, body["symbol"], body["side"], qty, currency)
        if existing:
            if tuple(existing[k] for k in ("order_id", "symbol", "side", "ordered_quantity", "currency")) != values:
                raise ExecutionEvidenceError("Conflicting submitted order identity")
            if existing["order_body"] and existing["order_body"] != body_text:
                raise ExecutionEvidenceError("Conflicting reviewed order terms")
            if not existing["order_body"]:
                self.db.execute("""UPDATE execution_tracked SET order_body=?
                    WHERE environment=? AND account_id=? AND client_order_id=?""",
                    (body_text, environment, account_id, client_id))
            return
        try:
            self.db.execute("""INSERT INTO execution_tracked
                (environment,account_id,client_order_id,order_id,symbol,side,ordered_quantity,currency,order_body,registered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (environment, account_id, client_id, *values, body_text, self.clock()))
        except sqlite3.IntegrityError:
            raise ExecutionEvidenceError("Conflicting submitted order identity")

    def _warn(self, environment, account_id, client_id, warning):
        self.db.execute("""INSERT INTO execution_warnings
            (environment,account_id,client_order_id,observed_at,warning) VALUES (?,?,?,?,?)""",
            (environment, account_id, client_id, self.clock(), warning))

    def warn(self, environment, account_id, client_id, warning):
        self._warn(environment, account_id, client_id, warning)

    def validate_candidate(self, body, order, expected_order_id=None, allow_incomplete=False):
        """Validate a complete detail before adopting its broker order ID."""
        client_id = body.get("client_order_id")
        if not isinstance(order, dict) or order.get("client_order_id") != client_id:
            raise ExecutionEvidenceError("Order detail client ID did not match the app-tracked order")
        order_id = order.get("order_id")
        if not isinstance(order_id, str) or not order_id or (expected_order_id and order_id != expected_order_id):
            raise ExecutionEvidenceError("Order detail broker ID did not match the app-tracked order")
        if order.get("symbol") != body.get("symbol") or order.get("side") != body.get("side"):
            raise ExecutionEvidenceError("Order detail instrument or side conflicted with the reviewed order")
        # These fields are required in Webull's detail schema. Fields described
        # as optional must agree when supplied; their absence cannot be invented.
        for field in ("order_type", "time_in_force", "entrust_type"):
            if field in body and order.get(field) != body[field]:
                raise ExecutionEvidenceError("Order detail %s conflicted with the reviewed order" % field)
        for field in ("instrument_type", "support_trading_session", "market"):
            if field in order and order[field] != body.get(field):
                raise ExecutionEvidenceError("Order detail %s conflicted with the reviewed order" % field)
        if body.get("order_type") == "LIMIT":
            if _decimal(order.get("limit_price"), "limit price", allow_zero=False) != _decimal(
                    body.get("limit_price"), "reviewed limit price", allow_zero=False):
                raise ExecutionEvidenceError("Order detail limit price conflicted with the reviewed order")
        elif order.get("limit_price") is not None and _decimal(order["limit_price"], "limit price") != 0:
            raise ExecutionEvidenceError("Market order detail contained a limit price")
        ordered = _decimal(body.get("quantity"), "ordered quantity", allow_zero=False)
        if _decimal(order.get("total_quantity"), "total quantity") != ordered:
            raise ExecutionEvidenceError("Order detail quantity conflicted with the reviewed order")
        state = order.get("status")
        if state not in self.STATES:
            raise ExecutionEvidenceError("Order detail had an unsupported state")
        if order.get("filled_quantity") is None and allow_incomplete:
            if order.get("filled_price") is not None:
                price = _decimal(order["filled_price"], "average fill price")
                if state in {"PENDING", "SUBMITTED"} and price > 0:
                    raise ExecutionEvidenceError("Open order state conflicted with a positive fill price")
            return None, None
        qty = _decimal(order.get("filled_quantity"), "filled quantity")
        if qty > ordered:
            raise ExecutionEvidenceError("Filled quantity exceeded the reviewed order quantity")
        if state == "FILLED" and qty != ordered:
            raise ExecutionEvidenceError("Filled order did not report the full reviewed quantity")
        if state == "PARTIAL_FILLED" and (qty == 0 or qty >= ordered):
            raise ExecutionEvidenceError("Partially filled order reported an inconsistent quantity")
        if state in {"PENDING", "SUBMITTED"} and qty > 0:
            raise ExecutionEvidenceError("Open order state conflicted with a positive filled quantity")
        if qty > 0 and order.get("filled_price") is None and allow_incomplete:
            return qty, None
        if qty == 0 and order.get("filled_price") is not None and _decimal(order["filled_price"], "average fill price") != 0:
            raise ExecutionEvidenceError("Zero filled quantity conflicted with a positive fill price")
        price = _decimal(order.get("filled_price"), "average fill price", allow_zero=False) if qty > 0 else None
        return qty, price

    def reconcile(self, environment, account_id, client_id, order):
        tracked = self.db.execute("""SELECT * FROM execution_tracked
            WHERE environment=? AND account_id=? AND client_order_id=?""",
            (environment, account_id, client_id)).fetchone()
        if not tracked:
            return False
        try:
            if not tracked["order_body"]:
                raise ExecutionEvidenceError("Reviewed execution terms have not been restored from the order review")
            body = json.loads(tracked["order_body"])
            qty, price = self.validate_candidate(body, order, tracked["order_id"])
            state = order["status"]
            qty_text = _text(qty)
            price_text = _text(price) if price is not None else None
            notional = _text(qty * price) if price is not None else None
            previous = self.db.execute("""SELECT * FROM execution_latest
                WHERE environment=? AND account_id=? AND client_order_id=?""",
                (environment, account_id, client_id)).fetchone()
            if previous:
                old_qty = _decimal(previous["filled_quantity"], "previous filled quantity")
                if qty < old_qty:
                    raise ExecutionEvidenceError("Broker detail decreased cumulative filled quantity")
                if qty == old_qty and qty > 0 and price_text != previous["average_fill_price"]:
                    raise ExecutionEvidenceError("Broker detail changed average price without a new fill")
                if qty > old_qty and old_qty > 0 and qty * price <= _decimal(previous["fill_notional"], "previous fill notional"):
                    raise ExecutionEvidenceError("Broker detail decreased cumulative fill value despite a new fill")
                if previous["state"] in {"FILLED", "FAILED", "CANCELLED"} and state != previous["state"]:
                    raise ExecutionEvidenceError("Broker detail conflicted with a terminal order state")
            snapshot = json.dumps({"state": state, "filled_quantity": qty_text,
                                  "average_fill_price": price_text, "fill_notional": notional},
                                 sort_keys=True, separators=(",", ":"))
            observed = self.clock()
            self.db.execute("""INSERT OR IGNORE INTO execution_evidence
                (environment,account_id,client_order_id,order_id,state,filled_quantity,
                 average_fill_price,fill_notional,observed_at,normalized_snapshot)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (environment, account_id, client_id, tracked["order_id"], state, qty_text,
                 price_text, notional, observed, snapshot))
            self.db.execute("""INSERT INTO execution_latest
                (environment,account_id,client_order_id,order_id,state,filled_quantity,
                 average_fill_price,fill_notional,updated_at,verification_version) VALUES (?,?,?,?,?,?,?,?,?,2)
                ON CONFLICT(environment,account_id,client_order_id) DO UPDATE SET
                 state=excluded.state,filled_quantity=excluded.filled_quantity,
                 average_fill_price=excluded.average_fill_price,
                 fill_notional=excluded.fill_notional,updated_at=excluded.updated_at,
                 verification_version=excluded.verification_version""",
                (environment, account_id, client_id, tracked["order_id"], state, qty_text,
                 price_text, notional, observed))
            return True
        except ExecutionEvidenceError as exc:
            self._warn(environment, account_id, client_id, str(exc))
            return False

    def summary(self, environment, account_id):
        rows = self.db.execute("""SELECT t.*,l.state,l.filled_quantity,l.average_fill_price,
                l.fill_notional,l.updated_at FROM execution_tracked t JOIN execution_latest l
                ON l.environment=t.environment AND l.account_id=t.account_id
                AND l.client_order_id=t.client_order_id
                WHERE t.environment=? AND t.account_id=?
                AND l.verification_version=2
                AND CAST(l.filled_quantity AS REAL)>0 ORDER BY l.updated_at DESC""",
                (environment, account_id)).fetchall()
        orders, totals = [], {}
        filled = partial = 0
        for row in rows:
            orders.append({"id": row["order_id"], "client_order_id": row["client_order_id"],
                "symbol": row["symbol"], "side": row["side"],
                "filled_quantity": row["filled_quantity"],
                "average_fill_price": row["average_fill_price"],
                "fill_notional": row["fill_notional"], "currency": row["currency"],
                "state": row["state"], "updated_at": row["updated_at"], "fees": None})
            filled += row["state"] == "FILLED"
            partial += row["state"] != "FILLED"
            bucket = totals.setdefault(row["currency"], {"buy": Decimal(0), "sell": Decimal(0)})
            bucket[row["side"].lower()] += _decimal(row["fill_notional"], "fill notional")
        warning_rows = self.db.execute("""SELECT warning FROM execution_warnings
            WHERE environment=? AND account_id=? ORDER BY id""", (environment, account_id)).fetchall()
        warnings = [r["warning"] for r in warning_rows]
        if self.db.execute("""SELECT 1 FROM execution_latest
            WHERE environment=? AND account_id=? AND verification_version<>2 LIMIT 1""",
            (environment, account_id)).fetchone():
            warnings.append("Saved execution observations need another verified broker refresh and were excluded.")
        warnings.append("Webull order detail does not provide verified fees here; fees and realized P&L are unavailable.")
        return {"environment": environment, "account_id": account_id, "scope": self.SCOPE,
            "as_of": self.clock(), "orders": orders, "warnings": warnings,
            "totals": {"filled_orders": filled, "partial_orders": partial,
                "notional_by_currency": {currency: {side: _text(value) for side, value in sides.items()}
                                         for currency, sides in totals.items()},
                "fees_known": False}}
