"""Installed SDK imports/signing/request construction; network/auth always mocked."""
import base64
import hashlib
import hmac
import io
import logging
import socket
import unittest
from unittest.mock import patch, Mock


class SDKContract(unittest.TestCase):
    def test_installed_sdk_contract_without_authentication(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')):
            from webull.core.client import ApiClient
            from webull.trade.trade_client import TradeClient
            from webull.core.http.initializer.client_initializer import ClientInitializer
            from webull.core.auth.algorithm.sha_hmac256_new import get_sign_string
            api = ApiClient('synthetic-key', 'synthetic-secret', 'us', auto_retry=False,
                            timeout=15, connect_timeout=10)
            api.set_stream_logger(log_level=logging.CRITICAL + 1, stream=io.StringIO())
            with patch.object(ClientInitializer, 'initializer') as initialize:
                client = TradeClient(api)
                initialize.assert_called_once_with(api)
            expected = base64.b64encode(hmac.new(b'fixture-secret', b'fixture-message', hashlib.sha256).digest()).decode()
            self.assertEqual(get_sign_string('fixture-message', 'fixture-secret'), expected)
            orders = [{'client_order_id':'synthetic-order','symbol':'AAPL','quantity':'3'}]
            with patch.object(api, 'get_response', return_value=Mock()) as transport:
                client.order_v3.preview_order('synthetic-account', orders)
                request = transport.call_args.args[0]
                self.assertEqual(request.get_method(), 'POST')
                self.assertEqual(request.get_version(), 'v3')
                self.assertEqual(request.get_body_params()['new_orders'], orders)
                self.assertEqual(request.get_body_params()['account_id'], 'synthetic-account')

    def test_native_cryptography_sign_verify(self):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        key = ed25519.Ed25519PrivateKey.generate()
        message = b'synthetic-contract-only'
        key.public_key().verify(key.sign(message), message)


if __name__ == '__main__': unittest.main()
