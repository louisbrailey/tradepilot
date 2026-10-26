import concurrent.futures
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from paper_service import PaperService


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'paper.sqlite'
        self.now = 1700000000.0
        self.service = PaperService(self.path, clock=lambda: self.now)

    def quote(self, price='100', symbol='AAPL', age=0):
        return dict(symbol=symbol, price=price, as_of=self.now-age, source='fixture daily close', delayed=True)

    def review(self, side='buy', quantity='3', client='request_001', **kwargs):
        return self.service.create_review(dict(symbol='AAPL', side=side, quantity=quantity, client_id=client), self.quote(**kwargs))

    def approve(self, review, service=None):
        return (service or self.service).confirm(dict(id=review['id'], token=review['token'], approved=True))

    def test_initial_and_roundtrip_decimal_accounting_survives_restart(self):
        self.assertEqual(self.service.state()['cash'], '10000')
        buy = self.approve(self.review())
        self.assertEqual(Decimal(buy['cash_after']), Decimal('9699.700'))
        self.assertNotIn('token', buy)
        self.service = PaperService(self.path, clock=lambda: self.now)
        self.now += 1
        self.approve(self.review(side='sell', quantity='1', client='request_002', price='110'))
        state = self.service.state()
        self.assertEqual(Decimal(state['cash']), Decimal('9809.590'))
        self.assertEqual(Decimal(state['realized_pnl']), Decimal('9.790'))
        self.assertEqual(Decimal(state['positions'][0]['quantity']), Decimal('2'))
        self.assertEqual(Decimal(state['positions'][0]['cost_basis']), Decimal('200.200'))
        self.assertEqual(len(state['orders']), 2)

    def test_duplicate_confirmation_is_concurrent_and_durable(self):
        review = self.review()
        services = [PaperService(self.path, clock=lambda: self.now) for _ in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda s: self.approve(review, s), services))
        self.assertTrue(all(r == results[0] for r in results))
        state = self.service.state()
        self.assertEqual(len(state['orders']), 1)
        self.assertEqual(len([e for e in state['journal'] if e['kind'] == 'simulated_fill']), 1)
        self.assertEqual(self.approve(review, PaperService(self.path)), results[0])

    def test_review_retry_preserves_price_token_expiry(self):
        first = self.review()
        self.now += 999999
        self.assertEqual(self.review(price='999'), first)
        with self.assertRaises(ValueError):
            self.review(quantity='4')

    def test_confirmed_client_id_cannot_reopen_as_new_review(self):
        self.approve(self.review())
        with self.assertRaisesRegex(ValueError, 'already confirmed'):
            self.review()
        self.assertEqual(len(self.service.state()['orders']), 1)

    def test_expiry_approval_and_immutable_confirmation(self):
        review = self.review()
        for extra in ({'approved': False}, {'token': 'wrong'}, {'quantity': '100'}):
            payload = dict(id=review['id'], token=review['token'], approved=True)
            payload.update(extra)
            with self.assertRaises(ValueError):
                self.service.confirm(payload)
        self.now += 300
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.approve(review)
        state = self.service.state()
        self.assertEqual(state['cash'], '10000')
        self.assertEqual(state['reviews'][0]['status'], 'EXPIRED')
        self.assertEqual(state['journal'][0]['kind'], 'rejected')

    def test_reject_overspend_oversell_and_concurrent_budget(self):
        with self.assertRaisesRegex(ValueError, 'holdings'):
            self.approve(self.review(side='sell'))
        reviews = [self.review(quantity='60', client='request_%03d' % n) for n in (2,3)]
        def confirm(review):
            try:
                self.approve(review, PaperService(self.path, clock=lambda: self.now))
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(confirm, reviews)), 1)
        self.assertEqual(Decimal(self.service.state()['cash']), Decimal('3994'))

    def test_numeric_and_quote_validation(self):
        for n in ('NaN','Infinity','-1','0','1e2','1.000000001','1000000001',True,1):
            with self.subTest(n=n), self.assertRaises(ValueError):
                self.review(quantity=n)
        payload = dict(symbol='AAPL',side='buy',quantity='1',client_id='valid_001')
        for update in ({'as_of':self.now+1},{'as_of':self.now-96*3600-1},{'as_of':True},{'as_of':float('nan')},{'symbol':'MSFT'},{'price':'NaN'},{'source':''},{'delayed':'true'}):
            quote = self.quote(); quote.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.service.create_review(payload,quote)
        payload['price'] = '0.01'
        with self.assertRaises(ValueError):
            self.service.create_review(payload,self.quote())

    def test_marking_complete_atomic_monotonic_and_drawdown(self):
        self.approve(self.review())
        before = self.service.state()
        with self.assertRaises(ValueError):
            self.service.mark_quotes([])
        with self.assertRaises(ValueError):
            self.service.mark_quotes([self.quote(price='90')])
        self.assertEqual(self.service.state(), before)
        self.now += 86400
        state = self.service.mark_quotes([self.quote(price='90')])
        self.assertEqual(Decimal(state['equity']), Decimal('9969.7'))
        self.assertEqual(Decimal(state['max_drawdown']), Decimal('0.00303'))
        self.assertEqual(Decimal(state['positions'][0]['unrealized_pnl']), Decimal('-30.3'))
        self.assertEqual(len(state['valuations']), 2)
        with self.assertRaises(ValueError):
            self.service.mark_quotes([self.quote(age=1)])
        with self.assertRaises(ValueError):
            self.service.mark_quotes([self.quote(),self.quote()])
        self.assertEqual(self.service.state(), state)

    def test_old_review_cannot_overwrite_newer_mark(self):
        self.approve(self.review())
        old = self.review(client='request_002')
        self.now += 1
        self.service.mark_quotes([self.quote(price='101')])
        with self.assertRaisesRegex(ValueError,'older'):
            self.approve(old)
        self.assertEqual(self.service.state()['positions'][0]['reference_price'], '101')

    def test_marks_rollback_all_holdings_if_later_quote_invalid(self):
        self.approve(self.review())
        msft = self.service.create_review(dict(symbol='MSFT',side='buy',quantity='1',client_id='request_msft'), self.quote(symbol='MSFT'))
        self.approve(msft)
        before = self.service.state()
        self.now += 1
        with self.assertRaises(ValueError):
            self.service.mark_quotes([self.quote(price='101'), self.quote(symbol='MSFT',age=1000000)])
        self.assertEqual(self.service.state(), before)

    def test_concurrent_review_retry_and_nonascii_token(self):
        payload = dict(symbol='AAPL',side='buy',quantity='1',client_id='same_request')
        services = [PaperService(self.path, clock=lambda: self.now) for _ in range(4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            reviews = list(pool.map(lambda service: service.create_review(payload,self.quote()),services))
        self.assertTrue(all(r == reviews[0] for r in reviews))
        self.assertEqual(len(self.service.state()['reviews']),1)
        with self.assertRaises(ValueError):
            self.service.confirm(dict(id=reviews[0]['id'],token='é',approved=True))

    def test_fractional_close_and_notes(self):
        self.approve(self.review(quantity='0.12345678'))
        self.approve(self.review(side='sell',quantity='0.12345678',client='request_002'))
        self.assertEqual(self.service.state()['positions'], [])
        note = self.service.add_note({'text':'  Test thesis  '})
        self.assertEqual(note['data']['text'], 'Test thesis')
        self.assertEqual(PaperService(self.path).state()['journal'][0],note)
        for payload in ({'text':''},{'text':'x'*4001},{'text':'ok','cash':'100000'}):
            with self.assertRaises(ValueError):
                self.service.add_note(payload)


if __name__ == '__main__':
    unittest.main()
