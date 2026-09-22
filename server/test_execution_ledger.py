import sqlite3
import unittest

from execution_ledger import ExecutionLedger, ExecutionEvidenceError


class ExecutionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.ledger = ExecutionLedger(self.db, lambda: self.now)
        self.body = {'client_order_id': 'client-1', 'symbol': 'AAPL', 'side': 'BUY',
                     'quantity': '4', 'market': 'US', 'instrument_type': 'EQUITY',
                     'order_type': 'MARKET', 'time_in_force': 'DAY', 'entrust_type': 'QTY',
                     'support_trading_session': 'CORE'}
        self.ledger.register('sandbox', 'acct-1', self.body, 'order-1')

    def tearDown(self):
        self.db.close()

    def detail(self, **changes):
        result = {'client_order_id': 'client-1', 'order_id': 'order-1',
                  'symbol': 'AAPL', 'side': 'BUY', 'total_quantity': '4',
                  'instrument_type': 'EQUITY', 'order_type': 'MARKET',
                  'time_in_force': 'DAY', 'entrust_type': 'QTY',
                  'support_trading_session': 'CORE',
                  'status': 'PARTIAL_FILLED', 'filled_quantity': '2',
                  'filled_price': '10'}
        result.update(changes)
        return result

    def test_partial_then_filled_is_cumulative_and_repeat_does_not_double_count(self):
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
        self.now += 1
        filled = self.detail(status='FILLED', filled_quantity='4', filled_price='11')
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', filled))
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', filled))
        summary = self.ledger.summary('sandbox', 'acct-1')
        self.assertEqual(summary['orders'][0]['filled_quantity'], '4')
        self.assertEqual(summary['orders'][0]['average_fill_price'], '11')
        self.assertEqual(summary['orders'][0]['fill_notional'], '44')
        self.assertEqual(summary['totals']['notional_by_currency'], {'USD': {'buy': '44', 'sell': '0'}})
        self.assertEqual(summary['totals']['filled_orders'], 1)
        count = self.db.execute('SELECT count(*) FROM execution_evidence').fetchone()[0]
        self.assertEqual(count, 2)

    def test_mismatched_ids_and_order_identity_are_refused(self):
        for changes in ({'order_id': 'other'}, {'symbol': 'MSFT'}, {'side': 'SELL'},
                        {'total_quantity': '5'}):
            with self.subTest(changes=changes):
                self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail(**changes)))
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'wrong-client', self.detail()))
        self.assertEqual(self.ledger.summary('sandbox', 'acct-1')['orders'], [])

    def test_account_and_environment_are_separate(self):
        self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail())
        self.assertEqual(len(self.ledger.summary('sandbox', 'acct-1')['orders']), 1)
        self.assertEqual(self.ledger.summary('production', 'acct-1')['orders'], [])
        self.assertEqual(self.ledger.summary('sandbox', 'acct-2')['orders'], [])

    def test_quantity_bounds_decrease_and_same_quantity_price_conflict_are_refused(self):
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1',
                                               self.detail(filled_quantity='5')))
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1',
                                               self.detail(filled_quantity='1')))
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1',
                                               self.detail(filled_price='10.5')))
        self.assertEqual(self.ledger.summary('sandbox', 'acct-1')['orders'][0]['fill_notional'], '20')

    def test_missing_or_zero_price_cannot_establish_fill_evidence(self):
        for price in (None, '0', 'NaN'):
            detail = self.detail(filled_price=price)
            self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', detail))
        summary = self.ledger.summary('sandbox', 'acct-1')
        self.assertEqual(summary['orders'], [])
        self.assertFalse(summary['totals']['fees_known'])
        self.assertTrue(any('fees' in warning.lower() for warning in summary['warnings']))

    def test_fill_state_and_quantity_must_agree(self):
        invalid = (
            self.detail(status='FILLED', filled_quantity='3'),
            self.detail(status='PARTIAL_FILLED', filled_quantity='0', filled_price=None),
            self.detail(status='PARTIAL_FILLED', filled_quantity='4'),
            self.detail(status='SUBMITTED', filled_quantity='1'),
            self.detail(status='PENDING', filled_quantity='1'),
        )
        for detail in invalid:
            with self.subTest(detail=detail):
                self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', detail))
        self.assertEqual(self.ledger.summary('sandbox', 'acct-1')['orders'], [])

    def test_verified_terms_are_durable_and_conflicting_reregistration_is_refused(self):
        for changes in ({'order_type': 'LIMIT', 'limit_price': '10'}, {'time_in_force': 'GTC'},
                        {'instrument_type': 'OPTION'}, {'support_trading_session': 'ALL'}):
            with self.subTest(changes=changes), self.assertRaises(ExecutionEvidenceError):
                self.ledger.register('sandbox', 'acct-1', {**self.body, **changes}, 'order-1')
        self.ledger = ExecutionLedger(self.db, lambda: self.now)
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail(order_type='LIMIT')))
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))

    def test_limit_detail_requires_exact_reviewed_limit(self):
        body = {**self.body, 'client_order_id': 'limit-client', 'order_type': 'LIMIT', 'limit_price': '10.00'}
        self.ledger.register('sandbox', 'acct-1', body, 'limit-order')
        candidate = self.detail(client_order_id='limit-client', order_id='limit-order', order_type='LIMIT')
        for limit in (None, '10.01', '0', 'NaN'):
            with self.subTest(limit=limit):
                self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'limit-client', {**candidate, 'limit_price': limit}))
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'limit-client', {**candidate, 'limit_price': '10'}))

    def test_optional_fields_may_be_absent_but_supplied_conflicts_are_refused(self):
        candidate = self.detail()
        candidate.pop('instrument_type')
        candidate.pop('support_trading_session')
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', candidate))
        for change in ({'instrument_type': 'CRYPTO'}, {'market': 'HK'}, {'limit_price': '100'}):
            with self.subTest(change=change):
                self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', {**candidate, **change}))
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_evidence').fetchone()[0], 1)

    def test_more_fills_cannot_decrease_cumulative_notional(self):
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
        for price in ('5', '6'):
            self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1',
                                                  self.detail(filled_quantity='3', filled_price=price)))
        self.assertEqual(self.ledger.summary('sandbox', 'acct-1')['orders'][0]['fill_notional'], '20')
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_evidence').fetchone()[0], 1)

    def test_missing_and_malformed_fills_do_not_change_verified_evidence(self):
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
        original = tuple(self.db.execute('SELECT * FROM execution_evidence').fetchone())
        for change in ({'filled_quantity': None}, {'filled_price': None}, {'filled_price': 'NaN'},
                       {'filled_quantity': '0', 'filled_price': '100', 'status': 'CANCELLED'}):
            self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail(**change)))
        self.assertEqual(tuple(self.db.execute('SELECT * FROM execution_evidence').fetchone()), original)
        self.assertEqual(self.db.execute('SELECT count(*) FROM execution_evidence').fetchone()[0], 1)

    def test_cancelled_partial_fill_remains_evidence_and_terminal_cannot_regress(self):
        candidate = self.detail(status='CANCELLED')
        self.assertTrue(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', candidate))
        self.assertFalse(self.ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
        summary = self.ledger.summary('sandbox', 'acct-1')
        self.assertEqual(summary['orders'][0]['state'], 'CANCELLED')
        self.assertEqual(summary['totals']['partial_orders'], 1)
        self.assertEqual(summary['totals']['notional_by_currency']['USD']['buy'], '20')

    def test_old_database_observations_are_excluded_until_reverified(self):
        legacy = sqlite3.connect(':memory:')
        legacy.row_factory = sqlite3.Row
        legacy.executescript("""
            CREATE TABLE execution_tracked (
                environment TEXT, account_id TEXT, client_order_id TEXT, order_id TEXT,
                symbol TEXT, side TEXT, ordered_quantity TEXT, currency TEXT, registered_at REAL,
                PRIMARY KEY(environment,account_id,client_order_id),
                UNIQUE(environment,account_id,order_id));
            CREATE TABLE execution_latest (
                environment TEXT, account_id TEXT, client_order_id TEXT, order_id TEXT,
                state TEXT, filled_quantity TEXT, average_fill_price TEXT, fill_notional TEXT, updated_at REAL,
                PRIMARY KEY(environment,account_id,client_order_id));
            INSERT INTO execution_tracked VALUES
                ('sandbox','acct-1','client-1','order-1','AAPL','BUY','4','USD',900);
            INSERT INTO execution_latest VALUES
                ('sandbox','acct-1','client-1','order-1','PARTIAL_FILLED','2','10','20',900);
        """)
        try:
            ledger = ExecutionLedger(legacy, lambda: self.now)
            summary = ledger.summary('sandbox', 'acct-1')
            self.assertEqual(summary['orders'], [])
            self.assertTrue(any('excluded' in warning for warning in summary['warnings']))
            ledger.register('sandbox', 'acct-1', self.body, 'order-1')
            self.assertEqual(ledger.summary('sandbox', 'acct-1')['orders'], [])
            self.assertTrue(ledger.reconcile('sandbox', 'acct-1', 'client-1', self.detail()))
            self.assertEqual(ledger.summary('sandbox', 'acct-1')['orders'][0]['fill_notional'], '20')
        finally:
            legacy.close()


if __name__ == '__main__':
    unittest.main()
