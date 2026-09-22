# Private gateway service

TradePilot's gateway can run automatically as a per-user macOS launch agent. The Mac must be awake, signed in, and on the same trusted LAN as the iPhone. This is local hosting, so the phone cannot reach it when the Mac sleeps or either device changes networks. Live trading remains governed by the existing private configuration and by the app's separate order review and confirmation.

Use a private deployment under `~/Library/Application Support/TradePilot`, outside the source checkout. macOS can deny a background agent access to Documents, Desktop, or Downloads before its Python process or logs start. The manager refuses those paths for installation. This avoids depending on an interactive terminal's protected-folder access; it does not change macOS privacy settings or grant Full Disk Access.

## Deploy without changing credentials

`scripts/manage-local-service.py deploy` copies the gateway code and the existing private state to a **new** destination. It creates a fresh Python virtual environment using the existing interpreter and installed packages, with no downloads. It preserves the app token, Webull keys, TLS certificate/key, pairing file, order journal, broker token files, and string configuration such as `AI_PROVIDER` and `OLLAMA_MODEL`. The existing Ollama service remains separate on loopback port 11434; deploying the gateway does not install, start, or reconfigure that model service. Only `TRADEPILOT_RUNTIME` changes to the new private directory. It copies only Massive/Polygon assignments from the market environment file, excluding unrelated Signal Forge credentials. It also copies the validated, sanitized `BACKTEST-SUMMARY.json` into the deployment root for the authenticated evaluation endpoint. It never copies the raw historical bar cache.

First stop the old TradePilot gateway after any in-flight request has finished. Do not stop an unrelated application using port 8787 on another address. The `--source-stopped` flag records that this has been done; the manager does not kill processes. Never run the old and new gateway together against divergent copies of the same trading state.

Review the deployment first. Dry run reads configuration privately but writes nothing and starts nothing:

```sh
python3 scripts/manage-local-service.py deploy \
  --destination "$HOME/Library/Application Support/TradePilot/gateway" \
  --private-dir /absolute/path/to/work/private \
  --address 192.168.68.66 \
  --market-env /absolute/path/to/signal-forge/.env \
  --python /absolute/path/to/webull-venv/bin/python \
  --dry-run
```

After stopping the source gateway, replace `--dry-run` with `--source-stopped`. The destination must not already exist. A failed deployment is retained for inspection and the source remains unchanged. A successful deployment includes a private review plist and has passed real imports of the installed Webull SDK.

All private directories use mode 700 and private files use mode 600. The script refuses symbolic links in the copied runtime and never includes private data in the source archive. Keep deployment directories and backups out of source control.

## Install the deployed service

Run the manager from the **new deployment**, using only its new paths. The certificate must already contain the selected address as an IP subject-alternative-name. No credentials or certificates are created or rotated by these commands.

```sh
python3 "$HOME/Library/Application Support/TradePilot/gateway/scripts/manage-local-service.py" install \
  --private-dir "$HOME/Library/Application Support/TradePilot/gateway/private" \
  --address 192.168.68.66 \
  --market-env "$HOME/Library/Application Support/TradePilot/gateway/private/market.env" \
  --python "$HOME/Library/Application Support/TradePilot/gateway/venv/bin/python" \
  --dry-run
```

Omit `--dry-run` to install and load the service. Dry run writes only a review plist and creates an owner-only log file in the private directory. Installation writes `~/Library/LaunchAgents/com.tradepilot.private-gateway.plist`, using an argument array without a shell. It unloads only that existing TradePilot label before loading the replacement. Existing plists receive recoverable backups. Child files inherit an owner-only umask; standard output and error go to `private/server.log`.

```sh
python3 "$HOME/Library/Application Support/TradePilot/gateway/scripts/manage-local-service.py" status
```

Status reports load state, PID, start count, and last exit code without reading private configuration. A failed process restarts with a 30-second throttle. Successful loading alone does not prove that the gateway is responding: verify the app's authenticated **Check connection & setup** screen, then a read-only account or market-data request. A TLS error must be resolved rather than bypassed.

## Addresses and local hostnames

Use the current private LAN address that matches the phone's pairing record and certificate. Literal addresses avoid ambiguous local hostname resolution. DHCP can change the address after reconnecting or restarting. With address mode, a changed address requires stopping the gateway, preserving the existing credentials and journal, deliberately updating the certificate/pairing record, and reinstalling at the new address. The tool never rotates a certificate silently.

Hostname mode is available if the Mac's `.local` name resolves to its reachable LAN address on the client and the certificate contains that DNS name. Replace `--address` with `--hostname Your-Mac.local --interface en0` during deployment and installation. Each startup discovers the interface's current private IPv4 address and binds that specific address. If no valid address exists, it exits and launchd retries. **A DHCP change while the server is already running still requires restarting this TradePilot service.** It does not monitor or rewrite network settings.

A simulator shares the Mac's DNS environment. If the hostname resolves first to `127.0.0.1`, it may connect to another local service, producing a certificate mismatch. Do not bypass certificate checks or stop that other service. Use a matching literal LAN-IP pairing record, or correct hostname resolution through an explicitly reviewed network setup. This limitation also means hostname mode is not a promise of uninterrupted connectivity.

## Remove or update

```sh
python3 "$HOME/Library/Application Support/TradePilot/gateway/scripts/manage-local-service.py" remove
```

Removal unloads only `com.tradepilot.private-gateway` for the current user and moves its plist to a recoverable `.removed` backup. It preserves the deployment, credentials, certificates, logs, and all journal data.

To update, stop/remove the running TradePilot service, deploy the updated source into a new directory using the **currently active deployment's** `private` directory and `private/market.env` as inputs, and install the new deployment. Retain the stopped previous version for rollback. Once a new deployment has accepted orders, its current journal and token files are authoritative; never roll back to a stale journal snapshot.
