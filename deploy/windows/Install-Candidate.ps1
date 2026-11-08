# Review-only; owner executes a verified copy from Admin-only staging after ALLOW.
param([Parameter(Mandatory=$true)][string]$Bundle,
      [string]$Python='C:\Program Files\Python314\python.exe',
      [Parameter(Mandatory=$true)][string]$GatekeeperAllow)
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator required; no automatic elevation'}
$install='C:\Program Files\TradePilot'
$state='C:\ProgramData\TradePilot'
foreach($p in @($install,$state,'C:\ProgramData\TradePilotOllama')){if(Test-Path -LiteralPath $p){throw 'Existing deployment preserved'}}
if(Get-Service TradePilot,TradePilotOllama -ErrorAction SilentlyContinue){throw 'Existing services preserved'}
function NoReparse([string]$Path){
 $p=[IO.Path]::GetFullPath($Path)
 if($p.StartsWith('\\') -or $p.Substring(2).Contains(':')){throw 'Expected local ordinary path'}
 while($p){if((Test-Path -LiteralPath $p) -and ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Reparse ancestor rejected'}; $p=Split-Path $p -Parent}
}
function ProtectedTree([string]$Path){
 NoReparse $Path
 $acl=[Security.AccessControl.DirectorySecurity]::new()
 $acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-11'),'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow'))
 Set-Acl -LiteralPath $Path -AclObject $acl
 & icacls.exe $Path /setowner '*S-1-5-32-544' /T /Q | Out-Null
 if($LASTEXITCODE){throw 'Cannot set immutable installation ownership'}
}
function PrivateDirectory([string]$Path,[string]$Account,[bool]$ReadOnly=$false){
 NoReparse $Path
 New-Item -ItemType Directory -Path $Path | Out-Null
 $acl=[Security.AccessControl.DirectorySecurity]::new();$acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))}
 $rights=if($ReadOnly){'ReadAndExecute'}else{'Modify'}
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($Account,$rights,'ContainerInherit,ObjectInherit','None','Allow'))
 Set-Acl -LiteralPath $Path -AclObject $acl
}
NoReparse $Bundle;NoReparse $Python;NoReparse $install;NoReparse $state
$approval=Get-Content -LiteralPath $GatekeeperAllow -Raw | ConvertFrom-Json
$manifestPath=Join-Path $Bundle 'manifest.json'
$manifestBytes=[IO.File]::ReadAllBytes($manifestPath)
$manifestHasher=[Security.Cryptography.SHA256]::Create()
try{$manifestHash=([BitConverter]::ToString($manifestHasher.ComputeHash($manifestBytes))).Replace('-','').ToLowerInvariant()}
finally{$manifestHasher.Dispose()}
if($approval.decision -ne 'ALLOW' -or $approval.manifest_sha256 -ne $manifestHash){throw 'ALLOW must bind this exact bundle manifest'}
$manifest=[Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json
if($manifest.version -ne 2){throw 'Complete bundle version2 required'}
$bundleRoot=(Resolve-Path -LiteralPath $Bundle).Path.TrimEnd('\')+'\'
$seen=@{}
foreach($entry in $manifest.files){
 if([IO.Path]::IsPathRooted($entry.path) -or $entry.path.Contains(':') -or ($entry.path -split '[/\\]') -contains '..' -or $seen.ContainsKey($entry.path)){throw 'Invalid/duplicate manifest path'}
 $seen[$entry.path]=$true
 $full=[IO.Path]::GetFullPath((Join-Path $bundleRoot $entry.path))
 if(-not $full.StartsWith($bundleRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Manifest path escape'}
 NoReparse $full
 if((Get-FileHash -LiteralPath $full).Hash -ne $entry.sha256){throw 'Bundle checksum mismatch'}
}
if(-not ([IO.Path]::GetFullPath($Python)).StartsWith('C:\Program Files\',[StringComparison]::OrdinalIgnoreCase)){throw 'Machine gateway Python required'}
$signature=Get-AuthenticodeSignature $Python
if($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'CN=Python Software Foundation(?:,|$)'){throw 'Expected PSF-signed gateway Python'}
$env:PYTHONDONTWRITEBYTECODE='1';$env:PYTHONNOUSERSITE='1'
New-Item -ItemType Directory -Path $install | Out-Null
ProtectedTree $install
foreach($entry in $manifest.files){
 $target=Join-Path $install $entry.path
 New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
 Copy-Item -LiteralPath (Join-Path $bundleRoot $entry.path) -Destination $target
 if((Get-FileHash -LiteralPath $target).Hash -ne $entry.sha256){throw 'Copied file mismatch'}
}
$installedManifestPath=Join-Path $install 'bundle-manifest.json'
[IO.File]::WriteAllBytes($installedManifestPath,$manifestBytes)
if((Get-FileHash -LiteralPath $installedManifestPath).Hash -ne $manifestHash){throw 'Installed manifest checksum mismatch'}
ProtectedTree $install
$version=& $Python -I -B "$install\source\deploy\windows\runtime_identity.py"
if($LASTEXITCODE -or $version -ne '3.14.10/64'){throw 'Gateway Python3.14.10 x86_64 required'}
& $Python -I -B "$install\source\deploy\windows\runtime_provenance.py" --archive "$install\runtime\model-python.tar.gz" --receipt "$install\runtime\model-provenance.json" --destination "$install\model-python"
if($LASTEXITCODE){throw 'Exact attested runtime extraction failed'}
ProtectedTree "$install\model-python"
$modelPython="$install\model-python\python.exe"
$modelVersion=& $modelPython -I -B "$install\source\deploy\windows\runtime_identity.py"
if($LASTEXITCODE -or $modelVersion -ne '3.12.16/64'){throw 'Exact model runtime version/architecture mismatch'}
& $Python -I -B -m venv "$install\venv"
if($LASTEXITCODE){throw 'Gateway venv failed'}
& $modelPython -I -B -m venv "$install\kronos-venv"
if($LASTEXITCODE){throw 'Model venv failed'}
foreach($item in @(@('venv','wheelhouse','requirements.offline.txt'),@('kronos-venv','kronos-wheelhouse','kronos.offline.txt'))){
 & "$install\$($item[0])\Scripts\python.exe" -I -B -m pip install --no-index --no-compile --find-links "$install\$($item[1])" --require-hashes -r "$install\$($item[2])"
 if($LASTEXITCODE){throw 'Offline hash-locked dependency install failed'}
}
Copy-Item "$install\venv\Lib\site-packages\win32\pythonservice.exe" "$install\venv\Scripts\pythonservice.exe"
Copy-Item "$install\venv\Lib\site-packages\pywin32_system32\*.dll" "$install\venv\Scripts\"
Copy-Item (Join-Path (Split-Path $Python) 'python314.dll') "$install\venv\Scripts\"
Get-ChildItem -LiteralPath (Split-Path $Python) -Filter 'vcruntime140*.dll' | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination "$install\venv\Scripts\"}
ProtectedTree $install
$hostScript="$install\source\deploy\windows\service_host.py"
& "$install\venv\Scripts\python.exe" -B $hostScript gateway --startup disabled --username 'NT SERVICE\TradePilot' install
if($LASTEXITCODE){throw 'Gateway registration failed'}
& "$install\venv\Scripts\python.exe" -B $hostScript ollama --startup disabled --username 'NT SERVICE\TradePilotOllama' install
if($LASTEXITCODE){throw 'Model registration failed'}
PrivateDirectory $state 'NT SERVICE\TradePilot' $true
PrivateDirectory "$state\private" 'NT SERVICE\TradePilot'
PrivateDirectory "$state\private\runtime" 'NT SERVICE\TradePilot'
PrivateDirectory "$state\backups" 'NT SERVICE\TradePilot'
PrivateDirectory 'C:\ProgramData\TradePilotOllama' 'NT SERVICE\TradePilotOllama'
$policyPath="$state\backup-schedule.json"
@{interval_seconds=3600;max_backup_bytes=10737418240;min_free_bytes=5368709120} | ConvertTo-Json | Set-Content -LiteralPath $policyPath -Encoding utf8
$policyAcl=Get-Acl -LiteralPath $policyPath;$policyAcl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'));Set-Acl -LiteralPath $policyPath -AclObject $policyAcl
Write-Host 'Installed disabled only. No activation/config/ledger/pairing/firewall. Prepare reviewed service preflight next.'
