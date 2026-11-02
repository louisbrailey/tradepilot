"""Manual cancellation of an app-tracked Webull order through the official SDK."""
import hashlib
import hmac
import json
import secrets
import time
import uuid
from broker_admission import AdmissionLedger
from webull_service import BrokerError


def cancellation_review(service, payload):
    if not isinstance(payload, dict) or set(payload) != {'id'}:
        raise BrokerError('Select the saved order to cancel.')
    # Validate authoritative broker identity and terms using the existing ledger.
    receipt = service.refresh(payload['id'])
    if receipt['state'] not in ('PENDING', 'SUBMITTED', 'PARTIAL_FILLED'):
        raise BrokerError('Only an acknowledged open app order can be cancelled; uncertain orders require reconciliation.')
    with service.lock, service.db:
        service.db.execute('''CREATE TABLE IF NOT EXISTS cancellation_reviews (
            id TEXT PRIMARY KEY, parent_id TEXT, digest TEXT, token_hash TEXT,
            expires REAL, state TEXT, summary TEXT)''')
        parent = service.row(payload['id'])
        body = json.loads(parent['body'])
        action_id, token, expires = uuid.uuid4().hex, secrets.token_urlsafe(32), service.clock() + 60
        terms = {'action': 'cancel_order', 'provider': 'webull', 'environment': parent['environment'],
                 'account_id': parent['account'], 'client_order_id': body['client_order_id'],
                 'saved_order': json.loads(parent['body']), 'expires_at': expires}
        summary = json.dumps(terms, sort_keys=True, indent=2)
        digest = hashlib.sha256(summary.encode()).hexdigest()
        service.db.execute('INSERT INTO cancellation_reviews VALUES (?,?,?,?,?,?,?)',
                           (action_id, parent['id'], digest, hashlib.sha256(token.encode()).hexdigest(), expires, 'REVIEW', summary))
    return {'id': action_id, 'token': token, 'digest': digest, 'expires_at': expires, 'state': 'REVIEW', 'summary': summary}


def cancellation_confirm(service, payload):
    import os
    if (not isinstance(payload, dict) or set(payload) != {'id', 'token', 'digest', 'approved'}
            or payload['approved'] is not True or not all(isinstance(payload[k], str) for k in ('id', 'token', 'digest'))):
        raise BrokerError('Confirmation requires exact saved ID, token, digest and approval.')
    if os.environ.get('WEBULL_LIVE_TRADING') != 'enabled':
        raise BrokerError('Webull writes are disabled.')
    with service.lock:
        row = service.db.execute('SELECT * FROM cancellation_reviews WHERE id=?', (payload['id'],)).fetchone()
        if not row or not hmac.compare_digest(row['digest'], payload['digest']) or not hmac.compare_digest(row['token_hash'], hashlib.sha256(payload['token'].encode()).hexdigest()):
            raise BrokerError('Confirmation does not match saved cancellation.')
        parent = service.row(row['parent_id'])
        if parent['environment'] != 'production':
            raise BrokerError('This cancellation interface is production-only.')
        result = {'id': row['id'], 'digest': row['digest'], 'summary': row['summary'], 'expires_at': row['expires']}
        if row['state'] != 'REVIEW':
            return result | {'state': row['state']}
        if service.clock() >= row['expires']:
            raise BrokerError('Cancellation review expired.')
        ledger = service.admission if service.admission is not None else AdmissionLedger()
        ledger.require_owned('webull', 'production', parent['account'], parent['id'])
        receipt = service.refresh(parent['id'])
        if receipt['state'] not in ('PENDING', 'SUBMITTED', 'PARTIAL_FILLED'):
            raise BrokerError('Order is not confirmed open.')
        service.account(parent['account'])
        if service.clock() >= row['expires'] or os.environ.get('WEBULL_LIVE_TRADING') != 'enabled':
            raise BrokerError('Cancellation expired or writes disabled during validation.')
        with service.db:
            service.db.execute('BEGIN IMMEDIATE')
            if service.db.execute("SELECT 1 FROM cancellation_reviews WHERE parent_id=? AND state IN ('SUBMITTING','UNKNOWN','ACCEPTED')", (parent['id'],)).fetchone():
                raise BrokerError('Another cancellation for this order is unresolved.')
            changed = service.db.execute("UPDATE cancellation_reviews SET state='SUBMITTING' WHERE id=? AND state='REVIEW'", (row['id'],)).rowcount
            if changed != 1:
                raise BrokerError('Cancellation already attempted.')
        body = json.loads(parent['body'])
        state = 'UNKNOWN'
        try:
            response = service.adapter.cancel(parent['account'], body['client_order_id'])
            if isinstance(response, dict) and response.get('client_order_id') == body['client_order_id']:
                state = 'ACCEPTED'
        except Exception:
            pass  # No provider body/exception text is persisted or exposed.
        if state == 'UNKNOWN':
            ledger.transition(parent['id'], 'UNKNOWN')
        with service.db:
            service.db.execute('UPDATE cancellation_reviews SET state=? WHERE id=?', (state, row['id']))
        return result | {'state': state}
