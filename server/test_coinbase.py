import base64
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from coinbase_service import CoinbaseAdapter, CoinbaseError, _NoRedirect

KEY = 'organizations/test-org/apiKeys/test-key'


def row(identity='one', amount='1.2300', currency='BTC'):
    return {'uuid': identity, 'name': currency + ' Wallet', 'currency': currency,
            'available_balance': {'value': amount, 'currency': currency},
            'hold': {'value': '0.0001', 'currency': currency}}


def page(rows=None, more=False, cursor=''):
    return {'accounts': rows if rows is not None else [row()], 'has_next': more, 'cursor': cursor}


def response(value):
    result = io.BytesIO(json.dumps(value).encode())
    result.status = 200
    return result


def adapter(*pages):
    opener = Mock()
    opener.open.side_effect = [response(p) for p in pages]
    return CoinbaseAdapter(KEY, 'fake-private', opener, lambda: 1234, lambda: 'fake-token')


class CoinbaseTests(unittest.TestCase):
    def test_not_configured_never_requests(self):
        service = CoinbaseAdapter(opener=Mock())
        with self.assertRaises(CoinbaseError) as caught:
            service.state()
        self.assertEqual(caught.exception.code, 'not_configured')
        service.opener.open.assert_not_called()

    def test_configuration_requires_string_key_material(self):
        for name, secret in ((True, 'pem'), (KEY, {}), (KEY, 123), (KEY, '   '), (' ', 'pem')):
            with self.subTest(name=name, secret_type=type(secret).__name__):
                service = CoinbaseAdapter(name, secret, opener=Mock())
                self.assertFalse(service.configured)
                with self.assertRaises(CoinbaseError) as caught:
                    service.state()
                self.assertEqual(caught.exception.code, 'not_configured')
                service.opener.open.assert_not_called()

    def test_missing_pagination_contract_is_not_empty_success(self):
        for malformed in ({}, {'has_next': False}, {'accounts': []},
                          {'accounts': [], 'has_next': None},
                          {'accounts': [row()], 'has_next': True, 'cursor': 123}):
            with self.subTest(malformed=malformed), self.assertRaises(CoinbaseError):
                adapter(malformed).state()

    def test_complete_pagination_and_exact_balances(self):
        service = adapter(page(more=True, cursor='a/b+'), page([row('two', '2.0000', 'USD')]))
        state = service.state()
        self.assertTrue(state['read_only'])
        self.assertEqual(state['accounts'][0]['total'], '1.2301')
        self.assertEqual(state['accounts'][1]['currency'], 'USD')
        self.assertEqual(state['as_of'], 1234)
        calls = service.opener.open.call_args_list
        self.assertEqual(calls[1].args[0].full_url, 'https://api.coinbase.com/api/v3/brokerage/accounts?limit=250&cursor=a%2Fb%2B')
        self.assertEqual(calls[0].args[0].get_method(), 'GET')
        self.assertEqual(calls[0].kwargs, {'timeout': 15})

    def test_empty_valid_account_list(self):
        self.assertEqual(adapter(page([])).state()['accounts'], [])

    def test_balance_validation(self):
        for value in ('NaN', 'Infinity', '-1', '1e2', ' 1', '', True, 1.2, '9' * 101):
            with self.subTest(value=value), self.assertRaises(CoinbaseError):
                adapter(page([row(amount=value)])).state()
        bad = row()
        bad['hold']['currency'] = 'USD'
        with self.assertRaises(CoinbaseError):
            adapter(page([bad])).state()

    def test_long_decimal_sum_does_not_round(self):
        account = row(amount='9' * 70 + '.123456789')
        account['hold']['value'] = '0.000000001'
        self.assertEqual(adapter(page([account])).state()['accounts'][0]['total'], '9' * 70 + '.123456790')

    def test_duplicate_identity_across_pages(self):
        with self.assertRaises(CoinbaseError):
            adapter(page(more=True, cursor='next'), page()).state()

    def test_nonadvancing_and_invalid_pagination(self):
        for bad in (page(more=True), page([], True, 'next'), {'accounts': [], 'has_next': 'false'},
                    {'accounts': [], 'has_next': False, 'size': True}):
            with self.subTest(bad=bad), self.assertRaises(CoinbaseError):
                adapter(bad).state()
        with self.assertRaises(CoinbaseError):
            adapter(page(more=True, cursor='next'), page([row('two')], True, 'next')).state()
        with patch('coinbase_service.MAX_PAGES', 1), self.assertRaises(CoinbaseError):
            adapter(page(more=True, cursor='next')).state()

    def test_malformed_accounts(self):
        for field, value in (('uuid', ''), ('name', '\n'), ('currency', 'USD\n')):
            bad = row()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(CoinbaseError):
                adapter(page([bad])).state()

    def test_error_is_sanitized_and_response_closed(self):
        service = adapter()
        body = io.BytesIO(b'secret token')
        service.opener.open.side_effect = HTTPError('https://private', 401, 'secret token', {}, body)
        with self.assertRaises(CoinbaseError) as caught:
            service.state()
        self.assertEqual(caught.exception.code, 'authorization_failed')
        self.assertNotIn('secret', str(caught.exception))
        self.assertTrue(body.closed)

    def test_transport_and_body_limits(self):
        service = adapter()
        service.opener.open.side_effect = URLError('private details')
        with self.assertRaises(CoinbaseError):
            service.state()
        for data in (b'not json', b'[]', b'x' * (2 * 1024 * 1024 + 1)):
            service = adapter()
            resp = io.BytesIO(data)
            resp.status = 200
            service.opener.open.side_effect = [resp]
            with self.assertRaises(CoinbaseError):
                service.state()
            self.assertTrue(resp.closed)

    def test_redirects_refused(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_key_name_checked_even_with_injected_signer(self):
        service = adapter(page())
        service.key_name = 'bad\nname'
        with self.assertRaises(CoinbaseError):
            service.state()
        service.opener.open.assert_not_called()

    def test_real_es256_signature_and_claims(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec, utils
        except ImportError:
            self.skipTest('cryptography optional; verify with gateway interpreter')
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
        service = CoinbaseAdapter(KEY, pem, clock=lambda: 1234)
        token = service._token()
        header, payload, signature = token.split('.')
        decode = lambda s: base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        claims, headers = json.loads(decode(payload)), json.loads(decode(header))
        self.assertEqual(claims, {'iss': 'cdp', 'sub': KEY, 'nbf': 1234, 'exp': 1354,
                                 'uri': 'GET api.coinbase.com/api/v3/brokerage/accounts'})
        self.assertEqual(headers['kid'], KEY)
        self.assertEqual(headers['alg'], 'ES256')
        self.assertNotEqual(headers['nonce'], json.loads(decode(service._token().split('.')[0]))['nonce'])
        raw = decode(signature)
        self.assertEqual(len(raw), 64)
        der = utils.encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        key.public_key().verify(der, (header + '.' + payload).encode(), ec.ECDSA(hashes.SHA256()))
        service.private_key = 'not a key'
        with self.assertRaises(CoinbaseError):
            service._token()
        wrong = ec.generate_private_key(ec.SECP384R1())
        service.private_key = wrong.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                   serialization.NoEncryption()).decode()
        with self.assertRaises(CoinbaseError):
            service._token()


if __name__ == '__main__':
    unittest.main()
