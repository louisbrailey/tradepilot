# Model runtime provisioning contract

The complete disabled installer owns provisioning. Review `Install-Candidate.ps1` and `runtime_provenance.py` together; running the extraction helper alone does not establish protected machine ownership or service readiness.

## Inputs

- Archive: `runtime/model-python.tar.gz`, Astral CPython 3.12.16 x86_64 Windows release `20261026`.
- Exact archive SHA-256: `1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149`.
- Receipt: `runtime/model-provenance.json`, bound by the complete bundle's approved manifest hash.
- Receipt fields required by the helper:
  - `archive_sha256`: the exact archive hash above.
  - `identity`: `https://github.com/astral-sh/python-build-standalone/.github/workflows/release.yml@refs/heads/main`.
  - `attestation_verification_exit`: integer `0`.
  - `predicate`: `https://slsa.dev/provenance/v1`.
- The bundle also retains `runtime/model-attestation.jsonl` and `runtime/model-verification.json` for independent review. The summary receipt does not itself perform a fresh cryptographic attestation check; the compiled-in archive hash binds the reviewed artifact.

## Installation and output

The installer first verifies the complete bundle and actual PSF-signed machine Python 3.14.10, then creates and protects `C:/Program Files/TradePilot`. It invokes the helper with `--archive`, `--receipt` and the fresh destination `C:/Program Files/TradePilot/model-python`. Existing deployments are refused and retained, so do not provision this root independently before running the complete installer.

The helper checks every tar path, rejects links and duplicate case-insensitive names, and accepts only ordinary files/directories under the archive's `python` root. It omits regenerable `.pyc`/`__pycache__` content. The extracted `python.exe` must have SHA-256 `246221b571e7a692a8b26818b628cac4c163e836de9897812eaebc2a8e1efa90`.

It writes `model-python/installed-members.json` with this exact schema:

```json
{
  "version": "3.12.16",
  "architecture": "x86_64",
  "archive_sha256": "1f2ab53880fc67ea323398c6388e05af28addc99a8e389209f08a51fdff4b149",
  "bytecode": "Excluded; runtime uses dont_write_bytecode",
  "files": { "relative/path": "sha256 of installed member" }
}
```

`relative/path` above is a schema illustration, not a valid production receipt. The helper generates every real member entry from extracted bytes. The installer applies Administrator ownership and protected System/Administrators write permissions, with authenticated-user read/execute access, then runs `runtime_identity.py` through the extracted interpreter and requires `3.12.16/64`. A failed extraction/check leaves evidence for owner inspection; no automated deletion or overwrite occurs.

The same service preflight verifies the protected installed receipt, every recorded member hash and the pinned interpreter hash through `verify_installed`. It separately exercises Kronos as the real service identity. Successful extraction alone does not pass that service gate, authorize startup or establish a Mac-writer fence.

## Reviewed execution boundary

This path requires the deployment owner's independent approval for the exact full bundle. It creates no broker credentials, real ledgers, pairing, activation permit or running scheduler. The Mac remains the active writer until the separately owned cutover.
