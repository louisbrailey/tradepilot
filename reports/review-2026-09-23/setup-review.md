# Local setup review — September 23, 2026

Reviewed source: `scripts/manage-local-service.py`, `scripts/pair-local-server.py`, `scripts/start-private-server.sh`, `scripts/install-iphone.sh`, and `scripts/test_local_service.py`. This review used synthetic configuration, temporary keys/files, and mocked launchd calls. It did not read deployed credentials, contact brokers, modify a deployed service, or install on a phone. Claude did not participate in this review; the coordinating task reported that its local CLI was unauthenticated.

## Fixed findings

- **Pairing could change configuration on a refused rerun.** Previously, configuration defaults were written before the check for existing TLS files. Pairing now refuses existing TLS or pairing files before reading or rewriting configuration. A regression test verifies byte-for-byte configuration preservation for each existing artifact.
- **Pairing accepted an existing directory readable by other users and unsafe existing inputs.** The script now requires an owner-only ordinary directory, an owner-only ordinary configuration file, valid string configuration values, and an existing token of at least 32 characters. Symlinked configuration and dangling TLS/pairing symlinks are refused. New private artifacts use exclusive creation with mode 600; the caller's umask is restored. Certificate generation happens before filesystem mutation, including when the required cryptography dependency is unavailable.
- **Pairing accepted addresses that were not usable private LAN endpoints.** Wildcard, loopback, link-local, multicast, and public addresses are refused. Hostnames remain single-label `.local` names. The manual launcher now uses the manager's same private-address and certificate preflight.
- **Service replacement checked certificate names but not usable TLS material.** Preflight now checks certificate validity dates and whether the key loads with the certificate before any launchd change. Encrypted keys cannot cause an unattended password prompt. Invalid, expired, future-dated, or mismatched material fails closed. Temporary real self-signed certificates verify matching/mismatching key handling; controlled certificate dates verify validity bounds.
- **Installation followed an existing log symlink.** Secret input files, the server log, and a dry-run review plist must be ordinary files. The log regression verifies that an unrelated symlink target keeps its content and permissions.
- **Shell helpers reported missing arguments as success.** Both helpers return exit 2 for invalid invocation and retain exit 0 for explicit help. No physical installation command was executed in validation.

## Verification evidence

Baseline: 8 setup tests passed, log `.toolkit-runs/20260923T074643.130098Z.log`.

After changes: 22 setup tests passed, including 14 new tests, using:

```sh
devkit run --lines 40 -- python3 -m unittest discover -s scripts -p test_local_service.py -v
```

Full log: `.toolkit-runs/20260923T075135.667486Z.log`. `bash -n` passed for both shell helpers. Pairing and foreground-manager `--help` passed. `git diff --check` passed. Successful synthetic deployment checks preserve the source configuration and runtime, keep live trading disabled, filter unrelated environment keys, preserve the virtualenv interpreter path, and make no launchd call.

## Completeness and remaining limits

- Local hosting remains dependent on an awake, signed-in Mac and reachable LAN. The documented 30-second launchd failure retry remains unchanged. A DHCP change while running still needs a service restart; there is no network-change watcher.
- Certificates remain valid for 90 days when generated. Renewal/re-pairing is deliberate; there is no automatic renewal workflow. Preflight reports unusable certificates instead of silently rotating trust or unloading the current service.
- The source changes have not been deployed. They do not establish that the current gateway is serving this revision or that phone pairing works against it.
- Fresh pairing's cryptographic generation requires a Python environment with `cryptography`. The host's default `python3` lacks it. The coordinating agent subsequently used the existing backend virtualenv to generate real certificates and a pairing file in a temporary directory, load the matching key/certificate, validate file modes and token binding, and verify a refused rerun leaves files byte-identical. Log: `.toolkit-runs/20260923T075515.806506Z.log`. No dependency was installed or deployed configuration changed.
- Physical device availability, signing, and installation are the coordinating agent's separate verification scope. These script changes do not resolve missing trusted hardware or Apple/Webull authentication.
- The backend owner resolved the IPv6 mismatch by selecting the listener address family. Subsequent isolated IPv4 and IPv6 authenticated setup checks both returned HTTP 200 with synthetic configuration. Log: `.toolkit-runs/20260923T075305.305552Z.log`.
- Safe update still requires stopping the old source first, deploying into a fresh directory from the latest authoritative private runtime, and avoiding rollback to a stale trading journal. Tests model this protocol; they do not prove a deployed process was stopped.

Evidence continuity: source task `01a08c5d-a368-7812-80bd-966e6b5916d7`, handoff checkpoint `/Users/louisbrailey/.local/share/codex-continuity/notes/20260923-004404-5bd7d5eb.md`, migration source record `17620`.
