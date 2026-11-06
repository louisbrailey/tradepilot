import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from broker_admission import AdmissionLedger, AdmissionError
from broker_actions import BrokerActions
from coinbase_access import CoinbaseAccess
from coinbase_service import CoinbaseError
from webull_service import BrokerError
import access_routes
import server

FLAGS = {'COINBASE_LIVE_TRADING': 'enabled', 'COINBASE_TRANSFERS': 'enabled', 'BROKER_KILL_SWITCH': 'disabled'}


class Fake:
    provider, environment = 'coinbase', 'production'
    exact_transfer_reconciliation = True
    def __init__(self):
        self.calls = []
        self.failure = None
        self.status = 'OPEN'
        self.funds = Decimal('10000')
        self.fee = '0.10'
        self.allowed = True
        self.source = '11111111-1111-4111-8111-111111111111'
        self.history = []
    def permissions(self):
        return {'can_view': True, 'can_trade': self.allowed, 'can_transfer': self.allowed, 'portfolio_uuid': self.source}
    def portfolios(self):
        return [{'id': '11111111-1111-4111-8111-111111111111', 'type': 'DEFAULT'}, {'id': '22222222-2222-4222-8222-222222222222', 'type': 'CONSUMER'}]
    def available(self, account, currency):
        return self.funds
    def product(self, product):
        return {'product_id': product, 'product_type': 'SPOT', 'status': 'online', 'trading_disabled': False,
                'cancel_only': False, 'view_only': False, 'base_increment': '0.01', 'price_increment': '0.01',
                'base_currency_id': 'BTC', 'quote_currency_id': 'USD', 'base_min_size': '0.01', 'base_max_size': '1000'}
    def preview(self, body):
        return {'errs': [], 'preview_id': 'preview', 'commission_total': self.fee, 'base_size': '1', 'commission_detail_total': {'total_commission': self.fee}}
    def submit(self, action, body):
        self.calls.append((action, body))
        if self.failure:
            raise self.failure
        if action == 'internal_transfer':
            return {k: body[k] for k in ('source_portfolio_uuid', 'target_portfolio_uuid')}
        if action == 'cancel_order':
            return {'results': [{'success': True, 'order_id': body['order_ids'][0]}]}
        return {'success': True, 'success_response': {k: body[k] for k in ('client_order_id', 'product_id', 'side')} | {'order_id': 'order-1'}}
    def detail(self, order):
        body = next((b for a, b in self.calls if a == 'limit_order'), {})
        return body | {'order_id': order, 'retail_portfolio_id': '11111111-1111-4111-8111-111111111111', 'status': self.status, 'total_fees': '0.10', 'filled_value': '10'}
    def orders(self, account):
        return self.history


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.admission = AdmissionLedger(self.path / 'shared.sqlite3')
        self.fake = Fake()
        self.now = 1000
        self.s = self.new_service()
        self.flags = patch.dict(os.environ, FLAGS, clear=True)
        self.flags.start(); self.addCleanup(self.flags.stop)
    def new_service(self):
        s = BrokerActions(self.path / 'actions.sqlite3', self.fake, self.admission, lambda: self.now)
        self.addCleanup(s.db.close)
        return s
    def intent(self, **updates):
        return {'client_id': 'client-1', 'account_id': '11111111-1111-4111-8111-111111111111', 'environment': 'production',
                'action': 'limit_order', 'product_id': 'BTC-USD', 'side': 'BUY', 'base_size': '1', 'limit_price': '10',
                'fee_policy': 'accept_rechecked_estimate', 'fee_estimate_ceiling': '0.10', 'debit_admission_ceiling': '10.20', 'headroom': '0.10', 'fee_currency': 'USD'} | updates
    def transfer(self, **updates):
        return {'client_id': 'transfer-1', 'account_id': '11111111-1111-4111-8111-111111111111', 'environment': 'production',
                'action': 'internal_transfer', 'destination': '22222222-2222-4222-8222-222222222222', 'currency': 'USDC', 'amount': '10',
                'network': 'coinbase_internal', 'fee_policy': 'internal_no_fee_parameter'} | updates
    def approval(self, review):
        return {k: review[k] for k in ('id', 'token', 'digest')} | {'approved': True}
    def holds(self):
        with self.admission.connect() as db:
            return db.execute('SELECT * FROM broker_admission ORDER BY account_id').fetchall()
    def test_exact_confirmation_fields_and_digest(self):
        review = self.s.review(self.intent())
        for updates in ({'digest': 'wrong'}, {'approved': 1}, {'token': 'wrong'}, {'account_id': 'other'}, {'amount': '100'}):
            with self.subTest(updates=updates), self.assertRaises(BrokerError):
                self.s.confirm(self.approval(review) | updates)
        self.assertEqual(self.fake.calls, [])
    def test_default_off_and_separate_transfer_flag(self):
        r = self.s.review(self.transfer())
        for values in ({}, {'BROKER_KILL_SWITCH': 'disabled', 'COINBASE_LIVE_TRADING': 'enabled'}):
            with patch.dict(os.environ, values, clear=True), self.assertRaises(BrokerError):
                self.s.confirm(self.approval(r))
        self.assertFalse(self.fake.calls)
    def test_expiry_before_and_during_validation(self):
        r = self.s.review(self.intent())
        self.now += 61
        with self.assertRaises(BrokerError): self.s.confirm(self.approval(r))
        self.assertFalse(self.fake.calls)
        self.now = 1000
        original = self.fake.available
        def expire(*args):
            self.now += 61
            return original(*args)
        self.fake.available = expire
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertFalse(self.holds())
    def test_submission_rechecks_identity_permissions_balance_fee_kill(self):
        mutations = [lambda: setattr(self.fake, 'source', 'other'), lambda: setattr(self.fake, 'allowed', False),
                     lambda: setattr(self.fake, 'funds', Decimal(0)), lambda: setattr(self.fake, 'fee', '1'),
                     lambda: os.environ.update(BROKER_KILL_SWITCH='enabled')]
        for index, mutate in enumerate(mutations):
            self.fake = Fake(); self.s.adapter = self.fake
            os.environ.update(FLAGS)
            r = self.s.review(self.intent(client_id=f'client-{index}'))
            mutate()
            try: result = self.s.confirm(self.approval(r))
            except BrokerError: pass
            else: self.assertEqual(result['state'], 'REJECTED')
            self.assertFalse(self.fake.calls)
            self.assertFalse(self.holds())
    def test_concurrent_confirmation_across_connections_single_send(self):
        r = self.s.review(self.intent()); other = self.new_service()
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda s: s.confirm(self.approval(r)), [self.s, other]))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.holds()[0][2], '11111111-1111-4111-8111-111111111111')
    def test_stable_intent_duplicate_and_changed_terms(self):
        self.s.review(self.intent())
        for p in (self.intent(), self.intent(limit_price='20')):
            with self.assertRaises(BrokerError): self.s.review(p)
        self.assertFalse(self.fake.calls)
    def test_unknown_restart_blocks_duplicate_new_order_and_transfer(self):
        self.fake.failure = TimeoutError('PRIVATE SECRET')
        r = self.s.review(self.intent())
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'UNKNOWN')
        other = self.new_service()
        self.assertEqual(other.confirm(self.approval(r))['state'], 'UNKNOWN')
        for p in (self.intent(client_id='new'), self.transfer()):
            next_review = other.review(p)
            self.assertEqual(other.confirm(self.approval(next_review))['state'], 'REJECTED')
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.holds()[0][-1], 'UNKNOWN')
        self.assertNotIn('PRIVATE SECRET', (self.path / 'actions.sqlite3').read_bytes().decode(errors='ignore'))
    def test_missing_lookup_cannot_clear_unknown(self):
        self.fake.failure = TimeoutError()
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        self.assertEqual(self.s.reconcile(r['id'])['state'], 'UNKNOWN')
        self.assertTrue(self.holds())
    def test_other_app_and_destination_hold_block_atomically(self):
        with self.admission.connect() as db:
            db.execute('INSERT INTO broker_admission VALUES (?,?,?,?,?,?)', ('coinbase', 'production', '22222222-2222-4222-8222-222222222222', 'sf-action', 'signal-forge', 'UNKNOWN'))
        r = self.s.review(self.transfer())
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertEqual(len(self.holds()), 1)
        self.assertFalse(self.fake.calls)
    def test_internal_transfer_documented_success_releases_after_durable_evidence(self):
        original = self.fake.submit
        def send(action, body):
            self.assertEqual([r[2] for r in self.holds()], ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'])
            self.assertTrue(all(r[-1] == 'SUBMITTING' for r in self.holds()))
            return original(action, body)
        self.fake.submit = send
        r = self.s.review(self.transfer())
        result = self.s.confirm(self.approval(r))
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(result['result']['funds'], {'value': '10', 'currency': 'USDC'})
        self.assertFalse(self.holds())
    def test_rejection_and_malformed_acceptance(self):
        r = self.s.review(self.intent())
        self.fake.submit = lambda *_: {'success': False, 'error_response': {'message': 'SECRET'}}
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertFalse(self.holds())
        r = self.s.review(self.intent(client_id='second'))
        self.fake.submit = lambda *_: {'success': True, 'success_response': {'order_id': 'other'}}
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'UNKNOWN')
        self.assertTrue(self.holds())
    def test_authoritative_terminal_release_requires_matching_terms(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        self.fake.status = 'FILLED'
        good = self.fake.detail
        self.fake.detail = lambda order: good(order) | {'side': 'SELL'}
        with self.assertRaises(BrokerError): self.s.reconcile(r['id'])
        self.assertTrue(self.holds())
        self.fake.detail = good
        self.assertEqual(self.s.reconcile(r['id'])['state'], 'COMPLETED')
        self.assertFalse(self.holds())
    def test_confirmed_cancellation_uses_existing_owned_order_hold(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        c = self.s.review({'client_id': 'cancel-1', 'action': 'cancel_order', 'environment': 'production',
                           'account_id': '11111111-1111-4111-8111-111111111111', 'order_id': 'order-1'})
        self.assertEqual(self.s.confirm(self.approval(c))['state'], 'ACCEPTED')
        self.assertEqual(len(self.fake.calls), 2)
        self.assertTrue(self.holds())
        self.fake.status = 'CANCELLED'
        self.assertEqual(self.s.reconcile(c['id'])['state'], 'COMPLETED')
        self.assertFalse(self.holds())
    def test_external_network_unsupported_bounds_and_bad_numeric_inputs_refused(self):
        for p in (self.transfer(network='ethereum'), self.transfer(destination='11111111-1111-4111-8111-111111111111'), self.intent(max_fee='0'),
                  self.intent(base_size='NaN'), self.intent(base_size='-1'), self.intent(environment='sandbox'),
                  self.intent(account_id='wallet-id'), self.intent(base_size='0.001')):
            with self.subTest(p=p), self.assertRaises((BrokerError, CoinbaseError)): self.s.review(p)
        self.assertFalse(self.fake.calls)

    def test_hard_cap_default_and_missing_fee_coverage_refuse(self):
        with self.assertRaises(BrokerError): self.s.review(self.intent(fee_policy='require_provider_cap'))
        self.fake.preview = lambda _: {'errs': [], 'preview_id': 'p', 'commission_total': '0.10', 'base_size': '1'}
        with self.assertRaises(BrokerError): self.s.review(self.intent())
        self.assertFalse(self.fake.calls)

    def test_foreign_open_orders_checked_after_admission(self):
        r = self.s.review(self.intent())
        def foreign(account):
            self.assertTrue(self.holds())
            return [{'status': 'OPEN', 'retail_portfolio_id': account}]
        self.fake.orders = foreign
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertFalse(self.fake.calls)
        self.assertFalse(self.holds())

    def test_stale_preview_and_sell_fee_reserve(self):
        r = self.s.review(self.intent())
        def slow_funds(*_):
            self.now += 16
            return Decimal('10000')
        self.fake.available = slow_funds
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertFalse(self.fake.calls)
        self.fake.available = lambda account, asset: Decimal('5') if asset == 'BTC' else Decimal('0')
        with self.assertRaises(BrokerError): self.s.review(self.intent(client_id='sell', side='SELL'))

    def test_protective_cancel_allowed_while_killed_but_transfer_blocked(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        os.environ['BROKER_KILL_SWITCH'] = 'enabled'
        c = self.s.review({'client_id': 'cancel-kill', 'action': 'cancel_order', 'environment': 'production',
                           'account_id': '11111111-1111-4111-8111-111111111111', 'order_id': 'order-1'})
        self.assertEqual(self.s.confirm(self.approval(c))['state'], 'ACCEPTED')
        t = self.s.review(self.transfer())
        with self.assertRaises(BrokerError): self.s.confirm(self.approval(t))

    def test_presend_crash_recovery_never_sends_and_cleans_hold(self):
        for index, shared_state in enumerate(('RESERVED', 'SUBMITTING')):
            r = self.s.review(self.intent(client_id=f'crash-{index}'))
            self.s.save(r['id'], 'VALIDATING')
            self.admission.reserve('coinbase', 'production', ['11111111-1111-4111-8111-111111111111'], r['id'])
            if shared_state == 'SUBMITTING': self.admission.transition(r['id'], shared_state)
            self.assertEqual(self.new_service().reconcile(r['id'])['state'], 'REJECTED')
            self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
            self.assertFalse(self.holds()); self.assertFalse(self.fake.calls)

    def test_presend_recovery_racing_live_validation_cannot_send(self):
        r = self.s.review(self.intent())
        other = self.new_service()
        original = self.fake.available
        def recover(*args):
            self.assertEqual(other.reconcile(r['id'])['state'], 'REJECTED')
            return original(*args)
        self.fake.available = recover
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'REJECTED')
        self.assertFalse(self.fake.calls); self.assertFalse(self.holds())

    def test_completed_hold_leftover_recovered_and_overrun_visible(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        original = self.fake.detail
        self.fake.detail = lambda order: original(order) | {'status': 'FILLED', 'total_fees': '1', 'filled_value': '10'}
        with patch.object(self.admission, 'release', side_effect=OSError('crash')):
            with self.assertRaises(OSError): self.s.reconcile(r['id'])
        self.assertTrue(self.holds())
        result = self.new_service().reconcile(r['id'])
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertTrue(result['result']['fee_overrun']); self.assertTrue(result['result']['debit_overrun'])
        self.assertFalse(self.holds())

    def test_canonical_uuid_case_coordinates_shared_owners(self):
        account = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.admission.reserve('coinbase', 'production', [account.upper()], 'other')
        with self.assertRaises(AdmissionError): self.admission.reserve('coinbase', 'production', [account], 'second')

    def test_missing_actual_fees_does_not_release_hold(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        original = self.fake.detail
        self.fake.detail = lambda order: {k: v for k, v in (original(order) | {'status': 'FILLED'}).items() if k != 'total_fees'}
        self.assertEqual(self.s.reconcile(r['id'])['state'], 'ACCEPTED')
        self.assertTrue(self.holds())

    def test_partial_fill_cancel_preserves_original_actual_cost_evidence(self):
        r = self.s.review(self.intent()); self.s.confirm(self.approval(r))
        c = self.s.review({'client_id': 'cancel-partial', 'action': 'cancel_order', 'environment': 'production',
                           'account_id': '11111111-1111-4111-8111-111111111111', 'order_id': 'order-1'})
        self.s.confirm(self.approval(c))
        good = self.fake.detail
        self.fake.detail = lambda order: good(order) | {'status': 'CANCELLED', 'total_fees': '1', 'filled_value': '5'}
        child = self.s.reconcile(c['id']); parent = self.s.status(r['id'])
        self.assertEqual(child['state'], 'COMPLETED')
        self.assertEqual(child['result'], parent['result'])
        self.assertEqual(parent['result']['actual_debit'], '6')
        self.assertTrue(parent['result']['fee_overrun']); self.assertFalse(self.holds())

    def test_late_timeout_cannot_overwrite_concurrent_terminal_outcome(self):
        r = self.s.review(self.intent()); other = self.new_service()
        send = self.fake.submit
        def delayed(action, body):
            send(action, body)
            self.fake.status = 'FILLED'
            self.fake.history = [self.fake.detail('order-1')]
            self.assertEqual(other.reconcile(r['id'])['state'], 'COMPLETED')
            raise TimeoutError('SECRET')
        self.fake.submit = delayed
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'COMPLETED')
        self.assertEqual(self.s.status(r['id'])['result']['actual_fee'], '0.10')
        self.assertFalse(self.holds())

    def test_exception_outcome_cas_cannot_overwrite_reconciliation_between_checks(self):
        r = self.s.review(self.intent()); other = self.new_service()
        self.fake.failure = TimeoutError()
        original = self.s.save_outcome
        def interleave(action_id, state, result):
            self.fake.status = 'FILLED'; self.fake.history = [self.fake.detail('order-1')]
            self.assertEqual(other.reconcile(action_id)['state'], 'COMPLETED')
            return original(action_id, state, result)
        self.s.save_outcome = interleave
        self.assertEqual(self.s.confirm(self.approval(r))['state'], 'COMPLETED')
        self.assertFalse(self.holds())
        self.assertEqual(self.s.status(r['id'])['result']['actual_fee'], '0.10')

    def test_transfer_malformed_error_or_mismatched_success_retains_both_holds(self):
        for index, response in enumerate(({}, {'source_portfolio_uuid': 'other'},
                {'source_portfolio_uuid': '11111111-1111-4111-8111-111111111111',
                 'target_portfolio_uuid': '22222222-2222-4222-8222-222222222222', 'error': 'SECRET'})):
            r = self.s.review(self.transfer(client_id=f'transfer-bad-{index}'))
            self.fake.submit = lambda *_: response
            self.assertEqual(self.s.confirm(self.approval(r))['state'], 'UNKNOWN' if index == 0 else 'REJECTED')
            self.assertEqual(len(self.holds()), 2)
        self.assertNotIn('SECRET', self.s.status(r['id'])['summary'])

    def test_transfer_success_crash_before_result_commit_retains_both_locks(self):
        r = self.s.review(self.transfer())
        with patch.object(self.s, 'save_outcome', side_effect=SystemExit('crash')):
            with self.assertRaises(SystemExit): self.s.confirm(self.approval(r))
        self.assertEqual(self.new_service().reconcile(r['id'])['state'], 'SUBMITTING')
        self.assertEqual(len(self.holds()), 2)
        self.s.confirm(self.approval(r))
        self.assertEqual(len(self.fake.calls), 1)

    def test_transfer_success_crash_after_result_commit_recovers_release(self):
        r = self.s.review(self.transfer())
        with patch.object(self.admission, 'release', side_effect=SystemExit('crash')):
            with self.assertRaises(SystemExit): self.s.confirm(self.approval(r))
        self.assertEqual(len(self.holds()), 2)
        result = self.new_service().reconcile(r['id'])
        self.assertEqual(result['state'], 'COMPLETED'); self.assertFalse(self.holds())
        self.assertEqual(result['result']['request_digest'], r['digest'])


class TransportTests(unittest.TestCase):
    def adapter(self, *responses):
        opener = Mock()
        converted = []
        for response in responses:
            if isinstance(response, Exception): converted.append(response); continue
            stream = io.BytesIO(json.dumps(response).encode()); stream.status = 200; converted.append(stream)
        opener.open.side_effect = converted
        return CoinbaseAccess('organizations/test/apiKeys/test', 'fake', opener=opener, token_factory=lambda: 'SECRET')
    def test_exact_transfer_contract_and_no_redirects(self):
        a = self.adapter({'source_portfolio_uuid': 'a', 'target_portfolio_uuid': 'b'})
        body = {'source_portfolio_uuid': 'a', 'target_portfolio_uuid': 'b', 'funds': {'currency': 'USDC', 'value': '1'}}
        a.submit('internal_transfer', body)
        request = a.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.coinbase.com/api/v3/brokerage/portfolios/move_funds')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.data), body)
    def test_http_rejection_timeout_and_json_errors_are_redacted(self):
        body = io.BytesIO(b'SECRET')
        for error, code in ((HTTPError('SECRET', 403, 'SECRET', {}, body), 'rejected'), (URLError('SECRET'), 'uncertain')):
            with self.assertRaises(CoinbaseError) as caught: self.adapter(error).permissions()
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn('SECRET', str(caught.exception))
        self.assertTrue(body.closed)
    def test_orders_complete_pagination_and_account_binding(self):
        a = self.adapter({'orders': [], 'has_next': True, 'cursor': 'x'})
        with self.assertRaises(CoinbaseError): a.orders('a')
        a = self.adapter({'orders': [{'retail_portfolio_id': 'other'}], 'has_next': False})
        with self.assertRaises(CoinbaseError): a.orders('a')
    def test_jwt_binds_exact_method_and_path(self):
        a = self.adapter({})
        a._token = Mock(return_value='fake')
        a.submit('cancel_order', {'order_ids': ['order-1']})
        a._token.assert_called_once_with('POST', '/api/v3/brokerage/orders/batch_cancel')


class RouteTests(unittest.TestCase):
    def test_every_new_route_requires_gateway_auth(self):
        with patch.dict(os.environ, {'APP_ACCESS_TOKEN': 'x' * 32}, clear=True):
            for path in access_routes.ACCESS_ROUTES:
                handler = server.Handler.__new__(server.Handler); handler.path = path; handler.headers = Message()
                responses = []; handler.reply = lambda code, data: responses.append(code)
                with patch.object(server, 'access_request') as dispatch:
                    handler.do_POST(); dispatch.assert_not_called()
                self.assertEqual(responses, [401])
    def test_routes_reachable_and_webull_funding_explicitly_refused(self):
        with patch.object(access_routes, 'service') as factory:
            for operation, method in (('review', 'review'), ('confirm', 'confirm'), ('status', 'status'), ('reconcile', 'reconcile')):
                access_routes.access_request('/v1/coinbase/action/' + operation, {'id': 'saved'})
                self.assertTrue(getattr(factory.return_value, method).called)
            with self.assertRaisesRegex(BrokerError, 'Institutional Broker API'):
                access_routes.access_request('/v1/webull/transfer/review', {})
