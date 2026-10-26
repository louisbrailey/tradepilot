import SwiftUI
import Foundation
import TradeCore

struct BrokerAccount: Decodable, Identifiable { let id: String; let label: String }
struct BrokerPosition: Decodable, Identifiable {
    let id: String; let symbol: String; let quantity: String; let price: String
    let cost: String; let gain: String; let kind: String; let currency: String
}
struct BrokerSnapshot: Decodable {
    let environment: String; let accounts: [BrokerAccount]; let positions: [BrokerPosition]
    let balance: String; let as_of: Double
}
struct BrokerReview: Codable, Identifiable {
    let id: String; let confirmation_token: String; let environment: String; let account_id: String
    let order: [String: String]; let estimated_cost: String; let estimated_fee: String; let expires_at: Double
}
struct BrokerReceipt: Decodable {
    let id: String; let state: String; let environment: String; let client_order_id: String; let detail: String
    let account_id: String
}
struct BrokerExecution: Decodable, Identifiable {
    let id: String; let client_order_id: String; let symbol: String; let side: String
    let filled_quantity: String; let average_fill_price: String; let fill_notional: String
    let currency: String; let state: String; let updated_at: Double; let fees: String?
}
struct BrokerExecutionLedger: Decodable {
    let environment: String; let account_id: String; let scope: String; let as_of: Double
    let orders: [BrokerExecution]; let warnings: [String]; let totals: BrokerExecutionTotals
}
struct BrokerExecutionTotals: Decodable {
    let filled_orders: Int; let partial_orders: Int
    let notional_by_currency: [String: BrokerExecutionNotional]
    let fees_known: Bool
}
struct BrokerExecutionNotional: Decodable {
    let buy: String; let sell: String
}
struct BrokerConnectionBinding {
    let endpoint: String
    let token: String
    func matches(endpoint: String, token: String) -> Bool {
        self.endpoint == endpoint && self.token == token
    }
}
enum BrokerValidation {
    static func aiReplyMatches(_ reply: AIReply, account: String, environment: String,
                               now: TimeInterval = Date().timeIntervalSince1970, maxAge: TimeInterval = 120) -> Bool {
        guard !account.isEmpty, reply.account_id == account, reply.environment == environment,
              let asOf = reply.snapshot_as_of, asOf <= now + 5, asOf >= now - maxAge,
              ["message", "portfolio", "trade"].contains(reply.kind) else { return false }
        guard reply.kind == "trade" else {
            return reply.side == nil && reply.quantity == nil && reply.symbol == nil
        }
        guard let side = reply.side?.uppercased(), ["BUY", "SELL"].contains(side),
              let rawQuantity = reply.quantity,
              let quantity = Decimal(string: rawQuantity, locale: Locale(identifier: "en_US_POSIX")), quantity > 0,
              NSDecimalNumber(decimal: quantity).doubleValue.isFinite,
              let symbol = reply.symbol,
              symbol.range(of: "^[A-Z][A-Z0-9.-]{0,14}$", options: .regularExpression) != nil else { return false }
        return true
    }

    static func reviewMatches(_ review: BrokerReview, account: String, environment: String?, side: String? = nil, symbol: String? = nil, quantity: String? = nil, orderType: String? = nil, limitPrice: String? = nil, now: TimeInterval = Date().timeIntervalSince1970) -> Bool {
        guard !account.isEmpty, review.account_id == account, environment == review.environment,
              ["sandbox", "production"].contains(review.environment),
              !review.id.isEmpty, !review.confirmation_token.isEmpty,
              review.expires_at.isFinite, review.expires_at > now,
              review.order["market"] == "US", review.order["instrument_type"] == "EQUITY",
              review.order["combo_type"] == "NORMAL", review.order["time_in_force"] == "DAY",
              review.order["support_trading_session"] == "CORE", review.order["entrust_type"] == "QTY",
              ["MARKET", "LIMIT"].contains(review.order["order_type"] ?? ""),
              finiteAmount(review.estimated_cost), finiteAmount(review.estimated_fee),
              let receivedSide = review.order["side"], ["BUY", "SELL"].contains(receivedSide),
              let receivedSymbol = review.order["symbol"], receivedSymbol.range(of: "^[A-Z][A-Z0-9.-]{0,14}$", options: .regularExpression) != nil,
              let receivedQuantity = review.order["quantity"], let receivedDecimal = Decimal(string: receivedQuantity, locale: Locale(identifier: "en_US_POSIX")), receivedDecimal > 0,
              let clientOrderID = review.order["client_order_id"], !clientOrderID.isEmpty else { return false }
        guard decimal(receivedQuantity, nonnegative: false) else { return false }
        if review.order["order_type"] == "LIMIT" {
            guard let price = review.order["limit_price"], decimal(price, nonnegative: false) else { return false }
        } else if review.order["limit_price"] != nil { return false }
        if let orderType, review.order["order_type"] != orderType { return false }
        if let limitPrice {
            guard decimal(limitPrice, nonnegative: false),
                  let actual = review.order["limit_price"],
                  Decimal(string: actual) == Decimal(string: limitPrice) else { return false }
        }
        if let side, receivedSide != side.uppercased() { return false }
        if let symbol, receivedSymbol.uppercased() != symbol.uppercased() { return false }
        if let quantity {
            guard let expectedDecimal = Decimal(string: quantity, locale: Locale(identifier: "en_US_POSIX")), receivedDecimal == expectedDecimal else { return false }
        }
        return true
    }

    static func executionLedgerMatches(_ ledger: BrokerExecutionLedger, account: String, environment: String) -> Bool {
        guard !account.isEmpty, ledger.account_id == account, ledger.environment == environment,
              ledger.scope == "APP-TRACKED ONLY", ledger.as_of.isFinite,
              ledger.totals.filled_orders >= 0, ledger.totals.partial_orders >= 0 else { return false }
        for order in ledger.orders {
            guard !order.id.isEmpty, !order.client_order_id.isEmpty,
                  order.symbol.range(of: "^[A-Z][A-Z0-9.-]{0,14}$", options: .regularExpression) != nil,
                  ["BUY", "SELL"].contains(order.side.uppercased()),
                  order.currency.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil,
                  !order.state.isEmpty, order.updated_at.isFinite,
                  decimal(order.filled_quantity, nonnegative: true),
                  decimal(order.average_fill_price, nonnegative: true),
                  decimal(order.fill_notional, nonnegative: true),
                  order.fees.map({ decimal($0, nonnegative: true) }) ?? true else { return false }
        }
        return ledger.totals.notional_by_currency.allSatisfy { entry in
            entry.key.range(of: "^[A-Z]{3}$", options: .regularExpression) != nil &&
            decimal(entry.value.buy, nonnegative: true) && decimal(entry.value.sell, nonnegative: true)
        }
    }

    private static func finiteAmount(_ raw: String) -> Bool {
        guard raw.range(of: "^-?[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              let value = Decimal(string: raw, locale: Locale(identifier: "en_US_POSIX")) else { return false }
        return NSDecimalNumber(decimal: value).doubleValue.isFinite
    }

    private static func decimal(_ raw: String, nonnegative: Bool) -> Bool {
        guard raw.range(of: "^[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              let value = Decimal(string: raw, locale: Locale(identifier: "en_US_POSIX")),
              NSDecimalNumber(decimal: value).doubleValue.isFinite else { return false }
        return nonnegative ? value >= 0 : value > 0
    }
}
private final class BrokerNoRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}
@MainActor
enum BrokerAPI {
    static func call<T: Decodable>(_ operation: String, endpoint: String, token: String, body: [String: Any]) async throws -> T {
        guard token.count >= 32 else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Set your private HTTPS server and access token in Accounts first."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/webull/\(operation)"))
        request.httpMethod = "POST"; request.timeoutInterval = 45
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let message = (try? JSONDecoder().decode([String: String].self, from: data))?["error"] ?? "Webull is unavailable. Refresh an attempted order before creating another."
            throw NSError(domain: "TradePilot", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

struct WebullView: View {
    @Environment(AppStore.self) private var store
    @State private var prompt = ""
    @State private var snapshot: BrokerSnapshot?
    @State private var portfolioAccount: String?
    @State private var executions: BrokerExecutionLedger?
    @State private var account = ""
    @State private var side = "SELL"
    @State private var symbol = ""
    @State private var quantity = ""
    @State private var limit = ""
    @State private var review: BrokerReview?
    @State private var reviewBinding: BrokerConnectionBinding?
    @State private var receipt: BrokerReceipt?
    @State private var attempted = false
    @State private var busy = false
    @State private var status = "Connect to load your Webull accounts. Credentials stay on your private server."
    @AppStorage("webullPendingReview") private var pendingID = ""
    @AppStorage("webullPendingEndpoint") private var pendingEndpoint = ""
    @AppStorage("webullPendingAccount") private var pendingAccount = ""
    @AppStorage("webullPendingEnvironment") private var pendingEnvironment = ""
    @AppStorage("webullPendingClientOrder") private var pendingClientOrder = ""

    var body: some View {
        Screen(title: "Webull", isDemo: false) {
            Text(snapshot?.environment == "production" ? "WEBULL · REAL ACCOUNT" : "WEBULL · \(snapshot?.environment.uppercased() ?? "DISCONNECTED")")
                .font(.caption.bold()).foregroundStyle(snapshot?.environment == "production" ? .orange : Palette.mint)
            Text(status).font(.subheadline).textSelection(.enabled)
            Button("Load accounts") { run { journal("request", "Load Webull accounts"); try await load() } }.buttonStyle(MintButton()).disabled(busy)
            if let snapshot {
                Picker("Account", selection: $account) {
                    Text("Select an account").tag("")
                    ForEach(snapshot.accounts) { Text($0.label).tag($0.id) }
                }.disabled(busy || review != nil || !pendingID.isEmpty)
                Button("Refresh portfolio") { run { journal("request", "Refresh Webull portfolio"); try await load() } }.disabled(busy || account.isEmpty)
                if portfolioAccount == account, !account.isEmpty {
                    portfolioSection(snapshot)
                } else if !account.isEmpty {
                    Text("Refresh portfolio for this account before viewing holdings or balances.").font(.caption).foregroundStyle(Palette.muted)
                }
                executionSection(snapshot)
            }
            if !pendingID.isEmpty {
                Text("An order submission needs reconciliation. Refresh its broker status before entering another order.").font(.subheadline)
                if !pendingAccount.isEmpty || !pendingEnvironment.isEmpty {
                    Text("Pending: \(pendingEnvironment) · account \(pendingAccount)").font(.caption).foregroundStyle(Palette.muted)
                }
                Button("Refresh submitted order") { run { try await refreshOrder() } }.disabled(busy)
            } else if let review {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Review \(review.environment == "production" ? "real" : "sandbox") order").font(.title2.bold())
                    Text("\(review.order["side"] ?? "") \(review.order["quantity"] ?? "") shares of \(review.order["symbol"] ?? "")").font(.headline)
                    Text("Account: \(snapshot?.accounts.first(where: { $0.id == review.account_id })?.label ?? review.account_id)")
                    Text("\(review.order["order_type"] ?? "") · Day · Regular market session")
                    if let price = review.order["limit_price"] { Text("Limit: $\(price)") }
                    Text("Estimated cost: $\(review.estimated_cost)\nEstimated fees: $\(review.estimated_fee)")
                    Text("Expires \(Date(timeIntervalSince1970: review.expires_at).formatted(date: .omitted, time: .standard)). Market execution prices can change.").font(.caption)
                    Button("Confirm and submit \(review.environment == "production" ? "real" : "sandbox") order") { run { try await confirm(review) } }
                        .buttonStyle(MintButton()).disabled(busy || attempted || Date().timeIntervalSince1970 >= review.expires_at)
                    Button("Dismiss review") { run {
                        journal("request", "Dismiss Webull review", reference: review.id, accountID: review.account_id, environment: review.environment)
                        let _: BrokerReceipt = try await api("dismiss", ["id": review.id])
                        self.review = nil
                    } }.disabled(busy || attempted)
                }.card()
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Ask about your Webull account").font(.headline)
                    TextField("Sell 3 shares of AAPL", text: $prompt)
                    Text("Send request uses the local command parser. Ask AI sends your prompt, the selected account’s fresh portfolio snapshot, and optional journal context to your server’s AI provider. Local Ollama keeps inference on your Mac; OpenAI mode sends this context to OpenAI. Check the provider in Accounts. A trade response only fills the editable form.").font(.caption).foregroundStyle(Palette.muted)
                    Button("Send request") { run { try await sendCommand() } }.disabled(busy || account.isEmpty)
                    if store.aiEnabled {
                        Button("Ask AI about this account") { run { try await askAI() } }
                            .disabled(busy || account.isEmpty || snapshot == nil)
                    }
                }.card()
                VStack(alignment: .leading, spacing: 14) {
                    Text("Prepare a stock order").font(.headline)
                    Picker("Action", selection: $side) { Text("Sell").tag("SELL"); Text("Buy").tag("BUY") }.pickerStyle(.segmented)
                    TextField("Ticker, e.g. AAPL", text: $symbol).phoneSymbolInput()
                    TextField("Number of shares", text: $quantity)
                    TextField("Limit price (blank = market)", text: $limit)
                    Text("Stock purchases and sales only. Review does not submit an order.").font(.caption).foregroundStyle(Palette.muted)
                    Button("Get Webull order preview") { run {
                        journal("request", "Request Webull preview: \(side) \(quantity) \(symbol.uppercased())")
                        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
                        var body = ["account_id": account, "symbol": symbol.uppercased(), "side": side, "quantity": quantity]
                        if !limit.isEmpty { body["limit_price"] = limit }
                        let candidate: BrokerReview = try await api("review", body)
                        try validateReview(candidate, account: body["account_id"]!, side: body["side"], symbol: body["symbol"], quantity: body["quantity"], orderType: body["limit_price"] == nil ? "MARKET" : "LIMIT", limitPrice: body["limit_price"])
                        guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { throw mismatchError() }
                        reviewBinding = binding
                        review = candidate
                        journal("proposal", reviewedOrderText(candidate), reference: candidate.id, accountID: candidate.account_id, environment: candidate.environment)
                        attempted = false; receipt = nil
                        status = "Review the account, quantity and costs before confirming."
                    } }.buttonStyle(MintButton()).disabled(busy || account.isEmpty)
                }.card()
            }
            if let receipt {
                VStack(alignment: .leading, spacing: 10) {
                    Text(receipt.state).font(.headline)
                    Text("Submitted is not filled. Broker details below show the latest reported result.").font(.caption)
                    Text(receipt.detail).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    Text("Order reference: \(receipt.client_order_id)").font(.caption2).textSelection(.enabled)
                }.card()
            }
            if busy { ProgressView() }
        }
        .onChange(of: store.aiEndpoint) { _, _ in invalidateConnection() }
        .onChange(of: store.aiToken) { _, _ in invalidateConnection() }
        .onChange(of: account) { _, _ in
            portfolioAccount = nil
            executions = nil
        }
    }

    private func invalidateConnection() {
        snapshot = nil; portfolioAccount = nil; executions = nil; review = nil; reviewBinding = nil; receipt = nil
        status = "Connection changed. Load accounts again. Pending orders remain locked for reconciliation."
    }

    @ViewBuilder private func portfolioSection(_ snapshot: BrokerSnapshot) -> some View {
        Text("Updated \(Date(timeIntervalSince1970: snapshot.as_of).formatted())").font(.caption).foregroundStyle(Palette.muted)
        ScrollView(.horizontal) {
            Grid(alignment: .leading, horizontalSpacing: 22, verticalSpacing: 12) {
                GridRow { Text("Holding"); Text("Shares"); Text("Price"); Text("Avg cost"); Text("Unrealized"); Text("Currency") }.font(.caption.bold())
                ForEach(snapshot.positions) { p in
                    GridRow { Text(p.symbol); Text(p.quantity); Text(p.price); Text(p.cost); Text(p.gain); Text(p.currency) }.font(.system(.caption, design: .monospaced))
                }
            }
        }.card()
        DisclosureGroup("Account balances") { Text(snapshot.balance).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }.card()
    }

    @ViewBuilder private func executionSection(_ snapshot: BrokerSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Executions & evidence").font(.headline)
            Text("APP-TRACKED ONLY — this is not your full broker history. Notional is an execution amount, not profit or loss.")
                .font(.caption).foregroundStyle(Palette.muted)
            Button("Load tracked executions") { run { try await loadExecutions() } }
                .disabled(busy || account.isEmpty)
            if let executions, executions.account_id == account, executions.environment == snapshot.environment {
                Text("As of \(Date(timeIntervalSince1970: executions.as_of).formatted()) · \(executions.scope)")
                    .font(.caption).foregroundStyle(Palette.muted)
                executionTable(executions)
                Text("Filled orders: \(executions.totals.filled_orders) · Partial orders: \(executions.totals.partial_orders) · Fees \(executions.totals.fees_known ? "reported" : "not fully reported")")
                    .font(.caption)
                if !executions.warnings.isEmpty {
                    ForEach(executions.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
                }
            }
        }.card()
    }

    private func executionTable(_ ledger: BrokerExecutionLedger) -> some View {
        ScrollView(.horizontal) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 8) {
                GridRow { Text("Symbol"); Text("Side"); Text("Filled"); Text("Avg fill"); Text("Notional"); Text("Currency"); Text("State") }.font(.caption.bold())
                ForEach(ledger.orders) { order in
                    GridRow {
                        Text(order.symbol); Text(order.side); Text(order.filled_quantity); Text(order.average_fill_price)
                        Text(order.fill_notional); Text(order.currency); Text(order.state)
                    }.font(.system(.caption, design: .monospaced))
                }
            }
        }
    }
    private func journal(_ kind: String, _ text: String, reference: String? = nil, accountID: String? = nil, environment: String? = nil) {
        store.journal.append(kind: kind, text: text, strategy: store.strategyID, accountID: accountID ?? account,
            reference: reference, holdings: [], mode: "webull_" + (environment ?? snapshot?.environment ?? "unknown"))
    }
    private func sendCommand() async throws {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        journal("request", text)
        switch DemoAssistant.parse(text) {
        case .portfolio:
            try await load()
            status = "Your Webull holdings are in the table above."
        case .trade(let intent):
            let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
            let candidate: BrokerReview = try await api("review", ["account_id": account, "symbol": intent.symbol,
                "side": intent.side.rawValue.uppercased(), "quantity": NSDecimalNumber(decimal: intent.quantity).stringValue])
            try validateReview(candidate, account: account, side: intent.side.rawValue.uppercased(), symbol: intent.symbol, quantity: NSDecimalNumber(decimal: intent.quantity).stringValue, orderType: "MARKET")
            guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { throw mismatchError() }
            reviewBinding = binding
            review = candidate
            journal("proposal", reviewedOrderText(candidate), reference: candidate.id, accountID: candidate.account_id, environment: candidate.environment)
            attempted = false; receipt = nil
            status = "Review this Webull order before confirming."
        case .help:
            status = "Try ‘show my portfolio’ or ‘sell 3 shares of AAPL’. Use the form for a limit order. No order was created."
        }
        journal("assistant", status)
        prompt = ""
    }
    private func askAI() async throws {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, let expectedEnvironment = snapshot?.environment else { return }
        let requestedAccount = account
        let requestedEndpoint = store.aiEndpoint
        let requestedToken = store.aiToken
        journal("request", text, accountID: requestedAccount, environment: expectedEnvironment)
        let context = store.useJournalContext ? store.journal.entries
            .filter { $0.mode == "webull_" + expectedEnvironment && $0.accountID == requestedAccount }
            .prefix(30).map { ["kind": $0.kind, "text": String($0.text.prefix(1000)),
                "strategy": $0.strategy, "timestamp": $0.timestamp.ISO8601Format(),
                "mode": $0.mode, "session": $0.sessionID.uuidString] } : []
        let reply = try await AIService.askWebull(endpoint: requestedEndpoint, token: requestedToken,
            prompt: text, selectedAccount: requestedAccount, expectedEnvironment: expectedEnvironment,
            strategy: store.strategyID, journal: context)
        guard store.aiEndpoint == requestedEndpoint, store.aiToken == requestedToken, account == requestedAccount,
              snapshot?.environment == expectedEnvironment,
              BrokerValidation.aiReplyMatches(reply, account: requestedAccount, environment: expectedEnvironment) else {
            throw NSError(domain: "TradePilot", code: 22, userInfo: [NSLocalizedDescriptionKey: "The AI response did not match the selected Webull account and environment. Refresh and try again. No order was created."])
        }
        if reply.kind == "trade" {
            guard let proposedSide = reply.side?.uppercased(), ["BUY", "SELL"].contains(proposedSide),
                  let proposedSymbol = reply.symbol, !proposedSymbol.isEmpty,
                  let proposedQuantity = reply.quantity, Decimal(string: proposedQuantity, locale: Locale(identifier: "en_US_POSIX")) != nil else {
                throw NSError(domain: "TradePilot", code: 23, userInfo: [NSLocalizedDescriptionKey: "The AI response did not contain a complete stock proposal. No order was created."])
            }
            side = proposedSide; symbol = proposedSymbol; quantity = proposedQuantity; limit = ""
            status = reply.message + " Check and edit the form, then request a separate Webull preview."
            journal("proposal", "AI form proposal: \(proposedSide) \(proposedQuantity) \(proposedSymbol)",
                accountID: requestedAccount, environment: expectedEnvironment)
        } else if reply.kind == "portfolio" {
            try await load()
            guard snapshot?.environment == expectedEnvironment,
                  snapshot?.accounts.contains(where: { $0.id == requestedAccount }) == true else {
                throw NSError(domain: "TradePilot", code: 24, userInfo: [NSLocalizedDescriptionKey: "The refreshed portfolio no longer matched the selected account. No order was created."])
            }
            status = reply.message
        } else {
            status = reply.message
        }
        journal("assistant", status, accountID: requestedAccount, environment: expectedEnvironment)
        prompt = ""
    }
    private func api<T: Decodable>(_ operation: String, _ body: [String: Any]) async throws -> T {
        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        let result: T = try await BrokerAPI.call(operation, endpoint: binding.endpoint, token: binding.token, body: body)
        guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { throw mismatchError() }
        return result
    }
    private func run(_ operation: @escaping @MainActor () async throws -> Void) {
        guard !busy else { return }
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do { try await operation() } catch {
                status = error.localizedDescription
                journal("error", status)
            }
        }
    }
    private func load() async throws {
        let requestedAccount = account
        snapshot = try await api("state", requestedAccount.isEmpty ? [:] : ["account_id": requestedAccount])
        portfolioAccount = requestedAccount.isEmpty ? nil : requestedAccount
        status = "Connected to Webull. Select an account and refresh its portfolio."
    }
    private func loadExecutions() async throws {
        guard let expectedEnvironment = snapshot?.environment, !account.isEmpty else { return }
        let requestedAccount = account
        let requestedEndpoint = store.aiEndpoint
        let requestedToken = store.aiToken
        journal("execution_sync", "Requested APP-TRACKED ONLY execution evidence.", accountID: requestedAccount, environment: expectedEnvironment)
        let ledger: BrokerExecutionLedger = try await BrokerAPI.call("executions", endpoint: requestedEndpoint,
            token: requestedToken, body: ["account_id": requestedAccount])
        guard store.aiEndpoint == requestedEndpoint, store.aiToken == requestedToken, account == requestedAccount,
              snapshot?.environment == expectedEnvironment,
              BrokerValidation.executionLedgerMatches(ledger, account: requestedAccount, environment: expectedEnvironment) else {
            throw NSError(domain: "TradePilot", code: 25, userInfo: [NSLocalizedDescriptionKey: "Execution evidence did not match the selected server, account, and environment. Refresh and try again."])
        }
        executions = ledger
        journal("execution_sync", "Loaded \(ledger.orders.count) APP-TRACKED ONLY execution records; \(ledger.totals.filled_orders) filled and \(ledger.totals.partial_orders) partial.", accountID: requestedAccount, environment: expectedEnvironment)
        status = "Tracked execution evidence loaded. Notional is not profit or loss."
    }
    private func confirm(_ review: BrokerReview) async throws {
        guard !attempted else { return }
        guard reviewBinding?.matches(endpoint: store.aiEndpoint, token: store.aiToken) == true else { throw mismatchError() }
        try validateReview(review, account: account)
        // Persist the recovery lock before any approval record or network access.
        pendingID = review.id
        pendingEndpoint = store.aiEndpoint
        pendingAccount = review.account_id
        pendingEnvironment = review.environment
        pendingClientOrder = review.order["client_order_id"]!
        attempted = true
        journal("approval", "Approve \(reviewedOrderText(review))", reference: review.id, accountID: review.account_id, environment: review.environment)
        guard store.journal.error == nil else {
            status = "Submission is locked for reconciliation because the journal approval could not be saved. \(store.journal.error ?? "Journal unavailable")"; return
        }
        let candidate: BrokerReceipt = try await api("confirm", ["id": review.id, "confirmation_token": review.confirmation_token, "approved": true])
        try validateReceipt(candidate)
        receipt = candidate
        journal("submission_result", candidate.state + " " + candidate.detail, reference: review.id, accountID: pendingAccount, environment: pendingEnvironment)
        self.review = nil
        status = "Request recorded. Refresh broker status to verify the outcome."
    }
    private func refreshOrder() async throws {
        guard pendingEndpoint == store.aiEndpoint else {
            status = "Restore the server URL used for this order before checking its status."; return
        }
        guard !pendingAccount.isEmpty, !pendingEnvironment.isEmpty else {
            status = "This pending order lacks the account and environment needed for safe reconciliation. It remains locked."; return
        }
        var candidate: BrokerReceipt = try await api("status", ["id": pendingID])
        try validateReceipt(candidate)
        if candidate.state == "REVIEW" {
            candidate = try await api("dismiss", ["id": pendingID])
            try validateReceipt(candidate)
        }
        receipt = candidate
        if let receipt { journal("broker_status", receipt.state + " " + receipt.detail, reference: pendingID, accountID: pendingAccount, environment: pendingEnvironment) }
        if let receipt, ["FILLED", "CANCELLED", "FAILED", "EXPIRED", "CANCELLED_REVIEW"].contains(receipt.state) {
            pendingID = ""; pendingEndpoint = ""; pendingAccount = ""; pendingEnvironment = ""; pendingClientOrder = ""; review = nil; attempted = false
        }
        status = "Broker status refreshed."
    }
    private func validateReview(_ review: BrokerReview, account expectedAccount: String, side expectedSide: String? = nil, symbol expectedSymbol: String? = nil, quantity expectedQuantity: String? = nil, orderType: String? = nil, limitPrice: String? = nil) throws {
        guard BrokerValidation.reviewMatches(review, account: expectedAccount, environment: snapshot?.environment, side: expectedSide, symbol: expectedSymbol, quantity: expectedQuantity, orderType: orderType, limitPrice: limitPrice) else {
            throw mismatchError()
        }
    }
    private func validateReceipt(_ receipt: BrokerReceipt) throws {
        guard receipt.id == pendingID, receipt.environment == pendingEnvironment,
              receipt.account_id == pendingAccount, !pendingClientOrder.isEmpty,
              !receipt.client_order_id.isEmpty, receipt.client_order_id == pendingClientOrder else {
            throw NSError(domain: "TradePilot", code: 21, userInfo: [NSLocalizedDescriptionKey: "The broker receipt did not match the pending order. The order remains locked for reconciliation."])
        }
    }
    private func reviewedOrderText(_ review: BrokerReview) -> String {
        "\(review.order["side"] ?? "") \(review.order["quantity"] ?? "") \(review.order["symbol"] ?? "")"
    }
    private func mismatchError() -> NSError {
        NSError(domain: "TradePilot", code: 20, userInfo: [NSLocalizedDescriptionKey: "The broker review did not match the requested order. Request a new review."])
    }
}
