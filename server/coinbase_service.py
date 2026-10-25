"""Read-only personal Coinbase Advanced Trade balances; no order/transfer methods."""
import base64
import json
import re
import secrets
import time
from decimal import Decimal, localcontext
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOST = 'api.coinbase.com'
PATH = '/api/v3/brokerage/accounts'
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 100


class CoinbaseError(Exception):
    def __init__(self, message, code='unavailable'):
        super().__init__(message)
        self.code = code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def _text(value, maximum=256):
    return isinstance(value, str) and 0 < len(value) <= maximum and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def _amount(value, currency):
    if not isinstance(value, dict) or value.get('currency') != currency:
        raise CoinbaseError('Coinbase returned conflicting balance currency.', 'invalid_response')
    amount = value.get('value')
    if not isinstance(amount, str) or len(amount) > 100 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', amount):
        raise CoinbaseError('Coinbase returned an invalid balance.', 'invalid_response')
    return amount


class CoinbaseAdapter:
    def __init__(self, key_name=None, private_key=None, opener=None, clock=time.time, token_factory=None):
        self.key_name = key_name
        self.private_key = private_key
        self.opener = opener if opener is not None else build_opener(_NoRedirect())
        self.clock = clock
        self.token_factory = token_factory

    @property
    def configured(self):
        return bool(isinstance(self.key_name, str) and self.key_name.strip() and
                    isinstance(self.private_key, str) and self.private_key.strip())

    def _token(self):
        if not self.configured:
            raise CoinbaseError('Coinbase read-only access is not configured.', 'not_configured')
        if not re.fullmatch(r'organizations/[A-Za-z0-9_-]+/apiKeys/[A-Za-z0-9_-]+', self.key_name):
            raise CoinbaseError('Coinbase API key name is invalid.', 'invalid_config')
        if self.token_factory is not None:
            return self.token_factory()
        try:
            from cryptography.exceptions import UnsupportedAlgorithm
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec, utils
        except ImportError:
            raise CoinbaseError('Coinbase signing requires the gateway cryptography dependency.', 'missing_dependency') from None
        try:
            key = serialization.load_pem_private_key(self.private_key.replace('\\n', '\n').encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError('wrong key type')
            now = int(self.clock())
            header = {'alg': 'ES256', 'typ': 'JWT', 'kid': self.key_name, 'nonce': secrets.token_hex(16)}
            payload = {'iss': 'cdp', 'sub': self.key_name, 'nbf': now, 'exp': now + 120,
                       'uri': 'GET ' + HOST + PATH}
            segments = [_b64(json.dumps(x, separators=(',', ':')).encode()) for x in (header, payload)]
            signing = '.'.join(segments).encode('ascii')
            r, s = utils.decode_dss_signature(key.sign(signing, ec.ECDSA(hashes.SHA256())))
            return signing.decode('ascii') + '.' + _b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
        except (ValueError, TypeError, OverflowError, UnsupportedAlgorithm):
            raise CoinbaseError('Coinbase signing configuration is invalid; use an ECDSA P-256 private key.', 'invalid_config') from None

    def _page(self, cursor):
        query = {'limit': 250}
        if cursor is not None:
            query['cursor'] = cursor
        request = Request('https://' + HOST + PATH + '?' + urlencode(query),
                          headers={'Authorization': 'Bearer ' + self._token(), 'Accept': 'application/json'}, method='GET')
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise CoinbaseError('Coinbase account request did not succeed.', 'upstream_error')
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise CoinbaseError('Coinbase response exceeded the safe size limit.', 'invalid_response')
                result = json.loads(data)
        except HTTPError as error:
            code = error.code
            error.close()
            if code in (401, 403):
                raise CoinbaseError('Coinbase authorization failed; check key permissions and restrictions.', 'authorization_failed') from None
            raise CoinbaseError('Coinbase account request failed.', 'upstream_error') from None
        except (URLError, OSError, TimeoutError):
            raise CoinbaseError('Coinbase could not be reached.', 'unavailable') from None
        except (ValueError, UnicodeError):
            raise CoinbaseError('Coinbase returned invalid JSON.', 'invalid_response') from None
        if not isinstance(result, dict):
            raise CoinbaseError('Coinbase returned an invalid account page.', 'invalid_response')
        return result

    def state(self):
        if not self.configured:
            raise CoinbaseError('Coinbase read-only access is not configured.', 'not_configured')
        accounts, ids, cursors = [], set(), set()
        cursor = None
        for _ in range(MAX_PAGES):
            page = self._page(cursor)
            rows = page.get('accounts')
            if not isinstance(rows, list) or len(rows) > 250 or type(page.get('has_next')) is not bool:
                raise CoinbaseError('Coinbase returned invalid pagination.', 'invalid_response')
            if 'size' in page and (type(page['size']) is not int or page['size'] != len(rows)):
                raise CoinbaseError('Coinbase account count does not match its page.', 'invalid_response')
            for row in rows:
                if not isinstance(row, dict):
                    raise CoinbaseError('Coinbase returned an invalid account.', 'invalid_response')
                identity, currency, name = row.get('uuid'), row.get('currency'), row.get('name')
                if not _text(identity) or identity in ids or not _text(name) or not isinstance(currency, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,39}', currency):
                    raise CoinbaseError('Coinbase returned invalid or duplicate account identity.', 'invalid_response')
                available = _amount(row.get('available_balance'), currency)
                hold = _amount(row.get('hold'), currency)
                with localcontext() as ctx:
                    ctx.prec = 202
                    total = format(Decimal(available) + Decimal(hold), 'f')
                accounts.append({'id': identity, 'currency': currency, 'name': name,
                                 'available': available, 'hold': hold, 'total': total})
                ids.add(identity)
            if not page['has_next']:
                return {'broker': 'coinbase', 'read_only': True, 'configured': True,
                        'as_of': self.clock(), 'accounts': accounts}
            cursor = page.get('cursor')
            if not rows or not _text(cursor, 2048) or cursor in cursors:
                raise CoinbaseError('Coinbase pagination did not advance.', 'invalid_response')
            cursors.add(cursor)
        raise CoinbaseError('Coinbase pagination exceeded the safe limit; no partial portfolio returned.', 'invalid_response')
