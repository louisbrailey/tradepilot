"""Fixed daily long/cash experiments; never trading instructions or promotion."""
import hashlib
import json
from datetime import datetime, timezone
from research import validated_daily_bars

VERSION = 'daily-comparison-v1'
RULES = {
    'trend_sma_20_50': 'Long when prior 20-close mean exceeds prior 50-close mean; otherwise cash.',
    'breakout_20': 'Enter when prior close exceeds the preceding 20 closes (excluding signal close); exit below their minimum; otherwise retain position.',
    'mean_reversion_20': 'Enter when prior close is at least 2% below prior 20-close mean; exit when prior close reaches that mean; otherwise retain position.',
}
COSTS = (0, 10, 25, 50)
SCOPE = ('Exploratory comparison of already-observed history, not unseen evidence. Fixed rules; no selection or tuning. '
         'Independent $10,000 fractional long/cash portfolios per stage. Prior-bar signals, next-open fills, final-close liquidation. '
         'Price returns only; no dividends, taxes, cash interest, market impact, shorts, options, FX, crypto, intraday or news strategy modeling.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def signal(bars, index, strategy, holding):
    if strategy not in RULES or index < 50 or index > len(bars):
        raise ValueError('Invalid signal parameters')
    closes = [row['c'] for row in bars[index-50:index]]
    prior = closes[-1]
    mean20 = sum(closes[-20:]) / 20
    if strategy == 'trend_sma_20_50':
        return mean20 > sum(closes) / 50
    if strategy == 'breakout_20':
        reference = closes[-21:-1]
        return prior >= min(reference) if holding else prior > max(reference)
    return prior < mean20 if holding else prior <= mean20 * .98


def simulate_strategy(bars, strategy, start, stop, cost_bps=10):
    if strategy not in RULES or not (50 <= start < stop <= len(bars)) or cost_bps not in COSTS:
        raise ValueError('Invalid simulation parameters')
    cash, shares, peak, drawdown, fills = 10000., 0., 10000., 0., 0
    cost = cost_bps / 10000
    benchmark_shares = 10000 / (bars[start]['o'] * (1 + cost))
    benchmark_peak, benchmark_drawdown = 10000., 0.
    for index in range(start, stop):
        wants_long = signal(bars, index, strategy, shares > 0)
        opening = bars[index]['o']
        if wants_long and shares == 0:
            shares, cash = cash / (opening * (1 + cost)), 0.
            fills += 1
        elif not wants_long and shares > 0:
            cash, shares = shares * opening * (1 - cost), 0.
            fills += 1
        equity = cash + shares * bars[index]['c']
        peak = max(peak, equity)
        drawdown = max(drawdown, 1 - equity / peak)
        benchmark_equity = benchmark_shares * bars[index]['c']
        benchmark_peak = max(benchmark_peak, benchmark_equity)
        benchmark_drawdown = max(benchmark_drawdown, 1 - benchmark_equity / benchmark_peak)
    if shares:
        cash = shares * bars[stop-1]['c'] * (1 - cost)
        fills += 1
        drawdown = max(drawdown, 1 - cash / peak)
    benchmark_cash = benchmark_shares * bars[stop-1]['c'] * (1 - cost)
    benchmark_drawdown = max(benchmark_drawdown, 1 - benchmark_cash / benchmark_peak)
    result = {'return_pct': (cash / 10000 - 1) * 100, 'max_drawdown_pct': drawdown * 100,
              'fills': fills, 'ending_equity': cash, 'benchmark_price_return_pct': (benchmark_cash / 10000 - 1) * 100,
              'benchmark_max_drawdown_pct': benchmark_drawdown * 100}
    result['excess_return_pct'] = result['return_pct'] - result['benchmark_price_return_pct']
    return result


def compare_strategies(rows):
    bars = validated_daily_bars(rows, minimum=160, require_ohlc=True)
    boundaries = {'validation': (len(bars)*3//5, len(bars)*4//5), 'final': (len(bars)*4//5, len(bars))}
    day = lambda index: datetime.fromtimestamp(bars[index]['t']/1000, timezone.utc).date().isoformat()
    stages = {name: {'start_index': start, 'stop_index_exclusive': stop,
                     'start_date': day(start), 'end_date': day(stop-1)} for name, (start, stop) in boundaries.items()}
    strategies = []
    for name, rule in RULES.items():
        item = {'strategy': name, 'version': '1', 'rule': rule}
        for stage, (start, stop) in boundaries.items():
            costs = {str(cost): simulate_strategy(bars, name, start, stop, cost) for cost in COSTS}
            item[stage] = {'baseline': costs['10'], 'cost_scenarios': costs}
        strategies.append(item)
    return {'version': VERSION, 'evidence': 'exploratory_previously_observed', 'scope': SCOPE,
            'bars': len(bars), 'input_sha256': digest(bars), 'stages': stages, 'strategies': strategies}
