# Home PC gateway

The home Windows desktop now runs the private gateway, paper scheduler, Ollama assistant and Kronos replay. The Mac gateway is stopped, persistently disabled and configuration-fenced. The six saved databases have moved without changing their schema or stored values. Live checks passed before and after a Windows reboot, and the gateway recovered automatically after an isolated process failure. Physical iPhone reachability remains pending.

## Actual host and installation

The desktop runs Windows 11 Home with a Ryzen 3700X, 32 GB RAM and an RTX 3070. Firmware virtualization is disabled. The deployment uses native Windows services; see [the Windows deployment contract](deploy/windows/README.md).

The reviewed Windows bundle is installed with PSF Python 3.14.10, an attested standalone Python 3.12.16 for Kronos, offline hash-locked dependencies, pinned public weights and a read-only installation tree. The gateway and Ollama use separate virtual service accounts. Installation registers them disabled and creates no production configuration, pairing, ledger or activation permit.

The actual restricted service account passed model-runtime integrity, trusted Tailscale status, held-connection ownership, exact-model share/negation fixtures, both Kronos horizons and a synthetic backup/restore with writer exclusion. The gateway peaked at 1.06 GiB of committed memory; the dedicated CPU model service peaked at 5.01 GiB under its revised 8 GiB cap. A small System service publishes only bounded, fresh Tailscale status; the gateway retains its separate restricted identity. The completed-snapshot restore fix is deployed. The actual service-account six-database backup, isolated restore and off-host Mac mirror match the exported state and pass integrity checks. All 16 pinned-TLS gateway checks passed before and after reboot, including actual assistant inference and Kronos. Tailscale unattended mode and delayed automatic services are configured.

## Acceptance before cutover

Use the synthetic preflight under the real gateway service account. It must verify trusted, fresh network status; exact model identity; explicit-share requests and negation; model unload; both Kronos horizons; bounded memory and shutdown; writer exclusion; and an isolated backup restore. It must not read production configuration or ledgers, open a gateway listener, access broker accounts or start the paper scheduler.

The assistant uses the reviewed CPU `qwen3.5:4b` candidate. Actual service-account inference passed, including explicit shares, fractional shares and negation, followed by unload and both pinned Kronos horizons. A 5 GiB shared service budget reproduced an allocation failure because it included the Python host; the reviewed 8 GiB cap resolves that failure while preserving the exact model digest, context and shared inference lock.

## Move the paper ledger and pair the iPhone

1. Stop and persistently fence the Mac gateway. Preserve its original configuration, pairing and TLS material for rollback.
2. Snapshot the five gateway SQLite databases and the shared admission database. Transfer them, the existing provider configuration and token cache over verified SSH into private Windows storage. Set explicit Admin/service ownership and ACLs; Unix permission bits do not establish Windows privacy.
3. Compare saved run IDs, observations, fills and pending decisions. Keep `paper_automation.py`, `paper_calendar.py`, `strategies.py` and `research.py` byte-identical.
4. Verify a completed backup and isolated restore while Windows remains fenced. Retain a private configuration backup and completed ledger snapshots on separate storage. The prepared Mac mirror runs when that Mac is awake; the PC gateway must operate independently.
5. After independent acceptance, create the separate activation permit, configure bounded service recovery and startup, and restrict HTTPS access to the intended Tailscale clients. Generate a fresh token and pinned TLS pairing for the desktop's MagicDNS identity.
6. Pair the USB iPhone and verify saved paper state, the assistant and Kronos with the Mac gateway stopped. Verify recovery after process failure and a Windows restart. A separate check is required to establish service availability before anyone signs in.

Live broker trading and transfers stay disabled, and the broker kill switch stays enabled. Paper observations continue prospectively; installation and model checks are not evidence of strategy profitability.

## Current operation and recovery evidence

Source `a7e4363`, installed manifest `65a1434d90611871c0be6d3e06342454b81514117a51b92608885cea430f9f52`. The gateway binds only the desktop Tailscale IPv4 and uses a new token and pinned certificate. The current firewall allows the Mac client only; phone access is awaiting a controlled route check. All broker live/trading/transfer flags stay off and the kill switch stays on. No real broker accounts were used as test probes.

The actual three service accounts are `NT SERVICE\TradePilot`, `NT SERVICE\TradePilotOllama` and LocalSystem for the fixed status-only publisher. All use delayed automatic startup. Recovery readback confirms restart delays of 15, 30 and 60 seconds followed by no action, with a one-day reset period. The first production backup completed automatically after 60 seconds.

After a graceful Windows reboot, all three services returned automatically with no manual service or app start. All 16 authenticated checks passed again. An interactive session was already present when inspected, so availability before user login remains unverified. An isolated gateway-process failure also recovered automatically; the other two service processes stayed unchanged, and pinned setup, paper and scheduler requests returned HTTP 200. A synchronous CIM monitoring call stalled, so the exact restart latency was not measured. See [migration acceptance](reports/home-pc-migration-2026-11-08.md).

The original Mac configuration, TLS, pairing and launch-agent plist are retained privately under `~/Documents/Backups/TradePilot/mac-fence-20261109T013831Z`. Exported Windows private material is retained under `home-pc-cutover-20261109T014605Z`. Completed Windows database backups are mirrored to `~/Documents/Backups/TradePilot/desktop-snapshots` when the Mac is awake; the PC has no operational dependency on that mirror. Snapshots are consistent per database, without a cross-database atomic-set guarantee.

Restore always targets a new isolated directory. A rollback must stop and persistently fence Windows before enabling any Mac writer; never reactivate the old Mac copy while Windows owns the ledger. Preserve the latest Windows state and reconcile changes before rolling back to an older snapshot.

The PC must stay powered, connected to the internet and available on Tailscale. Its current power plan has both AC sleep and AC hibernation timeouts set to zero, so idle power management will not suspend the server. The Mac can sleep; the off-host backup mirror catches up when it is awake. The iPhone still uses local development signing, with its current profile expiring November 11 at 00:35 Pacific. Gateway availability does not renew that app profile.
