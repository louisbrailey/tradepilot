"""Windows-only primitives. No installation, listener or service starts on import.

Trusted principals are the current service identity, SYSTEM and Administrators.
Private roots must be provisioned before use; never infer privacy from chmod.
"""
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import shutil
import time


def _api():
    import win32api, win32con, win32file, win32security
    return win32api, win32con, win32file, win32security


def trusted_sids():
    api, con, _, sec = _api()
    token = sec.OpenProcessToken(api.GetCurrentProcess(), con.TOKEN_QUERY)
    try:
        current = sec.GetTokenInformation(token, sec.TokenUser)[0]
    finally:
        token.Close()
    return {sec.ConvertSidToStringSid(current), 'S-1-5-18', 'S-1-5-32-544'}


def ordinary_path(path):
    """Reject UNC, relative/ADS paths and every existing reparse ancestor."""
    p = Path(path)
    if not p.is_absolute() or str(p).startswith(('\\\\', '//')) or ':' in str(p)[2:]:
        raise ValueError('Expected absolute local NTFS path')
    if '..' in p.parts:
        raise ValueError('Parent traversal is forbidden')
    for item in (p, *p.parents):
        if item.exists() or item.is_symlink():
            if item.lstat().st_file_attributes & 0x400:
                raise ValueError('Reparse paths are forbidden')
    return p


def private_path(path, directory=False):
    p = ordinary_path(path)
    if not (p.is_dir() if directory else p.is_file()):
        raise ValueError('Private path has wrong type')
    if not directory and p.stat().st_nlink != 1:
        raise ValueError('Private files must not have hard-link aliases')
    _, _, _, sec = _api()
    sd = sec.GetNamedSecurityInfo(str(p), sec.SE_FILE_OBJECT,
                                sec.OWNER_SECURITY_INFORMATION | sec.DACL_SECURITY_INFORMATION)
    trusted = trusted_sids()
    if sec.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) not in trusted:
        raise ValueError('Untrusted private-path owner')
    acl = sd.GetSecurityDescriptorDacl()
    if acl is None:
        raise ValueError('NULL DACL is public')
    for i in range(acl.GetAceCount()):
        ace = acl.GetAce(i)
        kind, flags = ace[0]
        # Fail closed for object/callback ACEs rather than misinterpreting them.
        if kind not in (sec.ACCESS_ALLOWED_ACE_TYPE, sec.ACCESS_DENIED_ACE_TYPE):
            raise ValueError('Unsupported private-path ACE')
        if kind == sec.ACCESS_ALLOWED_ACE_TYPE and not flags & 8:
            if ace[1] and sec.ConvertSidToStringSid(ace[2]) not in trusted:
                raise ValueError('Private data is accessible to another principal')
    return p


def private_directory(path):
    p = ordinary_path(path)
    if not p.exists():
        private_path(p.parent, directory=True)
        p.mkdir()  # Inherits an already-private parent; never creates a public root.
    return private_path(p, directory=True)


def admin_control_file(path):
    """Nonsecret control file: SYSTEM/Admin owner and no other writable ACE."""
    p = ordinary_path(path)
    if not p.is_file() or p.stat().st_nlink != 1:
        raise ValueError('Control file must be ordinary and unaliased')
    _, _, _, sec = _api()
    sd = sec.GetNamedSecurityInfo(str(p), sec.SE_FILE_OBJECT,
        sec.OWNER_SECURITY_INFORMATION | sec.DACL_SECURITY_INFORMATION)
    admins = {'S-1-5-18', 'S-1-5-32-544'}
    if sec.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) not in admins:
        raise ValueError('Control file must have an administrator owner')
    acl = sd.GetSecurityDescriptorDacl()
    if acl is None: raise ValueError('Unrestricted control file')
    write = 0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x40000000 | 0x10000000
    for i in range(acl.GetAceCount()):
        ace = acl.GetAce(i)
        if ace[0][0] not in (sec.ACCESS_ALLOWED_ACE_TYPE, sec.ACCESS_DENIED_ACE_TYPE):
            raise ValueError('Unsupported control ACE')
        if ace[0][0] == sec.ACCESS_ALLOWED_ACE_TYPE and not ace[0][1] & 8:
            if ace[1] & write and sec.ConvertSidToStringSid(ace[2]) not in admins:
                raise ValueError('Control file is writable outside administrators')
    return p


class RuntimeLease:
    def __init__(self, root):
        self.root, self.active = root, True

    def require(self, root):
        if not self.active or self.root != Path(root):
            raise ValueError('Live snapshot requires the held runtime writer lease')


def create_scratch_root(path):
    """Explicit provisioning for owned disposable tests, not production repair."""
    api, con, file, sec = _api()
    p = ordinary_path(path)
    if p.exists():
        raise ValueError('Refusing to alter existing ACLs')
    acl = sec.ACL()
    for sid in trusted_sids():
        acl.AddAccessAllowedAceEx(sec.ACL_REVISION, 3, con.GENERIC_ALL,
                                 sec.ConvertStringSidToSid(sid))
    sd = sec.SECURITY_DESCRIPTOR()
    sd.SetSecurityDescriptorDacl(1, acl, 0)
    sd.SetSecurityDescriptorControl(sec.SE_DACL_PROTECTED, sec.SE_DACL_PROTECTED)
    sa = sec.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    file.CreateDirectory(str(p), sa)
    return private_path(p, directory=True)


@contextlib.contextmanager
def exclusive_runtime(root):
    """No-share handle: gateway, backup and restore must all hold this lock."""
    _, con, file, _ = _api()
    root = private_path(root, directory=True)
    lock = ordinary_path(root / 'writer.lock')
    if lock.exists():
        private_path(lock)
    handle = file.CreateFile(str(lock), con.GENERIC_READ | con.GENERIC_WRITE, 0,
                             None, con.OPEN_ALWAYS, con.FILE_ATTRIBUTE_NORMAL, None)
    lease = RuntimeLease(root)
    try:
        private_path(lock)
        yield lease
    finally:
        lease.active = False
        handle.Close()


def child_environment(source):
    keys = ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'USERPROFILE',
            'HOME', 'HF_HOME', 'HF_HUB_CACHE')
    env = {k: source[k] for k in keys if k in source}
    env.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', PYTHONDONTWRITEBYTECODE='1',
               TOKENIZERS_PARALLELISM='false', PYTHONNOUSERSITE='1',
               PYTHONUTF8='1')
    return env


def kill_job(memory_limit=None):
    import win32job
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if memory_limit is not None:
        info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_JOB_MEMORY
        info['JobMemoryLimit'] = memory_limit
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    return job


def run_model(argv, *, input, timeout, env, cwd, **unused):
    """Assign a suspended process to a kill-on-close job BEFORE executing it."""
    import win32api, win32con, win32event, win32file, win32job, win32process, win32security
    scratch = private_directory(Path(os.environ['TRADEPILOT_RUNTIME']) / 'model-tmp')
    root = private_directory(scratch / str(uuid.uuid4()))
    try:
        paths = [root / name for name in ('stdin', 'stdout', 'stderr')]
        paths[0].write_text(input, encoding='utf-8')
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        handles = []
        job = kill_job()
        process = thread = None
        try:
            for i, p in enumerate(paths):
                handles.append(win32file.CreateFile(str(p), win32con.GENERIC_READ if i == 0 else win32con.GENERIC_WRITE,
                    win32con.FILE_SHARE_READ, sa, win32con.OPEN_EXISTING if i == 0 else win32con.CREATE_NEW, 0, None))
            startup = win32process.STARTUPINFO()
            startup.dwFlags |= win32process.STARTF_USESTDHANDLES
            startup.hStdInput, startup.hStdOutput, startup.hStdError = handles
            process, thread, _, _ = win32process.CreateProcess(str(argv[0]), subprocess.list2cmdline(argv),
                None, None, True, win32process.CREATE_SUSPENDED | win32process.CREATE_NO_WINDOW,
                env, str(cwd), startup)
            win32job.AssignProcessToJobObject(job, process)
            win32process.ResumeThread(thread)
            deadline = time.monotonic() + timeout
            while True:
                # Check while the writer is alive, not only after its deadline.
                # Polling permits one sampling interval of overshoot; not a disk quota.
                if any(win32file.GetFileSize(h) > 2_000_000 for h in handles[1:]):
                    raise ValueError('Model output exceeds limit')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                if win32event.WaitForSingleObject(process, max(1, min(50, int(remaining * 1000)))) == win32event.WAIT_OBJECT_0:
                    break
            code = win32process.GetExitCodeProcess(process)
        finally:
            if process is not None:
                # Also kills grandchildren after a nominally successful parent exit.
                win32job.TerminateJobObject(job, 125)
                win32event.WaitForSingleObject(process, 5000)
            for handle in handles:
                handle.Close()
            if thread is not None: thread.Close()
            if process is not None: process.Close()
            job.Close()
        if any(p.stat().st_size > 2_000_000 for p in paths[1:]):
            raise ValueError('Model output exceeds limit')
        return subprocess.CompletedProcess(argv, code, paths[1].read_text(encoding='utf-8'),
                                           paths[2].read_text(encoding='utf-8'))

    finally:
        private_path(root, directory=True)
        if root.parent != scratch:
            raise ValueError("Unexpected scratch boundary")
        shutil.rmtree(root)
