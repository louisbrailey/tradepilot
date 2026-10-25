import copy
import unittest
from strategies import compare_strategies, signal, simulate_strategy


def bars(prices):
    return [dict(t=1609459200000+i*86400000, o=p, h=p, l=p, c=p) for i,p in enumerate(prices)]


class StrategiesTests(unittest.TestCase):
    def test_hand_calculated_one_day_and_cost(self):
        data = bars(list(range(51,101)) + [110])
        data[-1].update(o=100, l=100)
        for cost in (0,10,25,50):
            result = simulate_strategy(data, 'trend_sma_20_50', 50,51,cost)
            expected = 10000/(100*(1+cost/10000))*110*(1-cost/10000)
            self.assertAlmostEqual(result['ending_equity'], expected)
            self.assertEqual(result['fills'], 2)
            self.assertAlmostEqual(result['return_pct'],result['benchmark_price_return_pct'])

    def test_drawdown_and_exit_accounting(self):
        data = bars(list(range(51,101)) + [110,90])
        result = simulate_strategy(data,'trend_sma_20_50',50,52,0)
        self.assertAlmostEqual(result['ending_equity'],10000*90/110)
        self.assertAlmostEqual(result['max_drawdown_pct'],100*(1-90/110))

    def test_signal_has_no_future_access(self):
        data = bars(list(range(100,300)))
        changed = copy.deepcopy(data)
        for row in changed[120:]: row.update(o=1,h=1,l=1,c=1)
        for name in ('trend_sma_20_50','breakout_20','mean_reversion_20'):
            for holding in (False,True):
                self.assertEqual(signal(data,120,name,holding),signal(changed,120,name,holding))
            self.assertEqual(simulate_strategy(data,name,100,120),simulate_strategy(changed,name,100,120))

    def test_breakout_excludes_signal_from_reference(self):
        data = bars([100]*49+[101,100])
        self.assertTrue(signal(data,50,'breakout_20',False))
        data[49]['c']=99
        self.assertFalse(signal(data,50,'breakout_20',True))

    def test_mean_reversion_entry_and_exit(self):
        data = bars([100]*49+[97,100])
        self.assertTrue(signal(data,50,'mean_reversion_20',False))
        self.assertTrue(signal(data,50,'mean_reversion_20',True))
        data[49]['c']=101
        self.assertFalse(signal(data,50,'mean_reversion_20',True))

    def test_cost_monotonic_and_cash_behavior(self):
        data=bars(list(range(100,300)))
        returns=[simulate_strategy(data,'trend_sma_20_50',120,160,c)['return_pct'] for c in (0,10,25,50)]
        self.assertEqual(returns, sorted(returns,reverse=True))
        result=simulate_strategy(bars([100]*200),'trend_sma_20_50',120,160,50)
        self.assertEqual((result['return_pct'],result['fills'],result['max_drawdown_pct']),(0,0,0))

    def test_schema_chronology_and_validation(self):
        data=bars(list(range(100,300)))
        result=compare_strategies(data)
        self.assertEqual(result['stages']['validation']['start_index'],120)
        self.assertEqual(result['stages']['final']['start_index'],160)
        self.assertEqual(len(result['strategies']),3)
        self.assertEqual(result['evidence'],'exploratory_previously_observed')
        changed=copy.deepcopy(data); changed[0]['c']=True
        with self.assertRaises(ValueError):compare_strategies(changed)
        with self.assertRaises(ValueError):compare_strategies(data[:100])
        changed=copy.deepcopy(data); changed[1]['t']=changed[0]['t']
        with self.assertRaises(ValueError):compare_strategies(changed)

    def test_future_final_cannot_change_validation(self):
        data=bars(list(range(100,300)))
        changed=copy.deepcopy(data)
        for row in changed[160:]:row.update(o=1,h=1,l=1,c=1)
        a,b=compare_strategies(data),compare_strategies(changed)
        for left,right in zip(a['strategies'],b['strategies']):
            self.assertEqual(left['validation'],right['validation'])

if __name__=='__main__':unittest.main()
