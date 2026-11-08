"""Fixed, nonsecret Windows network-status boundary. No gateway imports or state.

Only the dedicated LocalSystem publisher invokes Tailscale. Consumers can only
read a fresh, administrator-owned receipt; they never invoke privileged commands.
"""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

ROOT = Path(r'C:\ProgramData\TradePilotNetworkStatus')
STATUS = ROOT / 'status.json'
TAILSCALE = Path(r'C:\Program Files\Tailscale\tailscale.exe')
ADMINS = {'S-1-5-18', 'S-1-5-32-544'}
MAX_BYTES = 4096
MAX_OUTPUT = 131072
MAX_AGE = 20
WRITE_RIGHTS = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
SCHEMA = {'version', 'ok', 'BackendState', 'SelfOnline', 'IPv4', 'DNSName',
          'published_utc', 'boot_id', 'uptime_ms'}


def clock():
    """Read the kernel boot GUID and uptime; wall-clock adjustments fail closed."""
    class BootEnvironment(ctypes.Structure):
        _fields_ = [('identifier', ctypes.c_ubyte * 16), ('firmware', wintypes.ULONG),
                    ('flags', ctypes.c_ulonglong)]
    value = BootEnvironment()
    query = ctypes.WinDLL('ntdll').NtQuerySystemInformation
    query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p]
    query.restype = ctypes.c_long
    if query(90, ctypes.byref(value), ctypes.sizeof(value), None) != 0:
        raise ValueError('Cannot establish Windows boot identity')
    ticks = ctypes.WinDLL('kernel32').GetTickCount64
    ticks.restype = ctypes.c_ulonglong
    return datetime.now(timezone.utc), str(uuid.UUID(bytes_le=bytes(value.identifier))), ticks()


def validate_acl(owner, aces):
    """Reject unknown ACE kinds rather than attempting effective-rights inference."""
    if owner not in ADMINS or aces is None:
        raise ValueError('Network status requires administrator ownership and DACL')
    for kind, flags, rights, sid in aces:
        if kind not in (0, 1):
            raise ValueError('Unsupported network status ACE')
        if kind == 0 and not flags & 8 and rights & WRITE_RIGHTS and sid not in ADMINS:
            raise ValueError('Network status has an untrusted writer')


def check_handle(handle, *, directory=False):
    import win32file, win32security as sec
    info = win32file.GetFileInformationByHandle(handle)
    if info[0] & 0x400 or bool(info[0] & 0x10) != directory or (not directory and info[7] != 1):
        raise ValueError('Network status path must be ordinary and unaliased')
    sd = sec.GetSecurityInfo(handle, sec.SE_FILE_OBJECT,
                            sec.OWNER_SECURITY_INFORMATION | sec.DACL_SECURITY_INFORMATION)
    acl = sd.GetSecurityDescriptorDacl()
    rows = None if acl is None else [(a[0][0], a[0][1], a[1], sec.ConvertSidToStringSid(a[-1]))
                                    for a in (acl.GetAce(i) for i in range(acl.GetAceCount()))]
    validate_acl(sec.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()), rows)


@contextmanager
def managed_handle(handle):
    try: yield handle
    finally: handle.Close()


@contextmanager
def open_checked(path, *, directory=False):
    import win32con as con, win32file
    # This module has fixed production paths. Ancestor reparse checks plus a
    # no-delete/no-write-share handle pin each checked directory while used.
    for ancestor in (path, *path.parents):
        if ancestor.lstat().st_file_attributes & 0x400:
            raise ValueError('Network status reparse path rejected')
    handle = win32file.CreateFile(str(path), con.GENERIC_READ | con.READ_CONTROL,
        con.FILE_SHARE_READ, None, con.OPEN_EXISTING,
        0x00200000 | (con.FILE_FLAG_BACKUP_SEMANTICS if directory else 0), None)
    try:
        check_handle(handle, directory=directory)
        yield handle
    finally:
        handle.Close()


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('Oversize network status')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise ValueError('Duplicate network status key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def validate(record, now, boot_id, uptime_ms):
    if not isinstance(record, dict) or set(record) != SCHEMA or type(record['version']) is not int or record['version'] != 1:
        raise ValueError('Invalid network status schema')
    if type(record['ok']) is not bool or type(record['SelfOnline']) is not bool:
        raise ValueError('Invalid network status flags')
    if record['boot_id'] != boot_id or type(record['uptime_ms']) is not int:
        raise ValueError('Network status is from another boot')
    utc = record['published_utc']
    if not isinstance(utc, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', utc):
        raise ValueError('Invalid network status timestamp')
    age = (now - datetime.fromisoformat(utc.replace('Z', '+00:00'))).total_seconds()
    tick_age = (uptime_ms - record['uptime_ms']) / 1000
    if not 0 <= age <= MAX_AGE or not 0 <= tick_age <= MAX_AGE or abs(age - tick_age) > 2:
        raise ValueError('Network status is stale or clock changed')
    if not isinstance(record['BackendState'], str) or record['BackendState'] not in ('Running', 'Stopped', 'NeedsLogin', 'NeedsMachineAuth', 'Starting', 'NoState', 'InUseOtherUser', 'Unavailable'):
        raise ValueError('Invalid network backend state')
    ips = record['IPv4']
    if not isinstance(ips, list) or len(ips) > 4 or len(set(map(str, ips))) != len(ips):
        raise ValueError('Invalid network addresses')
    for value in ips:
        if not isinstance(value, str) or ipaddress.ip_address(value) not in ipaddress.ip_network('100.64.0.0/10'):
            raise ValueError('Invalid Tailscale IPv4')
    dns = record['DNSName']
    if not isinstance(dns, str) or len(dns) > 253 or (dns and not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net\.?', dns)):
        raise ValueError('Invalid MagicDNS name')
    if not record['ok']:
        raise ValueError('Network publisher reports unavailable status')
    return {'BackendState': record['BackendState'],
            'Self': {'Online': record['SelfOnline'], 'TailscaleIPs': ips, 'DNSName': dns}}


def read_status():
    import win32file
    try:
        # Only this protected control root, never private gateway state.
        with open_checked(ROOT, directory=True) as root_handle:
            with open_checked(STATUS) as handle:
                if win32file.GetFileSize(handle) > MAX_BYTES: raise ValueError('Oversize network status')
                _, raw = win32file.ReadFile(handle, MAX_BYTES + 1)
                return validate(decode(raw), *clock())
    except Exception as error:
        raise ValueError('Trusted fresh network status unavailable') from error


def record_status(raw, stamp):
    now, boot_id, ticks = stamp
    record = dict(version=1, ok=False, BackendState='Unavailable', SelfOnline=False, IPv4=[], DNSName='',
                  published_utc=now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), boot_id=boot_id, uptime_ms=ticks)
    if raw is not None:
        data = json.loads(raw)
        me = data.get('Self') or {}
        record.update(ok=True, BackendState=data.get('BackendState'), SelfOnline=me.get('Online'),
                      IPv4=[ip for ip in me.get('TailscaleIPs', []) if isinstance(ip, str) and ':' not in ip],
                      DNSName=me.get('DNSName', ''))
        validate(record, now, boot_id, ticks)
    return record


def query_status(stopped):
    """Fixed executable/arguments. Pipes have a hard retained-output bound."""
    with open_checked(TAILSCALE.parent, directory=True) as executable_directory, open_checked(TAILSCALE) as executable_handle:
        env = {'SystemRoot': r'C:\Windows', 'WINDIR': r'C:\Windows',
               'TEMP': str(ROOT), 'TMP': str(ROOT), 'USERPROFILE': str(ROOT),
               'PATH': r'C:\Windows\System32', 'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': ''}
        child = subprocess.Popen([str(TAILSCALE), 'status', '--json', '--peers=false'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=ROOT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        output = bytearray()
        finished, overflow = threading.Event(), threading.Event()
        def collect():
            try:
                while True:
                    chunk = child.stdout.read(4096)
                    if not chunk: break
                    if len(output) + len(chunk) > MAX_OUTPUT:
                        overflow.set(); break
                    output.extend(chunk)
            finally:
                finished.set()
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 8
            while not finished.wait(.05):
                if stopped.is_set() or overflow.is_set() or time.monotonic() > deadline:
                    raise ValueError('Network status query failed')
            if stopped.is_set() or overflow.is_set() or time.monotonic() > deadline:
                raise ValueError('Network status query failed')
            code = child.wait(timeout=max(.01, deadline - time.monotonic()))
            if code: raise ValueError('Network status query failed')
            return bytes(output)
        finally:
            if child.poll() is None: child.kill()
            child.wait(timeout=2)
            reader.join(2)
            if reader.is_alive(): raise RuntimeError('Network status reader did not stop')
            child.stdout.close()


def receipt_security():
    import win32security as sec
    acl = sec.ACL()
    for sid in ADMINS:
        acl.AddAccessAllowedAce(sec.ACL_REVISION, 0x1f01ff, sec.ConvertStringSidToSid(sid))
    gateway = sec.LookupAccountName(None, 'NT SERVICE\\TradePilot')[0]
    acl.AddAccessAllowedAce(sec.ACL_REVISION, 0x120089, gateway)
    sd = sec.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorOwner(sec.ConvertStringSidToSid('S-1-5-18'), False)
    sd.SetSecurityDescriptorDacl(1, acl, 0)
    sd.SetSecurityDescriptorControl(sec.SE_DACL_PROTECTED, sec.SE_DACL_PROTECTED)
    sa = sec.SECURITY_ATTRIBUTES(); sa.SECURITY_DESCRIPTOR = sd
    return sa


def publish(record):
    import win32con as con, win32file
    raw = (json.dumps(record, separators=(',', ':')) + '\n').encode()
    if len(raw) > MAX_BYTES: raise ValueError('Oversize sanitized network status')
    # Fixed temporary path is in an already validated Admin/System-only-writable
    # root. Existing scratch file is checked before removal; never follow links.
    temporary = ROOT / 'status.tmp'
    with open_checked(ROOT, directory=True) as directory:
        if temporary.exists():
            with open_checked(temporary): pass
            temporary.unlink()
        with managed_handle(win32file.CreateFile(str(temporary), con.GENERIC_WRITE, 0, receipt_security(), con.CREATE_NEW, 0, None)) as handle:
            win32file.WriteFile(handle, raw); win32file.FlushFileBuffers(handle)
        with open_checked(temporary): pass
        if STATUS.exists():
            with open_checked(STATUS): pass
        # Reader may briefly hold a no-delete-share handle. Retry only sharing
        # violation, bounded below the publication/freshness interval.
        for attempt in range(10):
            try: os.replace(temporary, STATUS); break
            except OSError as error:
                if getattr(error, 'winerror', None) != 32 or attempt == 9: raise
                time.sleep(.05)


def run(stopped):
    import win32api, win32con, win32security as sec
    token = sec.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try: sid = sec.ConvertSidToStringSid(sec.GetTokenInformation(token, sec.TokenUser)[0])
    finally: token.Close()
    if sid != 'S-1-5-18': raise ValueError('Dedicated network publisher must use LocalSystem')
    with open_checked(ROOT, directory=True): pass
    try:
        while not stopped.is_set():
            try: record = record_status(query_status(stopped), clock())
            except Exception: record = record_status(None, clock())
            publish(record)
            stopped.wait(5)
    finally:
        publish(record_status(None, clock()))
