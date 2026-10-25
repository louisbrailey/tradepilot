#!/usr/bin/env python3
"""Independent return recurrence reconciler; no use of strategy simulator/signals."""
import argparse
import json
from pathlib import Path
import math


def reconcile(rows, name, start, stop, cost_bps):
    closes=[row['c'] for row in rows]
    exposure=False
    equity=peak=10000.
    drawdown=0.
    fills=0
    cost=cost_bps/10000
    last_close=None
    for i in range(start,stop):
        history=closes[:i]
        prior=history[-1]
        mean20=math.fsum(history[-20:])/20
        if name=='trend_sma_20_50': target=mean20>math.fsum(history[-50:])/50
        elif name=='breakout_20':
            target=(prior>=min(history[-21:-1])) if exposure else (prior>max(history[-21:-1]))
        elif name=='mean_reversion_20':target=(prior<mean20) if exposure else (prior<=.98*mean20)
        else:raise ValueError(name)
        if exposure:equity*=rows[i]['o']/last_close
        if target!=exposure:
            equity*=1/(1+cost) if target else 1-cost
            fills+=1
        if target:equity*=closes[i]/rows[i]['o']
        peak=max(peak,equity)
        drawdown=max(drawdown,1-equity/peak)
        exposure=target
        last_close=closes[i]
    if exposure:
        equity*=1-cost
        fills+=1
        drawdown=max(drawdown,1-equity/peak)
    return equity,drawdown*100,fills


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache-dir',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    report=json.loads((root/'SUMMARY.json').read_text())
    maximum=0.
    checked=0
    for ticker,item in report['symbols'].items():
        source=item['source']
        path=Path(args.cache_dir)/f"{ticker}-{source['start']}-{source['end']}.json"
        rows=json.loads(path.read_text())['rows']
        comparison=item['comparison']
        for strategy in comparison['strategies']:
            for stage in ('validation','final'):
                period=comparison['stages'][stage]
                for cost,expected in strategy[stage]['cost_scenarios'].items():
                    cash,drawdown,fills=reconcile(rows,strategy['strategy'],period['start_index'],period['stop_index_exclusive'],int(cost))
                    differences=[abs((cash/10000-1)*100-expected['return_pct']),abs(drawdown-expected['max_drawdown_pct'])]
                    assert fills==expected['fills']
                    assert max(differences)<1e-9,(ticker,strategy['strategy'],stage,cost,differences)
                    maximum=max(maximum,*differences)
                    checked+=1
    result={'checked_runs':checked,'maximum_percentage_point_error':maximum,'method':'Independent overnight/open-close equity recurrence, separately calculated fixed signals, fills and closing drawdown; tolerance 1e-9 percentage points.'}
    (root/'INDEPENDENT-CHECK.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':main()
