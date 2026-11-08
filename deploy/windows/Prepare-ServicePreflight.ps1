# Prepare an admin-owned synthetic request only. Does not start services.
param([string]$StateRoot='C:\ProgramData\TradePilot')
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator required'}
if($StateRoot -ne 'C:\ProgramData\TradePilot'){throw 'Expected installed state root'}
if(Test-Path -LiteralPath "$StateRoot\cutover-allow.json"){throw 'Preflight refuses activation permit'}
if((Get-Service TradePilot).Status -ne 'Stopped'){throw 'Gateway service must be stopped'}
$path="$StateRoot\preflight-request.json"
if(Test-Path -LiteralPath $path){throw 'Existing request preserved; review/remove separately'}
$nonce=[guid]::NewGuid().ToString()
$request=@{version=1;mode='synthetic-service-preflight';nonce=$nonce;tailscale_address='100.96.0.24'} | ConvertTo-Json
[IO.File]::WriteAllText($path,$request,[Text.UTF8Encoding]::new($false))
$acl=[Security.AccessControl.FileSecurity]::new();$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($sid in @('S-1-5-18','S-1-5-32-544')){$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','Allow'))}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new('NT SERVICE\TradePilot','Read','Allow'))
Set-Acl -LiteralPath $path -AclObject $acl
Write-Host "Request prepared: $nonce. Owner may explicitly start model service, then gateway for synthetic preflight. No activation asserted."
