import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("update-local-gateway.py")
SPEC = importlib.util.spec_from_file_location("update_local_gateway", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GatewayUpdateTests(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        self.repo, self.root = base / "repo", base / "deployment"
        for directory in (self.repo / "server", self.repo / "scripts", self.root / "server", self.root / "scripts"):
            directory.mkdir(parents=True)
        (self.root / "private").mkdir(mode=0o700)
        (self.root / "private" / "ledger.sqlite3").write_text("authoritative")
        files = {"server/server.py": "new server", "server/market_service.py": "new module",
                 "server/test_market.py": "test only", "scripts/manage-local-service.py": "same",
                 "scripts/check.sh": "not deployed"}
        for name, text in files.items():
            (self.repo / name).write_text(text)
        (self.root / "server/server.py").write_text("old server")
        (self.root / "scripts/manage-local-service.py").write_text("same")

    def tearDown(self):
        self.folder.cleanup()

    def test_plan_lists_runtime_changes_only(self):
        changed, added = MODULE.plan(self.root, self.repo)
        self.assertEqual(changed, ["server/server.py"])
        self.assertEqual(added, ["server/market_service.py"])

    def test_apply_backs_up_installs_restarts_and_verifies(self):
        restart, check = mock.Mock(), mock.Mock()
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout="abc123\n")):
            backup = MODULE.apply(self.root, self.repo, restart_service=restart, check=check)
        restart.assert_called_once_with()
        check.assert_called_once_with(self.root)
        self.assertEqual((self.root / "server/server.py").read_text(), "new server")
        self.assertEqual((self.root / "server/market_service.py").read_text(), "new module")
        self.assertFalse((self.root / "server/test_market.py").exists())
        self.assertFalse((self.root / "scripts/check.sh").exists())
        self.assertEqual(os.stat(self.root / "server/server.py").st_mode & 0o777, 0o600)
        self.assertEqual((backup / "server/server.py").read_text(), "old server")
        manifest = json.loads((backup / "MANIFEST.json").read_text())
        self.assertEqual((manifest["replaced"], manifest["added"], manifest["source_commit"]),
                         (["server/server.py"], ["server/market_service.py"], "abc123"))
        self.assertEqual((self.root / "private/ledger.sqlite3").read_text(), "authoritative")
        self.assertIsNone(MODULE.apply(self.root, self.repo, restart_service=restart, check=check))
        restart.assert_called_once_with()

    def test_rollback_restores_and_removes_added_files(self):
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout="abc123\n")):
            backup = MODULE.apply(self.root, self.repo, restart_service=mock.Mock(), check=mock.Mock())
        restart, check = mock.Mock(), mock.Mock()
        MODULE.rollback(self.root, backup.name, restart_service=restart, check=check)
        self.assertEqual((self.root / "server/server.py").read_text(), "old server")
        self.assertFalse((self.root / "server/market_service.py").exists())
        restart.assert_called_once_with()
        for name in ("../escape", "ledger.sqlite3", "code-backup-other"):
            with self.subTest(name=name), self.assertRaises(SystemExit):
                MODULE.rollback(self.root, name, restart_service=restart, check=check)

    def test_symlinked_deployment_files_are_refused(self):
        (self.root / "server/server.py").unlink()
        (self.root / "server/server.py").symlink_to(self.repo / "server/server.py")
        with self.assertRaises(SystemExit):
            MODULE.plan(self.root, self.repo)

    def test_deployment_must_look_like_a_gateway_and_not_the_checkout(self):
        with self.assertRaises(SystemExit):
            MODULE.deployment_root(str(self.repo))
        with mock.patch.object(MODULE, "REPO", self.root), self.assertRaises(SystemExit):
            MODULE.deployment_root(str(self.root))
        self.assertEqual(MODULE.deployment_root(str(self.root)), self.root.resolve())

    def test_health_check_targets_follow_the_launch_arguments(self):
        arguments = ["python", "manage.py", "serve", "--hostname", "mac.local", "--interface", "en0"]
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout="192.168.1.20\n")):
            self.assertEqual(MODULE.endpoints(arguments), [("192.168.1.20", "mac.local"), ("::1", "mac.local")])
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout="")):
            self.assertEqual(MODULE.endpoints(arguments), [("::1", "mac.local")])
        self.assertEqual(MODULE.endpoints(["python", "manage.py", "serve", "--address", "192.168.1.5"])[0],
                         ("192.168.1.5", "192.168.1.5"))


if __name__ == "__main__":
    unittest.main()
