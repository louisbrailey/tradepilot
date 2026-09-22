# How TradePilot builds trading evidence

TradePilot keeps three kinds of evidence separate: user observations, historical simulations, and broker-reported activity. None automatically changes a trading rule or authorizes an order.

## Journal and reflection

Requests and order events retain their account, environment, strategy focus, timestamp, and session. Reflections attach to an existing event and record a thesis, expected outcome, observation, and lesson. These are the user's observations, not independently verified returns. Original events stay intact.

Optional journal retrieval supplies relevant text to an assistant. This is context reuse, not model-weight training. A demo fill, accepted order, or user-written outcome does not establish a profitable real trade. Actual performance accounting still requires reconciled executions, quantities, fees, currencies, corporate actions, and cash flows.

## Historical evaluation

Research uses daily stock bars with prior-close signals and subsequent open execution assumptions. Candidate parameters must be selected using earlier training data only. Later evaluation periods test those selections. Cost sensitivity shows how assumptions change the result; it must not become a way to choose parameters from the test period.

Repeated evaluation periods are useful diagnostics, but they are not independent proof of profitability. They share one ticker and related history. Selection bias, regime changes, and unmodeled execution remain. Dividend, short-selling, intraday, options, crypto, and FX profiles are research prompts until their required datasets and separate models are implemented.

## Assistant and execution boundary

The optional Webull assistant reads an authorized account snapshot on the server. An AI order suggestion may fill an editable form. The user then requests the broker's preview and separately confirms the exact account, instrument, side, quantity, and order terms. The model has no order-execution tool. Unknown outcomes stay locked for reconciliation.

The integration uses structured response fields and validates them independently. Structured output is a parsing contract, not proof that an investment claim is correct. See [OpenAI's structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

## Work still required

- Reconcile real executions and cancellations, including partial fills and fees.
- Build a separate performance ledger with account/currency boundaries and auditable cost-basis handling.
- Evaluate strategy-specific hypotheses on appropriate point-in-time datasets.
- Add prospective paper evaluation before considering a rule for real use.
- Keep any change to live execution explicit and reviewable; journal lessons never grant trading authorization.
