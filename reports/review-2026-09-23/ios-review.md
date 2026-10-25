# iPhone review — September 23, 2026

Reviewed Webull view requests, preview confirmation, response presentation and credential changes. The baseline native suite passed, but the following gaps were found by source review and fixed.

- Compare preview order type and requested limit price against the captured request, not editable fields after an asynchronous reply.
- Require supported US equity, normal-order, quantity, DAY and CORE-session terms. Reject empty review identities, malformed numeric strings, nonfinite expiry and unsupported order terms.
- Bind all broker API responses to the exact requested endpoint and token; clear displayed account/review/evidence when either changes. Require the original preview connection at confirmation.
- Validate receipt identity before displaying or journaling it. A mismatched receipt cannot appear as the requested order's new status; its recovery lock remains in place.

Added connection/preview regression checks for token and host changes, wrong market/instrument/session/time-in-force, malformed quantities, unexpected limit on a market order, and changed limit price.

Final simulator build passed: `.toolkit-runs/20260923T075550.400413Z.log`. Unsigned physical-device architecture build passed: `.toolkit-runs/20260923T075549.711895Z.log`. Current physical-device discovery found only simulated iPhones. No real accounts, orders, production gateway changes, or physical installation were used as tests. The final combined regression log is recorded in REVIEW.md.
