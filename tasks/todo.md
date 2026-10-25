# Remaining work acceptance checklist

- [ ] Paper ledger: durable accounting, explicit confirmation, retry/concurrency safety, quote provenance and valuation history verified.
- [ ] Strategy comparison: three fixed families, no-lookahead and accounting checks, real-cache report with known-history label.
- [ ] Coinbase: strict read-only account API and native table; malformed responses/pagination/signature tested.
- [ ] Gateway routes: authenticated exact payloads, no client-price or arbitrary-file access, connection-bound native responses.
- [ ] iOS: paper review/history and strategy results accessible; native builds pass and simulator launches.
- [ ] Fresh private gateway deploy preserves authoritative state; authenticated health check succeeds.
- [ ] Saved release notes, installation status and continuity checkpoint.
- [ ] Claude independently reviews current source (requires authenticated Claude).
- [ ] Physical iPhone signed and installed (requires available trusted device/signing).
- [ ] Real Webull/Coinbase account connectivity (requires valid provider credentials/auth; never inferred from tests).

Follow-on product scope retained explicitly: Fidelity supported data access, live crypto/options/short execution, dividend/FX/intraday strategy implementations with appropriate data, automated prospective strategy operation, and remote always-on infrastructure. Do not mark these complete from exploratory research or a manual paper ledger.
