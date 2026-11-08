"""Authenticated gateway dispatch for concrete broker capabilities."""
import os
from private_storage import ensure_private_directory, runtime_path
import threading
from pathlib import Path
from broker_actions import BrokerActions
from coinbase_access import CoinbaseAccess
from broker_admission import AdmissionError
from coinbase_service import CoinbaseError
from webull_service import BrokerError

ACCESS_ROUTES = tuple('/v1/coinbase/' + name for name in ('capabilities', 'portfolios', 'orders', 'action/review', 'action/confirm', 'action/status', 'action/reconcile')) + ('/v1/webull/capabilities', '/v1/webull/transfer/review')
_lock = threading.Lock()
_service = None


def service():
    global _service
    with _lock:
        if _service is None:
            runtime = runtime_path(os.environ.get('TRADEPILOT_RUNTIME', 'runtime'))
            ensure_private_directory(runtime)
            _service = BrokerActions(runtime / 'broker-actions.sqlite3', CoinbaseAccess(
                os.environ.get('COINBASE_API_KEY_NAME'), os.environ.get('COINBASE_API_PRIVATE_KEY')))
        return _service


def access_request(path, payload):
    if not isinstance(payload, dict):
        raise BrokerError('Expected an object.')
    if path == '/v1/webull/transfer/review':
        raise BrokerError('Webull retail Trading API funding is unavailable. Institutional Broker API entitlement and a separately verified funding integration are required.')
    if path == '/v1/webull/capabilities':
        if payload:
            raise BrokerError('Expected an empty request.')
        return {'provider': 'webull', 'requested': ['account', 'trade', 'transfer'],
                'implemented': ['accounts', 'positions', 'balance', 'long_equity_market_limit_day', 'confirmed_app_order_cancellation'],
                'granted': 'unknown_until_provider_read', 'verified': False,
                'transfers_enabled': False, 'limitations': ['Retail funding/withdrawals are unavailable through this integration; Broker API entitlement is separate.',
                'Options/futures/crypto execution requires product-specific contracts and risk validation, not just broader credentials.']}
    try:
        s = service()
        if path.endswith('/capabilities'):
            if payload:
                raise BrokerError('Expected an empty request.')
            return s.capabilities()
        if path.endswith('/portfolios'):
            if payload:
                raise BrokerError('Expected an empty request.')
            return {'portfolios': s.adapter.portfolios()}
        if path.endswith('/orders'):
            if set(payload) != {'account_id'}:
                raise BrokerError('Expected only account_id.')
            permissions = s.adapter.permissions()
            if permissions['portfolio_uuid'] != payload['account_id'] or not permissions['can_view']:
                raise BrokerError('Portfolio binding mismatch.')
            return {'orders': s.adapter.orders(payload['account_id'])}
        if path.endswith('/action/review'):
            return s.review(payload)
        if path.endswith('/action/confirm'):
            return s.confirm(payload)
        if path.endswith(('/action/status', '/action/reconcile')):
            if set(payload) != {'id'}:
                raise BrokerError('Expected only saved action ID.')
            return s.reconcile(payload['id']) if path.endswith('/reconcile') else s.status(payload['id'])
    except (CoinbaseError, AdmissionError) as error:
        raise BrokerError(str(error)) from None
    raise BrokerError('Unsupported broker operation.')
