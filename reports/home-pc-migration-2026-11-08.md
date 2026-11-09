# Home-PC migration acceptance — November 8, 2026

The home Windows PC now owns the TradePilot paper gateway and saved ledger. The Mac gateway is stopped, persistently disabled and configuration-fenced. The PC runs the paper scheduler, local Ollama assistant and Kronos independently. Physical iPhone access to this new endpoint remains pending; the controlled phone route check has not run.

## Deployed system

Source `a7e436380bed628adf2f5db0f362be9c37475967`, installed bundle manifest `65a1434d90611871c0be6d3e06342454b81514117a51b92608885cea430f9f52`. The source is pushed and [CI passed](https://github.com/louisbrailey/tradepilot/actions/runs/42551338815). Native Windows tests passed 67; script tests passed 71.

The native Windows services use separate gateway and Ollama virtual service accounts and a fixed LocalSystem network-status publisher. All three use delayed automatic startup. The gateway binds only the desktop Tailscale address, with hostname verification, a fresh access token and a pinned certificate. The firewall currently allows only the Mac client. Broker live trading and transfers remain disabled, and the broker kill switch remains enabled.

The exact CPU model, `qwen3.5:4b`, passed the actual service-account share/negation fixtures, unload and both Kronos horizons. The dedicated model service has an 8 GiB cap; the gateway has a 3 GiB cap. Public model weights, runtime files and offline dependencies were verified. These checks establish deployment behavior, not investment performance.

## Accepted evidence

| Check | Observed result |
| --- | --- |
| Ledger migration | Six databases retain the exported schemas and stored row fingerprints; integrity checks pass. |
| Saved automation | Three run IDs preserved, two observations each, fill counts 1/0/0 and November 9 next sessions. No new strategy armed. |
| Recovery copy | A real service-account backup, isolated restore and off-host Mac mirror match the exported state. Restore did not replace the active ledger. |
| Periodic backup | First production snapshot completed automatically and its six files were mirrored and verified off-host. |
| First production check | All 16 hostname-verified, exact-certificate authenticated checks passed, including actual demo AI and Kronos inference. |
| Graceful reboot | Boot time changed from November 8 18:30:15 UTC to November 9 03:15:17 UTC. All three services returned automatically; the watcher did not start them. No forced application closure was requested. |
| After reboot | All 16 authenticated checks passed again; saved paper state remained intact. |
| Isolated gateway fault | Gateway PID changed from 22964 to 27924 and returned Running automatically. Ollama and publisher PIDs stayed unchanged. Pinned setup, paper and scheduler requests returned HTTP 200. |
| Idle power policy | Active power plan has AC sleep and AC hibernation timeouts set to zero; no power setting was changed during this readback. |

Recovery policy readback confirms restart delays of 15, 30 and 60 seconds, then no action, with a one-day reset period. The process-fault monitor stalled in a synchronous CIM call; separate native status and authenticated API checks established recovery, but exact restart latency was not measured. An interactive Windows session was already present when the reboot was inspected, so service availability before user login remains unverified.

The live checks covered setup, authentication rejection, alerts, Markets/search/quotes/charts, crypto prices, read-only options, manual paper state, automated paper state, frozen evaluation and model routes. They did not use real broker accounts or submit, cancel or transfer anything. `paper_automation.py`, `paper_calendar.py`, `strategies.py` and `research.py` remain byte-identical.

## Private operational evidence

Detailed receipts and logs are local, excluded from Git along with credentials and runtime state. Under `.toolkit-runs/windows-review-20261108/`, the key receipts are `real-state-acceptance.json`, `real-maintenance-backup.json`, `real-maintenance-restore-isolated.json`, `first-periodic-backup.json`, `production-health-after-reboot.json`, `reboot-autostart.json`, `recovery-native-status.log`, `recovery-api-current.json`, `process-recovery-verified.json` and `power-settings-readback.log`. The complete post-reboot health log is `.toolkit-runs/20261109T032028.834708Z.log`.

The successful protected production stage is `C:\ProgramData\TradePilotProductionApproval-fdf10986dc5f43cb85926b1ceaf5b064`. A subsequent duplicate activation attempt was refused before changing production state; its separate evidence was retained. Activation must not be replayed against this active deployment.

## Operation and remaining acceptance

Keep the PC powered, connected and available on Tailscale. The Mac can sleep; its hourly off-host mirror catches up when available. Windows maintains its own periodic snapshots. Each database snapshot is consistent, with no claim of a cross-database atomic set.

The new private desktop pairing was copied successfully into the exact USB iPhone's app Documents directory after its certificate was verified against the running gateway. Import and a successful phone request remain unverified because the phone is locked. The candidate phone address has not been established as that device. An independently reviewed, bounded route probe may retain only the exact verified phone and Mac addresses; missing device/source evidence must restore the Mac-only rule. The probe's independent rollback task is a scheduler safeguard, not a guaranteed real-time deadline during OS suspension or scheduler failure.

The current iPhone development profile expires November 11 at 00:35 Pacific. The user chose to retain local development installation. Renewal still requires the appropriate Apple ID in Xcode; the always-on gateway does not remove this signing limit.

For rollback, stop and persistently fence Windows first. Preserve its latest state before considering the older Mac copy, and reconcile any intervening paper observations. Never run both ledger writers. See [the operational runbook](../HOME-PC.md) and [remaining product work](../tasks/todo.md).
