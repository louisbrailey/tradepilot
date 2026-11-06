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

from broker_admission import AdmissionLedger, AdmissionError
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

    def open_orders(self, account):
        rows, seen, cursor = [], set(), None
        for _ in range(100):
            page = self.data(self.client.order_v3.list_order_open(account, pagination_key=cursor))
            if not isinstance(page, dict) or not isinstance(page.get('data'), list):
                raise BrokerError('Webull open-order coverage is unverified; new exposure refused.')
            for row in page['data']:
                if not isinstance(row, dict) or row.get('account_id', account) != account:
                    raise BrokerError('Webull open-order account mismatch.')
                rows.append(row)
            cursor = page.get('pagination_key')
            if not cursor:
                return rows
            if not isinstance(cursor, str) or cursor in seen or not page['data']:
                raise BrokerError('Webull open-order pagination is incomplete.')
            seen.add(cursor)
        raise BrokerError('Webull open-order pagination exceeded the safe limit.')

    def cancel(self, account, client_id):
        return self.data(self.client.order_v3.cancel_order(account, client_id))

    def detail(self, account, client_id):
        return self.data(self.client.order_v3.get_order_detail(account, client_id))


class WebullService:
    def __init__(self, path, adapter, clock=time.time, admission=None):
        self.admission = admission
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
                token_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
                observed_filled_quantity TEXT);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, review_id TEXT,
                event TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cancellation_reviews (
                id TEXT PRIMARY KEY, parent_id TEXT, digest TEXT, token_hash TEXT,
                expires REAL, state TEXT, summary TEXT);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(reviews)")}
        if "observed_filled_quantity" not in columns:
            self.db.execute("ALTER TABLE reviews ADD COLUMN observed_filled_quantity TEXT")
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

    def economic_check(self, account, body, terms, preview):
        if terms.get('fee_policy', 'require_provider_cap') != 'accept_rechecked_estimate':
            raise BrokerError('Webull has no provider-enforced fee cap. Explicit reviewed estimate opt-in is required.')
        if body['order_type'] != 'LIMIT' or terms.get('fee_currency') != 'USD':
            raise BrokerError('Production estimates require a USD-settled long-stock LIMIT/DAY order.')
        if any(not isinstance(terms.get(k), str) or not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,8})?', terms[k]) for k in ('fee_estimate_ceiling', 'debit_admission_ceiling', 'headroom')):
            raise BrokerError('Use bounded plain decimal strings for economic limits.')
        fee, ceiling, debit, headroom = (number(preview['estimated_transaction_fee']), number(terms['fee_estimate_ceiling']),
                                       number(terms['debit_admission_ceiling']), number(terms['headroom']))
        if min(fee, ceiling, debit, headroom) < 0 or fee > ceiling:
            raise BrokerError('Estimated fees exceed the approved ceiling.')
        required = number(body['quantity']) * number(body['limit_price']) + ceiling + headroom if body['side'] == 'BUY' else ceiling + headroom
        if required > debit:
            raise BrokerError('Debit ceiling does not cover limit notional, approved fees and headroom.')
        balance = self.adapter.balance(account)
        if not isinstance(balance, dict) or balance.get('total_asset_currency') != 'USD':
            raise BrokerError('Account settlement currency is unverified.')
        rows = balance.get('account_currency_assets')
        if not isinstance(rows, list):
            raise BrokerError('Available funds are unverified.')
        usd = [r for r in rows if isinstance(r, dict) and r.get('currency') == 'USD']
        if len(usd) != 1 or min(number(usd[0].get('settled_cash')), number(usd[0].get('frozen_amount'))) < 0:
            raise BrokerError('Settled and frozen funds are unverified.')
        if number(usd[0]['settled_cash']) - number(usd[0]['frozen_amount']) < required:
            raise BrokerError('Insufficient unreserved settled USD funds. Margin borrowing is unsupported.')

    def create_review(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"account_id", "symbol", "side", "quantity", "limit_price", "fee_policy", "fee_estimate_ceiling", "debit_admission_ceiling", "headroom", "fee_currency"}:
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
        economic_terms = {k: payload[k] for k in ('fee_policy', 'fee_estimate_ceiling', 'debit_admission_ceiling', 'headroom', 'fee_currency') if k in payload}
        if self.adapter.environment == 'production':
            if len(economic_terms) != 5:
                raise BrokerError('Production fee policy defaults to require_provider_cap, which is unsupported. Explicit estimated-fee terms are required.')
            self.economic_check(account, body, economic_terms, preview)
            preview['_economic_terms'] = economic_terms
        review_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        expires = self.clock() + 60
        with self.lock, self.db:
            self.db.execute("INSERT INTO reviews(id,environment,account,body,preview,expires,token_hash,state) VALUES (?,?,?,?,?,?,?,?)",
                (review_id, self.adapter.environment, account, json.dumps(body), json.dumps(preview), expires,
                 hashlib.sha256(token.encode()).hexdigest(), "REVIEW"))
            self.audit(review_id, "proposal", {"account": account, "order": body, "preview": preview})
        saved = self.row(review_id)
        digest = hashlib.sha256((saved['environment'] + saved['account'] + saved['body'] + saved['preview'] + str(saved['expires'])).encode()).hexdigest()
        return {"id": review_id, "confirmation_token": token, "digest": digest, "environment": self.adapter.environment,
                "account_id": account, "order": body, "estimated_cost": str(preview["estimated_cost"]),
                "estimated_fee": str(preview["estimated_transaction_fee"]), "economic_terms": economic_terms or None, "expires_at": expires}

    def row(self, review_id):
        row = self.db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row or row["environment"] != self.adapter.environment:
            raise BrokerError("Unknown review for this environment")
        return row

    def receipt(self, row):
        state = row['state']
        if (row['environment'] == 'production' and json.loads(row['preview']).get('_economic_terms')
                and state in ('FILLED', 'CANCELLED', 'FAILED')
                and not json.loads(row['result']).get('_economic_evidence')):
            state = 'AWAITING_FEE_SETTLEMENT'
        return {"id": row["id"], "state": state, "environment": row["environment"],
                "account_id": row["account"],
                "client_order_id": json.loads(row["body"])["client_order_id"], "detail": row["result"]}

    def confirm(self, payload):
        production = self.adapter.environment == 'production'
        if production and os.environ.get('BROKER_KILL_SWITCH', 'enabled') != 'disabled':
            raise BrokerError('Broker kill switch is enabled')
        fields = {'id', 'confirmation_token', 'approved'} | ({'digest'} if production else set())
        if not isinstance(payload, dict) or set(payload) != fields:
            raise BrokerError('Production confirmation requires the immutable review digest')
        if payload['approved'] is not True or not isinstance(payload['confirmation_token'], str):
            raise BrokerError('Explicit approval is required')
        with self.lock:
            row = self.row(payload['id'])
            expected = hashlib.sha256((row['environment'] + row['account'] + row['body'] + row['preview'] + str(row['expires'])).encode()).hexdigest()
            if ((production and (not isinstance(payload['digest'], str) or not hmac.compare_digest(expected, payload['digest'])))
                    or not hmac.compare_digest(row['token_hash'], hashlib.sha256(payload['confirmation_token'].encode()).hexdigest())):
                raise BrokerError('Confirmation does not match saved terms')
            if row['state'] != 'REVIEW':
                return self.receipt(row)
            ledger = self.admission if self.admission is not None else AdmissionLedger()
            try:
                ledger.reserve('webull', self.adapter.environment, [row['account']], row['id'])
            except AdmissionError as error:
                with ledger.connect() as shared:
                    held = shared.execute('SELECT action_id,owner FROM broker_admission WHERE provider=? AND environment=? AND account_id=?', ('webull', self.adapter.environment, row['account'])).fetchone()
                if held == (row['id'], 'tradepilot'):
                    return self.receipt(self.row(row['id'])) | {'state': 'SUBMITTING'}
                raise BrokerError(str(error)) from None
            try:
                ledger.transition(row['id'], 'SUBMITTING')
                result = self._confirm({k: v for k, v in payload.items() if k != 'digest'})
                if result['state'] == 'CANCELLED_REVIEW':
                    ledger.release(row['id'])
                if result['state'] == 'UNKNOWN':
                    ledger.transition(row['id'], 'UNKNOWN')
                return result
            except Exception:
                if self.row(row['id'])['state'] == 'REVIEW':
                    ledger.release(row['id'])  # Existing confirmation proved no send occurred.
                else:
                    ledger.transition(row['id'], 'UNKNOWN')
                raise

    def _confirm(self, payload):
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
            if self.adapter.open_orders(row['account']):
                raise BrokerError('Existing open orders block a new order until reconciled.')
            self.validate(row["account"], body)
            fresh = self.adapter.preview(row["account"], body)
            preview_at = self.clock()
            original = json.loads(row["preview"])
            if self.adapter.environment == 'production':
                self.economic_check(row['account'], body, original.get('_economic_terms', {}), fresh)
                if self.clock() - preview_at > 15:
                    raise BrokerError('Fresh Webull preview became stale during validation')
            if any(number(fresh[k]) != number(original[k]) for k in ("estimated_cost", "estimated_transaction_fee")):
                raise BrokerError("Webull's cost estimate changed. Review a fresh order before submitting.")
            if self.clock() >= row["expires"]:
                raise BrokerError("Review expired during validation. Request a new preview.")
            if self.adapter.environment == 'production' and (os.environ.get('WEBULL_LIVE_TRADING') != 'enabled' or os.environ.get('BROKER_KILL_SWITCH', 'enabled') != 'disabled'):
                raise BrokerError('Broker writes disabled during validation')
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
                ledger = self.admission if self.admission is not None else AdmissionLedger()
                with self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    current = self.row(review_id)
                    if current['state'] in ('REVIEW', 'CANCELLED_REVIEW'):
                        with ledger.connect() as shared:
                            held = shared.execute('SELECT action_id,owner FROM broker_admission WHERE provider=? AND environment=? AND account_id=?', ('webull', row['environment'], row['account'])).fetchone()
                        if held == (review_id, 'tradepilot'):
                            self.db.execute("UPDATE reviews SET state='CANCELLED_REVIEW' WHERE id=?", (review_id,))
                            ledger.release(review_id)
                return self.receipt(self.row(review_id))
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
                observed_quantity = row["observed_filled_quantity"]
                # Older receipts can contain a verified quantity without a price.
                # Restore that lower bound, but do not turn it into a fill value.
                if observed_quantity is None:
                    try:
                        tracked = self.db.execute("""SELECT order_id FROM execution_tracked
                            WHERE environment=? AND account_id=? AND client_order_id=?""",
                            (row["environment"], row["account"], client_id)).fetchone()
                        saved = self.detail_candidate(result, row, body)
                        saved_qty, _ = self.executions.validate_candidate(
                            body, saved, tracked["order_id"] if tracked else None, allow_incomplete=True)
                        if saved["status"] == state and saved_qty is not None:
                            observed_quantity = str(saved_qty)
                    except ExecutionEvidenceError:
                        pass
                try:
                    candidate = self.detail_candidate(detail, row, body)
                    qty, price = self.executions.validate_candidate(body, candidate, allow_incomplete=True)
                    previous = self.db.execute("""SELECT filled_quantity FROM execution_latest
                        WHERE environment=? AND account_id=? AND client_order_id=?""",
                        (row["environment"], row["account"], client_id)).fetchone()
                    if (qty is not None and
                            ((previous and qty < Decimal(previous["filled_quantity"])) or
                             (observed_quantity is not None and qty < Decimal(observed_quantity)))):
                        raise ExecutionEvidenceError("Broker detail decreased cumulative filled quantity")
                    if (qty is None and candidate.get("filled_price") is not None
                            and Decimal(str(candidate["filled_price"])) == 0
                            and ((previous and Decimal(previous["filled_quantity"]) > 0) or
                                 (observed_quantity is not None and Decimal(observed_quantity) > 0))):
                        raise ExecutionEvidenceError("Zero fill price conflicted with a previously reported fill")
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
                        if qty is not None:
                            observed_quantity = str(qty)
                    else:
                        raise ExecutionEvidenceError("Broker detail conflicted with verified execution evidence")
                except ExecutionEvidenceError as exc:
                    self.executions.warn(row["environment"], row["account"], client_id, str(exc))
                    # Keep the last trusted result available for recovery and
                    # clearly explain why the new observation was not adopted.
                    result = {**result, "tradepilot_status_warning": str(exc)}
                economic_terms = json.loads(row['preview']).get('_economic_terms')
                if row['environment'] == 'production' and economic_terms and state in ('FILLED', 'CANCELLED', 'FAILED'):
                    try:
                        settled = self.detail_candidate(result, row, body)
                        commission, fees = settled.get('commission'), settled.get('fees')
                        if not isinstance(commission, dict) or not isinstance(fees, list):
                            raise BrokerError('Actual fees unavailable; account hold retained until settlement evidence arrives.')
                        actual = number(commission.get('actual_commission'))
                        if actual < 0 or actual != number(commission.get('receivable_commission')):
                            raise BrokerError('Commission settlement incomplete; hold retained.')
                        types = set()
                        for fee in fees:
                            if not isinstance(fee, dict) or not isinstance(fee.get('type'), str) or not fee['type'] or fee['type'] in types:
                                raise BrokerError('Fee breakdown incomplete; hold retained.')
                            types.add(fee['type'])
                            value = number(fee.get('actual_value'))
                            if value < 0 or value != number(fee.get('receivable_value')):
                                raise BrokerError('Fee settlement incomplete; hold retained.')
                            actual += value
                        quantity = number(settled.get('filled_quantity'))
                        price = number(settled.get('filled_price')) if quantity else Decimal(0)
                        if min(quantity, price) < 0:
                            raise BrokerError('Invalid fill value; hold retained.')
                        filled = quantity * price
                        debit = filled + actual if body['side'] == 'BUY' else actual
                        result['_economic_evidence'] = {'actual_fee': str(actual), 'actual_debit': str(debit), 'fee_currency': 'USD',
                            'fee_overrun': actual > number(economic_terms['fee_estimate_ceiling']),
                            'debit_overrun': debit > number(economic_terms['debit_admission_ceiling'])}
                    except (BrokerError, ExecutionEvidenceError):
                        result['_economic_warning'] = 'Actual fees or settlement incomplete; account hold retained. Refresh this order later.'
                self.db.execute("UPDATE reviews SET state=?,result=?,observed_filled_quantity=? WHERE id=?",
                                (state, json.dumps(result), observed_quantity, review_id))
                self.audit(review_id, "broker_status", detail)
            if self.receipt(self.row(review_id))['state'] in ('FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED', 'FAILED'):
                (self.admission if self.admission is not None else AdmissionLedger()).release(review_id)
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
                changed = self.db.execute(
                    "UPDATE reviews SET state='CANCELLED_REVIEW' WHERE id=? AND state='REVIEW'",
                    (review_id,)).rowcount
                if changed == 1:
                    self.audit(review_id, "cancelled_review", {})
            return self.receipt(self.row(review_id))
