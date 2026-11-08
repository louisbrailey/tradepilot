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

func coinbaseAccess(view: Bool = true, trade: Bool, transfer: Bool = false,
                    trading: Bool, cancellation: Bool = false, transfers: Bool = false,
                    portfolioType: String = "DEFAULT") -> AccessCapabilities {
    AccessCapabilities(provider: "coinbase", environment: "production",
        granted: AccessPermissions(can_view: view, can_trade: trade, can_transfer: transfer, portfolio_uuid: "account-a"),
        trading_enabled: trading, cancellation_enabled: cancellation, transfers_enabled: transfers,
        limitations: [], portfolios: [AccessPortfolio(id: "account-a", type: portfolioType)])
}
for provider in [false, true] {
    for gateway in [false, true] {
        let access = coinbaseAccess(trade: provider, transfer: provider, trading: gateway, cancellation: gateway, transfers: gateway)
        for action in ["limit_order", "cancel_order", "internal_transfer"] {
            precondition(access.permits(action, account: "account-a") == (provider && gateway))
            precondition(!access.permits(action, account: "account-b"))
        }
        precondition(!access.permits("unknown", account: "account-a"))
    }
}
precondition(!coinbaseAccess(view: false, trade: true, trading: true).permits("limit_order", account: "account-a"))
precondition(!coinbaseAccess(trade: true, trading: true, portfolioType: "INTX").permits("limit_order", account: "account-a"))
precondition(!coinbaseAccess(trade: true, trading: true, portfolioType: "unknown").permits("limit_order", account: "account-a"))
for (amount, hidden) in [("0", true), ("0.0000", true), ("0.00000000000000000000000000000000000000000000001", false),
                         ("1", false), ("NaN", false), ("", false), ("0\n", false)] {
    let asset = CoinbaseAccount(id: "one", currency: "BTC", name: "Bitcoin", available: amount, hold: "0", total: amount)
    precondition(asset.hasZeroBalance == hidden)
}
let held = CoinbaseAccount(id: "one", currency: "BTC", name: "Bitcoin", available: "0", hold: "0.01", total: "0.01")
precondition(!held.hasZeroBalance)
let balances = BrokerBalanceSummary.lines(#"{"total_asset_currency":"USD","total_cash_balance":"0.40","total_net_liquidation_value":"100","total_unrealized_profit_loss":"-2.50","total_market_value":"NaN"}"#)
precondition(balances.count == 3 && balances.contains { $0.title == "Cash" && $0.value == money(Decimal(string: "0.40")!, currency: "USD") })
precondition(balances.contains { $0.id == "total_unrealized_profit_loss" && $0.value == signedMoney(Decimal(string: "-2.50")!, currency: "USD") && $0.tone == .negative })
precondition(strictDecimal("1e5") == nil && strictDecimal("12abc") == nil && strictDecimal("-3.5") == Decimal(string: "-3.5") && strictDecimal("-1", allowNegative: false) == nil)
precondition(StatusBadge.orderState("FILLED").text == "Filled" && StatusBadge.environment("production").text == "Live" && StatusBadge.environment(nil).text == "Not connected")
precondition(BrokerBalanceSummary.lines(#"{"total_cash_balance":"100"}"#).isEmpty)
precondition(BrokerBalanceSummary.lines(#"{"total_asset_currency":"USD","total_cash_balance":true}"#).isEmpty)
precondition(BrokerBalanceSummary.lines("not JSON").isEmpty)
print("PASS provider-plus-gateway action gates, tiny/held Coinbase balances, and explicit-currency Webull summaries")

let setupFixture = #"{"version":"1","checked_at":1,"ai_configured":true,"market_data_configured":true,"webull_configured":true,"webull_environment":"production","live_trading_enabled":false,"configuration_only":true}"#
let legacySetup = try JSONDecoder().decode(GatewaySetup.self, from: Data(setupFixture.utf8))
precondition(legacySetup.coinbase_configured == nil)
for configured in ["true", "false"] {
    let currentSetup = setupFixture.dropLast() + ",\"coinbase_configured\":" + configured + "}"
    let decoded = try JSONDecoder().decode(GatewaySetup.self, from: Data(currentSetup.utf8))
    precondition(decoded.coinbase_configured == (configured == "true"))
}
print("PASS Coinbase setup status with legacy-gateway compatibility")

// A selected expiration and the contract deliverables must survive decoding together.
let standardOptionFields: [String: Any] = ["contract": "O:AAPL261113C00340000", "series": "AAPL", "type": "call",
    "strike": 340, "bid": 1, "ask": 1.2, "shares_per_contract": 100, "standard_contract": true]
func optionContract(_ fields: [String: Any]) throws -> OptionContract {
    try JSONDecoder().decode(OptionContract.self, from: JSONSerialization.data(withJSONObject: fields))
}
func optionChain(_ rows: [[String: Any]]) throws -> OptionChain {
    let fields: [String: Any] = ["symbol": "AAPL", "expirations": ["2026-11-13", "2026-11-20"], "expiration": "2026-11-13",
        "strikes": rows, "as_of": 1000]
    return try JSONDecoder().decode(OptionChain.self, from: JSONSerialization.data(withJSONObject: fields))
}
let standardOption = try optionContract(standardOptionFields)
precondition(abs(standardOption.estimatedPremium! - 110) < 0.0001)
var adjustedOptionFields = standardOptionFields
adjustedOptionFields["contract"] = "O:AAPL1261113C00340000"; adjustedOptionFields["series"] = "AAPL1"
adjustedOptionFields["shares_per_contract"] = 10; adjustedOptionFields["standard_contract"] = false
let adjustedOption = try optionContract(adjustedOptionFields)
precondition(adjustedOption.estimatedPremium == nil)
var unknownOptionFields = standardOptionFields
unknownOptionFields.removeValue(forKey: "shares_per_contract"); unknownOptionFields.removeValue(forKey: "standard_contract")
let unknownOption = try optionContract(unknownOptionFields)
precondition(unknownOption.estimatedPremium == nil)
let standardStrike: [String: Any] = ["strike": 340, "series": "AAPL", "call": standardOptionFields]
let adjustedStrike: [String: Any] = ["strike": 340, "series": "AAPL1", "call": adjustedOptionFields]
let decodedChain = try optionChain([standardStrike, adjustedStrike])
precondition(decodedChain.matches(symbol: "AAPL", expiration: "2026-11-13"))
precondition(!decodedChain.matches(symbol: "AAPL", expiration: "2026-11-20"))
precondition(!decodedChain.matches(symbol: "MSFT", expiration: nil))
let duplicateChain = try optionChain([standardStrike, standardStrike])
precondition(!duplicateChain.matches(symbol: "AAPL", expiration: nil))
print("PASS option expiration binding, distinct adjusted contracts, and verified standard premium estimates")

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

    let automationData = try Data(contentsOf: directory.appendingPathComponent("automation.json"))
    let automationState = try JSONDecoder().decode(AutomatedPaperSnapshot.self, from: automationData)
    precondition(automationState.mode == "automated_paper" && automationState.runs.count == 3)
    precondition(automationState.runs.allSatisfy { $0.active && $0.cash == "10000" && $0.observations == 0 && $0.pending == nil })
    precondition(automationState.runs.allSatisfy { $0.protocol.cost_bps == 10 && $0.symbol == "SPY" && !$0.events.isEmpty })
    print("PASS automated paper protocol, independent accounts and event decoding")
}
