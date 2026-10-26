# Remaining work acceptance checklist

- [x] Paper ledger: durable accounting, explicit confirmation, retry/concurrency safety, quote provenance and valuation history verified.
- [x] Strategy comparison: three fixed families, no-lookahead and accounting checks, real-cache report with known-history label.
- [x] Coinbase: strict read-only account API and native table; malformed responses/pagination/signature tested.
- [x] Gateway routes: authenticated exact payloads, no client-price or arbitrary-file access, connection-bound native responses.
- [ ] iOS: paper review/history and strategy results accessible; native builds pass and simulator launches. (Builds re-verified 2026-10-26; simulator launch not re-run.)
- [ ] Fresh private gateway deploy preserves authoritative state; authenticated health check succeeds. (Deployed copy predates the 2026-10-26 fixes and is offline: Mac has no usable LAN address and its mDNS name changed from louiss-macbook-pro-6 to louiss-MacBook-Pro-7.)
- [ ] Saved release notes, installation status and continuity checkpoint.
- [x] Claude independently reviews current source — done 2026-10-26; see reports/review-2026-10-26/REVIEW.md.
- [ ] Physical iPhone signed and installed (requires available trusted device/signing).
- [ ] Real Webull/Coinbase account connectivity (requires valid provider credentials/auth; never inferred from tests).

Follow-on product scope retained explicitly: Fidelity supported data access, live crypto/options/short execution, dividend/FX/intraday strategy implementations with appropriate data, automated prospective strategy operation, and remote always-on infrastructure. Do not mark these complete from exploratory research or a manual paper ledger.
