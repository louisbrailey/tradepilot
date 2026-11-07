# Always-on private gateway — prepared, not deployed

The intended deployment is now the user's [home PC](HOME-PC.md). The Ubuntu installer and single-writer migration steps below also apply to its guest VM. The VPS section records the earlier hosting proposal.

The Mac remains the active gateway. No cloud account/server has been created, no
hosting charge incurred, and no credentials or ledgers transferred for this work.
This plan includes the gateway, paper scheduler, AI and Kronos on one remote host.

## Hosting choice and cost

Selected after the user requested lower cost: **OVHcloud US VPS-2 2027**, **4 shared
vCores / 8 GB RAM / 75 GB NVMe**, Ubuntu 24.04 x86_64, Canada East (Beauharnois).
The live configurator on November 5, 2026 shows **$10/month with no long-term
commitment**, plus **$2.20/month Premium automatic backup** for seven daily restore
points: **$12.20/month before tax**. This replaces the $57.60 DigitalOcean proposal;
do not create or pay for that older proposal. The advertised $8.50 base rate requires
12 months upfront and is not the selected billing arrangement.

Confirm the exact checkout, renewal amount, taxes and included IPv4 before payment.
No GPU, managed database, additional volume, paid AI API or automatic upgrade is
planned. The configurator currently offers this model in Canada, and says services
outside US regions cannot be modified/upgraded after delivery. Do not rely on an
in-place resize if capacity tests fail. Monthly service renews automatically; powering
off does not cancel billing. Preserve state before explicit service cancellation.

Sources: [VPS specifications](https://us.ovhcloud.com/vps/),
[live configurator](https://us.ovhcloud.com/vps/configurator/?planCode=vps-2027-model2),
[billing and cancellation](https://support.us.ovhcloud.com/hc/en-us/articles/360002306224-Overview-of-Billing-with-OVHcloud-US).

The Mac's Qwen35 27.3B model will be replaced on this host by **Qwen3.5:4b**;
the 27.3B model is not a realistic fit for this memory budget. Smaller AI may have
lower answer quality. Kronos-small and its tokenizer retain their pinned revisions.
CPU latency and memory use are **not yet measured on this host**. Both models must
pass the acceptance checks below before cutover; do not silently resize or buy GPU
time if they fail. [Model specification](https://ollama.com/library/qwen3.5:4b).

## Privacy and topology

The iPhone connects through Tailscale to the server's full MagicDNS name, with
TradePilot's existing exact certificate pin and bearer authentication. Port 8787
binds only the assigned Tailscale IPv4 address. Never publish it or Ollama's 11434
port, configure Funnel, or disable certificate verification. Ollama uses loopback,
cloud inference disabled, one loaded model, and unload-after-response. Gateway AI
and Kronos serialize their requests through one lock. Memory limits bound both
services; timeouts/failures still require actual host stress verification.

Moving the gateway means the user's server and its provider backups will store the
Webull/Coinbase read credentials, market-data key, private ledgers and broker token
cache. Selected AI context travels encrypted to that server and is processed by
local weights there. No credentials belong in Git, cloud-init, shell arguments,
chat, images, logs or this document. Use owner-only files and SSH/SFTP with verified
host keys. Provider disk backups are a separate trust boundary; do not claim the
hosting operator cannot access guest data. Keep broker writes and transfers disabled.

## Stage the host without activating a second paper worker

1. Complete the hosting account, billing and exact plan selection. Use an SSH key,
   MFA and a host firewall, plus provider filtering where available. Initially permit SSH only from the operator's current
   IP; deny public inbound 8787 and 11434. Permit outbound HTTPS and Tailscale's
   documented connectivity. Keep console recovery access available.
2. Install Tailscale using its official Ubuntu instructions, join the existing
   private tailnet interactively, and record the actual server IPv4/MagicDNS name.
   Verify the iPhone running TradePilot is also joined; the other iPhone being
   online is not proof. Restrict device access with tailnet grants/ACLs. Review node
   key expiry for this unattended server. After proving a second private SSH session
   works, remove public SSH ingress. Do not lock out the only management route.
3. Install Ollama **0.40.11** from the official Linux release, verify its published
   release digest when available, and enable its systemd service. Use the official
   versioned installation procedure; never copy the Mac application binary.
   [Linux instructions](https://docs.ollama.com/linux),
   [release](https://github.com/ollama/ollama/releases/tag/v0.40.11),
   [Tailscale Linux](https://tailscale.com/kb/1031/install-linux).
4. Transfer a source-only `git archive` of the reviewed commit, not a recursive
   copy of this working directory. Extract it on the new server. Run
   `sudo bash deploy/remote/install.sh` there. It refuses existing application/state
   directories. It installs the backend, CPU-only Kronos, pinned public weights,
   Qwen3.5:4b and systemd definitions. It **does not enable/start the gateway or backup
   timer**. Installation errors leave staging for inspection; no destructive retry
   or automatic removal is performed.
5. With isolated fake state, verify the installed backend tests and real model
   inference. Do not copy real account credentials or active paper runs for this
   test. Check Qwen output against the app's JSON schema, cold/warm latency within
   the existing 90-second server timeout, and Kronos 5/20-session three-path replay
   from public fixture bars. Inspect memory peaks, OOM/restart counts and responsiveness
   during inference. The prepared resource limits are candidates, not capacity proof.

## Cutover — one writer, preserved history

Only begin after the new host passes its checks. Schedule away from the 20:15 ET
paper observation. Existing runs cannot make up missed decisions retrospectively.

1. Deploy the reviewed gateway source containing `GATEWAY_DISABLED` to the Mac
   through the existing backed-up deployment process. Compare SHA-256 of
   `paper_automation.py`, `paper_calendar.py`, `strategies.py` and `research.py`
   against the active deployment and new host: these files must remain identical
   for the active immutable protocols. Do not reset or recreate the three runs.
2. Atomically set Mac private config `GATEWAY_DISABLED` to `enabled`, retaining
   mode 600. This prevents subsequent starts; it does **not** stop an existing
   process. Unload `com.tradepilot.private-gateway`, verify its process/listener
   exited, and preserve the plist/config/pairing for rollback. Keep it unloaded
   and fenced through reboot. Do not re-enable it merely because the cloud is slow.
3. With the writer stopped, snapshot all private runtime databases using SQLite's
   backup API, verifying integrity and recording file digests. Preserve non-database
   Webull token-cache files too. Separately snapshot the shared admission database at
   `~/Library/Application Support/BrokerAccess/admission.sqlite3`. Do not copy a live
   SQLite main file while omitting its WAL. Retain original local files unchanged.
4. Transfer the snapshot, needed broker credentials and **only** accepted market
   key variables over verified SSH to owner-only storage. On the host use:

   - `/var/lib/tradepilot/private/config.json` (600)
   - `/var/lib/tradepilot/private/market.env` (600)
   - `/var/lib/tradepilot/private/runtime/` (700; files 600)
   - `/var/lib/tradepilot/Library/Application Support/BrokerAccess/admission.sqlite3`

   The service account owns state; root owns application code. Keep source gateway
   fenced. The shared admission snapshot does not coordinate future Mac/remote
   financial writes: those remain disabled.
5. Adapt the copied config without printing secrets: retain read credentials,
   set `TRADEPILOT_RUNTIME=/var/lib/tradepilot/private/runtime`,
   `KRONOS_HOME=/opt/tradepilot/kronos`,
   `KRONOS_PYTHON=/opt/tradepilot/kronos-venv/bin/python`, `AI_PROVIDER=ollama`,
   `OLLAMA_MODEL=qwen3.5:4b`, `OLLAMA_LOOPBACK_HOST=127.0.0.1`,
   `LOCAL_AI_KEEP_ALIVE=0`, `WEBULL_LIVE_TRADING=disabled`,
   `COINBASE_LIVE_TRADING=disabled`, `COINBASE_TRANSFERS=disabled`,
   `BROKER_KILL_SWITCH=enabled`, `GATEWAY_DISABLED=enabled`. Remove unused OpenAI
   credentials and generate a fresh random app token of at least 32 characters.
6. Write owner-only `/var/lib/tradepilot/remote.json` with exactly `address` and
   `hostname` from this node. Create new TLS material/pairing with the backend Python
   and `scripts/pair-local-server.py --network tailscale --private-dir
   /var/lib/tradepilot/private --address <actual-node-ip> --hostname <actual-node-name>`.
   Do not copy the Mac TLS identity. The tool refuses overwriting existing pairing.
   Confirm broker IP allowlists include the new static egress IP before read checks;
   retain old access until the new route is verified. Do not broaden key permissions.
7. Compare source/destination run IDs, code/protocol hashes, observation/fill/event
   counts and next-session intentions while both services remain stopped. Verify
   every restored database and record a private migration manifest. Only then set
   remote `GATEWAY_DISABLED=disabled` and run
   `sudo systemctl enable --now tradepilot.service tradepilot-backup.timer`.
8. Import the new pairing on the actual TradePilot iPhone and connect its Tailscale
   VPN. With Mac gateway still stopped, turn off phone Wi-Fi and verify setup,
   account reads, research, both model workflows and paper history over cellular.
   Check remote restart/reboot recovery and the next real scheduled observation.
   Do not submit real orders or create extra paper fills to prove migration.

Until these checks pass, describe this as staged or partially verified, never as
an operational always-on migration. Hosting is independent of the Mac once verified;
the current iPhone development signature still expires and requires local reinstall.

## Backups and recovery

The daily systemd timer creates owner-only SQLite backups with integrity checks;
each database is consistent individually. They are not a cross-database transaction
snapshot while the service is running. A `complete.json` marker is written last;
never restore an incomplete directory. Local snapshots alone do not survive loss
of the server, which is why provider backups are included. Verify a restore on a
fenced temporary host before relying on recovery. Keep all restored gateways fenced
until the original is stopped. Monitor failed units, last backup, disk use and paper
heartbeat; no external notification channel or automated retention deletion is
configured by these files.

If cutover fails **before** any cloud observation/write, stop and fence the cloud
copy, confirm it cannot restart, then restore the Mac's original configuration and
pairing and explicitly clear its fence. If cloud state advanced, preserve it and
reconcile/copy that latest state back while both copies are stopped; never restore
an old ledger over new observations. Re-pair the phone deliberately. Backups and
old hosts contain secrets and need deliberate retention/deletion.

The pinned leaf certificate lasts 90 days. Record its expiry, arrange renewal and
re-pair before then; automatic certificate rollover is not implemented. Keep routine
OS security updates, bounded application upgrades, provider account MFA and billing
alerts in the operating checklist. This is one host with backups, not a redundant
high-availability cluster.
