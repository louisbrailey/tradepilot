"""Durable, explicitly approved reference-price simulation. Never contacts a broker."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
import uuid
from decimal import Decimal, InvalidOperation, localcontext

LABEL = 'Paper simulation at a delayed reference price; not a real execution'


def decimal(value, name, positive=True):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d{1,8})?', value) or len(value) > 32:
        raise ValueError(name + ' must be a decimal string with at most 8 decimal places')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError('Invalid ' + name)
    if not result.is_finite() or result > Decimal('1000000000') or (result <= 0 if positive else result < 0):
        raise ValueError('Invalid ' + name)
    return result


def number(value):
    return format(value, 'f')


class PaperService:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        with self._db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS paper_account (id INTEGER PRIMARY KEY CHECK(id=1), cash TEXT NOT NULL, realized TEXT NOT NULL);
            INSERT OR IGNORE INTO paper_account VALUES(1,'10000','0');
            CREATE TABLE IF NOT EXISTS paper_positions (symbol TEXT PRIMARY KEY, quantity TEXT NOT NULL, basis TEXT NOT NULL, price TEXT NOT NULL, as_of REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_reviews (id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL, review TEXT NOT NULL, receipt TEXT);
            CREATE TABLE IF NOT EXISTS paper_valuations (id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at REAL NOT NULL, as_of REAL, cash TEXT NOT NULL, equity TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS paper_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, at REAL NOT NULL, data TEXT NOT NULL);
            ''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _event(self, db, kind, data):
        at = self.clock()
        cursor = db.execute('INSERT INTO paper_journal(kind,at,data) VALUES(?,?,?)', (kind, at, json.dumps(data, sort_keys=True)))
        return dict(id=cursor.lastrowid, kind=kind, at=at, data=data)

    @staticmethod
    def _quote(quote, symbol, now):
        if not isinstance(quote, dict) or quote.get('symbol') != symbol:
            raise ValueError('Quote identity mismatch')
        price = decimal(quote.get('price'), 'reference price')
        as_of = quote.get('as_of')
        if isinstance(as_of, bool) or not isinstance(as_of, (int, float)) or not math.isfinite(as_of) or not 0 <= now - as_of <= 96 * 3600:
            raise ValueError('Reference price must be dated within the previous 96 hours')
        if not isinstance(quote.get('source'), str) or not 1 <= len(quote['source']) <= 200 or not isinstance(quote.get('delayed'), bool):
            raise ValueError('Reference provenance required')
        return price, as_of

    def _valuation(self, db):
        cash = Decimal(db.execute('SELECT cash FROM paper_account WHERE id=1').fetchone()[0])
        equity, dates = cash, []
        for row in db.execute('SELECT * FROM paper_positions'):
            if Decimal(row['quantity']) > 0:
                equity += Decimal(row['quantity']) * Decimal(row['price'])
                dates.append(row['as_of'])
        db.execute('INSERT INTO paper_valuations(recorded_at,as_of,cash,equity) VALUES(?,?,?,?)',
                   (self.clock(), min(dates) if dates else None, number(cash), number(equity)))

    def mark_quotes(self, quotes):
        if not isinstance(quotes, list):
            raise ValueError('A complete list of server quotes is required')
        with self._db() as db, localcontext() as ctx:
            ctx.prec = 50
            db.execute('BEGIN IMMEDIATE')
            held = {r['symbol']: r for r in db.execute('SELECT * FROM paper_positions') if Decimal(r['quantity']) > 0}
            if len(quotes) != len(held) or any(not isinstance(q, dict) or not isinstance(q.get('symbol'), str) for q in quotes):
                raise ValueError('Every holding must have exactly one reference quote')
            if {q['symbol'] for q in quotes} != set(held):
                raise ValueError('Every holding must have exactly one reference quote')
            for quote in quotes:
                row = held[quote['symbol']]
                price, as_of = self._quote(quote, row['symbol'], self.clock())
                if as_of < row['as_of'] or (as_of == row['as_of'] and price != Decimal(row['price'])):
                    raise ValueError('Reference quote would regress or rewrite a previous price')
                db.execute('UPDATE paper_positions SET price=?,as_of=? WHERE symbol=?', (number(price), as_of, row['symbol']))
            self._valuation(db)
            self._event(db, 'valuation', {'mode': 'paper', 'quotes': quotes})
        return self.state()

    def create_review(self, payload, quote):
        if not isinstance(payload, dict) or set(payload) != {'symbol', 'side', 'quantity', 'client_id'}:
            raise ValueError('Paper review requires symbol, side, quantity and client_id only')
        symbol, side, client_id = payload['symbol'], payload['side'], payload['client_id']
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', symbol):
            raise ValueError('Invalid uppercase symbol')
        if side not in ('buy', 'sell') or not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', client_id):
            raise ValueError('Invalid side or client_id')
        qty = decimal(payload['quantity'], 'quantity')
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self._db() as db, localcontext() as ctx:
            ctx.prec = 50
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM paper_reviews WHERE client_id=?', (client_id,)).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise ValueError('client_id already used for different terms')
                if prior['receipt']:
                    raise ValueError('This paper order was already confirmed; refresh the paper account')
                return json.loads(prior['review'])
            now = self.clock()
            price, as_of = self._quote(quote, symbol, now)
            fill = price * (Decimal('1.001') if side == 'buy' else Decimal('0.999'))
            notional = qty * fill
            change = -notional if side == 'buy' else notional
            review = dict(mode='paper', label=LABEL, id=str(uuid.uuid4()), token=secrets.token_urlsafe(32), client_id=client_id,
                          status='REVIEW', symbol=symbol, side=side, quantity=number(qty), reference_price=number(price),
                          reference_as_of=as_of, source=quote['source'], delayed=quote['delayed'], fill_price=number(fill),
                          notional=number(notional), fee='0', cash_change=number(change), created_at=now, expires_at=now+300)
            db.execute('INSERT INTO paper_reviews(id,client_id,fingerprint,review) VALUES(?,?,?,?)',
                       (review['id'], client_id, fingerprint, json.dumps(review, sort_keys=True)))
            self._event(db, 'review', {k:v for k,v in review.items() if k != 'token'})
            return review

    def confirm(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'id', 'token', 'approved'} or payload['approved'] is not True:
            raise ValueError('Explicit approval of the saved paper review is required')
        if not isinstance(payload['id'], str) or not isinstance(payload['token'], str):
            raise ValueError('Invalid review credentials')
        error = None
        with self._db() as db, localcontext() as ctx:
            ctx.prec = 50
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM paper_reviews WHERE id=?', (payload['id'],)).fetchone()
            if not row:
                raise ValueError('Unknown paper review')
            review = json.loads(row['review'])
            if not hmac.compare_digest(review['token'].encode(), payload['token'].encode()):
                raise ValueError('Invalid review token')
            if row['receipt']:
                return json.loads(row['receipt'])
            account = db.execute('SELECT * FROM paper_account WHERE id=1').fetchone()
            cash, realized = Decimal(account['cash']), Decimal(account['realized'])
            position = db.execute('SELECT * FROM paper_positions WHERE symbol=?', (review['symbol'],)).fetchone()
            held = Decimal(position['quantity']) if position else Decimal(0)
            basis = Decimal(position['basis']) if position else Decimal(0)
            qty, notional = Decimal(review['quantity']), Decimal(review['notional'])
            if position and (review['reference_as_of'] < position['as_of'] or (review['reference_as_of'] == position['as_of'] and Decimal(review['reference_price']) != Decimal(position['price']))):
                error = 'Reviewed price is older than the latest position mark; create a new review'
            elif self.clock() >= review['expires_at']:
                error = 'Paper review expired; create a new review'
            elif review['side'] == 'buy' and cash < notional:
                error = 'Insufficient paper cash'
            elif review['side'] == 'sell' and held < qty:
                error = 'Insufficient paper holdings; short selling is unsupported'
            if error:
                self._event(db, 'rejected', dict(review_id=review['id'], reason=error))
            else:
                if review['side'] == 'buy':
                    held, basis, cash = held + qty, basis + notional, cash - notional
                else:
                    removed = basis if qty == held else basis * qty / held
                    held, basis, cash, realized = held - qty, basis - removed, cash + notional, realized + notional - removed
                db.execute('UPDATE paper_account SET cash=?,realized=? WHERE id=1', (number(cash), number(realized)))
                db.execute('INSERT OR REPLACE INTO paper_positions VALUES(?,?,?,?,?)',
                           (review['symbol'], number(held), number(basis), review['reference_price'], review['reference_as_of']))
                receipt = {k:v for k,v in review.items() if k != 'token'}
                receipt.update(status='FILLED', filled_at=self.clock(), cash_after=number(cash))
                db.execute('UPDATE paper_reviews SET receipt=? WHERE id=?', (json.dumps(receipt, sort_keys=True), review['id']))
                self._event(db, 'simulated_fill', receipt)
                self._valuation(db)
        if error:
            raise ValueError(error)
        return receipt

    def add_note(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'text'} or not isinstance(payload['text'], str) or not 1 <= len(payload['text'].strip()) <= 4000:
            raise ValueError('A paper journal note must contain 1–4000 characters')
        with self._db() as db:
            return self._event(db, 'note', {'text': payload['text'].strip(), 'mode': 'paper'})

    def state(self):
        with self._db() as db, localcontext() as ctx:
            ctx.prec = 50
            db.execute('BEGIN')
            account = db.execute('SELECT * FROM paper_account WHERE id=1').fetchone()
            positions, value = [], Decimal(0)
            for row in db.execute('SELECT * FROM paper_positions ORDER BY symbol'):
                qty, basis, price = Decimal(row['quantity']), Decimal(row['basis']), Decimal(row['price'])
                if qty == 0:
                    continue
                market = qty * price
                value += market
                positions.append(dict(symbol=row['symbol'], quantity=number(qty), cost_basis=number(basis), average_cost=number(basis/qty),
                                      reference_price=number(price), reference_as_of=row['as_of'], market_value=number(market), unrealized_pnl=number(market-basis)))
            reviews, orders = [], []
            for row in db.execute('SELECT review,receipt FROM paper_reviews ORDER BY rowid DESC LIMIT 200'):
                if row['receipt']:
                    orders.append(json.loads(row['receipt']))
                else:
                    review = json.loads(row['review'])
                    if self.clock() >= review['expires_at']:
                        review['status'] = 'EXPIRED'
                    reviews.append(review)
            journal = [dict(id=r['id'], kind=r['kind'], at=r['at'], data=json.loads(r['data']))
                       for r in db.execute('SELECT * FROM paper_journal ORDER BY id DESC LIMIT 500')]
            valuations = [dict(r) for r in db.execute('SELECT * FROM paper_valuations ORDER BY id')]
            peak, drawdown = Decimal('10000'), Decimal(0)
            for mark in valuations:
                equity = Decimal(mark['equity'])
                peak = max(peak, equity)
                drawdown = max(drawdown, (peak-equity)/peak)
            return dict(valuations=valuations[-100:], max_drawdown=number(drawdown),
                        mark_to_market_notice='Values use saved daily reference prices, not current executable quotes. Refresh marks to record another observation.',
                        mode='paper', label=LABEL, initial_cash='10000', cash=account['cash'], positions=positions,
                        equity=number(Decimal(account['cash'])+value), realized_pnl=account['realized'],
                        valuation_as_of=min((p['reference_as_of'] for p in positions), default=None), reviews=reviews, orders=orders, journal=journal)
