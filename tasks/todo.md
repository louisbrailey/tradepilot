# Remaining work acceptance checklist

- [x] Paper ledger: durable accounting, explicit confirmation, retry/concurrency safety, quote provenance and valuation history verified.
- [x] Strategy comparison: three fixed families, no-lookahead and accounting checks, real-cache report with known-history label.
- [x] Coinbase: strict read-only account API and native table; malformed responses/pagination/signature tested.
- [x] Gateway routes: authenticated exact payloads, no client-price or arbitrary-file access, connection-bound native responses.
- [x] iOS: paper review/history and strategy results accessible; native builds pass and simulator launches. (Builds and simulator end-to-end paper flow re-verified 2026-10-26.)
- [ ] Fresh private gateway deploy preserves authoritative state; authenticated health check succeeds. (Deployed copy matches 7ab6207 and was re-paired for louiss-macbook-pro-7.local on 2026-10-26, but the gateway is offline because the Mac is not on the home LAN; no request has been served since deployment and the phone still needs the new TradePilotPairing.json.)
- [x] Saved release notes, installation status and continuity checkpoint. (reports/review-2026-10-26/RELEASE-NOTES.md, DEVICE-CONNECTION-REPORT.md, codex-recall checkpoint 2026-10-26.)
- [x] Claude independently reviews current source — done 2026-10-26; see reports/review-2026-10-26/REVIEW.md.
- [ ] Physical iPhone signed and installed. (Phone 00008140-001C0D242638801C is connected and paired as of 2026-10-26; blocked until Developer Mode is turned on on the phone. The first scripts/install-iphone.sh build also registers the device to the team.)
- [ ] Real Webull/Coinbase account connectivity (requires valid provider credentials/auth; never inferred from tests).

Follow-on product scope retained explicitly: Fidelity supported data access, live crypto/options/short execution, dividend/FX/intraday strategy implementations with appropriate data, automated prospective strategy operation, and remote always-on infrastructure. Do not mark these complete from exploratory research or a manual paper ledger.
