"""Synthetic acceptance inside the installed GatewayService, never production start."""
from contextlib import closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import uuid
from urllib.request import build_opener, ProxyHandler, Request

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'server'))
from windows_runtime import admin_control_file, private_directory, private_path, exclusive_runtime


def request(root):
    root = Path(root)
    if (root/'cutover-allow.json').exists(): raise ValueError('Preflight refuses an activation permit')
    data = json.loads(admin_control_file(root/'preflight-request.json').read_text(encoding='utf-8-sig'))
    if set(data) != {'version','mode','nonce','tailscale_address'} or data['version'] != 1 or data['mode'] != 'synthetic-service-preflight':
        raise ValueError('Invalid preflight request')
    if str(uuid.UUID(data['nonce'])) != data['nonce'] or data['tailscale_address'] != '100.96.0.24':
        raise ValueError('Invalid preflight identity')
    return data


def service_identity():
    import win32api, win32con, win32security
    token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try: sid=win32security.GetTokenInformation(token,win32security.TokenUser)[0]
    finally: token.Close()
    expected=win32security.LookupAccountName(None,'NT SERVICE\\TradePilot')[0]
    if sid != expected: raise ValueError('Preflight must run as the actual gateway virtual account')
    return win32security.ConvertSidToStringSid(sid)


def ollama_service_listener():
    """Prove local port belongs to a descendant of the running SCM Ollama host."""
    import pythoncom, win32com.client, win32service
    manager=win32service.OpenSCManager(None,None,win32service.SC_MANAGER_CONNECT)
    try:
        service=win32service.OpenService(manager,'TradePilotOllama',win32service.SERVICE_QUERY_STATUS)
        try: status=win32service.QueryServiceStatusEx(service)
        finally: win32service.CloseServiceHandle(service)
    finally: win32service.CloseServiceHandle(manager)
    if status['CurrentState'] != win32service.SERVICE_RUNNING or not status['ProcessId']:
        raise ValueError('Dedicated Ollama service must be running')
    class Row(ctypes.Structure):
        _fields_=[(x,wintypes.DWORD) for x in ('state','local_addr','local_port','remote_addr','remote_port','pid')]
    size=wintypes.ULONG(0)
    get=ctypes.windll.iphlpapi.GetExtendedTcpTable
    if get(None,ctypes.byref(size),False,socket.AF_INET,5,0) != 122:
        raise ValueError('Cannot query TCP owner table')
    buffer=ctypes.create_string_buffer(size.value)
    if get(buffer,ctypes.byref(size),False,socket.AF_INET,5,0): raise ValueError('Cannot read TCP owner table')
    count=wintypes.DWORD.from_buffer(buffer).value
    rows=(Row*count).from_buffer(buffer,ctypes.sizeof(wintypes.DWORD))
    pids=[row.pid for row in rows if row.state==2 and socket.ntohs(row.local_port & 65535)==11434
          and socket.inet_ntoa(int(row.local_addr).to_bytes(4,'little'))=='127.0.0.1']
    if len(pids)!=1: raise ValueError('Expected one loopback Ollama listener')
    pythoncom.CoInitialize()
    try:
        parents={int(p.ProcessId):int(p.ParentProcessId) for p in win32com.client.GetObject('winmgmts:').ExecQuery('SELECT ProcessId,ParentProcessId FROM Win32_Process')}
    finally: pythoncom.CoUninitialize()
    pid=pids[0]
    for _ in range(8):
        if pid==status['ProcessId']: return {'service_pid':pid,'listener_pid':pids[0]}
        pid=parents.get(pid,0)
        if not pid: break
    raise ValueError('Port is not owned by the dedicated model service')


def network_guard(event,args):
    if event=='socket.bind': raise RuntimeError('Preflight cannot open a listener')
    if event=='socket.connect' and args[1] != ('127.0.0.1',11434):
        raise RuntimeError('Preflight permits only the dedicated local model API')
    if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1',):
        raise RuntimeError('Preflight cannot resolve external providers')


def synthetic_snapshot_drill(out):
    import snapshots
    root=private_directory(out/'backup-drill')
    private=private_directory(root/'private')
    runtime=private_directory(private/'runtime')
    (private/'config.json').write_text(json.dumps({'GATEWAY_DISABLED':'enabled'}))
    for name in ('paper','admission'):
        with closing(sqlite3.connect(runtime/(name+'.sqlite3'))) as db:
            db.execute('CREATE TABLE fixture(value INTEGER)'); db.execute('INSERT INTO fixture VALUES(42)'); db.commit()
    with exclusive_runtime(private) as lease:
        snapshot=snapshots.live_backup(root,lease)
        try:
            snapshots.backup(root)
        except Exception: excluded=True
        else: raise ValueError('Second writer was not excluded')
    restored=snapshots.restore(root,snapshot,root/'isolated-restore')
    for name in ('paper','admission'):
        with closing(sqlite3.connect(restored/(name+'.sqlite3'))) as db:
            if db.execute('SELECT value FROM fixture').fetchall()!=[(42,)]: raise ValueError('Synthetic restore mismatch')
    return {'passed':True,'writer_exclusion':excluded,'databases':2,'whole_set_atomic':False,
            'consistency':'per_database_online_backup','restore':'new isolated directory; never activated'}


def run(root, install, stopped, job):
    from gateway import tailscale_status, ollama_idle
    from runtime_provenance import verify_installed
    import win32job
    data=request(root)
    sid=service_identity()
    out=private_directory(private_directory(Path(root)/'private/preflight')/data['nonce'])
    if (out/'receipt.json').exists(): raise ValueError('Preflight nonce already used')
    report={'scope':'real GatewayService identity synthetic acceptance','nonce':data['nonce'],
            'identity_sid':sid,'production_started':False,'mac_writer_fenced':False,'steps':[]}
    try:
        # No private config/market environment/pairing/ledger is read in this mode.
        keep={k:os.environ[k] for k in ('SystemRoot','WINDIR','PATH') if k in os.environ}
        os.environ.clear(); os.environ.update(keep)
        os.environ.update(USERPROFILE=str(out),TEMP=str(out),TMP=str(out),PYTHONNOUSERSITE='1',
            PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
            TRADEPILOT_RUNTIME=str(private_directory(out/'runtime')),HF_HOME=str(install/'public-models/huggingface'),
            KRONOS_HOME=str(install/'kronos'),KRONOS_PYTHON=str(install/'kronos-venv/Scripts/python.exe'),
            AI_PROVIDER='ollama',OLLAMA_MODEL='qwen3.5:4b',OLLAMA_LOOPBACK_HOST='127.0.0.1',LOCAL_AI_KEEP_ALIVE='0',
            GATEWAY_DISABLED='enabled',BROKER_KILL_SWITCH='enabled',WEBULL_LIVE_TRADING='disabled',COINBASE_LIVE_TRADING='disabled',COINBASE_TRANSFERS='disabled')
        sys.addaudithook(network_guard)
        import cryptography, win32serviceutil, webull, server, kronos_service
        report['stage']='runtime-integrity'
        report['runtime']=verify_installed(install/'model-python')
        report['gateway_python']=sys.version
        if sys.version_info[:3]!=(3,14,10): raise ValueError('Expected gateway Python3.14.10')
        report['bundle_manifest_sha256']=hashlib.sha256(admin_control_file(install/'bundle-manifest.json').read_bytes()).hexdigest()
        report['stage']='tailscale-access'
        state=tailscale_status()
        me=state.get('Self',{})
        if state.get('BackendState')!='Running' or me.get('Online') is not True or data['tailscale_address'] not in me.get('TailscaleIPs',[]) or not me.get('DNSName'):
            raise ValueError('Service identity lacks matching online Tailscale access')
        report['tailscale_access']=True
        report['network_status_source']='restricted-system-publisher'
        report['stage']='dedicated-ollama-identity'
        report['ollama_service']=ollama_service_listener(); ollama_idle()
        opener=build_opener(ProxyHandler({}),server.NoLocalRedirects())
        def get(path):
            with opener.open(Request('http://127.0.0.1:11434'+path),timeout=5) as response:
                raw=response.read(1048577)
                if len(raw)>1048576: raise ValueError('Oversize local response')
                return json.loads(raw)
        models=get('/api/tags').get('models',[])
        expected='d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04'
        if not any(m.get('name')=='qwen3.5:4b' and m.get('digest')==expected for m in models):
            raise ValueError('Reviewed 4B digest missing')
        report['model_digest']=expected
        for prompt,expected_reply in [('sell 3 AAPL',('trade','sell','3','AAPL')),('buy 1.5 MSFT',('trade','buy','1.5','MSFT')),('Do not sell 3 AAPL',('message',None,None,None))]:
            report['stage']='4b-synthetic-semantics'
            if stopped.is_set(): raise InterruptedError('Preflight stopped')
            before=time.monotonic()
            context={'mode':'webull','prompt':prompt,'environment':'sandbox','snapshot':{'positions':[
                {'symbol':'AAPL','quantity':'10','price':'100','kind':'stock','currency':'USD'},
                {'symbol':'MSFT','quantity':'5','price':'200','kind':'stock','currency':'USD'}],'as_of':1794160000},'journal':[]}
            reply=server.ollama_reply('qwen3.5:4b',context,server.WEBULL_INSTRUCTIONS)
            if tuple(reply[k] for k in ('kind','side','quantity','symbol'))!=expected_reply: raise ValueError('4B semantic fixture failed')
            report['steps'].append({'fixture':prompt,'passed':True,'seconds':round(time.monotonic()-before,3)})
        if get('/api/ps').get('models')!=[]: raise ValueError('Refuse Kronos while Ollama loaded')
        if ollama_service_listener()!=report['ollama_service']: raise ValueError('Model service changed during preflight')
        history=[{'t':1700000000000+i*86400000,'o':100+i*.1,'h':101+i*.1,'l':99+i*.1,'c':100.5+i*.1,'v':1000+i} for i in range(128)]
        for horizon in (5,20):
            report['stage']='kronos-'+str(horizon)
            if stopped.is_set(): raise InterruptedError('Preflight stopped')
            before=time.monotonic()
            with kronos_service._LOCK:
                result=kronos_service.infer(history,[history[-1]['t']+(i+1)*86400000 for i in range(horizon)],3)
            report['steps'].append({'fixture':'Kronos','horizon':horizon,'samples':len(result['paths']),'passed':True,'seconds':round(time.monotonic()-before,3)})
        report['stage']='synthetic-backup-restore'
        report['backup_restore']=synthetic_snapshot_drill(out)
        report['gateway_job_peak_committed_bytes']=win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)['PeakJobMemoryUsed']
        report['ollama_memory_receipt']='C:/ProgramData/TradePilotOllama/memory-status.json (administrator reads separately)'
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',error=type(error).__name__)
        raise
    finally:
        temp=out/'receipt.tmp'; temp.write_text(json.dumps(report,indent=2)+'\n'); temp.replace(out/'receipt.json')
    return report
