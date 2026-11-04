# Physical iPhone verification — November 4, 2026

Target: USB-connected “louis’s iPhone”, hardware iPhone 16, iOS 26.0.1. Developer Mode enabled, developer profile trusted. Installed app includes merged PR #1 (source 8ea2d2d; subsequent changes are gateway/docs only). Observed directly through iPhone Mirroring after selecting the correct phone and completing user-assisted setup. Device Hub screen sharing requires iOS 27 and was unavailable for this device.

## Observed results

| Feature | Result |
| --- | --- |
| Overview and Holdings | Rendered sample portfolio and three demo accounts; after a fictional sale, Overview showed 21 AAPL and $12,495 demo cash. |
| Assistant demo review | Sell 3 AAPL displayed the exact review, explicit demo confirmation, then a simulated receipt. No broker request. |
| Assistant local AI | Initially failed because IPv4 localhost reached Lima Ollama with a different model inventory. After the routing fix below, “Show my portfolio” returned a local Qwen response and the demo portfolio table. |
| Private server setup | Reachable with pinned TLS; Massive and local Ollama configured; live submissions disabled. |
| Paper account | Loaded $10,000 practice account; reviewed and confirmed 1 AAPL using the November 3 delayed close $331.90. Simulated fill $332.2319, cash $9,667.7681 (UI $9,667.77), equity $9,999.6681 (UI $9,999.67). Position and simulated-fill journal entries visible. This one simulated order remains in the practice ledger. |
| Journal | Demo/paper records, filters, activity counts and export control rendered; paper fill visible. Export delivery and structured reflection editing were not exercised. |
| Massive research | AAPL response displayed 277 daily bars, 20 options samples, 20 dividend records and 8 Benzinga news records, with partial-page labels where appropriate. |
| Strategy lab | AAPL comparison returned historical results and costs, with already-observed-history limitations visible. |
| Kronos lab | Five-session historical replay completed on the local model and rendered forecast/baseline/actual chart. |
| Webull | Disconnected screen rendered; explicit Load accounts control and disabled dependent actions. No provider account read or order used as a test. |
| Coinbase | Balance screen and manual-confirmation action screen rendered; explicit loading required. No provider account read, transfer or order used as a test. |

## Fixed and deployed

1. The physical app included the merged broker screens but the gateway still ran older routes. Deployed all 18 production Python/service files to the existing private gateway, preserving private configuration/runtime. Previous code: `private/code-backup-20261104`.
2. Native Mac Ollama listens on IPv6 port 11434, while a Lima forward shadows IPv4. Added `OLLAMA_LOOPBACK_HOST`, limited to exactly `127.0.0.1` (default) or `::1`. This deployment explicitly uses `::1`, retaining the configured model, credentials, local-weight verification, no redirects/proxies and no remote fallback. Prior config/server copies are in `private/code-backup-20261104`. Phone AI request then succeeded.
3. LAN address changed during verification from 192.168.68.56 to 10.0.0.166. The hostname-paired gateway restarted on the new private address; no re-pair was needed. Authenticated certificate-verified setup returned HTTP 200 and live trading remained false.

## Checks and limits

Full gate before the inference fix: 13 core checks, 201 backend tests (one optional signing test skipped), 41 script tests, Swift smoke checks and project lint. Log `.toolkit-runs/20261104T084832.934918Z.log`. After the fix: 202 backend tests, one optional skip; log `.toolkit-runs/20261104T085340.364023Z.log`. Strict host-selection test covers IPv6 transport and rejects names, remote/private addresses and mapped-address variants before sending data.

This proves the listed physical-device paths. It does not verify real broker authentication/execution, background operation, every input/error case, notification behavior or all accessibility sizes. Live trading remains disabled. Broader product scope remains in tasks/todo.md.
