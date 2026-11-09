# REVIEW ONLY. Configure unattended startup AFTER independent acceptance/cutover.
# Does not start services. Never run during candidate staging.
param([Parameter(Mandatory=$true)][string]$AcceptanceReceipt,
      [Parameter(Mandatory=$true)][string[]]$AllowedTailscaleClients)
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator session required' }
$receipt = Get-Content -LiteralPath $AcceptanceReceipt -Raw | ConvertFrom-Json
if ($receipt.gatekeeper -ne 'ALLOW' -or $receipt.mac_writer_fenced -ne $true -or $receipt.models_accepted -ne $true -or $receipt.service_identity_accepted -ne $true) { throw 'Independent acceptance and fenced cutover required' }
$permit = Get-Content -LiteralPath C:\ProgramData\TradePilot\cutover-allow.json -Raw | ConvertFrom-Json
if ($permit.gatekeeper -ne 'ALLOW' -or $permit.mac_writer_fenced -ne $true -or $permit.activate_windows -ne $true) { throw 'Missing cutover permit' }
foreach ($name in @('TradePilot','TradePilotOllama','TradePilotNetworkStatus')) {
    if ((Get-Service $name).Status -ne 'Stopped') { throw 'All services must be stopped for configuration' }
}
if (-not $AllowedTailscaleClients.Count) { throw 'Explicit authorized Tailscale clients required' }
foreach($client in $AllowedTailscaleClients) {
    $ip = [Net.IPAddress]::Parse($client)
    $b = $ip.GetAddressBytes()
    if ($b.Length -ne 4 -or $b[0] -ne 100 -or $b[1] -lt 64 -or $b[1] -gt 127) { throw 'Client must be one explicit Tailscale IPv4 address' }
}
if (Get-NetFirewallRule -Name TradePilot-Gateway -ErrorAction SilentlyContinue) { throw 'Existing firewall rule preserved for separate review' }
# SCM reports own-process hosts; service-specific filter avoids another Python process.
New-NetFirewallRule -Name TradePilot-Gateway -DisplayName 'TradePilot accepted Tailscale gateway' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -LocalAddress 100.96.0.24 -RemoteAddress $AllowedTailscaleClients -Service TradePilot -Profile Any | Out-Null
& sc.exe config TradePilotOllama start= delayed-auto
if ($LASTEXITCODE) { throw 'Ollama startup configuration failed' }
& sc.exe config TradePilotNetworkStatus start= delayed-auto depend= Tailscale
if ($LASTEXITCODE) { throw 'Network publisher startup configuration failed' }
& sc.exe config TradePilot start= delayed-auto depend= Tailscale/TradePilotNetworkStatus/TradePilotOllama
if ($LASTEXITCODE) { throw 'Gateway startup configuration failed' }
& 'C:\Program Files\TradePilot\venv\Scripts\python.exe' -B 'C:\Program Files\TradePilot\source\deploy\windows\configure_recovery.py'
if ($LASTEXITCODE) { throw 'Bounded recovery configuration failed' }
Write-Host 'Configured only; services remain stopped. Reboot/logout acceptance is still required.'
