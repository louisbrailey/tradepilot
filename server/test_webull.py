import os
import json
import sqlite3
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from contextlib import closing
from webull_service import WebullAdapter, WebullService, BrokerError

class FakeBroker:
    environment = 'sandbox'
    cost = '300'
    calls = 0
    fail = False
    def accounts(self):
        return [{'account_id': 'cash', 'account_class': 'INDIVIDUAL_CASH'}]
    def positions(self, account):
        return [{'symbol': 'AAPL', 'quantity': '5', 'instrument_type': 'EQUITY'}]
    def preview(self, account, order):
        return {'estimated_cost': self.cost, 'estimated_transaction_fee': '0.01'}
    def place(self, account, order):
        self.calls += 1
        if self.fail:
            raise TimeoutError()
        return {'client_order_id': order['client_order_id'], 'order_id': 'broker-order'}
    def detail(self, account, order):
        return {'combo_type': 'NORMAL', 'orders': [{'status': 'FILLED', 'client_order_id': order,
            'order_id': 'broker-order', 'symbol': 'AAPL', 'side': 'SELL',
            'order_type': 'MARKET', 'time_in_force': 'DAY', 'entrust_type': 'QTY',
            'instrument_type': 'EQUITY', 'support_trading_session': 'CORE',
            'total_quantity': '3', 'filled_quantity': '3', 'filled_price': '100'}]}

class WebullTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/ledger.db'
        self.adapter = FakeBroker()
        self.now = 1000
        self.service = WebullService(self.path, self.adapter, lambda: self.now)
    def tearDown(self):
        self.service.db.close()
        self.tmp.cleanup()
    def review(self, **changes):
        return self.service.create_review({'account_id': 'cash', 'symbol': 'AAPL', 'side': 'SELL', 'quantity': '3', **changes})
    def approval(self, review):
        return {'id': review['id'], 'confirmation_token': review['confirmation_token'], 'approved': True}
    def test_preview_has_no_side_effect_and_approval_required(self):
        review = self.review()
        self.assertEqual(self.adapter.calls, 0)
        for extra in ({'approved': False}, {'confirmation_token': 'bad'}):
            with self.assertRaises(BrokerError):
                self.service.confirm({**self.approval(review), **extra})
        self.assertEqual(self.adapter.calls, 0)
    def test_duplicate_and_restart_do_not_submit_twice(self):
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        self.assertEqual(receipt['state'], 'SUBMITTED')
        self.assertEqual(self.service.confirm(approval), receipt)
        self.service.db.close()
        self.service = WebullService(self.path, self.adapter, lambda: self.now)
        self.assertEqual(self.service.confirm(approval), receipt)
        self.assertEqual(self.adapter.calls, 1)
    def test_unknown_outcome_never_retries(self):
        self.adapter.fail = True
        approval = self.approval(self.review())
        self.assertEqual(self.service.confirm(approval)['state'], 'UNKNOWN')
        self.service.confirm(approval)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')

    def test_unknown_malformed_detail_does_not_poison_later_exact_identity(self):
        self.adapter.fail = True
        approval = self.approval(self.review())
        self.assertEqual(self.service.confirm(approval)['state'], 'UNKNOWN')
        correct = self.adapter.detail('cash', self.service.receipt(
            self.service.row(approval['id']))['client_order_id'])
        malformed = {**correct, 'orders': [{**correct['orders'][0], 'symbol': 'MSFT', 'order_id': 'wrong-order'}]}
        responses = iter((malformed, correct))
        self.adapter.detail = lambda account, order: next(responses)
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'UNKNOWN')
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        summary = self.service.execution_summary('cash')
        self.assertEqual(summary['orders'][0]['id'], 'broker-order')
        self.assertEqual(self.adapter.calls, 1)

    def test_terminal_status_without_optional_fills_and_later_evidence(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        original = self.adapter.detail
        def missing(account, order):
            detail = original(account, order)
            detail['orders'][0].pop('filled_price')
            return detail
        self.adapter.detail = missing
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])
        self.adapter.detail = original
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        self.assertEqual(len(self.service.execution_summary('cash')['orders']), 1)
        self.assertEqual(self.adapter.calls, 1)

    def test_cancelled_without_optional_fill_quantity(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        original = self.adapter.detail
        def cancelled(account, order):
            detail = original(account, order)
            detail['orders'][0].update(status='CANCELLED')
            detail['orders'][0].pop('filled_quantity')
            detail['orders'][0].pop('filled_price')
            return detail
        self.adapter.detail = cancelled
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'CANCELLED')
        self.assertEqual(self.adapter.calls, 1)

    def test_terminal_state_does_not_regress_on_refresh(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        self.adapter.detail = lambda account, order: {'combo_type': 'NORMAL', 'orders': [
            {'status': 'SUBMITTED', 'client_order_id': order, 'order_id': 'broker-order',
             'symbol': 'AAPL', 'side': 'SELL', 'total_quantity': '3',
             'order_type': 'MARKET', 'time_in_force': 'DAY', 'entrust_type': 'QTY',
             'filled_quantity': '3', 'filled_price': '100'}]}
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
    def test_crash_after_committed_intent_does_not_retry(self):
        approval = self.approval(self.review())
        with self.service.db:
            self.service.db.execute("UPDATE reviews SET state='SUBMITTING'")
        self.assertEqual(self.service.confirm(approval)['state'], 'SUBMITTING')
        self.assertEqual(self.adapter.calls, 0)
    def test_expiry_and_changed_price(self):
        approval = self.approval(self.review())
        self.now += 60
        with self.assertRaises(BrokerError): self.service.confirm(approval)
        approval = self.approval(self.review())
        self.adapter.cost = '301'
        with self.assertRaises(BrokerError): self.service.confirm(approval)
        self.assertEqual(self.adapter.calls, 0)
    def test_unauthorized_account_and_short_rejected(self):
        for changes in ({'account_id': 'other'}, {'quantity': '6'}, {'side': 'SHORT'}, {'quantity': 'NaN'}, {'approved': True}):
            with self.assertRaises(BrokerError): self.review(**changes)
        self.assertEqual(self.adapter.calls, 0)
    def test_live_execution_requires_explicit_backend_enablement(self):
        self.adapter.environment = 'production'
        approval = self.approval(self.review())
        with patch.dict(os.environ, {'WEBULL_LIVE_TRADING': ''}):
            with self.assertRaises(BrokerError): self.service.confirm(approval)
        self.assertEqual(self.adapter.calls, 0)
    def test_cancelled_review_does_not_submit(self):
        review = self.review()
        self.service.cancel_review(review['id'])
        self.assertEqual(self.service.confirm(self.approval(review))['state'], 'CANCELLED_REVIEW')
        self.assertEqual(self.adapter.calls, 0)
    def test_dismissal_cannot_overwrite_confirmation_from_another_connection(self):
        review = self.review()
        other = WebullService(self.path, self.adapter, lambda: self.now)
        original_row = self.service.row
        first_read = True
        def interleaved_row(review_id):
            nonlocal first_read
            row = original_row(review_id)
            if first_read:
                first_read = False
                self.assertEqual(other.confirm(self.approval(review))['state'], 'SUBMITTED')
            return row
        try:
            with patch.object(self.service, 'row', side_effect=interleaved_row):
                receipt = self.service.cancel_review(review['id'])
            self.assertEqual(receipt['state'], 'SUBMITTED')
            self.assertEqual(self.adapter.calls, 1)
            self.assertEqual(self.service.db.execute(
                "SELECT count(*) FROM audit WHERE event='cancelled_review'").fetchone()[0], 0)
        finally:
            other.db.close()

    def test_incomplete_fill_quantity_cannot_regress_after_missing_fields_and_restart(self):
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        detail = self.adapter.detail('cash', receipt['client_order_id'])
        base = {key: value for key, value in detail['orders'][0].items()
                if key not in ('filled_quantity', 'filled_price')}
        def refresh(**fields):
            self.adapter.detail = lambda account, client: {**detail, 'orders': [
                {**base, 'status': 'PARTIAL_FILLED', **fields}]}
            return self.service.refresh(approval['id'])
        self.assertEqual(refresh(filled_quantity='2')['state'], 'PARTIAL_FILLED')
        self.assertEqual(refresh()['state'], 'PARTIAL_FILLED')
        self.service.db.close()
        self.service = WebullService(self.path, self.adapter, lambda: self.now)
        receipt = refresh(filled_quantity='1', filled_price='100')
        self.assertIn('decreased cumulative filled quantity', receipt['detail'])
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])
        self.assertEqual(refresh(filled_quantity='2', filled_price='100')['state'], 'PARTIAL_FILLED')
        self.assertEqual(self.service.execution_summary('cash')['orders'][0]['filled_quantity'], '2')

    def test_saved_incomplete_fill_quantity_is_restored_before_a_refresh(self):
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        detail = self.adapter.detail('cash', receipt['client_order_id'])
        detail['orders'][0].update(status='PARTIAL_FILLED', filled_quantity='2')
        detail['orders'][0].pop('filled_price')
        # Simulate a previously saved receipt from the older schema, which had
        # no complete execution_latest row for this optional-price omission.
        with self.service.db:
            self.service.db.execute("UPDATE reviews SET state='PARTIAL_FILLED',result=? WHERE id=?",
                                    (json.dumps(detail), approval['id']))
        self.service.db.close()
        with closing(sqlite3.connect(self.path)) as legacy:
            legacy.executescript("""
                ALTER TABLE reviews RENAME TO newer_reviews;
                CREATE TABLE reviews (
                    id TEXT PRIMARY KEY, environment TEXT NOT NULL, account TEXT NOT NULL,
                    body TEXT NOT NULL, preview TEXT NOT NULL, expires REAL NOT NULL,
                    token_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');
                INSERT INTO reviews SELECT id,environment,account,body,preview,expires,token_hash,state,result
                    FROM newer_reviews;
                DROP TABLE newer_reviews;
            """)
        self.service = WebullService(self.path, self.adapter, lambda: self.now)
        detail['orders'][0].update(filled_quantity='1', filled_price='100')
        self.adapter.detail = lambda account, client: detail
        receipt = self.service.refresh(approval['id'])
        self.assertIn('decreased cumulative filled quantity', receipt['detail'])
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])

    def test_environment_switch_rejects_existing_review(self):
        review = self.review()
        self.adapter.environment = 'production'
        with self.assertRaises(BrokerError): self.service.refresh(review['id'])
    def test_request_preserves_regular_session_and_no_short_side(self):
        review = self.review(limit_price='200')
        self.assertEqual(review['order']['support_trading_session'], 'CORE')
        self.assertEqual(review['order']['order_type'], 'LIMIT')
        self.assertEqual(review['order']['limit_price'], '200')
        self.assertEqual(len(review['order']['client_order_id']), 32)

    def test_receipt_includes_account_id(self):
        receipt = self.service.confirm(self.approval(self.review()))
        self.assertEqual(receipt['account_id'], 'cash')

    def test_execution_summary_requires_authorized_account(self):
        with self.assertRaises(BrokerError):
            self.service.execution_summary('other')

    def test_status_without_fill_fields_creates_no_false_execution(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        self.adapter.detail = lambda account, order: {'combo_type': 'NORMAL', 'orders': [{
            'status': 'FILLED', 'client_order_id': order, 'order_id': 'broker-order',
            'order_type': 'MARKET', 'time_in_force': 'DAY', 'entrust_type': 'QTY',
            'symbol': 'AAPL', 'side': 'SELL', 'total_quantity': '3'}]}
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])

    def test_confirmation_rejects_added_order_terms(self):
        approval = self.approval(self.review())
        for extra in ({'account_id': 'other'}, {'quantity': '999'}, {'side': 'BUY'}):
            with self.subTest(extra=extra), self.assertRaises(BrokerError):
                self.service.confirm({**approval, **extra})
        self.assertEqual(self.adapter.calls, 0)

    def test_invalid_limit_never_silently_becomes_market_order(self):
        for limit in (None, False, 0, '', [], {}, '0', 'NaN'):
            with self.subTest(limit=limit), self.assertRaises(BrokerError):
                self.review(limit_price=limit)
        self.assertEqual(self.service.db.execute('SELECT count(*) FROM reviews').fetchone()[0], 0)
        self.assertEqual(self.adapter.calls, 0)

    def test_untrusted_detail_never_adopts_an_order_id_or_fabricates_a_fill(self):
        self.adapter.fail = True
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        correct = self.adapter.detail('cash', receipt['client_order_id'])
        order = correct['orders'][0]
        altered = [
            {**correct, 'orders': [{**order, 'order_type': 'LIMIT', 'limit_price': '100'}]},
            {**correct, 'orders': [{**order, 'instrument_type': 'OPTION'}]},
            {**correct, 'orders': [{**order, 'time_in_force': 'GTC'}]},
            {**correct, 'orders': [{**order, 'entrust_type': 'AMOUNT'}]},
            {**correct, 'orders': [{**order, 'support_trading_session': 'ALL'}]},
            {**correct, 'orders': [{**order, 'market': 'HK'}]},
            {**correct, 'orders': [{**order, 'account_id': 'other'}]},
            {**correct, 'orders': [{**order, 'environment': 'production'}]},
            {**correct, 'account_id': 'other'},
            {**correct, 'environment': 'production'},
            {**correct, 'client_order_id': 'other'},
            {**correct, 'combo_type': 'OTO'},
            {**correct, 'orders': [order, order]},
            {**correct, 'orders': [None]},
            {**correct, 'orders': None},
            {'orders': [order]},
        ]
        for detail in altered:
            with self.subTest(detail=detail):
                self.adapter.detail = lambda account, client, detail=detail: detail
                receipt = self.service.refresh(approval['id'])
                self.assertEqual(receipt['state'], 'UNKNOWN')
                self.assertEqual(self.service.db.execute('SELECT count(*) FROM execution_tracked').fetchone()[0], 0)
                self.assertIn('tradepilot_status_warning', receipt['detail'])
        self.adapter.detail = lambda account, client: correct
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
        self.assertEqual(self.adapter.calls, 1)

    def test_partial_status_cannot_regress_when_optional_fills_disappear(self):
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        detail = self.adapter.detail('cash', receipt['client_order_id'])
        order = detail['orders'][0]
        self.adapter.detail = lambda account, client: {**detail, 'orders': [
            {**order, 'status': 'PARTIAL_FILLED', 'filled_quantity': '1'}]}
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'PARTIAL_FILLED')
        missing = {key: value for key, value in order.items() if key not in ('filled_quantity', 'filled_price')}
        self.adapter.detail = lambda account, client: {**detail, 'orders': [{**missing, 'status': 'SUBMITTED'}]}
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'PARTIAL_FILLED')
        self.adapter.detail = lambda account, client: {**detail, 'orders': [
            {**missing, 'status': 'CANCELLED', 'filled_price': '0'}]}
        rejected = self.service.refresh(approval['id'])
        self.assertEqual(rejected['state'], 'PARTIAL_FILLED')
        self.assertIn('Zero fill price conflicted', rejected['detail'])
        self.adapter.detail = lambda account, client: {**detail, 'orders': [{**missing, 'status': 'CANCELLED'}]}
        self.assertEqual(self.service.refresh(approval['id'])['state'], 'CANCELLED')
        self.assertEqual(self.service.execution_summary('cash')['totals']['notional_by_currency']['USD']['sell'], '100')

    def test_terminal_missing_fields_does_not_hide_inconsistent_provided_fields(self):
        approval = self.approval(self.review())
        receipt = self.service.confirm(approval)
        detail = self.adapter.detail('cash', receipt['client_order_id'])
        for changes in ({'status': 'CANCELLED', 'filled_quantity': '0', 'filled_price': 'NaN'},
                        {'status': 'CANCELLED', 'filled_quantity': '0', 'filled_price': '100'},
                        {'status': 'SUBMITTED', 'filled_quantity': None, 'filled_price': '100'},
                        {'status': 'FILLED', 'filled_quantity': None, 'filled_price': '0'},
                        {'status': 'PARTIAL_FILLED', 'filled_quantity': None, 'filled_price': '0'},
                        {'status': 'FILLED', 'filled_quantity': '2', 'filled_price': None}):
            with self.subTest(changes=changes):
                self.adapter.detail = lambda account, client, changes=changes: {
                    **detail, 'orders': [{**detail['orders'][0], **changes}]}
                self.assertEqual(self.service.refresh(approval['id'])['state'], 'SUBMITTED')
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])

    def test_broker_id_and_last_verified_result_survive_conflicting_refresh(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        self.service.refresh(approval['id'])
        original = self.adapter.detail
        self.adapter.detail = lambda account, client: {
            **original(account, client), 'orders': [{**original(account, client)['orders'][0], 'order_id': 'wrong'}]}
        receipt = self.service.refresh(approval['id'])
        self.assertEqual(receipt['state'], 'FILLED')
        self.assertIn('broker-order', receipt['detail'])
        self.assertNotIn('"order_id": "wrong"', receipt['detail'])
        self.assertEqual(self.service.execution_summary('cash')['orders'][0]['id'], 'broker-order')

    def test_late_acknowledgement_or_timeout_cannot_overwrite_terminal_refresh(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                # A separate database per scenario avoids FakeBroker's constant
                # order ID being reused for distinct test orders.
                path = self.tmp.name + '/concurrent-%s.db' % timeout
                primary = WebullService(path, self.adapter, lambda: self.now)
                observer = WebullService(path, FakeBroker(), lambda: self.now)
                review = primary.create_review({'account_id': 'cash', 'symbol': 'AAPL', 'side': 'SELL', 'quantity': '3'})
                def place(account, order):
                    self.assertEqual(observer.refresh(review['id'])['state'], 'FILLED')
                    if timeout:
                        raise TimeoutError()
                    return {'client_order_id': order['client_order_id'], 'order_id': 'broker-order'}
                self.adapter.place = place
                try:
                    self.assertEqual(primary.confirm(self.approval(review))['state'], 'FILLED')
                    self.assertEqual(primary.confirm(self.approval(review))['state'], 'FILLED')
                    self.assertEqual(primary.execution_summary('cash')['totals']['filled_orders'], 1)
                finally:
                    primary.db.close(); observer.db.close()

    def test_stale_refresh_cannot_overwrite_newer_terminal_state_across_processes(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        observer = WebullService(self.path, FakeBroker(), lambda: self.now)
        original = self.adapter.detail
        def stale(account, client):
            self.assertEqual(observer.refresh(approval['id'])['state'], 'FILLED')
            detail = original(account, client)
            detail['orders'][0].update(status='CANCELLED', filled_quantity='0', filled_price=None)
            return detail
        self.adapter.detail = stale
        try:
            self.assertEqual(self.service.refresh(approval['id'])['state'], 'FILLED')
            self.assertEqual(self.service.execution_summary('cash')['totals']['filled_orders'], 1)
        finally:
            observer.db.close()

    def test_simultaneous_confirmations_submit_once_across_database_connections(self):
        approval = self.approval(self.review())
        other = WebullService(self.path, self.adapter, lambda: self.now)
        barrier = threading.Barrier(2)
        original = self.adapter.preview
        def preview(account, order):
            barrier.wait(timeout=5)
            return original(account, order)
        self.adapter.preview = preview
        results, errors = [], []
        def confirm(service):
            try:
                results.append(service.confirm(approval))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=confirm, args=(service,)) for service in (self.service, other)]
        try:
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertEqual(self.adapter.calls, 1)
            self.assertEqual(self.service.confirm(approval)['state'], 'SUBMITTED')
        finally:
            other.db.close()

    def test_legacy_filled_review_requires_complete_terms_before_backfill(self):
        approval = self.approval(self.review())
        self.service.confirm(approval)
        receipt = self.service.refresh(approval['id'])
        valid = receipt['detail']
        invalid = json.loads(valid)
        invalid['orders'][0]['order_type'] = 'LIMIT'
        with self.service.db:
            self.service.db.execute('UPDATE execution_tracked SET order_body=NULL')
            self.service.db.execute('UPDATE execution_latest SET verification_version=1')
            self.service.db.execute('UPDATE reviews SET result=? WHERE id=?', (json.dumps(invalid), approval['id']))
        self.assertEqual(self.service.execution_summary('cash')['orders'], [])
        with self.service.db:
            self.service.db.execute('UPDATE reviews SET result=? WHERE id=?', (valid, approval['id']))
        self.assertEqual(self.service.execution_summary('cash')['totals']['filled_orders'], 1)
        self.assertEqual(self.service.db.execute('SELECT verification_version FROM execution_latest').fetchone()[0], 2)


class WebullAdapterTests(unittest.TestCase):
    def adapter(self, response, trade_error=None):
        api = types.ModuleType('webull.core.client')
        trade = types.ModuleType('webull.trade.trade_client')

        class ApiClient:
            def __init__(self, *args, **kwargs): self.token_dir = None
            def set_stream_logger(self, **kwargs): pass
            def add_endpoint(self, *args): pass
            def set_token_dir(self, path): self.token_dir = path

        class Orders:
            def place_order(self, account, orders): return response(orders[0])

        class TradeClient:
            def __init__(self, client):
                if trade_error:
                    raise trade_error
                self.api_client, self.order_v3 = client, Orders()

        api.ApiClient, trade.TradeClient = ApiClient, TradeClient
        modules = {'webull.core.client': api, 'webull.trade.trade_client': trade}
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {
                'WEBULL_APP_KEY': 'key', 'WEBULL_APP_SECRET': 'secret',
                'WEBULL_ENV': 'production'}):
            return WebullAdapter('/private/runtime')

    def test_token_cache_is_scoped_to_environment(self):
        adapter = self.adapter(lambda order: {})
        self.assertEqual(adapter.client.api_client.token_dir,
                         '/private/runtime/webull-tokens/production')

    def test_authentication_initialization_error_is_actionable_and_redacted(self):
        with self.assertRaises(BrokerError) as raised:
            self.adapter(lambda order: {}, RuntimeError('secret provider failure'))
        message = str(raised.exception)
        self.assertIn('Webull mobile app', message)
        self.assertIn('API 2FA', message)
        self.assertNotIn('secret provider failure', message)

    def test_place_requires_matching_client_and_broker_order_ids(self):
        order = {'client_order_id': 'expected'}
        accepted = self.adapter(lambda order: FakeResponse(
            {'client_order_id': order['client_order_id'], 'order_id': 'broker'}))
        self.assertEqual(accepted.place('cash', order)['order_id'], 'broker')
        for response in ({}, {'client_order_id': 'wrong', 'order_id': 'broker'},
                         {'client_order_id': 'expected', 'order_id': ''}):
            adapter = self.adapter(lambda order, response=response: FakeResponse(response))
            with self.subTest(response=response), self.assertRaises(BrokerError):
                adapter.place('cash', order)


class FakeResponse:
    status_code = 200
    def __init__(self, body): self.body = body
    def json(self): return self.body

if __name__ == '__main__': unittest.main()
