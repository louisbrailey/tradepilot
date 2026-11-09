"""Pull completed home-PC snapshots when this Mac is awake; no PC writes."""
import argparse
import base64
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import uuid

def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def verify(directory, marker_sha):
 if digest(directory/'complete.json')!=marker_sha:raise ValueError('Completion marker changed')
 marker=json.loads((directory/'complete.json').read_bytes())
 if marker.get('version')!=1 or not isinstance(marker.get('databases'),dict) or not marker['databases']:raise ValueError('Incomplete snapshot')
 for name,sha in marker['databases'].items():
  if not re.fullmatch(r'[A-Za-z0-9_-]+\.sqlite3',name) or not re.fullmatch(r'[0-9a-f]{64}',sha):raise ValueError('Invalid member')
  path=directory/name
  if not path.is_file() or path.is_symlink() or digest(path)!=sha:raise ValueError('Member mismatch')
  with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
   if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Backup integrity failure')
 return set(marker['databases'])|{'complete.json'}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--key',type=Path,required=True);parser.add_argument('--known-hosts',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
 args=parser.parse_args();os.umask(0o077)
 if args.key.is_symlink() or not args.key.is_file() or args.key.stat().st_mode&0o077:raise ValueError('Private ordinary SSH key required')
 if args.known_hosts.is_symlink() or not args.known_hosts.is_file():raise ValueError('Verified host keys required')
 destination=args.destination.expanduser()
 if destination.is_symlink():raise ValueError('Ordinary backup destination required')
 destination.mkdir(mode=0o700,parents=True,exist_ok=True)
 if destination.stat().st_mode&0o077:raise ValueError('Backup destination must be private')
 with (destination/'mirror.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  host_path=str(args.known_hosts)
  if any(c in host_path for c in '\r\n\x00'):raise ValueError('Invalid host-pin path')
  host_option='UserKnownHostsFile="'+host_path.replace('\\','\\\\').replace('"','\\"')+'"'
  ssh=['ssh','-i',str(args.key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o',host_option,'-o','ConnectTimeout=8','PC@100.96.0.24']
  script=r'''$ErrorActionPreference='Stop';$rows=@();Get-ChildItem -LiteralPath 'C:\ProgramData\TradePilot\backups' -Directory|Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'complete.json')}|Sort-Object LastWriteTimeUtc -Descending|Select-Object -First 24|ForEach-Object {$p=Join-Path $_.FullName 'complete.json';$rows+=@{id=$_.Name;manifest_sha256=(Get-FileHash -LiteralPath $p).Hash.ToLowerInvariant();bytes=[long]((Get-ChildItem -LiteralPath $_.FullName -File|Measure-Object Length -Sum).Sum)}};ConvertTo-Json -InputObject $rows -Compress'''
  encoded=base64.b64encode(script.encode('utf-16le')).decode()
  result=subprocess.run(ssh+['powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+encoded],capture_output=True,timeout=45,check=True)
  rows=json.loads(result.stdout);copied=0
  if not isinstance(rows,list) or len(rows)>24:raise ValueError('Invalid snapshot inventory')
  for row in reversed(rows):
   name=row['id'];sha=row['manifest_sha256'];size=row['bytes']
   if str(uuid.UUID(name))!=name or not re.fullmatch(r'[0-9a-f]{64}',sha) or type(size) is not int or not 0<size<=10*1024**3:raise ValueError('Invalid snapshot metadata')
   final=destination/name
   if final.exists():verify(final,sha);continue
   if shutil.disk_usage(destination).free<2*size+5*1024**3:raise ValueError('Mac backup space budget exhausted')
   incoming=Path(tempfile.mkdtemp(prefix='.incoming-',dir=destination));archive=incoming/'snapshot.tar'
   max_archive=size+1024**2
   def bound_file():resource.setrlimit(resource.RLIMIT_FSIZE,(max_archive,max_archive))
   with archive.open('xb') as output:
    subprocess.run(ssh+[r'C:\Windows\System32\tar.exe -cf - -C C:\ProgramData\TradePilot\backups '+name],stdout=output,stderr=subprocess.PIPE,timeout=180,check=True,preexec_fn=bound_file)
   extracted=incoming/name;extracted.mkdir(mode=0o700)
   with tarfile.open(archive) as tar:
    members=tar.getmembers()
    if len(members)>129:raise ValueError('Too many backup members')
    for member in members:
     if member.isdir() and member.name.rstrip('/')==name:continue
     relative=member.name.removeprefix(name+'/')
     if member.name==relative or not member.isfile() or not re.fullmatch(r'(?:[A-Za-z0-9_-]+\.sqlite3|complete\.json)',relative):raise ValueError('Unsafe backup archive')
     with tar.extractfile(member) as src,(extracted/relative).open('xb') as target:shutil.copyfileobj(src,target)
   expected=verify(extracted,sha)
   if {p.name for p in extracted.iterdir()}!=expected:raise ValueError('Extra backup files')
   for p in extracted.iterdir():
    p.chmod(0o600)
    with p.open('rb') as stream:os.fsync(stream.fileno())
   extracted.rename(final);archive.unlink();incoming.rmdir();copied+=1
  record={'status':'complete','checked':len(rows),'copied':copied,'utc':datetime.now(timezone.utc).isoformat(),'pc_modified':False,'whole_set_atomic':False}
  temporary=destination/'mirror-status.tmp';temporary.write_text(json.dumps(record)+'\n');temporary.replace(destination/'mirror-status.json');print(json.dumps(record))

if __name__=='__main__':main()
