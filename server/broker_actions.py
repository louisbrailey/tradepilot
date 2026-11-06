"""Immutable manually reviewed broker actions with durable single-send admission."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from decimal import Decimal
from broker_admission import AdmissionLedger, AdmissionError
from coinbase_service import CoinbaseError
from coinbase_access import identity, portfolio_id
from webull_service import BrokerError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decimal(value, positive=True):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,18}(?:\.[0-9]{1,18})?', value):
        raise BrokerError('Use a plain decimal string within supported precision.')
    number = Decimal(value)
    if number < 0 or (positive and number == 0):
        raise BrokerError('Amount is outside the supported bounds.')
    return number


class BrokerActions:
    def __init__(self, path, adapter, admission=None, clock=time.time):
        self.adapter, self.clock = adapter, clock
        self.admission = admission if admission is not None else AdmissionLedger()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS broker_actions (
              id TEXT PRIMARY KEY, client_id TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
              terms TEXT NOT NULL, digest TEXT NOT NULL, token_hash TEXT NOT NULL,
              expires REAL NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');''')

    def capabilities(self):
        permissions = self.adapter.permissions()
        return {'provider': 'coinbase', 'environment': 'production', 'requested': ['account', 'trade', 'transfer'],
                'granted': permissions, 'implemented': ['account', 'portfolios', 'orders', 'limit_order', 'cancel_order', 'internal_transfer'],
                'verified': 'permission_metadata_only; no transaction proof',
                'trading_enabled': self.enabled('limit_order'), 'cancellation_enabled': self.enabled('cancel_order'), 'transfers_enabled': self.enabled('internal_transfer') and self.adapter.exact_transfer_reconciliation,
                'limitations': ['Internal portfolio movement is confirmed by the synchronous provider response, not independently measured balances.',
                                'External withdrawals and bank funding require a separate supported API; unavailable here.',
                                'No API-enforced commission ceiling. Hard maximum fees or all-in debit bounds are refused.'],
                'portfolios': self.adapter.portfolios()}

    @staticmethod
    def enabled(action):
        flag = 'COINBASE_TRANSFERS' if action == 'internal_transfer' else 'COINBASE_LIVE_TRADING'
        return os.environ.get(flag) == 'enabled' and (action == 'cancel_order' or os.environ.get('BROKER_KILL_SWITCH', 'enabled') == 'disabled')

    def bind(self, account, action, destination=None):
        permissions = self.adapter.permissions()
        if permissions.get('portfolio_uuid') != account or permissions.get('can_view') is not True:
            raise BrokerError('The selected portfolio does not match the API key identity.')
        if permissions.get('can_transfer' if action == 'internal_transfer' else 'can_trade') is not True:
            raise BrokerError('The provider has not granted this action permission.')
        portfolios = self.adapter.portfolios()
        for wanted in (account, destination) if destination else (account,):
            matches = [r for r in portfolios if r['id'] == wanted and r['type'] in ('DEFAULT', 'CONSUMER')]
            if len(matches) != 1:
                raise BrokerError('Select an accessible spot portfolio; derivatives portfolios are unsupported.')

    def prepare(self, payload):
        if not isinstance(payload, dict):
            raise BrokerError('Expected action fields.')
        common = {'client_id', 'action', 'account_id', 'environment'}
        action = payload.get('action')
        fields = {'limit_order': {'product_id', 'side', 'base_size', 'limit_price', 'fee_policy', 'fee_estimate_ceiling', 'debit_admission_ceiling', 'headroom', 'fee_currency'},
                  'cancel_order': {'order_id'},
                  'internal_transfer': {'destination', 'currency', 'amount', 'network', 'fee_policy'}}
        if action not in fields or set(payload) != common | fields[action]:
            raise BrokerError('Unsupported action or fields; hard fee/debit bounds, withdrawals and bank funding are not supported by this interface.')
        if payload['environment'] != self.adapter.environment or self.adapter.provider != 'coinbase':
            raise BrokerError('Provider environment mismatch.')
        account = portfolio_id(payload['account_id'])
        if account != payload['account_id']:
            raise BrokerError('Use the canonical lowercase portfolio UUID.')
        identity(payload['client_id'])
        self.bind(account, action, payload.get('destination'))
        body = {}
        if action == 'limit_order':
            product = identity(payload['product_id'])
            if not re.fullmatch(r'[A-Z0-9]+-[A-Z0-9]+', product) or payload['side'] not in ('BUY', 'SELL'):
                raise BrokerError('Use an exact spot product and BUY or SELL.')
            decimal(payload['base_size']); decimal(payload['limit_price'])
            if payload['fee_policy'] != 'accept_rechecked_estimate':
                raise BrokerError('Coinbase does not support a hard commission cap on this order contract.')
            for key in ('fee_estimate_ceiling', 'debit_admission_ceiling', 'headroom'):
                decimal(payload[key], False)
            if payload['fee_currency'] != product.split('-')[1]:
                raise BrokerError('Fee currency must equal the exact product quote currency.')
            body = {'client_order_id': payload['client_id'], 'retail_portfolio_id': account,
                    'product_id': product, 'side': payload['side'],
                    'order_configuration': {'limit_limit_gtc': {'base_size': payload['base_size'],
                                                               'limit_price': payload['limit_price'], 'post_only': False}}}
        elif action == 'cancel_order':
            body = {'order_ids': [identity(payload['order_id'])]}
        else:
            if not self.adapter.exact_transfer_reconciliation:
                raise BrokerError('Internal portfolio transfer submission is unavailable: the official response cannot verify exact asset/amount completion. No funds were moved. External withdrawals are a separate unsupported interface.')
            destination = portfolio_id(payload['destination'])
            if destination != payload['destination']:
                raise BrokerError('Use the canonical lowercase destination portfolio UUID.')
            if destination == account or payload['network'] != 'coinbase_internal' or payload['fee_policy'] != 'internal_no_fee_parameter':
                raise BrokerError('Only distinct internal portfolios are supported; no external network or fee cap.')
            if not isinstance(payload['currency'], str) or not re.fullmatch(r'[A-Z0-9]{1,20}', payload['currency']):
                raise BrokerError('Invalid asset.')
            decimal(payload['amount'])
            body = {'funds': {'value': payload['amount'], 'currency': payload['currency']},
                    'source_portfolio_uuid': account, 'target_portfolio_uuid': destination}
        terms = {'provider': 'coinbase', 'environment': 'production', 'account_id': account,
                 'action': action, 'body': body, 'intent': payload}
        if action == 'cancel_order':
            with self.lock:
                for existing in self.db.execute("SELECT * FROM broker_actions WHERE state='ACCEPTED'").fetchall():
                    prior = json.loads(existing['terms'])
                    if (prior['action'] == 'limit_order' and prior['account_id'] == account
                            and json.loads(existing['result']).get('order_id') == payload['order_id']):
                        terms['admission_action_id'] = existing['id']
        terms.update(self.preflight(terms))
        return terms

    def preflight(self, terms, admitted=False):
        p, body, action = terms['intent'], terms['body'], terms['action']
        self.bind(terms['account_id'], action, p.get('destination'))
        if admitted and action != 'cancel_order':
            for account in ([p['account_id'], p['destination']] if action == 'internal_transfer' else [p['account_id']]):
                orders = self.adapter.orders(account)
                if any(o.get('status') not in ('FILLED', 'CANCELLED', 'EXPIRED', 'FAILED') for o in orders):
                    raise BrokerError('Foreign or unresolved open orders block new exposure and transfers.')
        if action == 'cancel_order':
            order = self.adapter.detail(p['order_id'])
            if order.get('order_id') != p['order_id'] or order.get('retail_portfolio_id') != p['account_id'] or order.get('status') not in ('OPEN', 'PENDING'):
                raise BrokerError('Only an identified open order in the selected portfolio can be cancelled.')
            return {}
        if action == 'internal_transfer':
            if self.adapter.available(p['account_id'], p['currency']) < decimal(p['amount']):
                raise BrokerError('Insufficient available source funds.')
            return {}
        product = self.adapter.product(p['product_id'])
        if (product.get('product_id') != p['product_id'] or product.get('product_type') != 'SPOT'
                or product.get('status') != 'online' or any(product.get(k) is not False for k in ('trading_disabled', 'cancel_only', 'view_only'))):
            raise BrokerError('Product identity, type or trading eligibility is unverified.')
        size, price = decimal(p['base_size']), decimal(p['limit_price'])
        if (size % decimal(product.get('base_increment')) != 0 or price % decimal(product.get('price_increment')) != 0
                or not decimal(product.get('base_min_size')) <= size <= decimal(product.get('base_max_size'))):
            raise BrokerError('Quantity or price violates current product limits.')
        preview = self.adapter.preview(body)
        preview_at = self.clock()
        if preview.get('errs') != [] or not isinstance(preview.get('preview_id'), str) or not preview['preview_id']:
            raise BrokerError('The broker did not provide an accepted order preview.')
        if (product.get('base_currency_id') != p['product_id'].split('-')[0]
                or product.get('quote_currency_id') != p['fee_currency']
                or decimal(preview.get('base_size')) != size):
            raise BrokerError('Preview units or product currencies do not match the reviewed order.')
        fee = decimal(preview.get('commission_total'), False)
        details = preview.get('commission_detail_total')
        if not isinstance(details, dict) or decimal(details.get('total_commission'), False) != fee:
            raise BrokerError('Complete commission coverage is unavailable; estimated-fee execution refused.')
        notional = size * price
        allowance = decimal(p['fee_estimate_ceiling'], False)
        headroom = decimal(p['headroom'], False)
        if fee > allowance:
            raise BrokerError('Estimated commission exceeds the approved ceiling; create a fresh review.')
        base, quote = p['product_id'].split('-')
        debit = notional + allowance + headroom if p['side'] == 'BUY' else allowance + headroom
        if debit > decimal(p['debit_admission_ceiling'], False):
            raise BrokerError('Debit admission ceiling does not cover notional, fee allowance and headroom.')
        required = debit if p['side'] == 'BUY' else size
        if self.adapter.available(p['account_id'], quote if p['side'] == 'BUY' else base) < required:
            raise BrokerError('Insufficient available funds; short selling is unsupported.')
        if p['side'] == 'SELL' and self.adapter.available(p['account_id'], quote) < allowance + headroom:
            raise BrokerError('Insufficient quote-currency funds for sell fees and headroom.')
        if self.clock() - preview_at > 15:
            raise BrokerError('The fresh preview became stale during admission.')
        return {'preview_retrieved_at': preview_at, 'estimated_fee': str(fee), 'maximum_limit_notional': str(notional),
                'quantity_units': base, 'time_in_force': 'GTC'}

    def review(self, payload):
        # Stable client_id makes repeated review creation idempotent; never mint a second action.
        request = canonical(payload)
        with self.lock:
            old = self.db.execute('SELECT * FROM broker_actions WHERE client_id=?', (payload.get('client_id') if isinstance(payload, dict) else None,)).fetchone()
            if old:
                if old['request'] != request:
                    raise BrokerError('This client ID already belongs to different terms.')
                raise BrokerError('This action already exists. Inspect saved status; create a fresh explicitly reviewed intent only when safe.')
        terms = self.prepare(payload)
        action_id, token, expires = uuid.uuid4().hex, secrets.token_urlsafe(32), self.clock() + 60
        terms['expires_at'] = expires
        digest = hashlib.sha256(canonical(terms).encode()).hexdigest()
        try:
            with self.lock, self.db:
                self.db.execute('INSERT INTO broker_actions VALUES (?,?,?,?,?,?,?,?,?)',
                                (action_id, payload['client_id'], request, canonical(terms), digest,
                                 hashlib.sha256(token.encode()).hexdigest(), expires, 'REVIEW', '{}'))
        except sqlite3.IntegrityError:
            raise BrokerError('Action already exists; inspect status.') from None
        return {'id': action_id, 'token': token, 'digest': digest, 'terms': terms,
                'summary': json.dumps(terms, indent=2, sort_keys=True), 'expires_at': expires, 'state': 'REVIEW'}

    def row(self, action_id):
        identity(action_id)
        row = self.db.execute('SELECT * FROM broker_actions WHERE id=?', (action_id,)).fetchone()
        if row is None:
            raise BrokerError('Unknown saved action.')
        return row

    def status(self, action_id):
        with self.lock:
            row = self.row(action_id)
            return {'id': row['id'], 'digest': row['digest'], 'state': row['state'],
                    'summary': json.dumps(json.loads(row['terms']), indent=2, sort_keys=True) + '\nResult: ' + row['result'],
                    'expires_at': row['expires'], 'result': json.loads(row['result'])}

    def confirm(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'id', 'token', 'digest', 'approved'} or payload['approved'] is not True:
            raise BrokerError('Confirmation must contain only saved ID, token, digest and explicit approval.')
        if not all(isinstance(payload[k], str) for k in ('id', 'token', 'digest')):
            raise BrokerError('Invalid confirmation.')
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row = self.row(payload['id'])
                if not hmac.compare_digest(row['token_hash'], hashlib.sha256(payload['token'].encode()).hexdigest()) or not hmac.compare_digest(row['digest'], payload['digest']):
                    raise BrokerError('Confirmation does not match the saved terms.')
                if row['state'] != 'REVIEW':
                    self.db.rollback()
                    return self.status(row['id'])
                terms = json.loads(row['terms'])
                if self.clock() >= row['expires'] or not self.enabled(terms['action']):
                    raise BrokerError('Review expired or broker writes are disabled.')
                parent = terms.get('admission_action_id')
                if parent:
                    changed = self.db.execute("UPDATE broker_actions SET state='CANCEL_PENDING' WHERE id=? AND state='ACCEPTED'", (parent,)).rowcount
                    if changed != 1:
                        raise BrokerError('The existing order already has an unresolved action.')
                self.db.execute("UPDATE broker_actions SET state='VALIDATING' WHERE id=?", (row['id'],))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        action_id, reserved, sent = row['id'], False, False
        hold_id = terms.get('admission_action_id', action_id)
        try:
            accounts = [terms['account_id']]
            if terms['action'] == 'internal_transfer':
                accounts.append(terms['intent']['destination'])
            if hold_id != action_id:
                self.admission.require_owned('coinbase', 'production', terms['account_id'], hold_id)
            else:
                self.admission.reserve('coinbase', 'production', accounts, action_id)
            reserved = True
            refreshed = self.preflight(terms, admitted=True)
            if self.clock() >= row['expires'] or not self.enabled(terms['action']):
                raise BrokerError('Review expired or writes disabled during validation.')
            with self.lock, self.db:
                self.db.execute('BEGIN IMMEDIATE')
                changed = self.db.execute("UPDATE broker_actions SET state='SUBMITTING',result=? WHERE id=? AND state='VALIDATING'", (canonical({'refreshed_preview': refreshed}), action_id)).rowcount
                if changed != 1:
                    raise BrokerError('Pre-send action was recovered; submission is cancelled.')
                self.admission.transition(hold_id, 'SUBMITTING')
            sent = True
            result = self.adapter.submit(terms['action'], terms['body'])
            state, clean = self.classify(terms, result)
            if not self.save_outcome(action_id, state, clean | {'refreshed_preview': refreshed}):
                return self.status(action_id)
            if state in ('REJECTED', 'COMPLETED'):
                if hold_id == action_id:
                    self.admission.release(action_id)
                elif state == 'REJECTED':
                    self.restore_parent(hold_id)
            elif state == 'UNKNOWN':
                self.mark_unknown_hold(action_id, hold_id)
        except Exception as error:
            # Unknown exceptions and response content are intentionally never logged/persisted.
            rejected = sent and isinstance(error, CoinbaseError) and error.code == 'rejected'
            state = 'UNKNOWN' if sent and not rejected else 'REJECTED'
            if sent:
                if not self.save_outcome(action_id, state, {}):
                    return self.status(action_id)
            else:
                with self.lock, self.db:
                    self.db.execute("UPDATE broker_actions SET state='REJECTED' WHERE id=? AND state='VALIDATING'", (action_id,))
            if reserved:
                if state == 'UNKNOWN':
                    self.mark_unknown_hold(action_id, hold_id)
                elif hold_id == action_id:
                    self.admission.release(action_id)
            if hold_id != action_id and (not sent or rejected):
                self.restore_parent(hold_id)

        return self.status(action_id)

    def mark_unknown_hold(self, action_id, hold_id):
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.row(action_id)['state'] == 'UNKNOWN':
                self.admission.transition(hold_id, 'UNKNOWN')

    def save_outcome(self, action_id, state, result):
        with self.lock, self.db:
            self.db.execute('BEGIN IMMEDIATE')
            changed = self.db.execute("UPDATE broker_actions SET state=?,result=? WHERE id=? AND state='SUBMITTING'", (state, canonical(result), action_id)).rowcount
            return changed == 1

    def restore_parent(self, action_id):
        with self.lock, self.db:
            self.db.execute("UPDATE broker_actions SET state='ACCEPTED' WHERE id=? AND state='CANCEL_PENDING'", (action_id,))

    def save(self, action_id, state, result=None):
        with self.lock, self.db:
            self.db.execute('UPDATE broker_actions SET state=?,result=? WHERE id=?', (state, canonical(result or {}), action_id))

    @staticmethod
    def classify(terms, result):
        if not isinstance(result, dict):
            return 'UNKNOWN', {}
        action, body = terms['action'], terms['body']
        if action == 'internal_transfer':
            if result.get('source_portfolio_uuid') == body['source_portfolio_uuid'] and result.get('target_portfolio_uuid') == body['target_portfolio_uuid']:
                if not any(k in result for k in ('error', 'errors', 'code', 'message', 'details')):
                    return 'COMPLETED', {'evidence': 'synchronous_provider_response', 'source': body['source_portfolio_uuid'], 'destination': body['target_portfolio_uuid'], 'funds': body['funds'], 'request_digest': hashlib.sha256(canonical(terms).encode()).hexdigest()}
        elif action == 'limit_order':
            if result.get('success') is False:
                return 'REJECTED', {}
            accepted = result.get('success_response', {})
            if result.get('success') is True and all(accepted.get(k) == body[k] for k in ('client_order_id', 'product_id', 'side')):
                try:
                    return 'ACCEPTED', {'order_id': identity(accepted.get('order_id'))}
                except CoinbaseError:
                    pass
        elif action == 'cancel_order':
            rows = result.get('results')
            if isinstance(rows, list) and len(rows) == 1 and rows[0].get('order_id') == body['order_ids'][0]:
                if rows[0].get('success') is False:
                    return 'REJECTED', {}
                if rows[0].get('success') is True:
                    return 'ACCEPTED', {'order_id': body['order_ids'][0]}
        return 'UNKNOWN', {}

    def reconcile(self, action_id):
        with self.lock:
            row = self.row(action_id)
            terms, result = json.loads(row['terms']), json.loads(row['result'])
        if row['state'] == 'VALIDATING':
            with self.lock, self.db:
                self.db.execute('BEGIN IMMEDIATE')
                changed = self.db.execute("UPDATE broker_actions SET state='REJECTED' WHERE id=? AND state='VALIDATING'", (action_id,)).rowcount
                if changed:
                    if terms.get('admission_action_id'):
                        self.db.execute("UPDATE broker_actions SET state='ACCEPTED' WHERE id=? AND state='CANCEL_PENDING'", (terms['admission_action_id'],))
                    else:
                        self.admission.release(action_id)
            return self.status(action_id)
        if row['state'] in ('COMPLETED', 'REJECTED'):
            if row['state'] == 'COMPLETED' or not terms.get('admission_action_id'):
                self.admission.release(terms.get('admission_action_id', action_id))
            else:
                self.restore_parent(terms['admission_action_id'])
            return self.status(action_id)
        if row['state'] not in ('ACCEPTED', 'UNKNOWN', 'SUBMITTING') or terms['action'] == 'internal_transfer':
            return self.status(action_id)
        self.bind(terms['account_id'], terms['action'])
        order_id = result.get('order_id') or terms['intent'].get('order_id')
        if not order_id:
            # Absence is not authoritative failure. Search only, never retransmit.
            matches = [o for o in self.adapter.orders(terms['account_id']) if o.get('client_order_id') == terms['body'].get('client_order_id')]
            if len(matches) != 1:
                return self.status(action_id)
            order_id = matches[0].get('order_id')
        order = self.adapter.detail(order_id)
        if order.get('retail_portfolio_id') != terms['account_id'] or order.get('order_id') != order_id:
            raise BrokerError('Reconciliation identity mismatch.')
        hold_id = terms.get('admission_action_id', action_id)
        economic_terms = terms
        parent_state = None
        if hold_id != action_id:
            with self.lock:
                parent = self.row(hold_id)
                parent_state = parent['state']
                economic_terms = json.loads(parent['terms'])
        if economic_terms['action'] == 'limit_order' and any(order.get(k) != economic_terms['body'][k] for k in ('client_order_id', 'product_id', 'side', 'order_configuration')):
            raise BrokerError('Reconciliation terms mismatch.')
        if (row['state'] in ('UNKNOWN', 'SUBMITTING') and hold_id == action_id and terms['action'] == 'limit_order'
                and order.get('status') in ('OPEN', 'PENDING', 'QUEUED')):
            # The broker positively identified a live order for this exact action: record acceptance
            # so it can be cancelled from the app. The hold stays; nothing is retransmitted.
            with self.lock, self.db:
                self.db.execute('BEGIN IMMEDIATE')
                changed = self.db.execute("UPDATE broker_actions SET state='ACCEPTED',result=? WHERE id=? AND state=?",
                                          (canonical({'order_id': order_id}), action_id, row['state'])).rowcount
            if changed:
                self.admission.transition(action_id, 'SUBMITTING')
            return self.status(action_id)
        if order.get('status') in ('FILLED', 'CANCELLED', 'EXPIRED', 'FAILED'):
            evidence = {'order_id': order_id, 'broker_status': order['status']}
            if economic_terms['action'] == 'limit_order':
                try:
                    fee = decimal(order.get('total_fees'), False)
                    value = decimal(order.get('filled_value'), False)
                except BrokerError:
                    return self.status(action_id)
                p = economic_terms['intent']
                debit = value + fee if p['side'] == 'BUY' else fee
                evidence.update(actual_fee=str(fee), actual_debit=str(debit), fee_currency=p['fee_currency'],
                                fee_overrun=fee > decimal(p['fee_estimate_ceiling'], False),
                                debit_overrun=debit > decimal(p['debit_admission_ceiling'], False))
            with self.lock, self.db:
                self.db.execute('BEGIN IMMEDIATE')
                if self.row(action_id)['state'] != row['state']:
                    return self.status(action_id)
                if hold_id != action_id and self.row(hold_id)['state'] != parent_state:
                    return self.status(action_id)
                self.db.execute("UPDATE broker_actions SET state='COMPLETED',result=? WHERE id=?", (canonical(evidence), action_id))
                if hold_id != action_id:
                    self.db.execute("UPDATE broker_actions SET state='COMPLETED',result=? WHERE id=?", (canonical(evidence), hold_id))
            self.admission.release(hold_id)
        return self.status(action_id)
