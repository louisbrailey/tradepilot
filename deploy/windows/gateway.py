"""Activated SCM lifecycle only. Importing this module never starts workers."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE / 'server'))
from windows_runtime import exclusive_runtime, private_path


def remote_module():
    spec = importlib.util.spec_from_file_location('remote_preflight', SOURCE / 'scripts/remote-gateway.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def activation(root):
    # Provisioned later by the Mac-owned cutover, never by installation.
    permit = json.loads(private_path(root / 'cutover-allow.json').read_text())
    if permit != {'gatekeeper': 'ALLOW', 'mac_writer_fenced': True, 'activate_windows': True}:
        raise ValueError('Windows activation requires reviewed fenced cutover')


def tailscale_status():
    from network_status import read_status
    return read_status()


def ollama_idle():
    # Restart must not release a poisoned inference lock while old Ollama work lives.
    opener = build_opener(ProxyHandler({}))
    from server import NoLocalRedirects
    opener.add_handler(NoLocalRedirects())
    def get(path):
        with opener.open(Request('http://127.0.0.1:11434' + path), timeout=5) as response:
            raw = response.read(1_048_577)
            if response.status != 200 or len(raw) > 1_048_576:
                raise ValueError('Invalid local Ollama response')
            return json.loads(raw)
    if get('/api/version').get('version') != '0.40.15':
        raise ValueError('Expected reviewed Ollama 0.40.15 candidate')
    if get('/api/ps').get('models') != []:
        raise ValueError('Ollama must be idle and unloaded before gateway startup')


def run(root, stopped):
    """No production entry via CLI; called only by the separately installed SCM host."""
    root = private_path(Path(root), directory=True)
    activation(root)
    remote = remote_module()
    with exclusive_runtime(root / 'private') as lease:
        # Retry unavailable Tailscale before constructing any worker/listener.
        while not stopped.is_set():
            try:
                status = tailscale_status()
                remote.command(root, status)
                break
            except (ValueError, subprocess.SubprocessError):
                if stopped.wait(15): return
        if stopped.is_set(): return
        import server
        server.load_private_config(root / 'private/config.json')
        server.require_gateway_enabled()
        ollama_idle()
        server.load_market_env(str(private_path(root / 'private/market.env')))
        # No inherited broker/provider environment: SCM host installs an explicit env.
        settings = remote.read_settings(root)
        http = server.GatewayHTTPServer((settings['address'], 8787), server.Handler)
        try:
            server.enable_tls(http, root / 'private/server.pem', root / 'private/server.key')
        except BaseException:
            http.server_close()
            raise
        workers = []
        serving = threading.Thread(target=http.serve_forever, name='gateway-http', daemon=True)
        serving.start()
        try:
            import snapshots
            backup_worker = snapshots.start_periodic(root, lease)
            if backup_worker is not None: workers.append(backup_worker)
            workers.append(server.start_worker(server.automation()))
            workers.append(server.start_alert_worker(server.alerts, server.market_data))
            while not stopped.wait(5):
                if backup_worker is not None and not backup_worker[1].is_alive():
                    raise RuntimeError('Backup worker terminated unexpectedly')
                if server._local_ai_lock.poisoned():
                    # Drain workers and fail this service instance. SCM recovery
                    # re-enters ollama_idle before any replacement worker starts.
                    raise RuntimeError('Inference transport requires supervised restart')
                activation(root)
                # Preserve fail-closed identity/config validation during operation.
                remote.command(root, tailscale_status())
        finally:
            for event, _ in workers: event.set()
            deadline = time.monotonic() + 55
            # ThreadingHTTPServer.server_close can wait forever on a stuck request.
            # Keep internal failure/poison drains bounded as well as SCM stop drains.
            def close_http():
                http.shutdown()
                http.server_close()
            closing = threading.Thread(target=close_http, name='gateway-drain', daemon=True)
            closing.start()
            for _, thread in workers:
                thread.join(max(0, deadline - time.monotonic()))
            closing.join(max(0, deadline - time.monotonic()))
            serving.join(max(0, deadline - time.monotonic()))
            if closing.is_alive() or serving.is_alive() or any(thread.is_alive() for _, thread in workers):
                raise RuntimeError('Worker did not stop before deadline')
