# Creates an admin-owned fenced maintenance request. Never starts services.
param([Parameter(Mandatory=$true)][ValidateSet('backup','restore-isolated')][string]$Action,
      [string]$Snapshot,[string]$ManifestSha256)
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator required'}
$root='C:\ProgramData\TradePilot'
if((Get-Service TradePilot).Status -ne 'Stopped'){throw 'Gateway must be stopped'}
foreach($name in @('cutover-allow.json','preflight-request.json','maintenance-request.json')){if(Test-Path -LiteralPath "$root\$name"){throw 'Existing activation/control request must be resolved separately'}}
$config=Get-Content -LiteralPath "$root\private\config.json" -Raw | ConvertFrom-Json
if($config.GATEWAY_DISABLED -eq 'disabled'){throw 'Gateway must be fenced before offline maintenance'}
if($Action -eq 'restore-isolated'){
 if(([guid]::Parse($Snapshot).ToString()) -ne $Snapshot -or $ManifestSha256 -notmatch '^[0-9a-fA-F]{64}$'){throw 'Exact snapshot UUID and completion manifest SHA required'}
}elseif($Snapshot -or $ManifestSha256){throw 'Backup request takes no snapshot arguments'}
$nonce=[guid]::NewGuid().ToString()
$request=@{version=1;action=$Action;nonce=$nonce;snapshot=$null;manifest_sha256=$null}
if($Action -eq 'restore-isolated'){$request.snapshot=$Snapshot;$request.manifest_sha256=$ManifestSha256.ToLowerInvariant()}
$path="$root\maintenance-request.json"
[IO.File]::WriteAllText($path,($request | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new('NT SERVICE\TradePilot','Read','Allow'))
Set-Acl -LiteralPath $path -AclObject $acl
Write-Host "Prepared $Action request $nonce only. Owner may run GatewayService manually; restore never replaces runtime."
