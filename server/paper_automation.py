"""Prospective scheduled PAPER portfolios. No broker adapter or order route.
Decisions are saved before the following daily bar begins. Settlement is a
later observation of that precommitted simulation, not a broker execution.
"""
from contextlib import contextmanager
from datetime import date, datetime, time as daytime
from decimal import Decimal, ROUND_DOWN, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from paper_calendar import ET, history_days, local_time, next_session, ready, session
from research import Massive, validated_daily_bars
from strategies import RULES, digest, signal

VERSION = 'prospective-paper-v1'
ACTIVE = ('running', 'waiting_data')
NOTICE = ('Paper only. Three independent $10,000 SPY experiments; not a profitable-strategy claim. '
          'Entry budget: at most 25% of prior equity and $2,500; exposure can drift after entry. '
          '10 bps per side. Daily-bar open/close references, not executable auction quotes. '
          'No dividends, interest, taxes, shorts or leverage. At 10% observed drawdown, pause with holdings retained. '
          'Missed sessions, changed source data and splits halt the run; no catch-up fills. '
          'The Mac must be awake. Manual paper and real accounts are separate.')


def implementation_hash():
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root / name).read_bytes() for name in
        ('paper_automation.py', 'paper_calendar.py', 'strategies.py', 'research.py'))).hexdigest()


def protocol(strategy):
    return dict(version=VERSION, implementation_sha256=implementation_hash(), symbol='SPY', strategy=strategy,
                rule=RULES[strategy], initial_cash='10000', entry_fraction='0.25', max_entry='2500',
                cost_bps=10, drawdown_stop='0.10', schedule='20:15 America/New_York on sessions; retry until midnight',
                fill_policy='Precommitted next daily-bar open; observed after that session', calendar='NYSE-2026-2028')


class MarketUnavailable(ValueError):
    pass


class AutomationMarket:
    """Fixed public-market GETs only. No access to any brokerage account."""
    def fetch(self, day):
        days = history_days(day)
        client = Massive()
        result = client.get(f'/v2/aggs/ticker/SPY/range/1/day/{days[0]}/{days[-1]}',
                            {'adjusted': 'false', 'sort': 'asc', 'limit': 50000})
        if result.get('available') is not True:
            raise MarketUnavailable('Daily data unavailable; retrying within this session window')
        if result.get('partial_page') or result.get('adjusted') is not False or result.get('ticker') != 'SPY':
            raise ValueError('Incomplete daily data, wrong symbol or unconfirmed adjustment basis')
        splits = client.get('/stocks/v1/splits', {'ticker': 'SPY', 'execution_date.gte': days[0],
                           'execution_date.lte': days[-1], 'limit': 1000})
        if splits.get('available') is not True:
            raise MarketUnavailable('Split checks unavailable; retrying within this session window')
        if splits.get('partial_page') or not isinstance(splits.get('results'), list) or splits['results']:
            raise ValueError('Split event or incomplete corporate-action coverage; start a new experiment after review')
        return result.get('results')


def checked_bars(rows, day):
    expected = history_days(day)
    clean = validated_daily_bars(rows, minimum=50, start=expected[0], end=expected[-1], require_ohlc=True)
    if any(not 1e-8 <= row[field] <= 1e9 for row in clean for field in ('o', 'h', 'l', 'c')):
        raise ValueError('Daily price outside supported simulation range')
    actual = []
    for source in rows:
        at = datetime.fromtimestamp(source['t'] / 1000, ET)
        if at.time() != daytime(0):
            raise ValueError('Daily bar must begin at midnight Eastern Time')
        volume = source.get('v')
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 < volume < 1e14:
            raise ValueError('Missing or invalid trading volume')
        actual.append(at.date().isoformat())
    if actual != expected:
        raise ValueError('Missing, extra or stale sessions; no forward fill or partial-history signals')
    return clean


class AutomationService:
    def __init__(self, path, market=None, clock=time.time):
        self.path, self.market, self.clock = str(path), market or AutomationMarket(), clock
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS automation_runs (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL, strategy TEXT NOT NULL,
                state TEXT NOT NULL, revision INTEGER NOT NULL, UNIQUE(client_id,strategy));
            CREATE TABLE IF NOT EXISTS automation_days (
                run_id TEXT NOT NULL, day TEXT NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(run_id,day));
            CREATE TABLE IF NOT EXISTS automation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, at REAL NOT NULL,
                kind TEXT NOT NULL, message TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS automation_worker (id INTEGER PRIMARY KEY CHECK(id=1), checked_at REAL NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, db, run, kind, message):
        db.execute('INSERT INTO automation_events(run_id,at,kind,message) VALUES(?,?,?,?)',
                   (run['id'], self.clock(), kind, message))

    def save(self, db, run):
        db.execute('UPDATE automation_runs SET state=?,revision=revision+1 WHERE id=?',
                   (json.dumps(run, sort_keys=True, allow_nan=False), run['id']))

    def start(self, payload):
        if (not isinstance(payload, dict) or set(payload) != {'client_id', 'approved'} or payload['approved'] is not True
                or not isinstance(payload['client_id'], str)):
            raise ValueError('Explicit approval of the fixed paper protocol is required')
        try:
            uuid.UUID(payload['client_id'])
        except (ValueError, AttributeError):
            raise ValueError('A UUID request identifier is required') from None
        now = self.clock()
        day = local_time(now).date()
        first = day if session(day) else next_session(day)
        history_days(first)  # fail closed if warm-up extends outside pinned calendar
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM automation_runs WHERE client_id=?', (payload['client_id'],)).fetchone():
                return self._state(db)
            rows = db.execute('SELECT state FROM automation_runs').fetchall()
            if any(json.loads(r['state'])['status'] in ACTIVE for r in rows):
                raise ValueError('Pause existing experiments before starting another group')
            if len(rows) >= 30:
                raise ValueError('Thirty preserved experiments reached; archive policy needs review before creating more')
            for strategy in RULES:
                spec = protocol(strategy)
                run = dict(id=str(uuid.uuid4()), strategy=strategy, symbol='SPY', status='running',
                           reason='Waiting for first completed-session observation; no prior trades backfilled',
                           created_at=now, protocol=spec, protocol_sha256=digest(spec),
                           cash='10000', quantity='0', basis='0', realized='0', equity='10000', peak='10000',
                           max_drawdown='0', costs='0', last_session=None, next_session=first.isoformat(),
                           pending=None, observations=0, fills=0, next_attempt=0, updated_at=now)
                db.execute('INSERT INTO automation_runs VALUES(?,?,?,?,0)',
                           (run['id'], payload['client_id'], strategy, json.dumps(run, sort_keys=True)))
                self.event(db, run, 'started', 'Approved fixed protocol ' + run['protocol_sha256'])
            return self._state(db)

    def pause(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'id'} or not isinstance(payload['id'], str):
            raise ValueError('Expected a saved experiment ID or all')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT state FROM automation_runs' + ('' if payload['id'] == 'all' else ' WHERE id=?'),
                              () if payload['id'] == 'all' else (payload['id'],)).fetchall()
            if not rows and payload['id'] != 'all':
                raise ValueError('Unknown experiment')
            for row in rows:
                run = json.loads(row['state'])
                if run['status'] in ACTIVE:
                    self.halt(db, run, 'paused', 'Stopped by user; pending simulation canceled, holdings retained without new marks')
            return self._state(db)

    def halt(self, db, run, status, reason):
        run.update(status=status, reason=reason, pending=None, updated_at=self.clock())
        self.save(db, run)
        self.event(db, run, status, reason)

    def _state(self, db):
        runs = []
        for row in db.execute('SELECT state FROM automation_runs ORDER BY rowid DESC'):
            run = json.loads(row['state'])
            run['events'] = [dict(e) for e in db.execute(
                'SELECT id,at,kind,message FROM automation_events WHERE run_id=? ORDER BY id DESC LIMIT 20', (run['id'],))]
            runs.append(run)
        worker = db.execute('SELECT checked_at FROM automation_worker WHERE id=1').fetchone()
        return dict(mode='automated_paper', version=VERSION, notice=NOTICE, runs=runs,
                    worker_checked_at=worker[0] if worker else None, checked_at=self.clock())

    def state(self):
        with self.db() as db:
            return self._state(db)

    def claim(self, run_id, now):
        """Short durable lease; no SQLite write lock is held over network IO."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM automation_runs WHERE id=?', (run_id,)).fetchone()
            run = json.loads(row['state'])
            if run['status'] not in ACTIVE:
                return None
            day = local_time(now).date()
            if run['protocol'] != protocol(run['strategy']):
                self.halt(db, run, 'data_hold', 'Implementation changed; preserve this experiment and start a new protocol')
                return None
            if run['next_session'] < day.isoformat():
                self.halt(db, run, 'data_hold', 'Missed scheduled session; no catch-up decisions or fills')
                return None
            if run['next_session'] != day.isoformat() or not ready(now) or run['next_attempt'] > now:
                return None
            run['next_attempt'] = now + 900
            self.save(db, run)
            return run, row['revision'] + 1

    def tick(self):
        now = self.clock()
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO automation_worker VALUES(1,?)', (now,))
            ids = [r[0] for r in db.execute('SELECT id FROM automation_runs')]
        cache = {}
        for run_id in ids:
            try:
                claimed = self.claim(run_id, now)
            except ValueError:
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    run = json.loads(db.execute('SELECT state FROM automation_runs WHERE id=?', (run_id,)).fetchone()[0])
                    if run['status'] in ACTIVE:
                        self.halt(db, run, 'data_hold', 'Calendar or protocol unavailable; operator review required')
                continue
            if not claimed:
                continue
            run, revision = claimed
            day = date.fromisoformat(run['next_session'])
            key = day.isoformat()
            if key not in cache:
                try:
                    raw = self.market.fetch(day)
                    cache[key] = checked_bars(raw, day)
                except MarketUnavailable as error:
                    cache[key] = error
                except ValueError as error:
                    cache[key] = ValueError(str(error))
                except Exception:
                    cache[key] = MarketUnavailable('Market-data request failed; retrying within this session window')
            with self.db() as db, localcontext() as ctx:
                ctx.prec = 40
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT revision FROM automation_runs WHERE id=?', (run_id,)).fetchone()[0]
                if current != revision:  # pause or another process won during the fetch
                    continue
                if local_time(self.clock()).date() != day or not ready(self.clock()):
                    self.halt(db, run, 'data_hold', 'Session window ended before data arrived; no late fill')
                    continue
                bars = cache[key]
                if isinstance(bars, MarketUnavailable):
                    run.update(status='waiting_data', reason=str(bars), updated_at=self.clock())
                    self.save(db, run)
                    self.event(db, run, 'waiting_data', str(bars))
                    continue
                if isinstance(bars, Exception):
                    self.halt(db, run, 'data_hold', str(bars))
                    continue
                try:
                    self.settle(db, run, bars, day)
                except ValueError as error:
                    self.halt(db, run, 'data_hold', str(error))
        return self.state()

    def settle(self, db, run, bars, day):
        if run['last_session']:
            previous = json.loads(db.execute('SELECT evidence FROM automation_days WHERE run_id=? AND day=?',
                                 (run['id'], run['last_session'])).fetchone()[0])
            old = {b['t']: b for b in previous['bars']}
            if any(b['t'] in old and b != old[b['t']] for b in bars):
                raise ValueError('Previously observed prices changed; preserved evidence cannot be rewritten')
        following = next_session(day).isoformat()  # calendar bound checked before ledger changes
        pending = run['pending']
        if pending and (pending['session'] != day.isoformat() or
                pending['recorded_at'] >= datetime.combine(day, daytime(0), ET).timestamp()):
            raise ValueError('Pending decision was not recorded before its execution session')
        opening, closing = (Decimal(str(bars[-1][f])) for f in ('o', 'c'))
        cash, qty, basis = (Decimal(run[f]) for f in ('cash', 'quantity', 'basis'))
        realized, costs = Decimal(run['realized']), Decimal(run['costs'])
        fill = None
        if pending:
            if pending['long'] and qty == 0:
                price = opening * Decimal('1.001')
                budget = min(cash, Decimal(pending['budget']))
                bought = (budget / price).quantize(Decimal('0.00000001'), rounding=ROUND_DOWN)
                if bought > 0:
                    qty, basis = bought, bought * price
                    cash -= basis
                    costs += qty * opening * Decimal('0.001')
                    fill = dict(side='buy', quantity=str(qty), price=str(price), notional=str(basis))
            elif not pending['long'] and qty > 0:
                price = opening * Decimal('0.999')
                proceeds = qty * price
                realized += proceeds - basis
                cash += proceeds
                costs += qty * opening * Decimal('0.001')
                fill = dict(side='sell', quantity=str(qty), price=str(price), notional=str(proceeds))
                qty, basis = Decimal(0), Decimal(0)
        equity = cash + qty * closing
        peak = max(Decimal(run['peak']), equity)
        drawdown = max(Decimal(run['max_drawdown']), 1 - equity / peak)
        stop = drawdown >= Decimal('0.10')
        wants_long = signal(bars, len(bars), run['strategy'], qty > 0)
        decision = None if stop else dict(long=wants_long, session=following, recorded_at=self.clock(),
                     budget=str(min(Decimal('2500'), equity * Decimal('0.25'))))
        run.update(cash=str(cash), quantity=str(qty), basis=str(basis), realized=str(realized), equity=str(equity),
                   peak=str(peak), max_drawdown=str(drawdown), costs=str(costs), last_session=day.isoformat(),
                   next_session=following, pending=decision, observations=run['observations'] + 1,
                   fills=run['fills'] + int(fill is not None), status='risk_paused' if stop else 'running',
                   reason='Drawdown limit reached; holdings retained without new marks' if stop else 'Session recorded; next decision saved',
                   updated_at=self.clock(), next_attempt=0)
        evidence = dict(protocol_sha256=run['protocol_sha256'], bars=bars, input_sha256=digest(bars),
                        recorded_at=self.clock(), consumed_decision=pending, fill=fill, decision=decision,
                        cash=run['cash'], quantity=run['quantity'], equity=run['equity'])
        db.execute('INSERT INTO automation_days VALUES(?,?,?)', (run['id'], day.isoformat(), json.dumps(evidence, sort_keys=True)))
        self.save(db, run)
        if fill:
            self.event(db, run, 'simulated_fill', f"{day}: {fill['side']} {fill['quantity']} SPY at {fill['price']} (daily reference + modeled costs)")
        self.event(db, run, 'risk_paused' if stop else 'decision', run['reason'] if stop else
                   f"{day}: {'long' if wants_long else 'cash'} for {following}; paper equity {equity}")


def start_worker(service, interval=60):
    stopped = threading.Event()
    def loop():
        while not stopped.is_set():
            try:
                service.tick()
            except Exception:
                # Never log payloads or credentials. A stale heartbeat is visible in the app.
                print('Paper scheduler cycle failed; saved state retained', flush=True)
            stopped.wait(interval)
    thread = threading.Thread(target=loop, name='paper-scheduler', daemon=True)
    thread.start()
    return stopped, thread
