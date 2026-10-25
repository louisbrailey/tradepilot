# TradePilot source review — September 23, 2026

The independent Codex review repaired confirmed defects and reproduced the existing backtest. **Claude did not participate:** an actual read-only Claude Code request returned “Not logged in · Please run /login”. Its sanitized [attempt result](claude-attempt.json) and [continuation handoff](CLAUDE-HANDOFF.md) are saved. This is source verification, not proof of working production brokerage authentication or physical iPhone installation.

## Changes

- **Execution integrity:** a conditional ledger update prevents a stale cancellation from overwriting a concurrently submitted review. Persisted cumulative fill quantities cannot regress when optional receipt fields disappear or after restart. Invalid explicit fill prices fail validation while genuinely missing optional values remain supported.
- **iPhone order review:** preview terms are compared with the captured request, including order type, quantity, limit, market, instrument and session. Responses remain bound to the original endpoint and token. Receipt identity is checked before display or journaling. Connection changes clear stale account and review data while retaining unresolved-order recovery protection. See [iPhone review](ios-review.md).
- **Gateway parsing:** ambiguous duplicate headers, transfer encoding, malformed sizes and truncated request bodies are rejected. IPv6 listener selection now matches private IPv6 endpoints accepted by the setup scripts.
- **Research integrity:** strict daily-bar validation, actual provider-adjustment checks for new data, private-cache and frozen-protocol checks, concurrent observation locking, consistent recorded-evaluation projection, and closure of provider error responses. Existing legacy adjustment response envelopes remain unknown rather than fabricated. See [research audit](RESEARCH-AUDIT.md).
- **Local setup:** pairing refuses conflicting artifacts before modifying configuration, protects private files, validates usable LAN addresses and TLS material, and refuses unsafe symlinks. Shell helpers now distinguish missing arguments from successful help. See [setup review](setup-review.md).

## Verification

| Check | Result | Full local evidence |
|---|---|---|
| Combined project gate | 148 tests: 13 core, 99 backend, 36 scripts; Swift journal, connection, order-review and evaluation smoke checks also pass | `.toolkit-runs/20260923T080158.893365Z.log` |
| iOS simulator build | Passed | `.toolkit-runs/20260923T075550.400413Z.log` |
| Physical iPhone architecture build | Passed with signing disabled; this is not an installable signed release | `.toolkit-runs/20260923T075549.711895Z.log` |
| Real temporary pairing generation | Certificate/key loaded, private file modes and token binding checked; refused rerun left files byte-identical | `.toolkit-runs/20260923T075515.806506Z.log` |
| Isolated IPv4 and IPv6 gateways | Authenticated setup returned HTTP 200 using synthetic configuration | `.toolkit-runs/20260923T075305.305552Z.log` |
| Frozen offline replay | Original numerical results, input hashes and protocol reproduced | `.toolkit-runs/20260923T080209.049899Z.log` |
| Independent strategy accounting | 119 runs reconciled; maximum discrepancy 2.203e-13 percentage points | [Independent check](INDEPENDENT-CHECK.json); `.toolkit-runs/20260923T080209.420544Z.log` |

Provider error-response closure also passed 15 focused research tests with ResourceWarning treated as errors (`.toolkit-runs/20260923T080022.370645Z.log`).

The tests use synthetic broker responses. No funded orders, transfers, production account reads, production credential changes or deployed-service updates were used in this review. The temporary cryptographic check used an existing Python environment, without changing that environment or the deployed gateway.

The backtest covers the existing SMA long/cash implementation across seven symbols with 1,177 daily bars each, January 3, 2022 through September 11, 2026. Training, validation, final periods and four cost scenarios remain frozen. One symbol passed validation and two beat their final benchmark; **none did both**. Replaying an already observed period is not new out-of-sample evidence. No parameters were tuned after viewing final outcomes. The [refreshed report](refreshed-replay/BACKTEST-REPORT.md) and [independent checker](check-backtest.py) preserve the evidence.

## Remaining work and limits

- Claude Code must have a usable authenticated session before its requested independent review can run. The saved handoff lists exact scope and current evidence.
- Current device discovery showed simulated devices only. No physical iPhone installation or usable signing/provisioning was established by this review.
- Real Webull authentication was not retried here. Earlier authentication failures are historical evidence, not a fresh account-status check. Fake-broker tests cannot establish live connectivity or execution success.
- These corrections are saved in `/Users/louisbrailey/tradepilot`; the previously deployed gateway was not updated. Deploying requires preserving the authoritative private runtime and ledger rather than overwriting it with an older snapshot.
- Coinbase/Fidelity integrations, live crypto/options/short execution, continuous prospective paper-performance tracking, wider strategy implementations/backtests and always-online hosting remain unfinished. Research profiles are not separate implemented strategies. Journaling/context retrieval does not retrain model weights.
- Current backtests do not establish exchange-calendar completeness, dividend cash-flow performance, intraday liquidity, taxes, borrow availability or real fills. Legacy provider adjustment confirmations were not retained and cannot be recovered from the frozen cache.

The source review began at commit `08a7ddf` on `main`. Changes and reports are saved locally and uncommitted; there was no push or deployment. Existing automated gates and the bounded independent accounting check passed, but they do not prove that all possible bugs or every originally requested capability are complete.
