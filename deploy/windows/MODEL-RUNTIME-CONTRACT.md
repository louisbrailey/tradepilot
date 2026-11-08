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

The deployment owner runs a verified installer copy from Administrator-only staging with a protected ALLOW receipt. The installer validates one manifest byte buffer and retains it for the installed receipt. It checks the machine Python signature, creates and protects `C:/Program Files/TradePilot`, copies and verifies every payload file and protects their ownership. Only then does it execute the installed version probe to require gateway Python 3.14.10/64. It invokes the installed extraction helper with `--archive`, `--receipt` and the fresh destination `C:/Program Files/TradePilot/model-python`. Existing deployments are refused and retained, so do not provision this root independently before running the complete installer.

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

The Ollama cache includes the public v2 tag `manifests-v2/ollama.com/library/qwen3.5/4b`, pinned to SHA-256 `492e37dc69072c5a189a0cf21d32d844c983d599e4553a1e4d2ebd3f6b1299e2`, together with the legacy tag and reviewed blobs. Ollama 0.40.15 selects its GGUF/llamacpp child `d8b0f5e9760cd1682034f292d7ef72ec46f432149be0df7574bf2d6e92e38c04`. The legacy tag alone reports a different identity in a fresh cache. Packaging rejects a missing or changed mapping; service preflight retains the exact selected-child digest check. Validation must use a fresh copy of packaged cache files, without a pull or existing user-cache metadata.

This path requires the deployment owner's independent approval for the exact full bundle. It creates no broker credentials, real ledgers, pairing, activation permit or running scheduler. The Mac remains the active writer until the separately owned cutover.
