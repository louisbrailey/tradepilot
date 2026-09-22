"""Personal Webull integration using the official SDK and a durable order ledger.

Broker credentials stay on the user's backend. Language-model code does not import
this module or receive its confirmation secrets. All network mutations are gated
by the explicit review confirmation route.
"""
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from execution_ledger import ExecutionLedger, ExecutionEvidenceError


class BrokerError(Exception):
    pass


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise BrokerError("Invalid numeric input")
    if not result.is_finite():
        raise BrokerError("Invalid numeric input")
    return result


class WebullAdapter:
    def __init__(self, runtime):
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
        key, secret = os.environ.get("WEBULL_APP_KEY"), os.environ.get("WEBULL_APP_SECRET")
        if not key or not secret:
            raise BrokerError("Webull credentials are not configured on your backend.")
        self.environment = os.environ.get("WEBULL_ENV", "sandbox")
        if self.environment not in ("sandbox", "production"):
            raise BrokerError("Invalid Webull environment")
        client = ApiClient(key, secret, "us", auto_retry=False, timeout=15, connect_timeout=10)
        client.set_stream_logger(log_level=logging.CRITICAL + 1, stream=io.StringIO())
        client.add_endpoint("us", "api.sandbox.webull.com" if self.environment == "sandbox" else "api.webull.com")
        client.set_token_dir(str(Path(runtime) / "webull-tokens" / self.environment))
        try:
            self.client = TradeClient(client)
        except Exception:
            raise BrokerError("Cannot establish Webull authentication. Open or update the Webull mobile app, sign into the same account, approve any pending API 2FA request, and check your network and credentials.")

    @staticmethod
    def data(response):
        if response.status_code != 200:
            raise BrokerError("Webull rejected the request (HTTP %s). Check access, permissions and account eligibility." % response.status_code)
        return response.json()

    def accounts(self):
        data = self.data(self.client.account_v2.get_account_list())
        if not isinstance(data, list):
            raise BrokerError("Unexpected Webull account response")
        return data

    def positions(self, account):
        data = self.data(self.client.account_v2.get_account_position(account))
        if not isinstance(data, list):
            raise BrokerError("Unexpected Webull positions response")
        return data

    def balance(self, account):
        return self.data(self.client.account_v2.get_account_balance(account))

    def preview(self, account, order):
        data = self.data(self.client.order_v3.preview_order(account, [order]))
        if not isinstance(data, dict) or not all(k in data for k in ("estimated_cost", "estimated_transaction_fee")):
            raise BrokerError("Webull did not provide a complete cost preview")
        number(data["estimated_cost"]); number(data["estimated_transaction_fee"])
        return data

    def place(self, account, order):
        data = self.data(self.client.order_v3.place_order(account, [order]))
        if (not isinstance(data, dict)
                or data.get("client_order_id") != order["client_order_id"]
                or not isinstance(data.get("order_id"), str)
                or not data["order_id"]):
            raise BrokerError("Webull did not provide a matching order acceptance")
        return data

    def detail(self, account, client_id):
        return self.data(self.client.order_v3.get_order_detail(account, client_id))


class WebullService:
    def __init__(self, path, adapter, clock=time.time):
        self.adapter, self.clock = adapter, clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, environment TEXT NOT NULL, account TEXT NOT NULL,
                body TEXT NOT NULL, preview TEXT NOT NULL, expires REAL NOT NULL,
                token_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, review_id TEXT,
                event TEXT NOT NULL, detail TEXT NOT NULL);
        """)
        self.executions = ExecutionLedger(self.db, self.clock)
        self.db.commit()

    def audit(self, review, event, detail):
        self.db.execute("INSERT INTO audit(at,review_id,event,detail) VALUES (?,?,?,?)",
                        (self.clock(), review, event, json.dumps(detail)))

    def account(self, account_id):
        match = [a for a in self.adapter.accounts() if a.get("account_id") == account_id]
        if len(match) != 1:
            raise BrokerError("Select an account authorized by these Webull credentials")
        if match[0].get("account_class") not in ("INDIVIDUAL_CASH", "INDIVIDUAL_MARGIN", "ROTH_IRA", "TRADITIONAL_IRA", "ROLLOVER_IRA"):
            raise BrokerError("This account type is not supported for stock orders")
        return match[0]

    def state(self, account_id=None):
        accounts = self.adapter.accounts()
        result = {"environment": self.adapter.environment, "accounts": [
            {"id": a["account_id"], "label": a.get("account_label", "Webull") + " · " + a.get("account_number", "")[-4:]}
            for a in accounts], "positions": [], "balance": "Select an account", "as_of": self.clock()}
        if account_id:
            self.account(account_id)
            positions = self.adapter.positions(account_id)
            result["positions"] = [{"id": p["position_id"], "symbol": p["symbol"],
                "quantity": p["quantity"], "price": p["last_price"], "cost": p["cost_price"],
                "gain": p["unrealized_profit_loss"], "kind": p["instrument_type"], "currency": p["currency"]} for p in positions]
            result["balance"] = json.dumps(self.adapter.balance(account_id), indent=2)
        return result

    def validate(self, account_id, body):
        self.account(account_id)
        qty = number(body["quantity"])
        if body["side"] == "SELL":
            owned = sum((number(p["quantity"]) for p in self.adapter.positions(account_id)
                         if p.get("symbol") == body["symbol"] and p.get("instrument_type") == "EQUITY"), Decimal(0))
            if qty > owned:
                raise BrokerError("Insufficient stock holdings. This app does not open short positions.")

    def create_review(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"account_id", "symbol", "side", "quantity", "limit_price"}:
            raise BrokerError("Unsupported order fields")
        account = payload.get("account_id")
        if not isinstance(account, str) or not account:
            raise BrokerError("Select an authorized Webull account")
        symbol, side = payload.get("symbol", ""), payload.get("side", "")
        quantity = payload.get("quantity", "")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", symbol):
            raise BrokerError("Enter an exact stock ticker")
        if side not in ("BUY", "SELL") or not isinstance(quantity, str) or not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,6})?", quantity) or number(quantity) <= 0:
            raise BrokerError("Enter BUY or SELL and a positive share quantity")
        body = {"client_order_id": uuid.uuid4().hex, "combo_type": "NORMAL", "symbol": symbol,
                "instrument_type": "EQUITY", "market": "US", "order_type": "MARKET",
                "side": side, "quantity": quantity, "time_in_force": "DAY",
                "support_trading_session": "CORE", "entrust_type": "QTY"}
        limit = payload.get("limit_price")
        if "limit_price" in payload:
            if not isinstance(limit, str) or not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,4})?", limit) or number(limit) <= 0:
                raise BrokerError("Invalid limit price")
            body.update(order_type="LIMIT", limit_price=limit)
        self.validate(account, body)
        preview = self.adapter.preview(account, body)
        review_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        expires = self.clock() + 60
        with self.lock, self.db:
            self.db.execute("INSERT INTO reviews(id,environment,account,body,preview,expires,token_hash,state) VALUES (?,?,?,?,?,?,?,?)",
                (review_id, self.adapter.environment, account, json.dumps(body), json.dumps(preview), expires,
                 hashlib.sha256(token.encode()).hexdigest(), "REVIEW"))
            self.audit(review_id, "proposal", {"account": account, "order": body, "preview": preview})
        return {"id": review_id, "confirmation_token": token, "environment": self.adapter.environment,
                "account_id": account, "order": body, "estimated_cost": str(preview["estimated_cost"]),
                "estimated_fee": str(preview["estimated_transaction_fee"]), "expires_at": expires}

    def row(self, review_id):
        row = self.db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row or row["environment"] != self.adapter.environment:
            raise BrokerError("Unknown review for this environment")
        return row

    def receipt(self, row):
        return {"id": row["id"], "state": row["state"], "environment": row["environment"],
                "account_id": row["account"],
                "client_order_id": json.loads(row["body"])["client_order_id"], "detail": row["result"]}

    def confirm(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"id", "confirmation_token", "approved"}:
            raise BrokerError("Confirmation must refer only to the reviewed order")
        if payload.get("approved") is not True:
            raise BrokerError("Explicit approval is required")
        if self.adapter.environment == "production" and os.environ.get("WEBULL_LIVE_TRADING") != "enabled":
            raise BrokerError("Live execution is disabled on the backend")
        review_id, token = payload.get("id"), payload.get("confirmation_token", "")
        if not isinstance(token, str):
            raise BrokerError("Invalid confirmation")
        with self.lock:
            row = self.row(review_id)
            if not hmac.compare_digest(row["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
                raise BrokerError("Confirmation does not match the reviewed order")
            if row["state"] != "REVIEW":
                return self.receipt(row)  # Never resubmit after a tap, timeout or restart.
            if self.clock() >= row["expires"]:
                raise BrokerError("Review expired. Request a new preview.")
            body = json.loads(row["body"])
            self.validate(row["account"], body)
            fresh = self.adapter.preview(row["account"], body)
            original = json.loads(row["preview"])
            if any(number(fresh[k]) != number(original[k]) for k in ("estimated_cost", "estimated_transaction_fee")):
                raise BrokerError("Webull's cost estimate changed. Review a fresh order before submitting.")
            if self.clock() >= row["expires"]:
                raise BrokerError("Review expired during validation. Request a new preview.")
            # Commit approval and attempted submission BEFORE the external side effect.
            with self.db:
                changed = self.db.execute("UPDATE reviews SET state='SUBMITTING' WHERE id=? AND state='REVIEW'", (review_id,)).rowcount
                if changed != 1:
                    return self.receipt(self.row(review_id))
                self.audit(review_id, "approved_and_submitting", body)
            try:
                response = self.adapter.place(row["account"], body)
                if (not isinstance(response, dict) or response.get("client_order_id") != body["client_order_id"]
                        or not isinstance(response.get("order_id"), str) or not response["order_id"]):
                    raise BrokerError("Webull did not provide a matching order acceptance")
                state = "SUBMITTED"  # Acceptance does not establish a fill.
            except Exception:
                response = {"message": "Submission outcome is uncertain. Refresh order status; do not recreate the order."}
                state = "UNKNOWN"
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if state == "SUBMITTED":
                    try:
                        self.executions.register(row["environment"], row["account"], body, response["order_id"])
                    except ExecutionEvidenceError:
                        # An acknowledgement cannot replace a verified execution
                        # identity learned by a simultaneous status refresh.
                        self.executions.warn(row["environment"], row["account"], body["client_order_id"],
                                             "Order acceptance conflicted with the app-tracked execution identity")
                        self.audit(review_id, "execution_registration_failed", {})
                # A second gateway process may already have reconciled this
                # order while place() was waiting. Never replace that evidence.
                self.db.execute("UPDATE reviews SET state=?,result=? WHERE id=? AND state='SUBMITTING'",
                                (state, json.dumps(response), review_id))
                self.audit(review_id, state.lower(), response)
            return self.receipt(self.row(review_id))

    @staticmethod
    def detail_candidate(detail, row, body):
        if not isinstance(detail, dict) or not isinstance(detail.get("orders"), list):
            raise ExecutionEvidenceError("Broker detail did not contain an order list")
        # TradePilot submits exactly one NORMAL equity order per client ID.
        if detail.get("combo_type") != body["combo_type"] or len(detail["orders"]) != 1:
            raise ExecutionEvidenceError("Broker detail did not identify one matching simple order")
        for key, expected in (("client_order_id", body["client_order_id"]),
                              ("account_id", row["account"]), ("environment", row["environment"])):
            if key in detail and detail[key] != expected:
                raise ExecutionEvidenceError("Broker detail %s did not match the reviewed order" % key)
        candidate = detail["orders"][0]
        if not isinstance(candidate, dict):
            raise ExecutionEvidenceError("Broker order detail was malformed")
        for key, expected in (("account_id", row["account"]), ("environment", row["environment"])):
            if key in candidate and candidate[key] != expected:
                raise ExecutionEvidenceError("Broker order %s did not match the reviewed order" % key)
        return candidate

    def refresh(self, review_id):
        with self.lock:
            row = self.row(review_id)
            if row["state"] in ("REVIEW", "CANCELLED_REVIEW"):
                return self.receipt(row)
            body = json.loads(row["body"])
            detail = self.adapter.detail(row["account"], body["client_order_id"])
            client_id = body["client_order_id"]
            with self.db:
                # Serialize status/evidence updates across gateway processes as
                # well as threads. Re-read after the network call to avoid stale
                # snapshots overwriting a newer terminal result.
                self.db.execute("BEGIN IMMEDIATE")
                row = self.row(review_id)
                state, result = row["state"], json.loads(row["result"])
                try:
                    candidate = self.detail_candidate(detail, row, body)
                    qty, price = self.executions.validate_candidate(body, candidate, allow_incomplete=True)
                    previous = self.db.execute("""SELECT filled_quantity FROM execution_latest
                        WHERE environment=? AND account_id=? AND client_order_id=?""",
                        (row["environment"], row["account"], client_id)).fetchone()
                    if previous and qty is not None and qty < Decimal(previous["filled_quantity"]):
                        raise ExecutionEvidenceError("Broker detail decreased cumulative filled quantity")
                    if state in ("CANCELLED", "FILLED", "FAILED") and candidate["status"] != state:
                        raise ExecutionEvidenceError("Broker detail conflicted with a terminal order state")
                    if state == "PARTIAL_FILLED" and candidate["status"] in ("SUBMITTED", "PENDING"):
                        raise ExecutionEvidenceError("Broker detail regressed from a partially filled order")
                    self.executions.register(row["environment"], row["account"], body,
                                             candidate.get("order_id"))
                    # Status and execution evidence have different completeness requirements.
                    # Missing optional fills cannot strand a confirmed terminal order.
                    complete = self.executions.reconcile(row["environment"], row["account"], client_id, candidate)
                    missing = qty is None or (qty > 0 and price is None)
                    if complete or missing:
                        state = candidate["status"]
                        result = detail
                    else:
                        raise ExecutionEvidenceError("Broker detail conflicted with verified execution evidence")
                except ExecutionEvidenceError as exc:
                    self.executions.warn(row["environment"], row["account"], client_id, str(exc))
                    # Keep the last trusted result available for recovery and
                    # clearly explain why the new observation was not adopted.
                    result = {**result, "tradepilot_status_warning": str(exc)}
                self.db.execute("UPDATE reviews SET state=?,result=? WHERE id=?", (state, json.dumps(result), review_id))
                self.audit(review_id, "broker_status", detail)
            return self.receipt(self.row(review_id))

    def execution_summary(self, account_id):
        with self.lock:
            self.account(account_id)
            legacy_warnings = []
            rows = self.db.execute("""SELECT * FROM reviews
                WHERE environment=? AND account=? AND state='FILLED'""",
                (self.adapter.environment, account_id)).fetchall()
            for row in rows:
                body = json.loads(row["body"])
                client_id = body["client_order_id"]
                if self.db.execute("""SELECT 1 FROM execution_latest
                    WHERE environment=? AND account_id=? AND client_order_id=? AND verification_version=2""",
                    (row["environment"], row["account"], client_id)).fetchone():
                    continue
                try:
                    saved = json.loads(row["result"])
                    candidate = self.detail_candidate(saved, row, body)
                    self.executions.validate_candidate(body, candidate)
                    self.executions.register(row["environment"], row["account"], body,
                                             candidate.get("order_id"))
                    if not self.executions.reconcile(row["environment"], row["account"],
                                                     client_id, candidate):
                        raise ExecutionEvidenceError("saved detail did not reconcile")
                except (ExecutionEvidenceError, TypeError, ValueError, AttributeError):
                    legacy_warnings.append(
                        "A legacy filled review lacks complete verified execution evidence and was excluded.")
            self.db.commit()
            result = self.executions.summary(self.adapter.environment, account_id)
            result["warnings"].extend(legacy_warnings)
            return result

    def cancel_review(self, review_id):
        with self.lock, self.db:
            row = self.row(review_id)
            if row["state"] == "REVIEW":
                self.db.execute("UPDATE reviews SET state='CANCELLED_REVIEW' WHERE id=?", (review_id,))
                self.audit(review_id, "cancelled_review", {})
            return self.receipt(self.row(review_id))
