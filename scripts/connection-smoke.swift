import Foundation

let paired = try ConnectionSettings.validatedEndpoint("https://192.168.68.64:8787")
let pairedOrigin = ConnectionSettings.origin(for: paired)
let otherPort = try ConnectionSettings.validatedEndpoint("https://192.168.68.64:8788")
let otherHost = try ConnectionSettings.validatedEndpoint("https://192.168.68.65:8787")
precondition(ConnectionSettings.matchesPairedOrigin(paired, pairedOrigin: pairedOrigin))
precondition(!ConnectionSettings.matchesPairedOrigin(otherPort, pairedOrigin: pairedOrigin))
precondition(!ConnectionSettings.matchesPairedOrigin(otherHost, pairedOrigin: pairedOrigin))

let review = BrokerReview(id: "review-1", confirmation_token: "confirmation", environment: "sandbox", account_id: "account-a", order: ["side": "BUY", "symbol": "AAPL", "quantity": "2", "client_order_id": "client-1"], estimated_cost: "200", estimated_fee: "0", expires_at: 2_000)
precondition(BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "BUY", symbol: "AAPL", quantity: "2", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-b", environment: "sandbox", side: "BUY", symbol: "AAPL", quantity: "2", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "production", side: "BUY", symbol: "AAPL", quantity: "2", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "SELL", symbol: "AAPL", quantity: "2", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "BUY", symbol: "MSFT", quantity: "2", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "BUY", symbol: "AAPL", quantity: "3", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "BUY", symbol: "AAPL", quantity: "invalid", now: 1_000))
precondition(!BrokerValidation.reviewMatches(review, account: "account-a", environment: "sandbox", side: "BUY", symbol: "AAPL", quantity: "2", now: 2_000))

let aiTrade = AIReply(kind: "trade", message: "Fill the form.", side: "buy", quantity: "2", symbol: "AAPL",
    account_id: "account-a", environment: "sandbox", snapshot_as_of: 995)
precondition(BrokerValidation.aiReplyMatches(aiTrade, account: "account-a", environment: "sandbox", now: 1_000))
precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "trade", message: "", side: "buy", quantity: "0", symbol: "AAPL", account_id: "account-a", environment: "sandbox", snapshot_as_of: 995), account: "account-a", environment: "sandbox", now: 1_000))
precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "trade", message: "", side: "buy", quantity: "NaN", symbol: "AAPL", account_id: "account-a", environment: "sandbox", snapshot_as_of: 995), account: "account-a", environment: "sandbox", now: 1_000))
precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "trade", message: "", side: "buy", quantity: "2", symbol: "AAPL", account_id: "account-b", environment: "sandbox", snapshot_as_of: 995), account: "account-a", environment: "sandbox", now: 1_000))
precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "portfolio", message: "", side: nil, quantity: nil, symbol: nil, account_id: "account-a", environment: "sandbox", snapshot_as_of: 800), account: "account-a", environment: "sandbox", now: 1_000))
precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "portfolio", message: "", side: "sell", quantity: nil, symbol: nil, account_id: "account-a", environment: "sandbox", snapshot_as_of: 995), account: "account-a", environment: "sandbox", now: 1_000))

let execution = BrokerExecution(id: "order-1", client_order_id: "client-1", symbol: "AAPL", side: "BUY",
    filled_quantity: "2", average_fill_price: "100.25", fill_notional: "200.50", currency: "USD",
    state: "FILLED", updated_at: 995, fees: "0.10")
let executionTotals = BrokerExecutionTotals(filled_orders: 1, partial_orders: 0,
    notional_by_currency: ["USD": BrokerExecutionNotional(buy: "200.50", sell: "0")], fees_known: true)
let ledger = BrokerExecutionLedger(environment: "sandbox", account_id: "account-a", scope: "APP-TRACKED ONLY",
    as_of: 1_000, orders: [execution], warnings: [], totals: executionTotals)
precondition(BrokerValidation.executionLedgerMatches(ledger, account: "account-a", environment: "sandbox"))
precondition(!BrokerValidation.executionLedgerMatches(ledger, account: "account-b", environment: "sandbox"))
precondition(!BrokerValidation.executionLedgerMatches(ledger, account: "account-a", environment: "production"))
precondition(!BrokerValidation.executionLedgerMatches(BrokerExecutionLedger(environment: "sandbox", account_id: "account-a", scope: "BROKER HISTORY", as_of: 1_000, orders: [execution], warnings: [], totals: executionTotals), account: "account-a", environment: "sandbox"))
let badExecution = BrokerExecution(id: "order-1", client_order_id: "client-1", symbol: "AAPL", side: "BUY",
    filled_quantity: "NaN", average_fill_price: "100.25", fill_notional: "200.50", currency: "USD",
    state: "FILLED", updated_at: 995, fees: nil)
precondition(!BrokerValidation.executionLedgerMatches(BrokerExecutionLedger(environment: "sandbox", account_id: "account-a", scope: "APP-TRACKED ONLY", as_of: 1_000, orders: [badExecution], warnings: [], totals: executionTotals), account: "account-a", environment: "sandbox"))
print("PASS paired-origin, broker-review, Webull AI, and execution-evidence binding validation")

let recordedFixture = #"""
{"schema_version":1,"historical_only":true,"previously_observed":true,"scope":"sma-long-cash",
 "evaluated_at":"2026-09-12T12:00:00+00:00","protocol_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
 "baseline_cost_bps":10,"source_start":"2022-01-03","source_end":"2026-09-11","expected_symbols":1,
 "unavailable_symbols":[],"conclusion":"Research only","limitations":["No dividends"],"rows":[{
 "symbol":"SPY","bar_count":1177,"selected_window":20,"source_start":"2022-01-03","source_end":"2026-09-11",
 "validation_passed":false,"validation_excess_pct":-9,"holdout_start":"2025-10-03","holdout_end":"2026-09-11",
 "holdout_return_pct":-2,"benchmark_return_pct":13,"excess_return_pct":-15,"max_drawdown_pct":11,"fills":38,
 "cost_sensitivity":[{"bps_per_side":0,"return_pct":1,"benchmark_return_pct":14},
 {"bps_per_side":10,"return_pct":-2,"benchmark_return_pct":13},{"bps_per_side":25,"return_pct":-8,"benchmark_return_pct":12},
 {"bps_per_side":50,"return_pct":-16,"benchmark_return_pct":11}]}]}
"""#
let recorded = try JSONDecoder().decode(RecordedEvaluation.self, from: Data(recordedFixture.utf8))
precondition(EvaluationValidation.isValid(recorded))
for mutation in [("\"historical_only\":true", "\"historical_only\":false"),
                 ("\"previously_observed\":true", "\"previously_observed\":false"),
                 ("\"selected_window\":20", "\"selected_window\":1"),
                 ("\"excess_return_pct\":-15", "\"excess_return_pct\":15"),
                 ("\"max_drawdown_pct\":11", "\"max_drawdown_pct\":-1"),
                 ("\"expected_symbols\":1", "\"expected_symbols\":2")] {
    let invalid = try JSONDecoder().decode(RecordedEvaluation.self, from: Data(recordedFixture.replacingOccurrences(of: mutation.0, with: mutation.1).utf8))
    precondition(!EvaluationValidation.isValid(invalid))
}
precondition(EvaluationValidation.connectionMatches(endpoint: "https://a.local:8787", token: "first", currentEndpoint: "https://a.local:8787", currentToken: "first"))
precondition(!EvaluationValidation.connectionMatches(endpoint: "https://a.local:8787", token: "first", currentEndpoint: "https://b.local:8787", currentToken: "first"))
precondition(!EvaluationValidation.connectionMatches(endpoint: "https://a.local:8787", token: "first", currentEndpoint: "https://a.local:8787", currentToken: "changed"))
print("PASS recorded evaluation metrics, historical scope, and connection binding")
