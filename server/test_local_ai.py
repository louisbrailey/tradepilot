import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from inference_guard import InferenceLock


class LocalAITests(unittest.TestCase):
    MODEL = "installed-local:latest"

    def setUp(self):
        self.environment = patch.dict(server.os.environ, {
            "AI_PROVIDER": "ollama", "OLLAMA_MODEL": self.MODEL,
            "OPENAI_API_KEY": "must-not-send", "OPENAI_MODEL": "remote-fallback-forbidden"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def proposal(self, **changes):
        return {"kind": "trade", "message": "Review this proposal.", "side": "sell",
                "quantity": "3", "symbol": "AAPL", **changes}

    def metadata(self, **changes):
        return {"details": {"format": "gguf", "family": "qwen35"},
                "model_info": {"general.architecture": "qwen35"}, **changes}

    def completion(self, proposal=None, **changes):
        return {"model": self.MODEL, "done": True, "done_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(proposal or self.proposal())}, **changes}

    def test_configured_provider_and_model_are_reported_without_network_or_secrets(self):
        with patch.object(server, "local_ollama_request") as local, patch.object(server, "urlopen") as remote:
            result = server.setup_status()
        self.assertEqual(result["ai_provider"], "ollama")
        self.assertEqual(result["ai_model"], self.MODEL)
        self.assertTrue(result["ai_configured"])
        self.assertTrue(result["configuration_only"])
        self.assertNotIn("must-not-send", json.dumps(result))
        local.assert_not_called(); remote.assert_not_called()

    def test_private_config_accepts_provider_selection_but_not_remote_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            if server.os.name == "nt":
                from windows_runtime import create_scratch_root
                directory = create_scratch_root(Path(directory) / "private")
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"AI_PROVIDER": "ollama", "OLLAMA_MODEL": self.MODEL}))
            config.chmod(0o600)
            server.load_private_config(config)
            self.assertEqual(server.ai_configuration(), ("ollama", self.MODEL, True))
            config.write_text(json.dumps({"OLLAMA_HOST": "https://remote.invalid"}))
            with self.assertRaises(ValueError):
                server.load_private_config(config)

    def test_structured_local_request_has_no_tools_credentials_or_remote_fallback(self):
        with patch.object(server, "local_ollama_request", side_effect=[self.metadata(), self.completion()]) as local, \
                patch.object(server, "urlopen") as remote:
            result = server.assistant({"mode": "demo", "prompt": "sell 3 AAPL", "holdings": [],
                                       "accounts": [], "secret": "do not forward"})
        self.assertEqual(result, self.proposal())
        calls = local.call_args_list
        self.assertEqual(calls[0].args, ("/api/show", {"model": self.MODEL}))
        self.assertEqual(calls[0].kwargs["timeout"], 10)
        self.assertEqual(calls[1].args[0], "/api/chat")
        self.assertEqual(calls[1].kwargs["timeout"], 90)
        body = calls[1].args[1]
        nontrade, trade = body["format"]["oneOf"]
        self.assertEqual(nontrade["properties"]["kind"]["enum"], ["message", "portfolio"])
        self.assertEqual(trade["properties"]["kind"], {"const": "trade"})
        for field in ("side", "quantity", "symbol"):
            self.assertIn(field, nontrade["required"])
            self.assertIn(field, trade["required"])
            self.assertEqual(nontrade["properties"][field]["type"], "null")
            self.assertEqual(trade["properties"][field]["type"], "string")
        self.assertFalse(body["stream"]); self.assertFalse(body["think"])
        self.assertFalse(body["truncate"]); self.assertFalse(body["shift"])
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertNotIn("tools", body)
        self.assertEqual([message["role"] for message in body["messages"]], ["system", "user"])
        self.assertNotIn("secret", json.loads(body["messages"][1]["content"]))
        self.assertNotIn("must-not-send", json.dumps(body))
        remote.assert_not_called()

    def test_cloud_or_unknown_model_is_rejected_before_context_is_sent(self):
        for metadata in (self.metadata(remote_model="remote"), self.metadata(remote_host="https://remote.invalid"),
                         self.metadata(details={}), self.metadata(model_info={}), {"error": "missing model"}):
            with self.subTest(metadata=metadata), \
                    patch.object(server, "local_ollama_request", return_value=metadata) as local, \
                    patch.object(server, "urlopen") as remote, self.assertRaises(RuntimeError):
                server.model_reply({"prompt": "private portfolio"}, server.INSTRUCTIONS)
            self.assertEqual(local.call_count, 1)
            self.assertNotIn("private portfolio", json.dumps(local.call_args.args))
            remote.assert_not_called()

    def test_partial_wrong_model_remote_and_tool_responses_fail_closed(self):
        invalid = [self.completion(done=False), self.completion(done_reason="length"),
                   self.completion(done_reason=None), self.completion(model="different:latest"),
                   self.completion(remote_host="https://remote.invalid"),
                   self.completion(message={"role": "user", "content": json.dumps(self.proposal())}),
                   self.completion(message={"role": "assistant", "content": json.dumps(self.proposal()),
                                            "tool_calls": [{"function": {"name": "sell"}}]}),
                   self.completion(message={"role": "assistant", "content": ""}),
                   self.completion(message=None)]
        for completion in invalid:
            with self.subTest(completion=completion), \
                    patch.object(server, "local_ollama_request", side_effect=[self.metadata(), completion]), \
                    patch.object(server, "urlopen") as remote, self.assertRaises(RuntimeError):
                server.model_reply({}, server.INSTRUCTIONS)
            remote.assert_not_called()

    def test_malformed_json_and_extra_execution_fields_fail_validation(self):
        for content in ('not JSON', '{"kind":', json.dumps(self.proposal(approved=True)),
                        json.dumps(self.proposal(quantity="NaN")), json.dumps(self.proposal(kind="message"))):
            completion = self.completion(message={"role": "assistant", "content": content})
            with self.subTest(content=content), \
                    patch.object(server, "local_ollama_request", side_effect=[self.metadata(), completion]), \
                    self.assertRaises(ValueError):
                server.model_reply({}, server.INSTRUCTIONS)

    def test_failure_never_uses_openai_even_when_credentials_exist(self):
        for failure in (TimeoutError("local timeout"), ConnectionError("not running"), RuntimeError("model missing")):
            with self.subTest(failure=failure), \
                    patch.object(server, "local_ollama_request", side_effect=failure), \
                    patch.object(server, "urlopen") as remote, self.assertRaises(type(failure)):
                server.model_reply({}, server.INSTRUCTIONS)
            remote.assert_not_called()
        # Failure releases the inference lock for the next independent request.
        with patch.object(server, "local_ollama_request", side_effect=[self.metadata(), self.completion()]):
            self.assertEqual(server.model_reply({}, server.INSTRUCTIONS), self.proposal())

    def test_invalid_or_missing_local_configuration_never_falls_back(self):
        for config in ({"OLLAMA_MODEL": ""}, {"OLLAMA_MODEL": "https://remote.invalid/model"}, {"AI_PROVIDER": "unknown"}):
            with self.subTest(config=config), patch.dict(server.os.environ, config), \
                    patch.object(server, "local_ollama_request") as local, \
                    patch.object(server, "urlopen") as remote, self.assertRaises(RuntimeError):
                server.model_reply({}, server.INSTRUCTIONS)
            local.assert_not_called(); remote.assert_not_called()

    def test_ipv6_loopback_and_remote_host_rejection(self):
        class Response(io.BytesIO):
            status = 200
        with patch.dict(server.os.environ, {"OLLAMA_LOOPBACK_HOST": "::1"}), patch.object(server, "build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value = Response(b'{}')
            self.assertEqual(server.local_ollama_request("/api/show", {}, timeout=10), {})
            self.assertEqual(build.return_value.open.call_args.args[0].full_url, "http://[::1]:11434/api/show")
        for host in ("localhost", "192.168.1.2", "remote.example", "::ffff:127.0.0.1", ""):
            with self.subTest(host=host), patch.dict(server.os.environ, {"OLLAMA_LOOPBACK_HOST": host}), patch.object(server, "build_opener") as build:
                with self.assertRaisesRegex(RuntimeError, "explicit loopback"):
                    server.local_ollama_request("/api/show", {}, timeout=10)
                build.assert_not_called()

    def test_busy_local_model_does_not_queue_another_generation(self):
        server._local_ai_lock.acquire()
        try:
            with patch.object(server, "local_ollama_request") as local, self.assertRaises(RuntimeError):
                server.model_reply({}, server.INSTRUCTIONS)
            local.assert_not_called()
        finally:
            server._local_ai_lock.release()

    def test_loopback_transport_disables_proxies_redirects_and_authorization(self):
        class Response(io.BytesIO):
            status = 200
        with patch.dict(server.os.environ, {"HTTP_PROXY": "https://remote.invalid", "OLLAMA_HOST": "https://remote.invalid"}), \
                patch.object(server, "build_opener") as build:
            build.return_value.open.return_value = Response(json.dumps(self.metadata()).encode())
            server.local_ollama_request("/api/show", {"model": self.MODEL}, timeout=10)
        proxy, redirects = build.call_args.args
        self.assertEqual(proxy.proxies, {})
        self.assertIsNone(redirects.redirect_request(None, None, 302, "Found", {}, "https://remote.invalid"))
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/show")
        self.assertIsNone(request.get_header("Authorization"))
        with self.assertRaises(RuntimeError):
            server.local_ollama_request("https://remote.invalid", {}, timeout=10)

    def test_transport_rejects_provider_errors_oversized_and_nonobject_responses(self):
        for status, raw in ((500, b'{"error":"failure"}'), (200, b'{"error":"failure"}'),
                            (200, b'[]'), (200, b' ' * 1_048_577)):
            with self.subTest(status=status, size=len(raw)), patch.object(server, "build_opener") as build:
                response = io.BytesIO(raw)
                response.status = status
                build.return_value.open.return_value = response
                with self.assertRaises(RuntimeError):
                    server.local_ollama_request("/api/show", {"model": self.MODEL}, timeout=10)

    def test_windows_transport_rejects_incomplete_valid_proposal_and_poisons_lock(self):
        for done in (False, None, 1):
            completion = self.completion(done=done)
            # The embedded proposal is valid; completion state alone must reject it.
            self.assertEqual(server.validate_reply(json.loads(completion["message"]["content"])), self.proposal())
            lock = InferenceLock()
            response = io.BytesIO(json.dumps(completion).encode())
            response.status = 200
            with self.subTest(done=done), patch.object(server.os, "name", "nt"), \
                    patch.object(server, "_local_ai_lock", lock), patch.object(server, "build_opener") as build:
                build.return_value.open.return_value = response
                with self.assertRaisesRegex(RuntimeError, "Local model response was incomplete"):
                    server.local_ollama_request("/api/chat", {"model": self.MODEL}, timeout=90)
            self.assertTrue(lock.poisoned())
            self.assertFalse(lock.acquire(blocking=False))
            self.assertTrue(response.closed)

    def test_windows_incomplete_transport_never_returns_an_assistant_proposal(self):
        responses = [io.BytesIO(json.dumps(payload).encode())
                     for payload in (self.metadata(), self.completion(done=False))]
        for response in responses:
            response.status = 200
        lock = InferenceLock()
        with patch.object(server.os, "name", "nt"), patch.object(server, "_local_ai_lock", lock), \
                patch.object(server, "build_opener") as build, \
                patch.object(server, "validate_reply", wraps=server.validate_reply) as validate, \
                patch.object(server, "urlopen") as remote:
            build.return_value.open.side_effect = responses
            with self.assertRaisesRegex(RuntimeError, "Local model response was incomplete"):
                server.assistant({"mode": "demo", "prompt": "sell 3 AAPL", "holdings": [], "accounts": []})
            validate.assert_not_called()
            self.assertTrue(lock.poisoned())
            self.assertFalse(lock.locked())
            with self.assertRaisesRegex(RuntimeError, "already processing"):
                server.model_reply({}, server.INSTRUCTIONS)
            self.assertEqual(build.return_value.open.call_count, 2)
            remote.assert_not_called()

    def test_transport_preserves_completed_windows_and_existing_posix_replies(self):
        for platform, done in (("nt", True), ("posix", True), ("posix", False)):
            completion = self.completion(done=done)
            response = io.BytesIO(json.dumps(completion).encode())
            response.status = 200
            lock = InferenceLock()
            with self.subTest(platform=platform, done=done), patch.object(server.os, "name", platform), \
                    patch.object(server, "_local_ai_lock", lock), patch.object(server, "build_opener") as build:
                build.return_value.open.return_value = response
                self.assertEqual(server.local_ollama_request("/api/chat", {"model": self.MODEL}, timeout=90), completion)
            self.assertFalse(lock.poisoned())

    def test_local_webull_proposal_still_requires_exact_user_command(self):
        class Broker:
            def state(self, account):
                return {"environment": "sandbox", "accounts": [{"id": account}], "positions": [], "as_of": 1234}
        for prompt, proposal in (("sell 3 AAPL", self.proposal(quantity="4")),
                                 ("should I sell 3 AAPL?", self.proposal())):
            with self.subTest(prompt=prompt), patch.object(server, "broker", return_value=Broker()), \
                    patch.object(server, "local_ollama_request", side_effect=[self.metadata(), self.completion(proposal)]), \
                    self.assertRaises(ValueError):
                server.assistant({"mode": "webull", "prompt": prompt, "selected_account": "account",
                                  "expected_environment": "sandbox"})


if __name__ == "__main__":
    unittest.main()
