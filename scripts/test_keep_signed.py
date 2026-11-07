import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("keep-iphone-signed.py")
SPEC = importlib.util.spec_from_file_location("keep_iphone_signed", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

ORIGINAL_DEVICE_REACHABLE = MODULE.device_reachable
NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc).timestamp()
DEVICE = "00008140-0010646A1413801C"
LISTING = ("Name  Hostname  Identifier  State  Model  Reality\n"
           f"louis's iPhone  {DEVICE} (UDID)  connected  iPhone 16 (iPhone17,3)  physical\n"
           "my iphone  00008140-001C0D242638801C (UDID)  unavailable  iPhone 16 Pro  physical\n")


class KeepSignedTests(unittest.TestCase):
    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        base = Path(self.folder.name)
        self.profiles, self.state = base / "profiles", base / "state"
        self.profiles.mkdir()
        for name, value in (("PROFILES", self.profiles), ("STATE_DIR", self.state)):
            patcher = mock.patch.object(MODULE, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.expiries = {}
        reader = mock.patch.object(MODULE, "read_profile", side_effect=self.fake_profile)
        reader.start()
        self.addCleanup(reader.stop)
        # No test may build, export, list real devices or install; each test re-patches what it needs.
        for name in ("build_and_install", "export_main", "device_reachable"):
            guard = mock.patch.object(MODULE, name, side_effect=AssertionError(f"unexpected real {name}"))
            guard.start()
            self.addCleanup(guard.stop)

    def fake_profile(self, path):
        if path.name not in self.expiries:
            return None
        bundle, expires = self.expiries[path.name]
        return {"Entitlements": {"application-identifier": f"ANWNGW59GP.{bundle}"},
                "ExpirationDate": datetime.fromtimestamp(expires, timezone.utc).replace(tzinfo=None)}

    def profile(self, name, expires, bundle=MODULE.BUNDLE_ID):
        (self.profiles / name).write_text("profile")
        self.expiries[name] = (bundle, expires)

    def test_only_tradepilot_profiles_count_and_latest_expiry_wins(self):
        self.profile("old.mobileprovision", NOW + 3600)
        self.profile("new.mobileprovision", NOW + 5 * 86400)
        self.profile("other.mobileprovision", NOW + 99 * 86400, bundle="com.example.Other")
        profiles = MODULE.app_profiles(self.profiles)
        self.assertEqual([path.name for path, _ in profiles], ["new.mobileprovision", "old.mobileprovision"])

    def test_refresh_window(self):
        self.assertTrue(MODULE.needs_refresh(None, NOW))
        self.assertTrue(MODULE.needs_refresh(NOW - 1, NOW))
        self.assertTrue(MODULE.needs_refresh(NOW + 47 * 3600, NOW))
        self.assertFalse(MODULE.needs_refresh(NOW + 3 * 86400, NOW))

    def test_device_must_be_connected_and_physical(self):
        with mock.patch.object(MODULE.subprocess, "run", return_value=mock.Mock(stdout=LISTING)), \
                mock.patch.object(MODULE, "device_reachable", ORIGINAL_DEVICE_REACHABLE):
            self.assertTrue(MODULE.device_reachable(DEVICE))
            self.assertFalse(MODULE.device_reachable("00008140-001C0D242638801C"))
            self.assertFalse(MODULE.device_reachable("missing"))

    def test_valid_profile_does_nothing_and_checks_no_device(self):
        self.profile("current.mobileprovision", NOW + 4 * 86400)
        with mock.patch.object(MODULE, "device_reachable") as reachable:
            self.assertIn("nothing to do", MODULE.run(DEVICE, now=NOW))
        reachable.assert_not_called()

    def test_unreachable_phone_waits(self):
        self.profile("current.mobileprovision", NOW + 3600)
        with mock.patch.object(MODULE, "device_reachable", return_value=False), \
                mock.patch.object(MODULE, "build_and_install") as build:
            self.assertIn("not reachable", MODULE.run(DEVICE, now=NOW))
        build.assert_not_called()
        self.assertTrue((self.profiles / "current.mobileprovision").exists())

    def test_refresh_builds_main_installs_and_records_state(self):
        self.profile("current.mobileprovision", NOW + 3600)

        def renew(device, source, derived):
            self.assertFalse((self.profiles / "current.mobileprovision").exists(), "old profile must be set aside")
            self.profile("renewed.mobileprovision", NOW + 7 * 86400)
            return derived
        with mock.patch.object(MODULE, "device_reachable", return_value=True), \
                mock.patch.object(MODULE, "export_main", return_value="abc123def4567") as export, \
                mock.patch.object(MODULE, "build_and_install", side_effect=renew) as build:
            message = MODULE.run(DEVICE, now=NOW)
        export.assert_called_once()
        build.assert_called_once()
        self.assertIn("installed abc123def456", message)
        state = json.loads((self.state / "state.json").read_text())
        self.assertEqual((state["installed_commit"], state["profile_expires_at"]), ("abc123def4567", NOW + 7 * 86400))
        self.assertEqual(list((self.state / "profile-backup").iterdir()), [])

    def test_unrenewed_profile_backs_off_until_it_expires(self):
        self.profile("current.mobileprovision", NOW + 3600)

        def same_profile(device, source, derived):
            self.profile("current.mobileprovision", NOW + 3600)
        with mock.patch.object(MODULE, "device_reachable", return_value=True), \
                mock.patch.object(MODULE, "export_main", return_value="abc"), \
                mock.patch.object(MODULE, "build_and_install", side_effect=same_profile) as build:
            MODULE.run(DEVICE, now=NOW)
            self.assertIn("waiting to retry", MODULE.run(DEVICE, now=NOW + 600))
            self.assertEqual(build.call_count, 1)
            MODULE.run(DEVICE, now=NOW + 3601)  # expired: try again
            self.assertEqual(build.call_count, 2)

    def test_failed_build_restores_the_previous_profile(self):
        self.profile("current.mobileprovision", NOW + 3600)
        with mock.patch.object(MODULE, "device_reachable", return_value=True), \
                mock.patch.object(MODULE, "export_main", return_value="abc"), \
                mock.patch.object(MODULE, "build_and_install", side_effect=RuntimeError("xcodebuild failed")):
            with self.assertRaisesRegex(RuntimeError, "xcodebuild failed"):
                MODULE.run(DEVICE, now=NOW)
        self.assertTrue((self.profiles / "current.mobileprovision").exists())
        self.assertFalse((self.state / "state.json").exists())

    def test_launch_agent_checks_hourly_without_pairing_or_launch(self):
        definition = MODULE.plist(DEVICE)
        self.assertEqual(definition["Label"], "com.tradepilot.keep-signed")
        self.assertEqual(definition["StartInterval"], 3600)
        self.assertEqual(definition["ProgramArguments"][2:], ["run", "--device", DEVICE])
        self.assertNotIn("pairing", json.dumps(definition).lower())
        self.assertTrue(definition["StandardOutPath"].startswith(str(self.state)))


if __name__ == "__main__":
    unittest.main()
