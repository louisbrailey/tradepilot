import concurrent.futures
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import uuid

from paper_automation import AutomationService, AutomationMarket, MarketUnavailable, checked_bars, start_worker
from paper_calendar import ET, history_days, next_session, session
from strategies import RULES


def epoch(day, hour=21, minute=0):
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=ET).timestamp()


def bars(day, drop=False):
    result = []
    for d in history_days(day):
        # Date-based prices keep overlap immutable as the window advances.
        price = 100 + (date.fromisoformat(d) - date(2026, 1, 1)).days
        if drop and d == day.isoformat(): price = 1
        result.append(dict(t=epoch(d, 0)*1000, o=price, c=price, h=price+1, l=max(.5, price-1), v=1000000))
    return result


class PaperAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'auto.sqlite3'
        self.now = epoch('2026-11-05')
        self.market = Mock()
        self.market.fetch.side_effect = bars
        self.service = AutomationService(self.path, self.market, lambda: self.now)
        self.payload = dict(client_id=str(uuid.uuid4()), approved=True)

    def start(self): return self.service.start(self.payload)
    def trend(self, state=None):
        return next(r for r in (state or self.service.state())['runs'] if r['strategy'] == 'trend_sma_20_50')

    def test_new_group_is_idempotent_approved_and_isolated(self):
        with self.assertRaises(ValueError): self.service.start({**self.payload, 'approved': False})
        with self.assertRaises(ValueError): self.service.start({**self.payload, 'price': '1'})
        first = self.start()
        self.assertEqual(len(first['runs']), 3)
        self.assertEqual({r['strategy'] for r in first['runs']}, set(RULES))
        self.assertEqual({r['cash'] for r in first['runs']}, {'10000'})
        self.assertEqual([r['id'] for r in first['runs']], [r['id'] for r in self.start()['runs']])
        self.market.fetch.assert_not_called()
        self.assertFalse((self.path.parent/'paper.sqlite3').exists())
        with self.assertRaises(ValueError): self.service.start(dict(client_id=str(uuid.uuid4()), approved=True))

    def test_forward_signal_then_next_session_fill_no_same_day_lookahead(self):
        self.start()
        one = self.trend(self.service.tick())
        self.assertEqual(one['fills'], 0)
        self.assertEqual(one['observations'], 1)
        self.assertTrue(one['pending']['long'])
        self.assertEqual(one['pending']['session'], '2026-11-06')
        self.service.tick()
        self.market.fetch.assert_called_once()  # one per date, shared across strategies
        self.now = epoch('2026-11-06')
        two = self.trend(self.service.tick())
        from decimal import Decimal
        self.assertEqual(two['fills'], 1)
        self.assertGreater(Decimal(two['quantity']), 0)
        self.assertGreaterEqual(Decimal(two['cash']), Decimal('7500'))
        self.assertEqual(Decimal(two['realized']), 0)
        self.assertEqual(Decimal(two['cash']) + Decimal(two['basis']), 10000)
        self.assertGreater(Decimal(two['costs']), 0)
        with self.service.db() as db:
            evidence = json.loads(db.execute('SELECT evidence FROM automation_days WHERE run_id=? AND day=?', (two['id'], '2026-11-06')).fetchone()[0])
        self.assertLess(evidence['consumed_decision']['recorded_at'], epoch('2026-11-06',0))
        self.assertEqual(evidence['fill']['side'], 'buy')

    def test_next_bar_cannot_change_saved_decision_and_drawdown_stops(self):
        self.start(); self.service.tick()
        self.now = epoch('2026-11-06'); self.service.tick()
        self.now = epoch('2026-11-09')
        self.market.fetch.side_effect = lambda d: bars(d, drop=True)
        run = self.trend(self.service.tick())
        self.assertEqual(run['status'], 'risk_paused')
        self.assertIsNone(run['pending'])
        self.assertEqual(run['fills'], 1)  # halt preserves holding; no invented stop-loss liquidation
        self.assertNotEqual(run['quantity'], '0')

    def test_costed_exit_realized_cash_and_no_short(self):
        self.start(); self.service.tick()
        self.now = epoch('2026-11-06'); self.service.tick()
        self.now = epoch('2026-11-09')
        with patch('paper_automation.signal', return_value=False): self.service.tick()
        self.now = epoch('2026-11-10'); run = self.trend(self.service.tick())
        self.assertEqual(run['quantity'], '0')
        self.assertEqual(run['fills'], 2)
        from decimal import Decimal
        self.assertEqual(Decimal(run['cash']) - 10000, Decimal(run['realized']))
        self.assertEqual(run['cash'], run['equity'])

    def test_no_processing_before_schedule_and_holiday_calendar_dst(self):
        self.start(); self.now = epoch('2026-11-05',20,14); self.service.tick()
        self.market.fetch.assert_not_called()
        self.now = epoch('2026-11-05',20,15); self.service.tick()
        self.market.fetch.assert_called_once()
        self.assertEqual(next_session(date(2026,11,25)),date(2026,11,27))
        self.assertEqual(next_session(date(2026,12,24)),date(2026,12,28))
        self.assertEqual(next_session(date(2027,12,31)),date(2028,1,3))
        self.assertEqual(datetime.fromtimestamp(epoch('2026-11-02'),ET).utcoffset().total_seconds(),-18000)
        with self.assertRaises(ValueError): session(date(2029,1,1))

    def test_missing_session_stops_without_retroactive_fill(self):
        self.start(); self.service.tick()
        self.now = epoch('2026-11-09')
        run = self.trend(self.service.tick())
        self.assertEqual(run['status'],'data_hold')
        self.assertEqual(run['fills'],0)
        self.assertIsNone(run['pending'])
        self.market.fetch.assert_called_once()

    def test_market_outage_retries_bounded_then_halts(self):
        self.start(); self.market.fetch.side_effect = MarketUnavailable('Unavailable')
        self.assertEqual(self.trend(self.service.tick())['status'],'waiting_data')
        self.service.tick(); self.market.fetch.assert_called_once()
        self.now += 901; self.market.fetch.side_effect = bars
        self.assertEqual(self.trend(self.service.tick())['observations'],1)
        self.now = epoch('2026-11-06'); self.market.fetch.side_effect = MarketUnavailable('Unavailable')
        self.service.tick(); self.now = epoch('2026-11-07',1)
        self.assertEqual(self.trend(self.service.tick())['status'],'data_hold')

    def test_bad_history_price_revision_and_split_checks_fail_closed(self):
        for mutation in ('missing','duplicate','future','no_volume','nan','timestamp'):
            values = bars(date(2026,11,5))
            if mutation == 'missing': values.pop(10)
            if mutation == 'duplicate': values[10] = values[9]
            if mutation == 'future': values[-1]['t'] += 86400000
            if mutation == 'no_volume': values[-1].pop('v')
            if mutation == 'nan': values[-1]['c'] = float('nan')
            if mutation == 'timestamp': values[-1]['t'] += 1000
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): checked_bars(values,date(2026,11,5))
        self.start(); self.service.tick(); self.now = epoch('2026-11-06')
        def revised(d):
            values = bars(d); values[20]['c'] += .5; return values
        self.market.fetch.side_effect = revised
        self.assertEqual(self.trend(self.service.tick())['status'],'data_hold')
        self.assertEqual(self.trend()['fills'],0)
        for response in ({'available':True,'partial_page':True,'results':[]}, {'available':True,'results':[{}]}):
            with patch('paper_automation.Massive') as client:
                client.return_value.get.side_effect = [{'available':True,'ticker':'SPY','adjusted':False,'results':bars(date(2026,11,5))},response]
                with self.assertRaises(ValueError): AutomationMarket().fetch(date(2026,11,5))

    def test_provider_identity_adjustment_and_requests_are_fixed(self):
        day = date(2026,11,5)
        for override in ({'ticker':'QQQ'}, {'adjusted':True}, {'partial_page':True}):
            with patch('paper_automation.Massive') as client:
                client.return_value.get.return_value = dict(available=True,ticker='SPY',adjusted=False,results=bars(day)) | override
                with self.assertRaises(ValueError): AutomationMarket().fetch(day)
        with patch('paper_automation.Massive') as client:
            client.return_value.get.side_effect = [dict(available=True,ticker='SPY',adjusted=False,results=bars(day)), dict(available=True,results=[])]
            self.assertEqual(AutomationMarket().fetch(day), bars(day))
            calls = client.return_value.get.call_args_list
            self.assertIn('/SPY/range/1/day/', calls[0].args[0])
            self.assertEqual(calls[0].args[1]['adjusted'], 'false')
            self.assertEqual(calls[1].args[0], '/stocks/v1/splits')
            self.assertEqual(calls[1].args[1]['execution_date.lte'], '2026-11-05')

    def test_pause_while_fetching_prevents_commit(self):
        self.start()
        def pause_fetch(d):
            self.service.pause({'id':'all'}); return bars(d)
        self.market.fetch.side_effect = pause_fetch
        result = self.service.tick()
        self.assertTrue(all(r['status']=='paused' and r['observations']==0 for r in result['runs']))

    def test_restart_and_concurrent_workers_cannot_duplicate_observations(self):
        self.start()
        def tick(): return AutomationService(self.path,self.market,lambda:self.now).tick()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: tick(),range(4)))
        self.assertTrue(all(r['observations']==1 for r in tick()['runs']))
        self.now = epoch('2026-11-06')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: tick(),range(4)))
        self.assertEqual(self.trend()['fills'],1)
        with self.service.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM automation_days').fetchone()[0],6)

    def test_request_crossing_midnight_and_implementation_change_halt(self):
        self.start()
        def late(d):
            self.now = epoch('2026-11-06',0); return bars(d)
        self.market.fetch.side_effect = late
        self.assertTrue(all(r['status']=='data_hold' for r in self.service.tick()['runs']))
        self.service.start(dict(client_id=str(uuid.uuid4()),approved=True))
        with patch('paper_automation.implementation_hash',return_value='changed'):
            self.assertTrue(all(r['status']=='data_hold' for r in self.service.tick()['runs']))

    def test_background_worker_and_state_do_not_depend_on_phone_polling(self):
        self.start()
        stopped, thread = start_worker(self.service,interval=.01)
        try:
            for _ in range(100):
                if self.trend()['observations']: break
                threading.Event().wait(.01)
            self.assertEqual(self.trend()['observations'],1)
            self.assertIsNotNone(self.service.state()['worker_checked_at'])
        finally:
            stopped.set(); thread.join(2)
        self.assertFalse(thread.is_alive())

if __name__ == '__main__': unittest.main()
