import subprocess
import threading
import unittest
from unittest.mock import Mock, patch
from network_watch import interface_address, watch_interface


class NetworkWatchTests(unittest.TestCase):
    def test_same_then_changed_calls_once_and_returns(self):
        getter = Mock(side_effect=['192.168.1.20', '192.168.1.21'])
        changed, wait = Mock(), Mock(return_value=False)
        self.assertTrue(watch_interface('en0', '192.168.1.20', threading.Event(), changed,
                                        getter=getter, wait=wait))
        changed.assert_called_once_with()
        self.assertEqual(getter.call_count, 2)
        self.assertEqual(wait.call_count, 2)
        wait.assert_called_with(30)

    def test_loss_invalid_and_failure_trigger_shutdown(self):
        for result in (None, '', '8.8.8.8', '127.0.0.1', '169.254.1.2', '::1', RuntimeError('failure')):
            getter = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
            changed = Mock()
            with self.subTest(result=result):
                self.assertTrue(watch_interface('en12', '10.0.0.2', threading.Event(), changed,
                                                getter=getter, wait=lambda _: False))
                changed.assert_called_once_with()

    def test_already_stopped_and_stop_during_wait(self):
        stop, getter, changed = threading.Event(), Mock(), Mock()
        stop.set()
        self.assertFalse(watch_interface('en0', '10.0.0.2', stop, changed, getter=getter))
        getter.assert_not_called()
        stop.clear()
        self.assertFalse(watch_interface('en0', '10.0.0.2', stop, changed, getter=getter, wait=lambda _: True))
        getter.assert_not_called()
        changed.assert_not_called()

    def test_stop_during_discovery_does_not_signal_change(self):
        stop, changed = threading.Event(), Mock()
        def getter(_):
            stop.set()
            return None
        self.assertFalse(watch_interface('en0', '10.0.0.2', stop, changed, getter=getter, wait=lambda _: False))
        changed.assert_not_called()

    def test_invalid_interface_address_and_interval(self):
        for interface in ('en0;echo', 'en100', 'lo0', '-h', '', None):
            with self.subTest(interface=interface), self.assertRaises(ValueError):
                watch_interface(interface, '10.0.0.2', threading.Event(), Mock())
        for address in ('0.0.0.0', '8.8.8.8', '224.0.0.1', '127.0.0.1', '::1', True, 167772162):
            with self.subTest(address=address), self.assertRaises(ValueError):
                watch_interface('en0', address, threading.Event(), Mock())
        for interval in (0, -1, True, float('nan'), float('inf'), '30'):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                watch_interface('en0', '10.0.0.2', threading.Event(), Mock(), interval)

    @patch('network_watch.subprocess.run')
    def test_discovery_fixed_argv_and_timeout(self, run):
        run.return_value = Mock(returncode=0, stdout='192.168.1.20\n')
        self.assertEqual(interface_address('en0'), '192.168.1.20')
        run.assert_called_once_with(['/usr/sbin/ipconfig', 'getifaddr', 'en0'],
                                    capture_output=True, text=True, timeout=10, check=False)
        for output in ('bad', '169.254.1.2', '255.255.255.255'):
            run.return_value = Mock(returncode=0, stdout=output)
            self.assertIsNone(interface_address('en0'))
        run.return_value = Mock(returncode=1, stdout='192.168.1.20')
        self.assertIsNone(interface_address('en0'))
        for error in (OSError(), subprocess.TimeoutExpired('ipconfig', 10)):
            run.side_effect = error
            self.assertIsNone(interface_address('en0'))
        run.reset_mock()
        with self.assertRaises(ValueError):
            interface_address('en0 && id')
        run.assert_not_called()

    def test_callback_exception_propagates_without_retry(self):
        callback = Mock(side_effect=RuntimeError('shutdown failed'))
        with self.assertRaises(RuntimeError):
            watch_interface('en0', '10.0.0.2', threading.Event(), callback,
                            getter=lambda _: None, wait=lambda _: False)
        callback.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
