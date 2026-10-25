"""Detect macOS LAN bind-address changes; lifecycle/restart belongs to the caller."""
import ipaddress
import math
import re
import subprocess


def _interface(value):
    if not isinstance(value, str) or not re.fullmatch(r'en[0-9]{1,2}', value):
        raise ValueError('Expected a macOS en0 through en99 interface')
    return value


def _private_ipv4(value):
    if not isinstance(value, str):
        return None
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        return None
    if (not address.is_private or address.is_loopback or address.is_link_local or
            address.is_multicast or address.is_unspecified or address.is_reserved):
        return None
    return str(address)


def interface_address(interface):
    """Return a usable private IPv4 bind address, or None when unavailable."""
    interface = _interface(interface)
    try:
        result = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface],
                                capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    return _private_ipv4(result.stdout.strip())


def watch_interface(interface, initial_address, stop_event, on_change, interval=30, *, getter=None, wait=None):
    """Poll until stopped or changed/lost; invoke on_change once then return True.

    Run from a separate thread. The caller can pass HTTPServer.shutdown as the
    callback, then close/join active request workers and let launchd restart.
    This module neither kills processes nor changes a running server's socket.
    getter and wait are dependency injection seams for deterministic tests.
    """
    interface = _interface(interface)
    address = _private_ipv4(initial_address)
    if address is None:
        raise ValueError('Initial bind address must be a private IPv4 address')
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError('Poll interval must be positive and finite')
    getter = interface_address if getter is None else getter
    wait = stop_event.wait if wait is None else wait
    while not stop_event.is_set():
        if wait(interval) or stop_event.is_set():
            return False
        try:
            current = _private_ipv4(getter(interface))
        except Exception:
            # Discovery failed: stale bind state cannot establish reachability.
            current = None
        if stop_event.is_set():
            return False
        if current != address:
            on_change()
            return True
    return False
