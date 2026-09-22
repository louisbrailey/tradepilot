# Trade execution integrity review

Reviewed and tested September 12, 2026. Scope: TradePilot's confirmed, single-order US equity workflow and its app-tracked execution ledger. All brokerage responses were mocked; no credentials were read and no brokerage requests or real orders were made by this review.

## Corrections

- Confirmation accepts only the saved review ID, its matching secret token, and explicit approval. Additional order/account fields are rejected. A supplied invalid limit can no longer silently create a market order.
- Broker detail must identify one matching simple order. Client ID, broker ID, ticker, side, total quantity, order type, time-in-force, quantity entrustment, and limit price are checked against the immutable review. Optional instrument/session/market fields and any returned account/environment fields must agree when present. Malformed or conflicting details cannot establish execution evidence or replace the last trusted receipt.
- Status/evidence writes use an immediate SQLite transaction and re-read the current review after the network request. A late placement acknowledgement or timeout cannot overwrite a terminal result already observed by another service instance. Concurrent confirmations still submit at most once, including after restart or an uncertain response.
- A terminal status can be accepted when Webull omits optional fill fields. Missing fields create no invented fill, fee, or P&L; later complete evidence can be added. Supplied inconsistent values are rejected. Terminal states and partial fills cannot regress to an earlier open state.
- Execution snapshots remain immutable and deduplicated. Quantities cannot decrease, an unchanged quantity cannot acquire a different average price, and an increased quantity cannot reduce cumulative fill value. Totals use the latest verified cumulative snapshot for each order, avoiding double counting repeated status responses.
- The ledger now retains reviewed execution terms and records its verification version. Older observations are preserved but excluded from totals until revalidated against saved complete broker detail or a fresh broker response.

## Verification

73 backend tests passed after these changes, including 30 Webull service/adapter tests and 13 execution-ledger tests. New adversarial coverage uses independent service objects and SQLite connections sharing one database file to exercise competing confirmations, competing status responses, and acknowledgements arriving after reconciliation. Migration tests exercise the older database schema and refusal/recovery of incomplete legacy evidence.

The official [Webull order-detail reference](https://developer.webull.com/apis/docs/reference/order-detail/) defines the required order identity/terms and optional cumulative fill quantity and average fill price. Optional fields remain optional; conflicting values fail verification.

## Remaining boundaries

These tests establish application behavior under controlled responses, not successful production authentication, broker execution, or investment performance. The ledger covers only orders submitted by this app. It has no verified fees, complete account history, tax basis, or realized P&L. Real execution remains subject to the existing backend enablement setting, fresh broker preview, user confirmation, account eligibility, and the broker's own acceptance.
