# Durable paper trading

The paper service records user-requested, separately approved simulations in an isolated SQLite ledger. It starts with $10,000 of simulated cash and has no reset endpoint. It never calls a brokerage, changes a real account, or promotes a strategy to live trading.

A review fixes the symbol, side, fractional quantity, server-supplied reference price and timestamp, source, and simulated cost. Confirmation accepts only its ID, secret token, and `approved: true`, within five minutes. The price model applies 10 basis points of adverse slippage on each side, with zero explicit commission. Buys cost `quantity × reference × 1.001`; sells receive `quantity × reference × 0.999`. The persisted receipt explicitly labels the result a reference-price simulation, not execution evidence. Same-ID retries return the original receipt even after expiry. Requesting a review again with an already confirmed `client_id` is refused rather than reopening it as a new review. SQLite immediate transactions prevent competing confirmations from spending the same cash or shares twice.

Only positive decimal-string quantities with up to eight fractional places and a maximum of one billion are accepted. Symbols must be uppercase. Client-supplied prices are not part of the review request. Server reference prices must be finite and positive, carry source/delay information, and be no more than 96 hours old or future-dated. The gateway timestamps each completed daily bar at its 16:00 America/New_York close, which allows reference closes across weekends and single-day market holidays; it does not make them executable market quotes. Fractional simulations do not establish a broker's fractional-share eligibility. Short sales, leverage, dividends, corporate actions, borrow fees, options and crypto are not modeled.

## Valuation and journal

Holdings retain weighted cost basis, last saved reference price and its date, market value, and unrealized P&L. Sales record realized P&L using average cost; this is simulated accounting, not tax-lot accounting. Cash, quantities and money use decimal arithmetic and JSON strings.

Explicit mark refreshes require exactly one server quote per held symbol and commit atomically. Prices cannot move backwards in time or change at the same timestamp. A stale review cannot overwrite a newer mark. Each fill and successful refresh stores a valuation observation with cash, equity, recording time, and the oldest held-price timestamp. State exposes the last 100 observations and maximum observed peak-to-trough drawdown across the complete stored history. Drawdown is a fraction, not a percentage. It is sampled at observations, not a continuous intraday risk estimate. State always warns that its saved references are not current executable quotes.

Reviews, simulated fills, identified business rejections, valuation provenance, and user notes are durably journaled. State returns at most 200 recent review/order records and 500 recent journal entries; the database retains the complete history. Review retries use a client idempotency key and cannot change its original payload or expiry. Users must request a new review with a new key after expiry or changed terms.

This creates forward-recorded paper observations as the app is used. It does not backfill prospective evidence, continuously poll markets, retrain model weights, prove profitable strategies, or predict live fills. The existing historical strategy evaluation remains separate.

## Implementation contract

`PaperService(path, clock=time.time)` provides `state()`, `create_review(payload, quote)`, `confirm(payload)`, `add_note(payload)` and `mark_quotes(quotes)`. Routes must authenticate callers and obtain quotes on the server; the quote argument is an internal trusted-provider boundary. The database belongs in the gateway's private state directory and is separate from the broker execution ledger. One service object may be recreated per request; transactions and idempotency survive restarts and multiple instances.

- Review payload: `{symbol, side: "buy"|"sell", quantity: decimalString, client_id}`.
- Internal quote: `{symbol, price: decimalString, as_of: epochSeconds, source, delayed: boolean}`.
- Confirmation: exactly `{id, token, approved: true}`.
- Note: exactly `{text}` (1–4,000 trimmed characters).
- `ValueError` denotes invalid requests or rejected simulation approval.

The focused suite in `server/test_paper.py` exercises accounting, persistence, concurrent review/approval, concurrent budget limits, expiry, malformed numbers, price freshness, immutable reviews, fractional exits, atomic marking, quote regression, stale reviews, drawdown, and notes. All data is synthetic; no real accounts or credentials are used.
