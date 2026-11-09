# REVIEW ONLY: exact 724697e -> network-status delta, executed from verified Admin-only staging.
# Never starts/stops services, changes accounts, or reads/writes gateway private state.
param([Parameter(Mandatory=$true)][string]$Bundle,
      [Parameter(Mandatory=$true)][string]$GatekeeperAllow)
$ErrorActionPreference='Stop'
function NoReparse([string]$Path){
 $p=[IO.Path]::GetFullPath($Path)
 if($p.StartsWith('\\') -or $p.Substring(2).Contains(':')){throw 'Expected local ordinary path'}
 while($p){if((Test-Path -LiteralPath $p) -and ((Get-Item -LiteralPath $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Reparse ancestor rejected'}; $p=Split-Path $p -Parent}
}
function AssertProtected([string]$Path){
 NoReparse $Path
 $acl=Get-Acl -LiteralPath $Path
 $owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
 if($owner -notin @('S-1-5-18','S-1-5-32-544')){throw 'Administrator ownership required'}
 $rules=$acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])
 # Reject unknown/object ACEs as well as NULL DACL; never infer safety from an empty projection.
 $raw=[Security.AccessControl.RawSecurityDescriptor]::new($acl.GetSecurityDescriptorBinaryForm(),0)
 if($null -eq $raw.DiscretionaryAcl){throw 'NULL DACL rejected'}
 foreach($ace in $raw.DiscretionaryAcl){if($ace.AceType -notin @('AccessAllowed','AccessDenied')){throw 'Unsupported ACL entry'}}
 foreach($r in $rules){
  if($r.AccessControlType -eq 'Allow' -and -not ($r.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)){
   if(($r.FileSystemRights.value__ -band 0x500d0156) -and $r.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){throw 'Untrusted writable path'}
  }
 }
}
function ProtectPath([string]$Path,[bool]$Directory,[string]$Reader=''){
 NoReparse $Path
 $acl=if($Directory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
 $acl.SetAccessRuleProtection($true,$false)
 $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
 $inherit=if($Directory){'ContainerInherit,ObjectInherit'}else{'None'}
 foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl',$inherit,'None','Allow'))}
 if($Reader){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($Reader,'ReadAndExecute',$inherit,'None','Allow'))}
 Set-Acl -LiteralPath $Path -AclObject $acl
 AssertProtected $Path
}
function HashBytes([byte[]]$Bytes){
 $h=[Security.Cryptography.SHA256]::Create()
 try{return ([BitConverter]::ToString($h.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}finally{$h.Dispose()}
}
function PlanNetworkDelta($Before,$After){
 $allowed=@('Configure-AcceptedStartup.ps1','Install-Candidate.ps1','gateway.py','service_host.py','service_preflight.py',
  'configure_recovery.py','network_status.py','Update-NetworkStatus.ps1','NETWORK-STATUS.md','test_network_status.py','test_network_delta.py','test_windows.py')
 $old=@{};$new=@{}
 foreach($pair in @(@($Before,$old),@($After,$new))){
  if($pair[0].version -ne 2){throw 'Complete version2 manifests required'}
  foreach($entry in $pair[0].files){
   if(-not ($entry.path -is [string]) -or [IO.Path]::IsPathRooted($entry.path) -or $entry.path.Contains(':') -or $entry.path.Contains('\') -or ($entry.path -split '/') -contains '..' -or ($entry.path -split '/') -contains '.' -or ($entry.path -split '/') -contains '' -or $pair[1].ContainsKey($entry.path) -or $entry.sha256 -cnotmatch '^[0-9a-f]{64}$'){throw 'Invalid delta manifest entry'}
   $pair[1][$entry.path]=$entry.sha256
  }
 }
 foreach($path in $old.Keys){if(-not $new.ContainsKey($path)){throw 'Delta cannot remove existing payload'}}
 foreach($required in @('network_status.py','configure_recovery.py','Update-NetworkStatus.ps1','service_host.py','gateway.py','service_preflight.py')){
  if(-not $new.ContainsKey('source/deploy/windows/'+$required)){throw 'Missing network delta payload'}
 }
 foreach($entry in $After.files){
  if(-not $old.ContainsKey($entry.path) -or $old[$entry.path] -ne $entry.sha256){
   if(-not $entry.path.StartsWith('source/deploy/windows/',[StringComparison]::Ordinal) -or $entry.path.Substring('source/deploy/windows/'.Length) -cnotin $allowed){throw 'Delta exceeds reviewed network scope'}
   $entry
  }
 }
}
function RequireStoppedDisabled{
 foreach($name in @('TradePilot','TradePilotOllama')){
  $service=Get-CimInstance Win32_Service -Filter "Name='$name'"
  if(-not $service -or $service.State -ne 'Stopped' -or $service.StartMode -ne 'Disabled' -or $service.StartName -ne "NT SERVICE\$name" -or $service.PathName.Trim('"') -ne 'C:\Program Files\TradePilot\venv\Scripts\pythonservice.exe'){throw 'Expected stopped disabled restricted services'}
 }
}
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator required; no automatic elevation'}
$install='C:\Program Files\TradePilot'
$control='C:\ProgramData\TradePilotNetworkStatus'
$baseHash='3a0bfe014e6582c30358ebf407efe474307ac3ba570cd318dac889a6bb29e724'
RequireStoppedDisabled
NoReparse $control
if((Test-Path -LiteralPath $control) -or (Get-Service TradePilotNetworkStatus -ErrorAction SilentlyContinue)){throw 'Existing publisher preserved'}
if(Test-Path -LiteralPath 'C:\ProgramData\TradePilot\cutover-allow.json'){throw 'Activated gateway requires separate update review'}
AssertProtected $install
AssertProtected (Split-Path $GatekeeperAllow)
AssertProtected $GatekeeperAllow
$approval=Get-Content -LiteralPath $GatekeeperAllow -Raw | ConvertFrom-Json
NoReparse $Bundle
$manifestBytes=[IO.File]::ReadAllBytes((Join-Path $Bundle 'manifest.json'))
$manifestHash=HashBytes $manifestBytes
if($approval.decision -ne 'ALLOW' -or $approval.mode -ne 'network-status-delta' -or $approval.base_manifest_sha256 -ne $baseHash -or $approval.manifest_sha256 -ne $manifestHash){throw 'ALLOW must bind exact base and target manifests'}
$manifest=[Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json
$basePath=Join-Path $install 'bundle-manifest.json'
AssertProtected $basePath
$baseBytes=[IO.File]::ReadAllBytes($basePath)
if((HashBytes $baseBytes) -ne $baseHash){throw 'Installed baseline is not reviewed724697e'}
$before=[Text.Encoding]::UTF8.GetString($baseBytes) | ConvertFrom-Json
if($before.source_commit -ne '724697ec708bdce9a71102facc3eca86b5019d07'){throw 'Unexpected base commit'}
$changes=@(PlanNetworkDelta $before $manifest)
$delta=@($manifest.files | Where-Object {$_.path -ceq 'source/deploy/windows/Update-NetworkStatus.ps1'})
if($delta.Count -ne 1 -or $approval.delta_sha256 -ne $delta[0].sha256){throw 'ALLOW must bind reviewed delta script'}
foreach($entry in $before.files){
 $p=Join-Path $install $entry.path
 AssertProtected $p
 if((Get-FileHash -LiteralPath $p).Hash -ne $entry.sha256){throw 'Existing payload differs; no mutation'}
}
foreach($entry in $manifest.files){
 $p=Join-Path $Bundle $entry.path;NoReparse $p
 if((Get-FileHash -LiteralPath $p).Hash -ne $entry.sha256){throw 'Target payload checksum mismatch'}
}
# Stage all changed bytes before overwriting any destination. Originals and both
# manifest byte buffers are retained permanently for owner-reviewed recovery.
$updates=Join-Path $install 'reviewed-updates'
if(Test-Path -LiteralPath $updates){AssertProtected $updates}else{New-Item -ItemType Directory -Path $updates | Out-Null;ProtectPath $updates $true}
$stage=Join-Path $updates $manifestHash
if(Test-Path -LiteralPath $stage){throw 'Existing update evidence preserved; inspect before retry'}
New-Item -ItemType Directory -Path $stage | Out-Null;ProtectPath $stage $true
[IO.File]::WriteAllBytes((Join-Path $stage 'before-manifest.json'),$baseBytes)
[IO.File]::WriteAllBytes((Join-Path $stage 'after-manifest.json'),$manifestBytes)
$oldServices=@(Get-CimInstance Win32_Service -Filter "Name='TradePilot' OR Name='TradePilotOllama'" | Select-Object Name,StartName,StartMode,PathName,State,@{Name='Dependencies';Expression={@((Get-Service $_.Name).ServicesDependedOn.Name)}})
$oldServices | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'before-services.json') -Encoding utf8
foreach($entry in $changes){
 $name=Split-Path $entry.path -Leaf
 $copy=Join-Path $stage ('new-'+$name)
 Copy-Item -LiteralPath (Join-Path $Bundle $entry.path) -Destination $copy
 ProtectPath $copy $false
 if((Get-FileHash -LiteralPath $copy).Hash -ne $entry.sha256){throw 'Staged delta checksum mismatch'}
 $destination=Join-Path $install $entry.path
 AssertProtected (Split-Path $destination)
 if(Test-Path -LiteralPath $destination){
  AssertProtected $destination
  Copy-Item -LiteralPath $destination -Destination (Join-Path $stage ('before-'+$name))
 }
}
RequireStoppedDisabled
foreach($entry in $changes){
 $name=Split-Path $entry.path -Leaf
 $destination=Join-Path $install $entry.path
 $copy=Join-Path $stage ('new-'+$name)
 if(Test-Path -LiteralPath $destination){[IO.File]::Replace($copy,$destination,$null)}else{[IO.File]::Move($copy,$destination)}
 ProtectPath $destination $false 'Authenticated Users'
 if((Get-FileHash -LiteralPath $destination).Hash -ne $entry.sha256){throw 'Installed delta checksum mismatch'}
}
# Register only the new publisher; retain both existing service accounts and all
# gateway/Ollama state. No firewall, login, unattended, or activation changes.
$env:PYTHONDONTWRITEBYTECODE='1';$env:PYTHONNOUSERSITE='1'
& "$install\venv\Scripts\python.exe" -B "$install\source\deploy\windows\service_host.py" network-status --startup disabled install
if($LASTEXITCODE){throw 'Publisher registration failed; preserve update evidence'}
$publisher=Get-CimInstance Win32_Service -Filter "Name='TradePilotNetworkStatus'"
if($publisher.StartName -ne 'LocalSystem' -or $publisher.State -ne 'Stopped' -or $publisher.StartMode -ne 'Disabled'){throw 'Publisher identity/start mode mismatch'}
New-Item -ItemType Directory -Path $control | Out-Null
ProtectPath $control $true 'NT SERVICE\TradePilot'
& sc.exe config TradePilotNetworkStatus depend= Tailscale
if($LASTEXITCODE){throw 'Publisher dependency failed'}
& sc.exe config TradePilot depend= Tailscale/TradePilotNetworkStatus/TradePilotOllama
if($LASTEXITCODE){throw 'Gateway dependency failed'}
# Publish the new installed receipt last. The original bytes remain in stage.
$nextManifest=Join-Path $stage 'next-manifest.json'
[IO.File]::WriteAllBytes($nextManifest,$manifestBytes)
[IO.File]::Replace($nextManifest,$basePath,$null)
ProtectPath $basePath $false 'Authenticated Users'
if((Get-FileHash -LiteralPath $basePath).Hash -ne $manifestHash){throw 'Updated manifest receipt mismatch'}
@{version=1;status='installed-disabled';base_manifest_sha256=$baseHash;manifest_sha256=$manifestHash;delta_sha256=$delta[0].sha256} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'result.json') -Encoding utf8
Write-Host 'Network delta installed DISABLED. Existing private state and controls preserved. Explicit service acceptance remains required.'
