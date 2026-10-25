"""Local Kronos historical research. No broker access or order generation."""
import hashlib
import json
import math
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from research import Massive, validated_daily_bars

_LOCK = threading.Lock()
LOOKBACK = 128
MODEL = 'NeoQuasar/Kronos-small'
NOTICE = ('Historical replay, not a live forecast or trading strategy. Model training overlap is not verified. '
          'Sampling spread is not a calibrated confidence interval. Price error excludes fees and slippage; '
          'no profitability or order recommendation is implied.')


class KronosError(Exception):
    pass


def settings():
    home = Path(os.environ.get('KRONOS_HOME', str(Path.home() / 'my-stack/Kronos'))).expanduser()
    python = Path(os.environ.get('KRONOS_PYTHON', str(home / '.venv/bin/python'))).expanduser()
    return home, python


def status():
    home, python = settings()
    return {'configured': (home / 'model/kronos.py').is_file() and python.is_file(),
            'model': MODEL, 'mode': 'historical_replay', 'lookback': LOOKBACK,
            'horizons': [5, 20], 'notice': NOTICE,
            'configuration_only': True}


def fetch_bars(symbol):
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=400)
    try:
        source = Massive().get(f'/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}',
                               {'adjusted': 'true', 'sort': 'asc', 'limit': 50000})
        if (not source.get('available') or source.get('partial_page') or source.get('adjusted') is not True):
            raise ValueError('Incomplete adjusted history')
        raw = source.get('results')
        clean = validated_daily_bars(raw, minimum=LOOKBACK + 20, start=str(start), end=str(end), require_ohlc=True)
        for bar, original in zip(clean, raw):
            volume = original.get('v')
            if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume) or volume < 0:
                raise ValueError('Invalid volume')
            bar['v'] = volume
        return clean
    except Exception:
        raise KronosError('Complete adjusted daily OHLCV history is unavailable. Check the gateway market-data access.') from None


def infer(history, dates, samples):
    home, python = settings()
    if not status()['configured']:
        raise KronosError('Local Kronos runtime is missing. Configure KRONOS_HOME and KRONOS_PYTHON on the gateway.')
    # The model subprocess gets only public price bars, never gateway/broker credentials.
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'TMPDIR') if k in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false', PYTHONNOUSERSITE='1')
    try:
        run = subprocess.run([str(python), str(Path(__file__).with_name('kronos_worker.py')), str(home)],
            input=json.dumps({'history': history, 'dates': dates, 'samples': samples}),
            text=True, capture_output=True, timeout=90, env=env, cwd=home)
        if run.returncode:
            raise ValueError('Model process failed')
        result = json.loads(run.stdout)
        if not isinstance(result, dict) or len(result.get('paths', [])) != samples:
            raise ValueError('Bad model result')
        for path in result['paths']:
            if len(path) != len(dates) or any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0 for p in path):
                raise ValueError('Invalid predicted closes')
        return result
    except subprocess.TimeoutExpired:
        raise KronosError('Local model timed out. Try the 5-session horizon.') from None
    except Exception:
        raise KronosError('Local inference failed. Check the cached Kronos-small model and Python environment on the Mac.') from None


def replay(payload):
    if not isinstance(payload, dict) or set(payload) - {'ticker', 'horizon'}:
        raise ValueError('Expected ticker and horizon')
    symbol, horizon = payload.get('ticker'), payload.get('horizon', 5)
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', symbol):
        raise ValueError('Invalid ticker')
    if type(horizon) is not int or horizon not in (5, 20):
        raise ValueError('Invalid horizon')
    if not _LOCK.acquire(blocking=False):
        raise KronosError('Kronos is already running a forecast. Wait for it to finish.')
    try:
        bars = fetch_bars(symbol)
        history, actual = bars[-LOOKBACK-horizon:-horizon], bars[-horizon:]
        # No held-out prices or volumes cross this inference boundary.
        dates = [bar['t'] for bar in actual]
        output = infer(history, dates, 3)
        paths = output['paths']
        points = []
        last = history[-1]['c']
        for i, row in enumerate(actual):
            values = [path[i] for path in paths]
            points.append({'date': day(row['t']), 'actual': row['c'], 'predicted': sum(values)/len(values),
                           'low': min(values), 'high': max(values), 'baseline': last})
        mae = sum(abs(p['predicted'] - p['actual']) for p in points)/horizon
        baseline = sum(abs(p['baseline'] - p['actual']) for p in points)/horizon
        digest = hashlib.sha256(json.dumps({'ticker':symbol, 'bars':history+actual, 'model':MODEL, 'seed':42}, sort_keys=True).encode()).hexdigest()
        return {'id': digest, 'ticker': symbol, 'model': MODEL, 'mode':'historical_replay', 'source':'Massive adjusted daily OHLCV',
                'generated_at': time.time(), 'input_start':day(history[0]['t']), 'input_end':day(history[-1]['t']),
                'lookback': LOOKBACK, 'horizon':horizon, 'samples':3, 'seed':42, 'notice':NOTICE,
                'mae':mae, 'baseline_mae':baseline, 'points':points,
                'history':[{'date':day(b['t']), 'close':b['c']} for b in history[-30:]]}
    finally:
        _LOCK.release()


def day(timestamp):
    return datetime.fromtimestamp(timestamp/1000, timezone.utc).date().isoformat()


def request(path, payload):
    if path == '/v1/kronos/status':
        if payload != {}:
            raise ValueError('Expected empty status request')
        return status()
    return replay(payload)
