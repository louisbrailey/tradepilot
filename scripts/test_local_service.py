import argparse
import base64
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("manage-local-service.py")
SPEC = importlib.util.spec_from_file_location("manage_local_service", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
PAIR_SPEC = importlib.util.spec_from_file_location("pair_local_server", SCRIPT.with_name("pair-local-server.py"))
PAIR = importlib.util.module_from_spec(PAIR_SPEC)
assert PAIR_SPEC.loader is not None
PAIR_SPEC.loader.exec_module(PAIR)


def private_inputs(root):
    private = root / "private"
    private.mkdir(mode=0o700)
    for name in ("config.json", "server.key", "server.pem"):
        path = private / name
        path.write_text("placeholder")
        path.chmod(0o600)
    market = root / "market.env"
    market.write_text("MASSIVE_API_KEY=isolated-test-value")
    return argparse.Namespace(private_dir=str(private), address="192.168.1.20", hostname=None,
                              interface=None, market_env=str(market), python=sys.executable, dry_run=False)


class LocalServiceTests(unittest.TestCase):
    def test_install_writes_direct_argv_and_preserves_python_path(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            private = root / "private"
            private.mkdir()
            private.chmod(0o700)
            for name, mode in (("config.json", 0o600), ("server.key", 0o600), ("server.pem", 0o644)):
                path = private / name
                path.write_text("placeholder")
                path.chmod(mode)
            env = root / "market.env"
            env.write_text("MASSIVE_API_KEY=private-value\n")
            python = root / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!python\n")
            python.chmod(0o755)
            destination = root / "LaunchAgents" / "agent.plist"
            args = argparse.Namespace(private_dir=str(private), address="192.168.1.20",
                                      market_env=str(env), python=str(python), dry_run=False)
            completed = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(MODULE, "validate_tls_material"), \
                 mock.patch.object(MODULE, "validate_cert_san"), \
                 mock.patch.object(MODULE, "assert_launch_paths_accessible"), \
                 mock.patch.object(MODULE, "launch_agent_path", return_value=destination), \
                 mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
                MODULE.install(args)
            with destination.open("rb") as handle:
                generated = plistlib.load(handle)
            self.assertEqual(generated["Label"], MODULE.LABEL)
            argv = generated["ProgramArguments"]
            self.assertEqual(argv[0], str(python))
            self.assertEqual(argv[2:], ["--config", str((private / "config.json").resolve()), "--market-env", str(env.resolve()),
                                        "--bind", "192.168.1.20", "--tls-cert", str((private / "server.pem").resolve()),
                                        "--tls-key", str((private / "server.key").resolve())])
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertEqual((private / "server.log").stat().st_mode & 0o777, 0o600)
            self.assertTrue(any(call.args[0][:2] == ["launchctl", "bootstrap"] for call in run.call_args_list))
            self.assertNotIn("private-value", destination.read_text())

    def test_san_parser_matches_any_ip_san_on_line(self):
        result = subprocess.CompletedProcess([], 0, "X509v3 Subject Alternative Name:\n IP Address:10.0.0.2, IP Address:192.168.1.20\n", "")
        with mock.patch.object(MODULE.subprocess, "run", return_value=result):
            MODULE.validate_cert_san(Path("/tmp/cert.pem"), "192.168.1.20")

        result = subprocess.CompletedProcess([], 0, "X509v3 Subject Alternative Name:\n DNS:other.local, DNS:louiss-macbook-pro.local\n", "")
        with mock.patch.object(MODULE.subprocess, "run", return_value=result):
            MODULE.validate_cert_san(Path("/tmp/cert.pem"), hostname="louiss-MacBook-Pro.local")

    def test_hostname_install_uses_dynamic_serve_wrapper(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            private = root / "private"
            private.mkdir(mode=0o700)
            for name, mode in (("config.json", 0o600), ("server.key", 0o600), ("server.pem", 0o644)):
                path = private / name
                path.write_text("placeholder")
                path.chmod(mode)
            env = root / "market.env"
            env.write_text("private-value")
            python = root / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("#!python")
            python.chmod(0o755)
            destination = root / "LaunchAgents" / "agent.plist"
            args = argparse.Namespace(private_dir=str(private), hostname="louiss-macbook-pro.local",
                                      interface="en0", market_env=str(env), python=str(python), dry_run=False,
                                      address=None)
            completed = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(MODULE, "validate_tls_material"), \
                 mock.patch.object(MODULE, "validate_cert_san"), \
                 mock.patch.object(MODULE, "assert_launch_paths_accessible"), \
                 mock.patch.object(MODULE, "launch_agent_path", return_value=destination), \
                 mock.patch.object(MODULE.subprocess, "run", return_value=completed):
                MODULE.install(args)
            with destination.open("rb") as handle:
                generated = plistlib.load(handle)
            argv = generated["ProgramArguments"]
            self.assertEqual(argv[:3], [str(python), str(SCRIPT), "serve"])
            self.assertIn("--hostname", argv)
            self.assertIn("louiss-macbook-pro.local", argv)
            self.assertIn("--interface", argv)
            self.assertIn("en0", argv)
            self.assertEqual(argv[argv.index("--python") + 1], str(python))

    def test_private_directory_must_be_owner_only(self):
        with tempfile.TemporaryDirectory() as root:
            private = Path(root) / "private"
            private.mkdir(mode=0o750)
            args = argparse.Namespace(private_dir=str(private), address="192.168.1.20",
                                      market_env=str(private), python=str(private))
            with self.assertRaises(SystemExit):
                MODULE.validate_inputs(args)


    def test_deploy_preserves_private_state_without_installing_or_copying_other_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "source"
            source.mkdir(mode=0o700)
            runtime = source / "runtime"
            runtime.mkdir(mode=0o700)
            (runtime / "orders.sqlite3").write_bytes(b"saved-journal")
            config = {"APP_ACCESS_TOKEN": "private-token", "WEBULL_LIVE_TRADING": "disabled",
                      "AI_PROVIDER": "ollama", "OLLAMA_MODEL": "local-test-model",
                      "TRADEPILOT_RUNTIME": str(runtime)}
            (source / "config.json").write_text(json.dumps(config))
            for name in ("server.key", "server.pem", "TradePilotPairing.json"):
                (source / name).write_text("private-" + name)
            for path in source.iterdir():
                path.chmod(0o700 if path.is_dir() else 0o600)
            market = root / "market.env"
            market.write_text("MASSIVE_API_KEY=market-secret\nUNRELATED_API_KEY=must-not-copy\n")
            python = root / "source-python"
            python.write_text("#!python")
            python.chmod(0o700)
            packages = root / "packages"
            packages.mkdir()
            (packages / "sdk.py").write_text("# existing package")
            destination = root / "deployment"
            def python_paths(executable):
                directory = packages if executable == python else destination / "venv" / "lib" / "site-packages"
                return {"purelib": str(directory), "platlib": str(directory)}
            args = argparse.Namespace(private_dir=str(source), address="192.168.1.20", hostname=None,
                                      interface=None, market_env=str(market), python=str(python),
                                      destination=str(destination), dry_run=False, source_stopped=True)
            with mock.patch.object(MODULE, "validate_tls_material"), \
                 mock.patch.object(MODULE, "validate_cert_san"), \
                 mock.patch.object(MODULE, "inspect_python", side_effect=python_paths), \
                 mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                MODULE.deploy(args)
            new_config = json.loads((destination / "private" / "config.json").read_text())
            self.assertEqual(new_config["APP_ACCESS_TOKEN"], config["APP_ACCESS_TOKEN"])
            self.assertEqual(new_config["WEBULL_LIVE_TRADING"], "disabled")
            self.assertEqual(new_config["AI_PROVIDER"], "ollama")
            self.assertEqual(new_config["OLLAMA_MODEL"], "local-test-model")
            self.assertEqual((destination / "BACKTEST-SUMMARY.json").read_bytes(),
                             (SCRIPT.parent.parent / "BACKTEST-SUMMARY.json").read_bytes())
            self.assertEqual(new_config["TRADEPILOT_RUNTIME"], str(destination / "private" / "runtime"))
            self.assertEqual(json.loads((source / "config.json").read_text()), config)
            self.assertEqual((destination / "private" / "runtime" / "orders.sqlite3").read_bytes(), b"saved-journal")
            self.assertEqual((destination / "private" / "server.key").read_text(), "private-server.key")
            self.assertNotIn("UNRELATED", (destination / "private" / "market.env").read_text())
            self.assertEqual((destination / "private").stat().st_mode & 0o777, 0o700)
            for path in (destination / "private").rglob("*"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
            self.assertFalse(any(call.args[0][0] == "launchctl" for call in run.call_args_list))
            with self.assertRaises(SystemExit):
                with mock.patch.object(MODULE, "validate_cert_san"):
                    MODULE.deploy(args)

    def test_frozen_evaluation_requires_valid_ordinary_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "BACKTEST-SUMMARY.json"
            with self.assertRaises(SystemExit):
                MODULE.evaluation_artifact(root)
            artifact.write_text("{}")
            with self.assertRaises(SystemExit):
                MODULE.evaluation_artifact(root)
            valid = json.dumps({"evaluated_at": "2026-09-12T00:00:00Z", "protocol": {}, "results": {}})
            artifact.write_text(valid)
            self.assertEqual(MODULE.evaluation_artifact(root), valid.encode())
            artifact.unlink()
            original = root / "other.json"
            original.write_text(valid)
            artifact.symlink_to(original)
            with self.assertRaises(SystemExit):
                MODULE.evaluation_artifact(root)

    def test_runtime_symlinks_are_rejected_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            source = root / "runtime"
            source.mkdir()
            original = root / "other.txt"
            original.write_text("unrelated")
            (source / "link").symlink_to(original)
            with self.assertRaises(SystemExit):
                MODULE.copy_runtime(source, root / "destination")
            self.assertEqual(original.read_text(), "unrelated")
            self.assertFalse((root / "destination").exists())

    def test_background_paths_and_invalid_networks_fail_closed(self):
        home = Path.home()
        self.assertTrue(MODULE.protected_location(home / "Documents" / "gateway"))
        self.assertFalse(MODULE.protected_location(home / "Library" / "Application Support" / "TradePilot"))
        for address in ("127.0.0.1", "0.0.0.0", "169.254.1.2", "8.8.8.8", "::1", "224.1.1.1"):
            with self.assertRaises(SystemExit):
                MODULE.validate_address(address)
        self.assertEqual(MODULE.validate_address("192.168.68.66"), "192.168.68.66")


class PairingTests(unittest.TestCase):
    def test_existing_tls_or_pairing_refusal_preserves_config_byte_for_byte(self):
        for filename in ("server.key", "server.pem", "TradePilotPairing.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                original = b'{"WEBULL_LIVE_TRADING": "disabled"}\n'
                config = root / "config.json"
                config.write_bytes(original)
                config.chmod(0o600)
                (root / filename).write_text("existing")
                with self.assertRaises(SystemExit), mock.patch.object(PAIR, "certificate_material") as create:
                    PAIR.create_pairing(str(root), "192.168.1.20")
                create.assert_not_called()
                self.assertEqual(config.read_bytes(), original)
                self.assertEqual(sorted(path.name for path in root.iterdir()), sorted(["config.json", filename]))

    def test_unusable_network_addresses_fail_before_creating_private_files(self):
        for address in ("0.0.0.0", "127.0.0.1", "169.254.1.2", "8.8.8.8", "::", "::1", "fe80::1", "224.1.1.1", "not-an-ip"):
            with self.subTest(address=address), tempfile.TemporaryDirectory() as folder:
                root = Path(folder) / "new-private"
                with self.assertRaises(SystemExit):
                    PAIR.create_pairing(str(root), address)
                self.assertFalse(root.exists())

    def test_readable_private_directory_is_refused_without_changing_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            root.chmod(0o755)
            with self.assertRaises(SystemExit):
                PAIR.create_pairing(str(root), "192.168.1.20")
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(root.iterdir()), [])

    def test_invalid_config_or_short_existing_token_is_preserved(self):
        for content in ('[]', '{"APP_ACCESS_TOKEN": "short"}', '{"APP_ACCESS_TOKEN": 42}', '{invalid'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as folder:
                config = Path(folder) / "config.json"
                config.write_text(content)
                config.chmod(0o600)
                with self.assertRaises(SystemExit), mock.patch.object(PAIR, "certificate_material") as create:
                    PAIR.create_pairing(folder, "192.168.1.20")
                create.assert_not_called()
                self.assertEqual(config.read_text(), content)
                self.assertEqual([path.name for path in Path(folder).iterdir()], ["config.json"])

    def test_symlinked_config_and_dangling_tls_paths_are_refused(self):
        for filename in ("config.json", "server.key", "TradePilotPairing.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                private = root / "private"
                private.mkdir(mode=0o700)
                target = root / "unrelated"
                (private / filename).symlink_to(target)
                with self.assertRaises(SystemExit):
                    PAIR.create_pairing(str(private), "192.168.1.20")
                self.assertFalse(target.exists())

    def test_generation_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "new-private"
            with mock.patch.object(PAIR, "certificate_material", side_effect=SystemExit("dependency unavailable")):
                with self.assertRaises(SystemExit):
                    PAIR.create_pairing(str(root), "192.168.1.20")
            self.assertFalse(root.exists())

    def test_success_preserves_existing_config_and_secures_all_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_config = {"APP_ACCESS_TOKEN": "isolated-test-token-" * 3, "AI_PROVIDER": "ollama"}
            (root / "config.json").write_text(json.dumps(old_config))
            (root / "config.json").chmod(0o600)
            prior_umask = os.umask(0o022)
            try:
                with mock.patch.object(PAIR, "certificate_material", return_value=(b"test-key", b"test-cert", b"test-der")):
                    PAIR.create_pairing(str(root), "192.168.1.20", "Test-Mac.local")
                observed = os.umask(0o022)
            finally:
                os.umask(prior_umask)
            self.assertEqual(observed, 0o022)
            config = json.loads((root / "config.json").read_text())
            for key, value in old_config.items():
                self.assertEqual(config[key], value)
            self.assertEqual(config["WEBULL_LIVE_TRADING"], "disabled")
            pair = json.loads((root / "TradePilotPairing.json").read_text())
            self.assertEqual(pair["endpoint"], "https://test-mac.local:8787")
            self.assertEqual(pair["token"], old_config["APP_ACCESS_TOKEN"])
            self.assertEqual(base64.b64decode(pair["certificate"]), b"test-der")
            for path in root.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class LaunchPreflightTests(unittest.TestCase):
    def test_expired_or_not_yet_valid_certificate_is_refused(self):
        cases = (("Jan  1 00:00:00 2020 GMT", "Jan  1 00:00:00 2021 GMT"),
                 ("Jan  1 00:00:00 2040 GMT", "Jan  1 00:00:00 2041 GMT"))
        for before, after in cases:
            result = subprocess.CompletedProcess([], 0, f"notBefore={before}\nnotAfter={after}\n", "")
            with self.subTest(before=before), mock.patch.object(MODULE.ssl, "SSLContext"), \
                 mock.patch.object(MODULE.time, "time", return_value=1800000000), \
                 mock.patch.object(MODULE.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(SystemExit, "expired or not yet valid"):
                    MODULE.validate_tls_material(Path("cert"), Path("key"))

    def test_real_tls_material_accepts_matching_key_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cert, key, other = root / "cert.pem", root / "key.pem", root / "other.key"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                            "-subj", "/CN=isolated-test", "-keyout", str(key), "-out", str(cert)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run(["openssl", "genrsa", "-out", str(other), "2048"],
                           check=True, capture_output=True, timeout=30)
            MODULE.validate_tls_material(cert, key)
            with self.assertRaisesRegex(SystemExit, "mismatched"):
                MODULE.validate_tls_material(cert, other)

    def test_invalid_tls_preflight_cannot_call_launchctl(self):
        with tempfile.TemporaryDirectory() as folder:
            args = private_inputs(Path(folder))
            with mock.patch.object(MODULE, "validate_tls_material", side_effect=SystemExit("bad TLS")), \
                 mock.patch.object(MODULE.subprocess, "run") as run:
                with self.assertRaises(SystemExit):
                    MODULE.install(args)
            run.assert_not_called()
            self.assertFalse((Path(args.private_dir) / "server.log").exists())

    def test_symlinked_log_cannot_modify_an_unrelated_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            args = private_inputs(root)
            args.dry_run = True
            unrelated = root / "unrelated"
            unrelated.write_text("preserve")
            unrelated.chmod(0o644)
            (Path(args.private_dir) / "server.log").symlink_to(unrelated)
            with mock.patch.object(MODULE, "validate_tls_material"), mock.patch.object(MODULE, "validate_cert_san"):
                with self.assertRaisesRegex(SystemExit, "log must be an ordinary file"):
                    MODULE.install(args)
            self.assertEqual(unrelated.read_text(), "preserve")
            self.assertEqual(unrelated.stat().st_mode & 0o777, 0o644)

    def test_foreground_address_mode_validates_before_executing(self):
        with tempfile.TemporaryDirectory() as folder:
            args = private_inputs(Path(folder))
            with mock.patch.object(MODULE, "validate_tls_material") as validate, \
                 mock.patch.object(MODULE, "validate_cert_san") as san, \
                 mock.patch.object(MODULE.os, "execv") as execute, \
                 mock.patch.object(MODULE, "discover_interface_address") as discover:
                MODULE.serve(args)
            validate.assert_called_once()
            san.assert_called_once()
            discover.assert_not_called()
            argv = execute.call_args.args[1]
            self.assertEqual(argv[argv.index("--bind") + 1], "192.168.1.20")

    def test_shell_helpers_report_missing_arguments_as_failures(self):
        for filename in ("start-private-server.sh", "install-iphone.sh"):
            for args, expected in (([], 2), (["--help"], 0)):
                with self.subTest(filename=filename, args=args):
                    result = subprocess.run(["bash", str(SCRIPT.with_name(filename)), *args], capture_output=True)
                    self.assertEqual(result.returncode, expected)

    def test_manual_launcher_refuses_wildcard_before_starting_server(self):
        with tempfile.TemporaryDirectory() as folder:
            args = private_inputs(Path(folder))
            result = subprocess.run(["bash", str(SCRIPT.with_name("start-private-server.sh")), args.private_dir,
                                     "0.0.0.0", args.market_env], text=True, capture_output=True,
                                    env=dict(os.environ, VENV_PYTHON=sys.executable), timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wildcard/public binds are refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
