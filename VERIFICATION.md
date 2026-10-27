# Verification — October 26, 2026

- Core: 13 checks passed. Backend: 159 tests passed (one Coinbase ES256 signing test skipped on system Python; 15/15 pass with the gateway venv). Scripts: 37 tests passed. Swift smoke checks passed. Log: `.toolkit-runs/20261026T230327.747172Z.log` (before the installer pre-flight test was added).
- Native builds: iOS Simulator and unsigned `generic/platform=iOS` succeeded.
- Simulator: certificate-pinned connection, paper account load, 1-share AAPL review at the real delayed close stamped 16:00 ET, confirmed fill and position, and Coinbase "not configured" message, all against an isolated gateway running the deployed code on `[::1]:8787` with a temporary certificate and token. See [the review](reports/review-2026-10-26/REVIEW.md).
- Not verified: physical iPhone (connected and paired; Developer Mode off), the deployed gateway serving a request (Mac not on the home LAN), real Webull or Coinbase access, live submission. No real orders or transfers were used as tests.

# Verification — September 12, 2026 (historical)

- Core: 13 checks passed.
- Backend: 90 tests passed, including broker identity, multi-process race cases, durable confirmation, execution evidence, local inference restrictions and authenticated evaluation projection.
- Scripts: 17 tests passed, including multistage evaluation and private deployment.
- Swift: type checks, journal persistence/corruption/reflections, endpoint/account/review binding and historical evaluation integrity passed.
- Native builds: signed iOS simulator and unsigned iPhone architecture succeeded.
- Runtime: launchd service running; authenticated pinned-TLS setup and 7-row evaluation returned HTTP200. Actual local AI completed through gateway and installed app. Setup remained responsive during inference.
- Simulator: verified pairing import, provider display, local assistant, recorded results and exact demo order-review details. Manual confirmation was interrupted by an automatic UI approval timeout and is not reported as passed.
- Market evaluation: seven real daily-bar datasets; train/validation/final separation; costs at0/10/25/50bps; replay reproduced all numerical outputs. No strategy promotion supported.

Physical installation, real Webull authentication, live submission/fills, and full multi-broker coverage are not verified. No real orders or transfers were used as tests.
