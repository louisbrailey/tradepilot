# Review-only until gatekeeper ALLOW. Never starts/enables either service.
param(
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$ModelPython,
    [Parameter(Mandatory=$true)][string]$GatekeeperAllow
)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator session required; no automatic elevation.' }
$install = 'C:\Program Files\TradePilot'
$state = 'C:\ProgramData\TradePilot'
if ((Test-Path $install) -or (Test-Path $state) -or (Test-Path 'C:\ProgramData\TradePilotOllama') -or (Get-Service TradePilot,TradePilotOllama -ErrorAction SilentlyContinue)) { throw 'Existing deployment preserved; use a separately reviewed upgrade.' }
$approval = Get-Content -LiteralPath $GatekeeperAllow -Raw | ConvertFrom-Json
$manifestPath = Join-Path $Bundle 'manifest.json'
if ($approval.decision -ne 'ALLOW' -or $approval.manifest_sha256 -ne (Get-FileHash $manifestPath).Hash) { throw 'Gatekeeper ALLOW must name this exact bundle manifest hash.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$bundleRoot = (Resolve-Path -LiteralPath $Bundle).Path.TrimEnd('\') + '\'
foreach ($entry in $manifest.files) {
    if ([IO.Path]::IsPathRooted($entry.path) -or $entry.path.Contains(':') -or ($entry.path -split '[/\\]') -contains '..') { throw 'Manifest paths must be simple relative paths.' }
    $full = [IO.Path]::GetFullPath((Join-Path $bundleRoot $entry.path))
    if (-not $full.StartsWith($bundleRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path escape' }
    if ((Get-Item -LiteralPath $full).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse bundle member' }
    if ((Get-FileHash -LiteralPath $full).Hash -ne $entry.sha256) { throw 'Bundle checksum mismatch' }
}
# Python must be a separately installed, Microsoft/PSF-signed machine interpreter.
if (-not ([IO.Path]::GetFullPath($Python)).StartsWith('C:\Program Files\',[StringComparison]::OrdinalIgnoreCase)) { throw 'User-writable Python is not an unattended service runtime.' }
if ((Get-AuthenticodeSignature $Python).Status -ne 'Valid') { throw 'Python signature invalid' }
if (-not ([IO.Path]::GetFullPath($ModelPython)).StartsWith('C:\Program Files\',[StringComparison]::OrdinalIgnoreCase) -or (Get-AuthenticodeSignature $ModelPython).Status -ne 'Valid') { throw 'Model Python must be a signed machine installation.' }
$gatewayVersion = & $Python -c 'import sys; print("%s.%s" % sys.version_info[:2])'
$modelVersion = & $ModelPython -c 'import sys; print("%s.%s" % sys.version_info[:2])'
if ($gatewayVersion -ne '3.14' -or $modelVersion -ne '3.12') { throw 'Gateway requires3.14; Kronos requires3.12.' }
New-Item -ItemType Directory -Path $install | Out-Null
# Copy only manifest-listed files, never private state or arbitrary extra bundle files.
foreach ($entry in $manifest.files) {
    $target = Join-Path $install $entry.path
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundleRoot $entry.path) -Destination $target
    if ((Get-FileHash -LiteralPath $target).Hash -ne $entry.sha256) { throw 'Copied file changed; do not execute installation payload.' }
}
& $Python -m venv "$install\venv"
if ($LASTEXITCODE) { throw 'venv creation failed' }
$runtimePython = "$install\venv\Scripts\python.exe"
& $runtimePython -m pip install --no-index --find-links "$install\wheelhouse" --require-hashes -r "$install\requirements.offline.txt"
if ($LASTEXITCODE) { throw 'Offline locked dependency install failed' }
& $ModelPython -m venv "$install\kronos-venv"
if ($LASTEXITCODE) { throw 'Model environment creation failed' }
& "$install\kronos-venv\Scripts\python.exe" -m pip install --no-index --find-links "$install\kronos-wheelhouse" --require-hashes -r "$install\kronos.offline.txt"
if ($LASTEXITCODE) { throw 'Offline model dependency install failed' }
# Native SCM host and DLLs beside its executable, not in a user's profile.
Copy-Item "$install\venv\Lib\site-packages\win32\pythonservice.exe" "$install\venv\Scripts\pythonservice.exe"
Copy-Item "$install\venv\Lib\site-packages\pywin32_system32\*.dll" "$install\venv\Scripts\"
Copy-Item (Join-Path (Split-Path $Python) 'python314.dll') "$install\venv\Scripts\"
$hostScript = "$install\source\deploy\windows\service_host.py"
& $runtimePython $hostScript gateway --startup disabled --username 'NT SERVICE\TradePilot' install
if ($LASTEXITCODE) { throw 'Gateway service registration failed; remains disabled' }
& $runtimePython $hostScript ollama --startup disabled --username 'NT SERVICE\TradePilotOllama' install
if ($LASTEXITCODE) { throw 'Ollama service registration failed; remains disabled' }
function PrivateDirectory([string]$Path,[string]$Account,[bool]$ReadOnly=$false) {
    New-Item -ItemType Directory -Path $Path | Out-Null
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach($sid in @('S-1-5-18','S-1-5-32-544')) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
    }
    $rights = if($ReadOnly){'ReadAndExecute'}else{'Modify'}
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($Account,$rights,'ContainerInherit,ObjectInherit','None','Allow'))
    Set-Acl -LiteralPath $Path -AclObject $acl
}
PrivateDirectory $state 'NT SERVICE\TradePilot' $true
PrivateDirectory "$state\private" 'NT SERVICE\TradePilot'
PrivateDirectory "$state\private\runtime" 'NT SERVICE\TradePilot'
PrivateDirectory "$state\backups" 'NT SERVICE\TradePilot'
PrivateDirectory 'C:\ProgramData\TradePilotOllama' 'NT SERVICE\TradePilotOllama'
# No config, tokens, pairing, cutover permit, firewall rule, recovery or auto-start.
Write-Host 'Candidate installed disabled. Gatekeeper and Mac-owned cutover still required.'
