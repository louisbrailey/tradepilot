import io
import json
import socket
import unittest
from email.message import Message
from unittest.mock import patch
import server


class GatewayTests(unittest.TestCase):
    def test_setup_configuration_is_not_a_provider_check_and_contains_no_secrets(self):
        with patch.dict(server.os.environ, {"OPENAI_API_KEY": "secret-openai", "OPENAI_MODEL": "test-model",
                "WEBULL_APP_KEY": "secret-webull", "WEBULL_APP_SECRET": "secret-other",
                "MASSIVE_API_KEY": "secret-market", "WEBULL_ENV": "production"}, clear=True), \
                patch.object(server, "broker") as broker:
            result = server.setup_status()
        broker.assert_not_called()
        self.assertTrue(result["configuration_only"])
        self.assertTrue(result["ai_configured"])
        self.assertEqual(result["ai_provider"], "openai")
        self.assertEqual(result["ai_model"], "test-model")
        self.assertTrue(result["webull_configured"])
        self.assertFalse(result["live_trading_enabled"])
        self.assertNotIn("secret-", json.dumps(result))

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_setup_route_requires_authentication(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/v1/setup"
        handler.headers = Message()
        responses = []
        handler.reply = lambda status, payload: responses.append(status)
        with patch.object(server, "setup_status") as setup:
            handler.do_POST()
        setup.assert_not_called()
        self.assertEqual(responses, [401])

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_evaluation_route_requires_authentication_and_exact_empty_object(self):
        for authorized, payload, expected in ((False, {}, 401), (True, {}, 200),
                                               (True, {"path": "/private/other.json"}, 400),
                                               (True, [], 400), (True, None, 400)):
            with self.subTest(authorized=authorized, payload=payload):
                handler = server.Handler.__new__(server.Handler)
                handler.path = "/v1/research/evaluation"
                handler.headers = Message()
                if authorized:
                    handler.headers["Authorization"] = "Bearer " + "x" * 32
                data = json.dumps(payload).encode()
                handler.headers["Content-Type"] = "application/json"
                handler.headers["Content-Length"] = str(len(data))
                handler.rfile = io.BytesIO(data)
                responses = []
                handler.reply = lambda status, result: responses.append((status, result))
                with patch.object(server, "load_evaluation", return_value={"source": "saved evaluation"}) as load:
                    handler.do_POST()
                self.assertEqual(responses[0][0], expected)
                self.assertEqual(load.call_count, int(expected == 200))

    class FakeBroker:
        def state(self, account):
            if account != "acct-1":
                raise server.BrokerError("unauthorized account")
            return {"environment": "sandbox", "accounts": [{"id": "acct-1", "label": "Webull · 1234"}],
                    "positions": [{"id": "p1", "symbol": "AAPL", "quantity": "5", "price": "100",
                                   "cost": "90", "gain": "50", "kind": "EQUITY", "currency": "USD"}],
                    "balance": "{}", "as_of": 1234.0}

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_http_authentication_rejects_without_model_call(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/v1/assistant"
        handler.headers = Message()
        responses = []
        handler.reply = lambda status, payload: responses.append((status, payload))
        with patch.object(server, "assistant") as model:
            handler.do_POST()
            model.assert_not_called()
        self.assertEqual(responses[0][0], 401)

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_http_rejects_oversized_body(self):
        handler = server.Handler.__new__(server.Handler)
        handler.path = "/v1/assistant"
        handler.headers = Message()
        handler.headers["Authorization"] = "Bearer " + "x" * 32
        handler.headers["Content-Type"] = "application/json"
        handler.headers["Content-Length"] = "65537"
        responses = []
        handler.reply = lambda status, payload: responses.append(status)
        handler.do_POST()
        self.assertEqual(responses, [413])

    @patch.dict(server.os.environ, {"APP_ACCESS_TOKEN": "x" * 32})
    def test_ambiguous_or_truncated_http_requests_fail_before_dispatch(self):
        cases = (([("Content-Length", "3")], 400),
                 ([("Content-Length", "2"), ("Content-Length", "2")], 400),
                 ([("Content-Length", "2"), ("Authorization", "Bearer other")], 401),
                 ([("Content-Length", "2"), ("Transfer-Encoding", "chunked")], 400))
        for headers, expected in cases:
            with self.subTest(headers=headers):
                handler = server.Handler.__new__(server.Handler)
                handler.path = "/v1/setup"
                handler.headers = Message()
                handler.headers["Authorization"] = "Bearer " + "x" * 32
                handler.headers["Content-Type"] = "application/json"
                for name, value in headers:
                    handler.headers[name] = value
                handler.rfile = io.BytesIO(b"{}")
                responses = []
                handler.reply = lambda status, payload: responses.append(status)
                with patch.object(server, "setup_status") as setup:
                    handler.do_POST()
                self.assertEqual(responses, [expected])
                setup.assert_not_called()

    def test_idle_tls_peer_does_not_block_other_clients(self):
        import ssl, subprocess, tempfile, threading
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            cert, key = Path(folder) / "c.pem", Path(folder) / "k.pem"
            made = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                                   "-subj", "/CN=127.0.0.1", "-keyout", str(key), "-out", str(cert)],
                                  capture_output=True)
            if made.returncode:
                self.skipTest("openssl unavailable")
            service = server.GatewayHTTPServer(("127.0.0.1", 0), server.Handler)
            server.enable_tls(service, cert, key)
            port = service.server_address[1]
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            idle = socket.create_connection(("127.0.0.1", port))
            try:
                client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                client.check_hostname = False
                client.verify_mode = ssl.CERT_NONE  # Availability test only; pinning is tested in the app.
                with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
                    with client.wrap_socket(raw) as tls:
                        tls.sendall(b"POST /v1/setup HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\n{}")
                        self.assertIn(b"401", tls.recv(64))
                stopper = threading.Thread(target=service.shutdown)
                stopper.start()
                stopper.join(5)
                self.assertFalse(stopper.is_alive())
            finally:
                idle.close()
                service.server_close()

    def test_gateway_chooses_the_bind_address_family(self):
        for address, family in (("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)):
            with self.subTest(address=address), \
                    patch.object(server.ThreadingHTTPServer, "__init__", return_value=None) as initialize:
                gateway = server.GatewayHTTPServer((address, 0), server.Handler)
                self.assertEqual(gateway.address_family, family)
                initialize.assert_called_once_with((address, 0), server.Handler)

    def proposal(self, **changes):
        return {"kind": "trade", "message": "Review this proposal.", "side": "sell", "quantity": "3", "symbol": "AAPL", **changes}

    def test_valid_proposal(self):
        self.assertEqual(server.validate_reply(self.proposal())["quantity"], "3")

    def test_invalid_quantities(self):
        for value in ["0", "-3", "NaN", "Infinity", "1e2", "0.123456789", "1000000001", 3, None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.validate_reply(self.proposal(quantity=value))

    def test_invalid_symbols_and_side(self):
        for changes in [{"symbol": "AAPL;DROP"}, {"symbol": ""}, {"side": "transfer"}]:
            with self.assertRaises(ValueError):
                server.validate_reply(self.proposal(**changes))

    def test_nontrade_cannot_smuggle_order(self):
        with self.assertRaises(ValueError):
            server.validate_reply(self.proposal(kind="message"))

    def test_execution_field_rejected(self):
        with self.assertRaises(ValueError):
            server.validate_reply(self.proposal(approved=True))

    def test_live_mode_rejected(self):
        with self.assertRaises(ValueError):
            server.assistant({"mode": "live"})

    def test_invalid_prompt_rejected(self):
        with self.assertRaises(ValueError):
            server.assistant({"mode": "demo", "prompt": "x" * 4001})

    @patch.dict(server.os.environ, {"AI_PROVIDER": "openai", "OPENAI_API_KEY": "unit-test-only", "OPENAI_MODEL": "test-model"})
    def test_structured_request_and_response(self):
        result = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(self.proposal())}]}]}
        with patch.object(server, "urlopen", return_value=io.BytesIO(json.dumps(result).encode())) as call:
            answer = server.assistant({"mode": "demo", "prompt": "sell 3 AAPL", "holdings": [], "accounts": [], "selected_account": "all", "secret": "do not forward"})
            request = call.call_args.args[0]
            body = json.loads(request.data)
            self.assertFalse(body["store"])
            self.assertTrue(body["text"]["format"]["strict"])
            self.assertNotIn("secret", json.loads(body["input"]))
            self.assertNotIn("tools", body)
            self.assertEqual(answer, self.proposal())

    @patch.dict(server.os.environ, {"AI_PROVIDER": "openai", "OPENAI_API_KEY": "unit-test-only", "OPENAI_MODEL": "test-model"})
    def test_incomplete_and_refusal_fail_closed(self):
        for result in [{"status": "incomplete"}, {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No"}]}]}]:
            with patch.object(server, "urlopen", return_value=io.BytesIO(json.dumps(result).encode())), self.assertRaises(RuntimeError):
                server.assistant({"mode": "demo", "prompt": "sell 3 AAPL", "holdings": [], "accounts": []})

    def test_webull_uses_server_snapshot_and_binds_reply(self):
        proposal = self.proposal()
        payload = {"mode": "webull", "prompt": "sell 3 shares of AAPL", "selected_account": "acct-1",
                   "expected_environment": "sandbox", "journal": [], "positions": [{"symbol": "FAKE"}],
                   "credentials": "must-not-forward"}
        with patch.object(server, "broker", return_value=self.FakeBroker()), \
             patch.object(server, "model_reply", return_value=proposal) as model:
            answer = server.assistant(payload)
        context, instructions = model.call_args.args
        self.assertEqual(context["snapshot"]["positions"][0]["symbol"], "AAPL")
        self.assertEqual(set(context["snapshot"]), {"environment", "positions", "as_of"})
        self.assertNotIn("acct-1", json.dumps(context))
        self.assertNotIn("balance", context["snapshot"])
        self.assertNotIn("credentials", context)
        self.assertNotIn("positions", context)
        self.assertEqual(instructions, server.WEBULL_INSTRUCTIONS)
        self.assertEqual((answer["account_id"], answer["environment"], answer["snapshot_as_of"]),
                         ("acct-1", "sandbox", 1234.0))

    def test_webull_environment_mismatch_fails_before_model(self):
        payload = {"mode": "webull", "prompt": "show my portfolio", "selected_account": "acct-1",
                   "expected_environment": "production", "journal": []}
        with patch.object(server, "broker", return_value=self.FakeBroker()), \
             patch.object(server, "model_reply") as model, self.assertRaises(server.BrokerError):
            server.assistant(payload)
        model.assert_not_called()

    def test_webull_rejects_inferred_or_changed_trade_fields(self):
        for prompt, changes in [("sell some AAPL", {}), ("sell 3 shares of AAPL", {"quantity": "4"}),
                                ("should I sell 3 shares of AAPL?", {}), ("do not sell 3 shares of AAPL", {}),
                                ("sell 3 AAPL and buy 2 MSFT", {}), ("short 3 shares of AAPL", {}),
                                ("sell $3 of AAPL", {}), ("sell 3 shares of AAPL at 100", {}),
                                ("sell .3 shares of AAPL", {"quantity": "3"}),
                                ("sell 1000000000 AAPL", {"quantity": "1000000000"}),
                                ("sell 0.12345678 AAPL", {"quantity": "0.12345678"})]:
            with self.subTest(prompt=prompt), patch.object(server, "broker", return_value=self.FakeBroker()), \
                 patch.object(server, "model_reply", return_value=self.proposal(**changes)), self.assertRaises(ValueError):
                server.assistant({"mode": "webull", "prompt": prompt, "selected_account": "acct-1",
                                  "expected_environment": "sandbox", "journal": []})

    def test_webull_permits_one_exact_simple_command(self):
        for prompt, quantity in (("sell 3 AAPL", "3"), ("Please, sell 3 shares of AAPL.", "3"),
                                 ("sell 999999999.123456 AAPL", "999999999.123456")):
            with self.subTest(prompt=prompt), patch.object(server, "broker", return_value=self.FakeBroker()), \
                 patch.object(server, "model_reply", return_value=self.proposal(quantity=quantity)):
                answer = server.assistant({"mode": "webull", "prompt": prompt, "selected_account": "acct-1",
                                           "expected_environment": "sandbox", "journal": []})
            self.assertEqual(answer["kind"], "trade")


if __name__ == "__main__":
    unittest.main()
