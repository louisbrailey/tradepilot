"""Concrete Advanced Trade contracts; no caller-controlled HTTP method or origin."""
import json
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request
from coinbase_service import CoinbaseAdapter, CoinbaseError, HOST, MAX_BYTES, MAX_PAGES

PREFIX = '/api/v3/brokerage'


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', value):
        raise CoinbaseError('Invalid broker identity.', 'invalid_request')
    return value


def portfolio_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise CoinbaseError('Select a canonical portfolio UUID.', 'invalid_request') from None


class CoinbaseAccess(CoinbaseAdapter):
    environment = 'production'
    provider = 'coinbase'
    exact_transfer_reconciliation = True

    def _request(self, method, path, body=None, query=None):
        request = Request('https://' + HOST + PREFIX + path + ('?' + urlencode(query, doseq=True) if query else ''),
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Authorization': 'Bearer ' + self._token(method, PREFIX + path),
                                   'Content-Type': 'application/json', 'Accept': 'application/json'}, method=method)
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise CoinbaseError('Broker response requires reconciliation.', 'uncertain')
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise CoinbaseError('Broker response exceeded size limit.', 'uncertain')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError()
                return result
        except HTTPError as error:
            status = error.code
            error.close()
            # Never persist provider bodies, URLs, JWTs or exception text.
            raise CoinbaseError('Broker rejected the request.' if status in (400, 401, 403, 422) else
                                'Broker result is uncertain; do not resubmit.',
                                'rejected' if status in (400, 401, 403, 422) else 'uncertain') from None
        except (URLError, OSError, ValueError, UnicodeError):
            raise CoinbaseError('Broker result is uncertain; do not resubmit.', 'uncertain') from None

    def permissions(self):
        result = self._request('GET', '/key_permissions')
        if any(type(result.get(k)) is not bool for k in ('can_view', 'can_trade', 'can_transfer')):
            raise CoinbaseError('Invalid permission response.')
        return {k: result[k] for k in ('can_view', 'can_trade', 'can_transfer')} | {
            'portfolio_uuid': portfolio_id(result.get('portfolio_uuid'))}

    def portfolios(self):
        result = self._request('GET', '/portfolios')
        rows = result.get('portfolios')
        if not isinstance(rows, list):
            raise CoinbaseError('Invalid portfolio response.')
        clean = []
        for row in rows:
            if not isinstance(row, dict) or row.get('type') not in ('DEFAULT', 'CONSUMER', 'INTX'):
                raise CoinbaseError('Unrecognized portfolio type.')
            clean.append({'id': portfolio_id(row.get('uuid')), 'type': row['type']})
        if len({r['id'] for r in clean}) != len(clean):
            raise CoinbaseError('Duplicate portfolio identity.')
        return clean

    def product(self, product):
        return self._request('GET', '/products/' + identity(product))

    def orders(self, account):
        rows, cursors, cursor = [], set(), None
        for _ in range(MAX_PAGES):
            query = {'retail_portfolio_id': identity(account), 'limit': 100}
            if cursor:
                query['cursor'] = cursor
            page = self._request('GET', '/orders/historical/batch', query=query)
            batch = page.get('orders')
            if not isinstance(batch, list) or type(page.get('has_next')) is not bool:
                raise CoinbaseError('Incomplete order history.')
            for item in batch:
                if not isinstance(item, dict) or item.get('retail_portfolio_id') != account:
                    raise CoinbaseError('Order history account mismatch.')
                rows.append({k: item.get(k) for k in ('order_id', 'client_order_id', 'product_id', 'side', 'status',
                                                     'retail_portfolio_id', 'order_configuration')})
            if not page['has_next']:
                return rows
            cursor = page.get('cursor')
            if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in cursors or not batch:
                raise CoinbaseError('Order pagination did not advance.')
            cursors.add(cursor)
        raise CoinbaseError('Order history is incomplete.')

    def detail(self, order_id):
        return self._request('GET', '/orders/historical/' + identity(order_id)).get('order', {})

    def preview(self, body):
        return self._request('POST', '/orders/preview', {k: v for k, v in body.items() if k != 'client_order_id'})

    def submit(self, action, body):
        paths = {'limit_order': '/orders', 'cancel_order': '/orders/batch_cancel',
                 'internal_transfer': '/portfolios/move_funds'}
        if action not in paths:
            raise CoinbaseError('Unsupported Coinbase action.')
        return self._request('POST', paths[action], body)

    def available(self, portfolio, currency):
        from decimal import Decimal
        # Validate the complete account snapshot with the existing strict parser first.
        # A second scan below is independently validated; no partial balances are accepted.
        from coinbase_service import _amount, _text
        cursor, seen, ids, amount = None, set(), set(), Decimal(0)
        for _ in range(MAX_PAGES):
            page = self._page(cursor)
            rows = page.get('accounts')
            if not isinstance(rows, list) or type(page.get('has_next')) is not bool:
                raise CoinbaseError('Incomplete account balances.')
            for row in rows:
                if not isinstance(row, dict) or not _text(row.get('uuid')) or row['uuid'] in ids:
                    raise CoinbaseError('Invalid account balances.')
                ids.add(row['uuid'])
                if portfolio_id(row.get('retail_portfolio_id')) == portfolio and row.get('currency') == currency:
                    if row.get('active') is not True or row.get('ready') is not True:
                        raise CoinbaseError('Currency account is not ready.')
                    amount += Decimal(_amount(row.get('available_balance'), currency))
            if not page['has_next']:
                return amount
            cursor = page.get('cursor')
            if not _text(cursor, 2048) or cursor in seen or not rows:
                raise CoinbaseError('Incomplete account balances.')
            seen.add(cursor)
        raise CoinbaseError('Incomplete account balances.')
