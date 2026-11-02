# Confirmed broker access

Source implementation, not a deployment or a successful account test. No production
configuration, credentials or accounts were changed. All verification uses fakes.

## Reachable app features

Accounts → Coinbase → Trading and internal transfers provides current permission
metadata, portfolio selection, paginated order history, spot LIMIT/GTC orders,
confirmed cancellation and internal portfolio movement. Coinbase balances retain
the existing strictly paginated read-only screen. Accounts → Webull provides
account/position/balance reads, long-stock LIMIT/DAY production reviews and
cancellation of acknowledged app-tracked orders. Sandbox market/DAY behavior stays
available. All submissions use the authenticated private gateway; AI cannot approve.

Every action requires an immutable saved review, expiring single-use confirmation,
account/environment binding and durable pre-send state. Coinbase client IDs persist
through submission; repeated confirmations never send twice. A lost review response
has made no financial mutation. A lost submission response must be reconciled, never
recreated as a retry. The UI preserves the last action reference across restart.

### Fee policy

The default `require_provider_cap` is refused: these provider order contracts do not
enforce hard fees or an all-in debit cap. The user may explicitly select
`accept_rechecked_estimate` and enter fee estimate ceiling, debit admission ceiling,
headroom and exact quote/settlement currency. Those values are in the immutable
review digest and displayed before confirmation. **Actual fees and debit can exceed
these pre-send ceilings.** No silent fallback or automatic ceiling increase occurs.

Fresh account permissions/membership, complete open-order coverage, balances and
provider preview are checked under shared admission. New exposure/transfers refuse
foreign/open/unresolved orders. Coinbase requires SPOT identity, product increments,
base limits, exact base/quote currencies and matching complete commission total.
Webull uses USD settlement, `settled_cash - frozen_amount`, and the official preview's
estimated transaction fee including exchange, clearing and commission. BUY reserves
limit notional + fee allowance + headroom; SELL requires holdings plus separate
quote-currency fee/headroom funds. No margin borrowing, shorts or leveraged orders.
Previews older than 15 seconds after retrieval and expired reviews refuse.

Actual fee/debit evidence and overruns appear in saved status. Missing or unsettled
Webull commission/fee evidence displays `AWAITING_FEE_SETTLEMENT` and keeps admission.
Coinbase terminal reconciliation similarly keeps the hold until actual cost evidence
is complete. Partial-fill cancellation reconciles the original order's economic
terms before releasing its hold. Protective cancellation is allowed while the kill
switch blocks new exposure/transfers; it still needs enabled trading, current
provider authority/account binding and a separate explicit confirmation.

### Transfers and provider limitations

Coinbase internal portfolio moves are not external crypto withdrawals or bank
funding. The documented synchronous HTTP 200 response contains only source and
destination UUIDs. A matching non-error success tied to the exact saved funds request
is recorded as `synchronous_provider_response`, with the exact funds and request
digest durably saved before releasing both locks. No invented provider transfer ID
or independent balance measurement is claimed. The provider documents internal
moves as instantaneous and free. A timeout, malformed/mismatched result or crash
before durable success remains unresolved with both holds retained, without retry.
There is no automatic lookup-based resolution for uncertain transfers.

Webull retail funding/withdrawals explicitly refuse. Institutional Broker API
entitlement is separate and no institutional funding integration is installed.
Coinbase external withdrawals, bank funding, derivatives, conversions, advanced
order types and portfolio administration are not implemented by this change.
Webull options/futures/crypto execution and order replacement are also not
implemented; broader key permissions do not make those routes available. These are
application scope limits, not claims that the providers have no such APIs.

## Shared admission protocol

Default path: `~/Library/Application Support/BrokerAccess/admission.sqlite3`.
Both apps must use this same file, not independent runtime directories.

```sql
CREATE TABLE IF NOT EXISTS broker_admission (
  provider TEXT, environment TEXT, account_id TEXT, action_id TEXT,
  owner TEXT, state TEXT,
  PRIMARY KEY(provider,environment,account_id)
);
```

Owner is `tradepilot`; Signal Forge uses its own owner. Coinbase account keys are
canonical lowercase portfolio UUIDs, never currency wallet UUIDs. Webull uses exact
broker account IDs. A transfer reserves source AND destination atomically using
`BEGIN IMMEDIATE`; any existing hold blocks. States are RESERVED, SUBMITTING and
UNKNOWN. No automatic expiration, takeover or arbitrary operator unlock exists.
Confirmed cancellation uses its exact original order's owned hold, never a new
self-conflicting reservation. Terminal/rejected proof or provable pre-send abort
is required to release. Missing lookup is never rejection. Pre-send crash recovery
invalidates local approval atomically so a live validator cannot subsequently send.
A crash after durable completion but before release is recoverable without resend.

All legacy Webull submissions also use admission. No deployed process was restarted:
old deployed software must be stopped/upgraded before relying on cross-app exclusion.
No tests open the default admission database; test paths are explicit temp files.

## Operator enablement (not performed)

The private config accepts `COINBASE_LIVE_TRADING`, `COINBASE_TRANSFERS`,
`WEBULL_LIVE_TRADING` (`enabled` only) and `BROKER_KILL_SWITCH` (`disabled` to permit
new exposure/transfers; defaults enabled). The operator supplies fresh credentials
out of band and is responsible for provider-granted view/trade/transfer scopes.
Configuration switches grant no provider entitlement. Transfers have their own
switch and never use the protective-cancellation exception.

New authenticated POST routes: `/v1/coinbase/{capabilities,portfolios,orders}`,
`/v1/coinbase/action/{review,confirm,status,reconcile}`,
`/v1/webull/{capabilities,transfer/review,cancel/review,cancel/confirm}`.
Existing Webull order/state/execution routes retain their names. No arbitrary HTTP
proxy or caller-selected provider origin is exposed. Provider error bodies/JWTs are
not persisted; confirmation tokens are stored as hashes.

## Official contracts checked November 1, 2026

- [Coinbase create order](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order)
- [Coinbase preview](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/preview-orders)
- [Coinbase internal move](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/portfolios/move-portfolios-funds)
- [Coinbase portfolios and free instantaneous moves](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/portfolios)
- [Official Coinbase SDK](https://github.com/coinbase/coinbase-advanced-py/tree/master/coinbase/rest)
- [Webull preview](https://developer.webull.com/apis/docs/reference/common-order-preview/)
- [Webull balances](https://developer.webull.com/apis/docs/reference/account-balance/)
- [Webull open-order pagination](https://developer.webull.com/apis/docs/reference/order-open/)
- [Webull detail, commission and fees](https://developer.webull.com/apis/docs/reference/order-detail/)
- [Webull cancellation](https://developer.webull.com/apis/docs/reference/common-order-cancel/)

Webull request signatures were verified against the pinned official SDK 3.0.0;
response schemas against the official reference page bundles. Production behavior
still requires operator-provisioned accounts and read-only entitlement verification.
