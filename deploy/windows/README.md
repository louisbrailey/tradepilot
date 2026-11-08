# Native Windows candidate — NOT approved for activation

Based on TradePilot c4fd7bdb41b102f9e2c8397b06c5fa6b21012d5c. Windows changes only; no iOS/release changes. The Mac is still the sole paper writer. No service, production listener, firewall, pairing, broker request or state migration was performed while preparing this candidate.

## Implemented boundaries

- Frozen paper_automation.py, paper_calendar.py, strategies.py and research.py retain exact original Git blob bytes. Scoped -text attributes prevent Git conversion; package_candidate.py independently checks SHA256.
- windows_runtime.py checks actual DACL owner/ACEs, rejects NULL/unsupported ACLs, untrusted grants, hard-link files, UNC/ADS/traversal and reparse ancestors. It creates runtime children only beneath an already private parent. It does not pretend chmod secures NTFS. The threat model trusts the current service identity, SYSTEM and Administrators; validation is not a general race-proof sandbox against that same trusted identity.
- All gateway entrypoints use private runtime creation; Windows admission state is inside the backed-up runtime. Direct server.py startup on Windows is refused. Existing POSIX behavior remains available.
- Kronos receives an allowlisted Windows environment without gateway/broker secrets. A suspended process enters a kill-on-close Job Object before resume; timeout and completion kill its child tree. Model scratch is private and scoped. CPU/four Torch threads are preserved.
- Windows transport failures/incomplete Ollama chat responses poison the shared inference lock. Restart requires Ollama0.40.15 reporting no loaded models before workers start. The exclusive runtime file handle excludes a second gateway, snapshot or restore. Keep qwen3.5:4b and keep_alive=0; no2B/0.6B substitute.
- Gateway lifecycle reuses existing remote preflight (Tailscale identity, pinned TLS, pairing, migration fence and disabled broker flags). Missing cutover permit prevents startup. Network identity/config are rechecked during operation. Both existing background workers are retained and explicitly stopped/drained.
- SCM service classes use separate virtual identities, no interactive login and no LocalSystem runtime. A service-level Job Object contains children with3GiB gateway/5GiB Ollama committed-memory budgets; these are not GPU VRAM limits. Timeout forces process exit and OS job cleanup.
- snapshots.py takes offline, exclusive, fenced SQLite backups including admission state, checks integrity, hashes members and publishes a completion manifest last. Restore verifies hashes and restores only to a new isolated directory. It never overwrites or activates the production runtime. Partial snapshots remain evidence and are not automatically deleted. This is an offline maintenance workflow, not a tested automatic backup schedule.

## Supported gateway dependency candidate

Gateway: Python3.14.7, Webull SDK3.0.4, cryptography50.0.2, pywin32 311, tzdata2026.2. Full hashes and transitive versions are in requirements.lock. SDK3.0.4 metadata permits cryptography>=43,<55 on Python>=3.14; no metadata override or --no-deps installation was used. The Mac dependency files are unchanged.

The discarded Python3.12/SDK3.0.0 trial required cryptography42.0.8 and is NOT accepted. A subsequent48.0.1 trial had6 audit findings (3 unique advisory IDs);50.0.2 resolves those reported findings. pip-audit against the final installed gateway environment reported no known vulnerabilities on2026-11-08, with no skipped packages. This is a dated advisory check, not a guarantee of security.

Primary sources: https://pypi.org/pypi/webull-openapi-python-sdk/3.0.4/json ; https://github.com/pyca/cryptography/security/advisories/GHSA-537c-gmf6-5ccf . The SDK wheel SHA256 is801e21e6c18d955e0be4bbc2fe33fa6cef52a34ec2e731949348ab7b0801b4c0.

Kronos remains a separate Python3.12 environment, source commit67b630e67f6a18c9e9be918d9b4337c960db1e9a, original remote model requirements and pinned public model revisions. kronos.lock resolves those pins; PyPI advisory metadata checks for27 resolved packages returned no flagged/unknown entries. This is NOT an installed-Kronos audit or inference validation. GPU wheel selection/ABI imports remain unverified.

Ollama0.40.15 is retained as the Windows candidate version, not silently downgraded to the Linux0.40.11 pin. Startup checks that version, but actual4B inference is UNVERIFIED. Existing desktop Ollama is not stopped or repurposed. The service refuses an occupied11434 port; later coordination must prevent competition for that port.

## Reviewable installation, not activation

1. Prepare public gateway wheels from requirements.lock using Python3.14 and separate model wheels from kronos.lock using Python3.12. Keep build/source provenance, then audit wheel contents and hashes. Do not install an old vulnerable gateway lock.
2. package_candidate.py requires --source, --wheels, --ollama, --output, --kronos-source and --kronos-wheels. Use the official complete Ollama0.40.15 distribution and the pinned Kronos repository. It produces an allowlisted source bundle, wheel-specific offline requirements and manifest.json. No private config, runtime or history is packaged. A complete deployment bundle was NOT built during this source-candidate pass.
3. Obtain gatekeeper ALLOW for the exact candidate and bundle manifest. The approval JSON consumed by the installer contains decision=ALLOW and manifest_sha256. This is an administrator-supplied review receipt, not a cryptographic gatekeeper attestation.
4. In a separately authorized administrator session, after signed machine-wide Python3.14 and3.12 installations exist:

```powershell
& .\deploy\windows\Install-Candidate.ps1 -Bundle 'C:\reviewed-bundle' -Python 'C:\Program Files\Python314\python.exe' -ModelPython 'C:\Program Files\Python312\python.exe' -GatekeeperAllow 'C:\reviewed-allow.json'
```

The exact script is reviewable and has only been parsed, NOT run. It refuses existing deployments, verifies manifest hashes before and after copying, creates immutable installation files and separate environments, and registers both services DISABLED. It provisions separate private directories for gateway and Ollama. Failure leaves partial files/disabled service registrations for inspection; it does not delete an existing deployment or perform an automatic rollback. Machine-wide signed Python prerequisites are not currently proven installed.

No credentials, pairing, firewall rule, cutover permit, automatic startup or recovery is created. Later reviewed configuration must set absolute KRONOS_HOME, KRONOS_PYTHON and HF_HOME, preserve pinned model refs using the included cache-models.py, and supply the4B model cache. Public weight staging and final private config provision are separate steps.

Unattended activation requires a separate reviewed step: delayed automatic service startup, Tailscale/Ollama dependencies and bounded recovery, exact Tailscale firewall scope and a Mac-owned fenced cutover permit. Do not activate this candidate merely because unit tests pass. The permit fields are gatekeeper=ALLOW, mac_writer_fenced=true, activate_windows=true; installation never creates it. Existing GATEWAY_DISABLED semantics are preserved: value 'disabled' means the migration-disable switch is off. Backup/restore require that switch ON and the permit absent.

## Tests and remaining acceptance

Run tests in the isolated Python3.14 gateway environment:

```text
python deploy/windows/run_backend_tests.py
python -m unittest discover -s deploy/windows -p test_windows.py -v
python -m unittest discover -s deploy/windows -p test_sdk_contract.py -v
```

The backend runner prohibits outbound sockets, permits only ephemeral loopback test binds and the reviewed OpenSSL certificate fixture, clears inherited credentials, and supplies genuine private disposable ACL fixtures. Existing script suites with macOS/system mutation assumptions were not run. The installed SDK test mocks token initialization and transport before constructing requests; it does not authenticate or contact an account.

Verified:278 backend tests;9 Windows tests covering ACL rejection/private inheritance, junction rejection, exclusive lock, child environment, suspended-job I/O/timeout, snapshot/restore tampering and fencing, missing-cutover startup rejection, mocked dual-worker shutdown and inference poisoning;2 real-SDK/crypto synthetic contract tests. Installer parsing and frozen-byte comparison pass. Full local devkit logs remain outside Git. Tests are not service integration acceptance.

Required before merge/activation: independent gatekeeper review; complete bundle/manifest review; actual SCM registration/import/DLL discovery under virtual accounts; all ancestor/install ACL and reparse-race review; synthetic child/grandchild crash cleanup and prolonged output/disk pressure; backup crash-consistency/restore drill and scheduled maintenance design; qwen3.5:4b exact-share/schema cold/warm latency and RAM/VRAM benchmarks; actual pinned Kronos imports/offline inference and90-second acceptance; no model overlap; final-service-identity GPU access; Tailscale startup/loss/recovery; reboot-before-login and logout survival; bounded shutdown with stalled requests; power/sleep availability. These are UNVERIFIED, not waived. No reboot, power change, production scheduler or second writer is authorized by this document.
