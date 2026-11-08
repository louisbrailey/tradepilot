"""Explicit non-admin synthetic acceptance; isolated ephemeral-loopback Ollama.

No gateway HTTP server, scheduler, broker client or production state is created.
Ollama downloads only the requested public4B model into the specified model cache.
Kronos uses pinned, already downloaded offline weights and synthetic price bars.
"""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'server'))
from windows_runtime import create_scratch_root, kill_job
import win32api, win32job

JOB = None


def kronos_only(args):
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    runtime = create_scratch_root(output / 'synthetic-runtime')
    os.environ.update(TRADEPILOT_RUNTIME=str(runtime), KRONOS_HOME=str(args.kronos.absolute()),
                      KRONOS_PYTHON=str(args.model_python.absolute()), HF_HOME=str(args.hf_home.absolute()))
    import kronos_service
    report = {'scope':'synthetic offline CPU Kronos, interactive user', 'horizons':[]}
    history = [{'t':1700000000000+i*86400000,'o':100+i*.1,'h':101+i*.1,
                'l':99+i*.1,'c':100.5+i*.1,'v':1000+i} for i in range(128)]
    for horizon in args.horizons:
        start = time.monotonic()
        try:
            result = kronos_service.infer(history, [history[-1]['t']+(i+1)*86400000 for i in range(horizon)], 3)
            report['horizons'].append({'horizon':horizon,'seconds':round(time.monotonic()-start,3),'paths':result['paths']})
        except Exception as error:
            report['horizons'].append({'horizon':horizon,'seconds':round(time.monotonic()-start,3),
                                       'error':type(error).__name__+': '+str(error)})
    (output/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(str(output/'results.json'))
    return int(any('error' in row for row in report['horizons']))


def main(args):
    global JOB
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    runtime = create_scratch_root(output / 'synthetic-runtime')
    args.models.mkdir(parents=True, exist_ok=True)
    JOB = kill_job()
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    env = {k: os.environ[k] for k in ('SystemRoot','WINDIR','PATH','TEMP','TMP') if k in os.environ}
    env.update(USERPROFILE=str(runtime), OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=str(args.models.absolute()),
               OLLAMA_NO_CLOUD='1', OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1',
               OLLAMA_MAX_QUEUE='1', OLLAMA_CONTEXT_LENGTH='8192', OLLAMA_KEEP_ALIVE='0')
    if args.cpu:
        env.update(CUDA_VISIBLE_DEVICES='-1', OLLAMA_VULKAN='0', GGML_VK_VISIBLE_DEVICES='-1')
    from server import NoLocalRedirects
    opener = build_opener(ProxyHandler({}), NoLocalRedirects())
    def request(path, body=None, timeout=90):
        req = Request(f'http://127.0.0.1:{port}' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type':'application/json'})
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000: raise ValueError('Oversized model response')
            return json.loads(raw)
    report = {'scope':'synthetic interactive-user acceptance, not service acceptance',
              'ollama_version_expected':'0.40.15','model':'qwen3.5:4b','cpu_requested':args.cpu,'fixtures':[]}
    child = None
    try:
        with (output / 'ollama.log').open('wb') as log:
            child = subprocess.Popen([str(args.ollama), 'serve'], env=env, stdout=log, stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            handle = win32api.OpenProcess(0x0100 | 0x0200 | 0x0001, False, child.pid)
            try: win32job.AssignProcessToJobObject(JOB, handle)
            finally: handle.Close()
            deadline = time.monotonic() + 30
            while True:
                try:
                    report['ollama_version'] = request('/api/version', timeout=2)['version']
                    break
                except Exception:
                    if child.poll() is not None or time.monotonic() > deadline: raise
                    time.sleep(.25)
            if report['ollama_version'] != '0.40.15': raise ValueError('Unexpected Ollama version')
            start = time.monotonic()
            pulled = request('/api/pull', {'model':'qwen3.5:4b','stream':False}, timeout=900)
            report['pull_seconds'] = round(time.monotonic()-start,3)
            if pulled.get('status') != 'success': raise ValueError('4B pull failed')
            report['model_metadata'] = request('/api/show', {'model':'qwen3.5:4b'})
            import server
            # Reuse exact schema/instructions/validation; replace only transport port.
            server.local_ollama_request = request
            os.environ.update(AI_PROVIDER='ollama', OLLAMA_MODEL='qwen3.5:4b', LOCAL_AI_KEEP_ALIVE='0')
            cases = [('sell 3 AAPL','trade','sell','3','AAPL'),
                     ('buy 1.5 MSFT','trade','buy','1.5','MSFT'),
                     ('Do not sell 3 AAPL','message',None,None,None)]
            for prompt, kind, side, quantity, symbol in cases:
                start = time.monotonic()
                context = {'mode':'webull','prompt':prompt,'environment':'sandbox',
                           'snapshot':{'positions':[{'symbol':'AAPL','quantity':'10','price':'100','kind':'stock','currency':'USD'}, {'symbol':'MSFT','quantity':'5','price':'200','kind':'stock','currency':'USD'}],'as_of':1794160000},'journal':[]}
                reply = server.local_model_completion('qwen3.5:4b', context, server.WEBULL_INSTRUCTIONS)
                expected = (kind,side,quantity,symbol)
                actual = tuple(reply[k] for k in ('kind','side','quantity','symbol'))
                report['fixtures'].append({'prompt':prompt,'seconds':round(time.monotonic()-start,3),
                                           'pass':actual==expected,'reply':reply,'keep_alive':'0'})
            # Separate explicitly labelled warm-cache comparison, not production policy.
            os.environ['LOCAL_AI_KEEP_ALIVE'] = '5m'
            report['warm_probe'] = []
            for _ in range(2):
                start = time.monotonic()
                reply = server.local_model_completion('qwen3.5:4b', {'mode':'webull','prompt':'sell 3 AAPL','environment':'sandbox','snapshot':{'positions':[{'symbol':'AAPL','quantity':'10','price':'100','kind':'stock','currency':'USD'}],'as_of':1794160000},'journal':[]}, server.WEBULL_INSTRUCTIONS)
                report['warm_probe'].append({'seconds':round(time.monotonic()-start,3), 'reply':reply,
                                            'loaded_models':request('/api/ps').get('models')})
            request('/api/generate', {'model':'qwen3.5:4b','keep_alive':0,'stream':False})
            report['ollama_unloaded'] = request('/api/ps').get('models') == []
            if not report['ollama_unloaded']: raise ValueError('Refuse Kronos while Ollama remains loaded')
            if args.skip_kronos:
                (output / 'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                return int(not all(x['pass'] for x in report['fixtures']))
            os.environ.update(TRADEPILOT_RUNTIME=str(runtime), KRONOS_HOME=str(args.kronos.absolute()),
                              KRONOS_PYTHON=str(args.model_python.absolute()), HF_HOME=str(args.hf_home.absolute()))
            import kronos_service
            history = [{'t':1700000000000+i*86400000,'o':100+i*.1,'h':101+i*.1,
                        'l':99+i*.1,'c':100.5+i*.1,'v':1000+i} for i in range(128)]
            dates = [history[-1]['t']+(i+1)*86400000 for i in range(5)]
            start=time.monotonic()
            prediction=kronos_service.infer(history, dates, 3)
            report['kronos']={'seconds':round(time.monotonic()-start,3),'paths':prediction['paths'],
                              'device':'cpu','synthetic':True}
    except Exception as error:
        report['error']={'type':type(error).__name__,'message':str(error)[:300]}
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(10)
            except subprocess.TimeoutExpired:child.kill();child.wait(5)
        JOB.Close()
        JOB = None
        (output / 'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(str(output / 'results.json'))
    return 1 if report.get('error') or not all(x['pass'] for x in report['fixtures']) else 0


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kronos-only',action='store_true',help='Offline CPU tests only; caller must ensure no competing inference')
    p.add_argument('--horizons',type=int,nargs='+',choices=(5,20),default=[5,20])
    p.add_argument('--skip-kronos',action='store_true',help='Keep existing Kronos evidence; run only the changed Ollama fixture')
    p.add_argument('--cpu',action='store_true',help='Explicit CPU comparison; never changes production service configuration')
    for name in ('ollama','models','kronos','model-python','hf-home','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    raise SystemExit(kronos_only(args) if args.kronos_only else main(args))
