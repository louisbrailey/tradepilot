# Home PC gateway

The home Windows PC is the intended host for the gateway, paper scheduler, Ollama assistant, and Kronos replay. The phone will use its existing private Tailscale network to reach an Ubuntu guest on that PC. The current Mac gateway continues to hold the paper ledger until cutover.

## Check the host when it comes online

Identify the Windows version and edition, virtualization support, available memory and disk space, and the existing remote management route. Confirm the phone that runs TradePilot is enrolled in the same tailnet. These checks are read-only.

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, FreePhysicalMemory
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory, NumberOfLogicalProcessors, HypervisorPresent
Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter, SizeRemaining
Get-Command Get-VM, wsl, ssh -ErrorAction SilentlyContinue | Select-Object Name, Source
```

Use a dedicated Ubuntu 24.04 x86-64 VM if Hyper-V is available and the PC has room for it. Start with four virtual CPUs, 8 GB of guest RAM, and at least 60 GB free for dependencies, models, and snapshots. Select a private NAT network and join Tailscale from the guest. Verify its own MagicDNS name and allow SSH and TCP 8787 only from the intended tailnet devices. A host with WSL requires a persistent Windows startup task and a reboot check because systemd alone does not keep WSL running. Confirm the host and route before choosing either setup.

[Hyper-V requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v) · [WSL service lifetime](https://learn.microsoft.com/en-us/windows/wsl/systemd)

## Stage and validate

1. Export the reviewed commit using `git archive` and transfer it over verified SSH. Install the Linux dependencies and public model weights using `deploy/remote/install.sh` inside the guest.
2. Use synthetic data to exercise the gateway, Qwen assistant, and pinned Kronos replay. Check both models against the 90-second server timeout and inspect memory use on the actual PC. Verify that the assistant shows holdings, asks for shares when given a dollar-denominated order, and returns exact terms for an explicit share proposal.
3. Configure VM startup with Windows and graceful guest shutdown. For Hyper-V, use `Set-VM -Name TradePilot -AutomaticStartAction Start -AutomaticStopAction ShutDown` after the VM exists. Verify that the gateway can recover after a host reboot and that the PC can stay awake on AC power while the display is off. [Hyper-V start and stop settings](https://learn.microsoft.com/en-us/powershell/module/hyper-v/set-vm)

Benchmark `qwen3.5:4b` on the PC before cutover. It exceeded the deadline in a four-CPU ARM64 Linux rehearsal. The 2B Q4 trial showed the holdings and clarified a dollar amount, then asked for a share count on an order that already included one. That trial failed the exact-share proposal check. Kronos completed both replay horizons on emulated x86-64 Ubuntu. Record the assistant model digest, latency and memory use on the actual PC. [Ollama model tags](https://ollama.com/library/qwen3.5/tags)

## Move the paper ledger and pair the iPhone

Follow the single-writer [cutover and recovery steps](REMOTE-SETUP.md#cutover--one-writer-preserved-history). Stop and fence the Mac gateway before copying the active SQLite ledgers. Preserve the automation protocol files and compare run IDs, saved observations, and pending decisions before enabling the guest scheduler. Generate a fresh token and TLS pairing for the guest's Tailscale identity. Keep the broker trading and transfer flags disabled.

With the Mac gateway stopped, check the phone over cellular and Tailscale, including paper history, the assistant, and Kronos. Confirm the next scheduled observation and test a ledger restore into a fenced guest. Keep a periodic backup of the latest completed SQLite snapshots on separate local storage so a PC disk failure can be recovered.
