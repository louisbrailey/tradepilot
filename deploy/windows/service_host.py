"""SCM hosts. Registration is explicit; both services install DISABLED."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import win32api
import win32job
import win32service
import win32serviceutil
import servicemanager

import gateway
from windows_runtime import kill_job, private_path

ROOT = Path(r'C:\ProgramData\TradePilot')
INSTALL = Path(r'C:\Program Files\TradePilot')


class BaseHost(win32serviceutil.ServiceFramework):
    _exe_name_ = str(INSTALL / 'venv/Scripts/pythonservice.exe')
    def __init__(self, args):
        super().__init__(args)
        self.stop = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop.set()

    def SvcDoRun(self):
        job = kill_job((5 if self._svc_name_ == 'TradePilotOllama' else 3) * 1024**3)
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        errors = []
        def work():
            try: self.run_work()
            except BaseException as error:
                errors.append(type(error).__name__)  # Never log secrets or config values.
            finally: self.stop.set()
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        self.stop.wait()
        deadline = time.monotonic() + 60
        while thread.is_alive() and time.monotonic() < deadline:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=5000)
            thread.join(1)
        if thread.is_alive() or errors:
            servicemanager.LogErrorMsg('TradePilot stopped: ' + (errors[0] if errors else 'shutdown timeout'))
            os._exit(1)  # OS closes job handle and kills the service's entire child tree.
        # Closing a job containing ourselves terminates us; retain until process exits.
        self.job = job


class GatewayService(BaseHost):
    _svc_name_ = 'TradePilot'
    _svc_display_name_ = 'TradePilot private gateway'
    _svc_description_ = 'Fenced paper gateway; activation is a separate reviewed cutover.'

    def run_work(self):
        safe = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'PATH') if k in os.environ}
        os.environ.clear()
        os.environ.update(safe)
        os.environ["USERPROFILE"] = str(ROOT / "private")
        gateway.run(ROOT, self.stop, Path(r'C:\Program Files\Tailscale\tailscale.exe'))


class OllamaService(BaseHost):
    _svc_name_ = 'TradePilotOllama'
    _svc_display_name_ = 'TradePilot local Ollama'
    _svc_description_ = 'Dedicated loopback Ollama 0.40.15; no cloud models.'

    def run_work(self):
        # This service does not get gateway-private directory access.
        root = private_path(Path(r'C:/ProgramData/TradePilotOllama'), directory=True)
        executable = INSTALL / 'ollama/ollama.exe'
        env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH') if k in os.environ}
        env.update(USERPROFILE=str(root), TEMP=str(root), TMP=str(root), OLLAMA_MODELS=str(root / 'models'),
                   CUDA_VISIBLE_DEVICES='-1', OLLAMA_VULKAN='0', GGML_VK_VISIBLE_DEVICES='-1',
                   OLLAMA_HOST='127.0.0.1:11434', OLLAMA_NO_CLOUD='1',
                   OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1',
                   OLLAMA_MAX_QUEUE='1', OLLAMA_CONTEXT_LENGTH='8192', OLLAMA_KEEP_ALIVE='0')
        # An occupied port must fail; never kill an existing desktop daemon.
        import socket
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 11434))
        child = subprocess.Popen([str(executable), 'serve'], env=env,
                                 cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while not self.stop.wait(.5):
                if child.poll() is not None: raise RuntimeError('Ollama exited')
        finally:
            child.terminate()
            try: child.wait(10)
            except subprocess.TimeoutExpired: child.kill(); child.wait(5)


if __name__ == '__main__':
    role = sys.argv.pop(1) if len(sys.argv) > 1 else ''
    if role not in ('gateway', 'ollama'):
        raise SystemExit('Choose gateway or ollama; no implicit startup')
    win32serviceutil.HandleCommandLine(GatewayService if role == 'gateway' else OllamaService)
