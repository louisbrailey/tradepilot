import Foundation

let paired = try ConnectionSettings.validatedEndpoint("https://192.168.68.64:8787")
let pairedOrigin = ConnectionSettings.origin(for: paired)
let otherPort = try ConnectionSettings.validatedEndpoint("https://192.168.68.64:8788")
let otherHost = try ConnectionSettings.validatedEndpoint("https://192.168.68.65:8787")
precondition(ConnectionSettings.matchesPairedOrigin(paired, pairedOrigin: pairedOrigin))
precondition(!ConnectionSettings.matchesPairedOrigin(otherPort, pairedOrigin: pairedOrigin))
precondition(!ConnectionSettings.matchesPairedOrigin(otherHost, pairedOrigin: pairedOrigin))

let review = BrokerReview(id: "review-1", confirmation_token: "confirmation", environment: "sandbox", account_id: "account-a", order: ["side": "BUY", "symbol": "AAPL", "quantity": "2", "client_order_id": "client-1", "market": "US", "instrument_type": "EQUITY", "combo_type": "NORMAL", "order_type": "MARKET", "time_in_force": "DAY", "support_trading_session": "CORE", "entrust_type": "QTY"], estimated_cost: "200", estimated_fee: "0", expires_at: 2_000)
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
// Forms Decimal(string:) accepts but the strict quantity pattern must reject.
for quantity in ["1e2", "+2", "2.", ".5", " 2", "2 ", "2,5", "2\n"] {
    precondition(!BrokerValidation.aiReplyMatches(AIReply(kind: "trade", message: "", side: "buy", quantity: quantity, symbol: "AAPL", account_id: "account-a", environment: "sandbox", snapshot_as_of: 995), account: "account-a", environment: "sandbox", now: 1_000), quantity)
}
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

let connection = BrokerConnectionBinding(endpoint: "https://a.local", token: "first")
precondition(connection.matches(endpoint: "https://a.local", token: "first"))
precondition(!connection.matches(endpoint: "https://a.local", token: "rotated"))
precondition(!connection.matches(endpoint: "https://b.local", token: "first"))
func changedReview(_ changes: [String: String]) -> BrokerReview {
    BrokerReview(id: review.id, confirmation_token: review.confirmation_token, environment: review.environment,
        account_id: review.account_id, order: review.order.merging(changes) { _, new in new },
        estimated_cost: review.estimated_cost, estimated_fee: review.estimated_fee, expires_at: review.expires_at)
}
for changes in [["time_in_force": "GTC"], ["market": "HK"], ["instrument_type": "OPTION"],
                ["support_trading_session": "ALL"], ["quantity": "2oops"], ["limit_price": "10"]] {
    precondition(!BrokerValidation.reviewMatches(changedReview(changes), account: "account-a", environment: "sandbox", now: 1000))
}
let limited = changedReview(["order_type": "LIMIT", "limit_price": "100.25"])
precondition(BrokerValidation.reviewMatches(limited, account: "account-a", environment: "sandbox", orderType: "LIMIT", limitPrice: "100.2500", now: 1000))
precondition(!BrokerValidation.reviewMatches(limited, account: "account-a", environment: "sandbox", orderType: "MARKET", now: 1000))
precondition(!BrokerValidation.reviewMatches(limited, account: "account-a", environment: "sandbox", orderType: "LIMIT", limitPrice: "100.26", now: 1000))
print("PASS exact preview terms and credential-change binding")

let signedEstimate = BrokerReview(id: review.id, confirmation_token: review.confirmation_token,
    environment: review.environment, account_id: review.account_id, order: review.order,
    estimated_cost: "-200", estimated_fee: "-0.01", expires_at: review.expires_at)
precondition(BrokerValidation.reviewMatches(signedEstimate, account: "account-a", environment: "sandbox", now: 1000))

if CommandLine.arguments.count > 1 {
    let directory = URL(fileURLWithPath: CommandLine.arguments[1])
    func fixture<T: Decodable>(_ name: String, as type: T.Type) throws -> T {
        try JSONDecoder().decode(type, from: Data(contentsOf: directory.appendingPathComponent(name + ".json")))
    }
    let paperReview = try fixture("review", as: PaperReview.self)
    let paperReceipt = try fixture("receipt", as: PaperReview.self)
    let paperState = try fixture("state", as: PaperSnapshot.self)
    let intent = PaperIntentRequest(symbol: "AAPL", side: "buy", quantity: "2", client_id: "fixture-1234")
    precondition(PaperValidation.reviewMatches(paperReview, request: intent))
    precondition(PaperValidation.receiptMatches(paperReceipt, review: paperReview))
    precondition(paperState.mode == "paper" && paperState.positions.first?.quantity == "2")
    precondition(paperState.journal.first?.data.text == "Synthetic reflection")
    precondition(PaperValidation.decimal("1junk") == nil)
    precondition(PaperValidation.decimal("NaN") == nil)
    precondition(PaperValidation.decimal("1e5") == nil)
    precondition(!PaperValidation.reviewMatches(paperReview, request: PaperIntentRequest(symbol: "AAPL", side: "sell", quantity: "2", client_id: "fixture-1234")))
    precondition(!PaperValidation.reviewMatches(paperReview, request: intent, now: paperReview.expires_at))
    var receiptJSON = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("receipt.json"))) as! [String: Any]
    receiptJSON["fill_price"] = "1.00"
    let wrongPrice = try JSONDecoder().decode(PaperReview.self, from: JSONSerialization.data(withJSONObject: receiptJSON))
    precondition(!PaperValidation.receiptMatches(wrongPrice, review: paperReview))
    let strategies = try fixture("strategies", as: StrategyComparison.self)
    precondition(strategies.strategies.count == 3 && strategies.evidence == "exploratory_previously_observed")
    print("PASS native paper review/receipt arithmetic, strict decimals, persisted journal and strategy API decoding")
}
