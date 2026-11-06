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
struct BrokerBalanceLine: Identifiable {
    let id: String; let title: String; let value: String; let amount: Decimal
    var tone: Tone { amount > 0 ? .positive : amount < 0 ? .negative : .neutral }
}
enum BrokerBalanceSummary {
    static func lines(_ json: String) -> [BrokerBalanceLine] {
        guard let data = json.data(using: .utf8),
              let values = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let currency = values["total_asset_currency"] as? String,
              currency.count == 3, currency.allSatisfy({ $0.isASCII && $0.isUppercase }) else { return [] }
        let fields = [("total_net_liquidation_value", "Net liquidation value"),
                      ("total_market_value", "Market value"), ("total_cash_balance", "Cash"),
                      ("total_unrealized_profit_loss", "Unrealised P/L"),
                      ("total_day_profit_loss", "Day P/L")]
        return fields.compactMap { key, title in
            guard let value = values[key] as? String, let number = strictDecimal(value) else { return nil }
            let signed = key.hasSuffix("profit_loss")
            return BrokerBalanceLine(id: key, title: title, value: signed ? signedMoney(number, currency: currency) : money(number, currency: currency), amount: number)
        }
    }
}
struct BrokerReview: Codable, Identifiable {
    var digest: String? = nil
    var economic_terms: [String: String]? = nil
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
              let rawQuantity = reply.quantity, rawQuantity.range(of: "^[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
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
@MainActor
enum BrokerAPI {
    static func call<T: Decodable>(_ operation: String, endpoint: String, token: String, body: [String: Any]) async throws -> T {
        guard token.count >= 32 else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Connect to your server in Settings first."])
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
            let message = (try? JSONDecoder().decode([String: String].self, from: data))?["error"] ?? "Couldn’t reach Webull (HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0))."
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
    @State private var feePolicy = "accept_rechecked_estimate"
    @State private var feeCeiling = ""
    @State private var debitCeiling = ""
    @State private var headroom = ""
    @State private var review: BrokerReview?
    @State private var reviewBinding: BrokerConnectionBinding?
    @State private var receipt: BrokerReceipt?
    @State private var attempted = false
    @State private var busy = false
    @State private var status = ""
    @State private var statusKind: NoticeKind = .info
    @State private var sheetStatus = ""
    @State private var cancellation: AccessReview?
    @State private var cancellationBinding: BrokerConnectionBinding?
    @AppStorage("webullPendingReview") private var pendingID = ""
    @AppStorage("webullPendingEndpoint") private var pendingEndpoint = ""
    @AppStorage("webullPendingAccount") private var pendingAccount = ""
    @AppStorage("webullPendingEnvironment") private var pendingEnvironment = ""
    @AppStorage("webullPendingClientOrder") private var pendingClientOrder = ""

    private var isLive: Bool { snapshot?.environment == "production" }
    private var accountLabel: String { snapshot?.accounts.first(where: { $0.id == account })?.label ?? account }

    var body: some View {
        SubScreen(title: "Webull", refresh: { await refreshCurrent() }) {
            HStack(spacing: Spacing.s) {
                StatusBadge.environment(snapshot?.environment)
                if let snapshot, portfolioAccount == account, !account.isEmpty { Text("Updated \(relativeTime(snapshot.as_of))").font(.footnote).foregroundStyle(Theme.textTertiary) }
                Spacer()
                if busy { ProgressView() }
            }
            if !pendingID.isEmpty { pendingSection }
            if let snapshot {
                SectionCard {
                    Picker("Account", selection: $account) {
                        Text("Select an account").tag("")
                        ForEach(snapshot.accounts) { Text($0.label).tag($0.id) }
                    }.pickerStyle(.menu).disabled(busy || review != nil || !pendingID.isEmpty)
                    if account.isEmpty { Footnote("Choose an account to load its balances and holdings.") }
                }
                if portfolioAccount == account, !account.isEmpty {
                    portfolioSection(snapshot)
                    executionSection(snapshot)
                    if pendingID.isEmpty && review == nil { orderForm }
                } else if !account.isEmpty, !busy {
                    EmptyState(title: "Not loaded", message: "Pull down to load this account.", icon: "arrow.down")
                }
            } else if !busy {
                EmptyState(title: "Not connected", message: "Pull down to load your Webull accounts through your server.", icon: "arrow.down")
            }
            if let receipt {
                SectionCard(title: "Last order") {
                    HStack { StatusBadge.orderState(receipt.state); Spacer(); Text("Ref \(receipt.client_order_id.prefix(8))").font(.caption).monospaced().foregroundStyle(Theme.textTertiary) }
                    Text(receipt.detail).font(.footnote).foregroundStyle(Theme.textSecondary).textSelection(.enabled)
                    Footnote("Sent is not filled. Check the status until the broker reports a final state.")
                }
            }
            OutcomeNotice(text: status, kind: statusKind)
        }
        .task { if snapshot == nil { await refreshCurrent() } }
        .onConnectionChange(store) { invalidateConnection() }
        .onChange(of: account) { _, _ in portfolioAccount = nil; executions = nil; Task { await refreshCurrent() } }
        .sheet(item: $review, onDismiss: { sheetStatus = "" }) { r in
            ConfirmationSheet(title: "Review order",
                              headline: "\(r.order["side"]?.capitalized ?? "") \(r.order["quantity"] ?? "") \(r.order["symbol"] ?? "")",
                              badge: StatusBadge.environment(r.environment),
                              disclaimer: r.environment == "production" ? "This places a real order with Webull. Market prices can move before it executes, and actual fees and debit can exceed the estimates." : "Sandbox orders do not use real money.",
                              expiresAt: Date(timeIntervalSince1970: r.expires_at),
                              confirmTitle: r.environment == "production" ? "Place live order" : "Place sandbox order",
                              destructive: r.environment == "production",
                              busy: busy || attempted, notice: sheetStatus, noticeKind: .error,
                              rows: {
                                  DetailRow("Account", snapshot?.accounts.first(where: { $0.id == r.account_id })?.label ?? r.account_id)
                                  DetailRow("Order type", "\((r.order["order_type"] ?? "").capitalized) · good for the day")
                                  if let price = r.order["limit_price"] { DetailRow("Limit price", gatewayMoney(price)) }
                                  DetailRow("Estimated cost", gatewayMoney(r.estimated_cost))
                                  DetailRow("Estimated fees", gatewayMoney(r.estimated_fee))
                                  if let terms = r.economic_terms {
                                      Divider().overlay(Theme.separator)
                                      ForEach(terms.keys.sorted(), id: \.self) { key in DetailRow(titleCase(key), terms[key] ?? "") }
                                  }
                              },
                              confirm: { run { try await confirm(r) } },
                              cancel: { run {
                                  journal("request", "Dismiss Webull review", reference: r.id, accountID: r.account_id, environment: r.environment)
                                  let _: BrokerReceipt = try await api("dismiss", ["id": r.id])
                                  self.review = nil
                              } })
            .interactiveDismissDisabled()
        }
    }

    // MARK: Sections

    private var pendingSection: some View {
        SectionCard(title: "Order awaiting confirmation") {
            HStack(spacing: Spacing.s) {
                StatusBadge.environment(pendingEnvironment)
                Text(pendingAccount.isEmpty ? "" : (snapshot?.accounts.first(where: { $0.id == pendingAccount })?.label ?? pendingAccount)).font(.footnote).foregroundStyle(Theme.textSecondary)
            }
            Footnote("Webull has not yet reported a final result. Check its status before placing another order.")
            Button("Check status") { run { try await refreshOrder() } }.buttonStyle(PrimaryButtonStyle()).disabled(busy)
            if pendingEnvironment == "production" {
                if let c = cancellation {
                    Divider().overlay(Theme.separator)
                    Text(c.summary).font(.footnote).monospaced().textSelection(.enabled)
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let expired = context.date.timeIntervalSince1970 >= c.expires_at
                        Button(expired ? "Cancellation review expired" : "Confirm cancellation") { run {
                            guard cancellationBinding?.matches(endpoint: store.aiEndpoint, token: store.aiToken) == true,
                                  let token = c.token, c.expires_at > Date().timeIntervalSince1970 else { throw mismatchError() }
                            cancellation = nil; cancellationBinding = nil
                            let r: AccessReview = try await api("cancel/confirm", ["id": c.id, "token": token, "digest": c.digest, "approved": true])
                            guard r.id == c.id else { throw mismatchError() }
                            status = "Cancel request \(StatusBadge.orderState(r.state).text.lowercased()). Check the order’s status for the final result."; statusKind = .info
                        } }.buttonStyle(PrimaryButtonStyle(tone: .live)).disabled(busy || expired)
                    }
                } else {
                    Button("Request cancellation") { run {
                        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
                        guard pendingEndpoint == binding.endpoint else { throw mismatchError() }
                        let r: AccessReview = try await api("cancel/review", ["id": pendingID])
                        guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { throw mismatchError() }
                        cancellation = r; cancellationBinding = binding
                    } }.buttonStyle(SecondaryButtonStyle()).disabled(busy)
                }
            }
        }
    }

    @ViewBuilder private func portfolioSection(_ snapshot: BrokerSnapshot) -> some View {
        let lines = BrokerBalanceSummary.lines(snapshot.balance)
        SectionCard {
            if let net = lines.first(where: { $0.id == "total_net_liquidation_value" }) {
                HeroMetric(label: "Net liquidation value", value: net.value,
                           delta: lines.first(where: { $0.id == "total_day_profit_loss" }).map { "\($0.value) today" }, deltaTone: lines.first(where: { $0.id == "total_day_profit_loss" }).map { $0.tone } ?? .neutral)
            } else {
                Eyebrow("Balances")
                Footnote("Webull did not return a summary for this account.")
            }
            HStack(spacing: Spacing.l) {
                ForEach(lines.filter { ["total_cash_balance", "total_market_value", "total_unrealized_profit_loss"].contains($0.id) }) { line in
                    MetricTile(label: line.title, value: line.value, tone: line.id == "total_unrealized_profit_loss" ? line.tone : nil)
                }
            }
        }
        SectionCard(title: "Holdings") {
            if snapshot.positions.isEmpty {
                EmptyState(title: "No open holdings", message: "Positions in this account appear here.", icon: "chart.pie")
            } else {
                ForEach(snapshot.positions) { p in
                    HoldingRow(symbol: p.symbol, detail: "\(p.quantity) shares · avg \(gatewayMoney(p.cost, currency: p.currency))",
                               value: gatewayMoney(p.price, currency: p.currency), change: gatewayMoney(p.gain, currency: p.currency, signed: true), changeTone: deltaColorTone(p.gain))
                }
            }
        }
    }

    @ViewBuilder private func executionSection(_ snapshot: BrokerSnapshot) -> some View {
        SectionCard(title: "Orders placed from TradePilot", footer: "Doesn’t include orders placed elsewhere. Notional is the executed amount, not profit or loss.") {
            if let executions, executions.account_id == account, executions.environment == snapshot.environment {
                HStack(spacing: Spacing.l) {
                    MetricTile(label: "Filled", value: "\(executions.totals.filled_orders)")
                    MetricTile(label: "Partial", value: "\(executions.totals.partial_orders)")
                    MetricTile(label: "Fees", value: executions.totals.fees_known ? "Reported" : "Incomplete")
                }
                if executions.orders.isEmpty {
                    EmptyState(title: "No orders", message: "Orders you place here will be listed.")
                } else {
                    ForEach(executions.orders) { order in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(order.side.capitalized) \(order.filled_quantity) \(order.symbol)").font(.subheadline.weight(.semibold))
                                Text("avg \(gatewayMoney(order.average_fill_price, currency: order.currency)) · \(relativeTime(order.updated_at))").font(.caption).foregroundStyle(Theme.textSecondary)
                            }
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(gatewayMoney(order.fill_notional, currency: order.currency)).font(.subheadline).monospacedDigit()
                                StatusBadge.orderState(order.state)
                            }
                        }.padding(.vertical, Spacing.xs).accessibilityElement(children: .combine)
                    }
                }
                ForEach(executions.warnings, id: \.self) { InlineNotice(kind: .warning, message: $0) }
            } else {
                Button("Load orders") { run { try await loadExecutions() } }.buttonStyle(SecondaryButtonStyle()).disabled(busy || account.isEmpty)
            }
        }
    }

    private var orderForm: some View {
        SectionCard(title: "New order", footer: isLive ? "Live orders need a limit price. You’ll review Webull’s estimate before anything is placed." : "You’ll review Webull’s estimate before anything is placed.") {
            Picker("Side", selection: $side) { Text("Sell").tag("SELL"); Text("Buy").tag("BUY") }.pickerStyle(.segmented)
            HStack(spacing: Spacing.m) {
                TextField("Symbol", text: $symbol).phoneSymbolInput().fieldStyle()
                TextField("Shares", text: $quantity).phoneDecimalInput().fieldStyle()
            }
            TextField(isLive ? "Limit price (required)" : "Limit price (blank = market)", text: $limit).phoneDecimalInput().fieldStyle()
            if isLive {
                DisclosureGroup("Fee limits") {
                    VStack(alignment: .leading, spacing: Spacing.m) {
                        Picker("Fee policy", selection: $feePolicy) {
                            Text("Accept a rechecked estimate").tag("accept_rechecked_estimate")
                            Text("Require an exact cap (not offered by Webull)").tag("require_provider_cap")
                        }.pickerStyle(.menu)
                        TextField("Max fee (USD)", text: $feeCeiling).phoneDecimalInput().fieldStyle()
                        TextField("Max total debit (USD)", text: $debitCeiling).phoneDecimalInput().fieldStyle()
                        TextField("Buffer (USD)", text: $headroom).phoneDecimalInput().fieldStyle()
                        Footnote("Pre-send checks on an estimate. Actual fees and debit can be higher.")
                    }.padding(.top, Spacing.s)
                }.font(.footnote.weight(.semibold))
            }
            Button("Review order") { run { try await requestPreview() } }
                .buttonStyle(PrimaryButtonStyle()).disabled(busy || account.isEmpty || symbol.trimmingCharacters(in: .whitespaces).isEmpty || quantity.isEmpty || (isLive && limit.isEmpty))
            Divider().overlay(Theme.separator)
            HStack(spacing: Spacing.m) {
                TextField(store.aiEnabled ? "Ask about this account" : "Type an order, e.g. Sell 3 AAPL", text: $prompt).fieldStyle()
                Button("Ask") { run { if store.aiEnabled { try await askAI() } else { try await sendCommand() } } }
                    .buttonStyle(SecondaryButtonStyle()).frame(width: 80).disabled(busy || account.isEmpty || prompt.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            Footnote(store.aiEnabled ? "Your question, this account’s fresh snapshot and optional journal context go to the model on your server. A trade suggestion only fills in the form above." : "Commands are parsed on this phone and only fill in the form above.")
        }
    }

    // MARK: Helpers

    private func deltaColorTone(_ text: String) -> Tone {
        guard let value = strictDecimal(text) else { return .neutral }
        return value > 0 ? .positive : value < 0 ? .negative : .neutral
    }
    private func invalidateConnection() {
        snapshot = nil; portfolioAccount = nil; executions = nil; review = nil; reviewBinding = nil; receipt = nil
        cancellation = nil; cancellationBinding = nil
        status = pendingID.isEmpty ? "" : "Connection changed. The pending order stays locked until its status is checked from its original server."; statusKind = .warning
    }
    private func refreshCurrent() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do { try await load() } catch { status = error.localizedDescription; statusKind = .error; journal("error", status) }
    }
    private func requestPreview() async throws {
        journal("request", "Request Webull preview: \(side) \(quantity) \(symbol.uppercased())")
        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        let requestedAccount = account
        var body = ["account_id": requestedAccount, "symbol": symbol.uppercased().trimmingCharacters(in: .whitespaces), "side": side, "quantity": quantity]
        if !limit.isEmpty { body["limit_price"] = limit }
        let economics = ["fee_policy": feePolicy, "fee_estimate_ceiling": feeCeiling, "debit_admission_ceiling": debitCeiling, "headroom": headroom, "fee_currency": "USD"]
        if isLive { body.merge(economics) { _, new in new } }
        let candidate: BrokerReview = try await api("review", body)
        if candidate.environment == "production" && candidate.economic_terms != economics { throw mismatchError() }
        try validateReview(candidate, account: requestedAccount, side: body["side"], symbol: body["symbol"], quantity: body["quantity"], orderType: body["limit_price"] == nil ? "MARKET" : "LIMIT", limitPrice: body["limit_price"])
        guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { throw mismatchError() }
        reviewBinding = binding
        review = candidate
        journal("proposal", reviewedOrderText(candidate), reference: candidate.id, accountID: candidate.account_id, environment: candidate.environment)
        attempted = false; receipt = nil; status = ""
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
            status = ""
        case .trade(let intent):
            symbol = intent.symbol; side = intent.side.rawValue.uppercased()
            quantity = NSDecimalNumber(decimal: intent.quantity).stringValue
            status = isLive ? "Form filled in. Add a limit price, then review." : "Form filled in. Review when ready."; statusKind = .info
        case .help:
            status = "Couldn’t read that. Try “Sell 3 AAPL”."; statusKind = .warning
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
        let context = store.useJournalContext ? store.journal.context(mode: "webull_" + expectedEnvironment, account: requestedAccount) : []
        let reply = try await AIService.askWebull(endpoint: requestedEndpoint, token: requestedToken,
            prompt: text, selectedAccount: requestedAccount, expectedEnvironment: expectedEnvironment,
            strategy: store.strategyID, journal: context)
        guard store.aiEndpoint == requestedEndpoint, store.aiToken == requestedToken, account == requestedAccount,
              snapshot?.environment == expectedEnvironment,
              BrokerValidation.aiReplyMatches(reply, account: requestedAccount, environment: expectedEnvironment) else {
            throw NSError(domain: "TradePilot", code: 22, userInfo: [NSLocalizedDescriptionKey: "The reply didn’t match the selected Webull account. Refresh and try again. No order was created."])
        }
        if reply.kind == "trade" {
            guard let proposedSide = reply.side?.uppercased(), ["BUY", "SELL"].contains(proposedSide),
                  let proposedSymbol = reply.symbol, !proposedSymbol.isEmpty,
                  let proposedQuantity = reply.quantity, strictDecimal(proposedQuantity, allowNegative: false) != nil else {
                throw NSError(domain: "TradePilot", code: 23, userInfo: [NSLocalizedDescriptionKey: "The reply didn’t contain a complete stock proposal. No order was created."])
            }
            side = proposedSide; symbol = proposedSymbol; quantity = proposedQuantity; limit = ""
            status = reply.message + " The form has been filled in; check it, then review."; statusKind = .info
            journal("proposal", "AI form proposal: \(proposedSide) \(proposedQuantity) \(proposedSymbol)",
                accountID: requestedAccount, environment: expectedEnvironment)
        } else if reply.kind == "portfolio" {
            try await load()
            guard snapshot?.environment == expectedEnvironment,
                  snapshot?.accounts.contains(where: { $0.id == requestedAccount }) == true else {
                throw NSError(domain: "TradePilot", code: 24, userInfo: [NSLocalizedDescriptionKey: "The refreshed portfolio no longer matched the selected account. No order was created."])
            }
            status = reply.message; statusKind = .info
        } else {
            status = reply.message; statusKind = .info
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
                if review != nil { sheetStatus = error.localizedDescription } else { status = error.localizedDescription; statusKind = .error }
                journal("error", error.localizedDescription)
            }
        }
    }
    private func load() async throws {
        let requestedAccount = account
        snapshot = try await api("state", requestedAccount.isEmpty ? [:] : ["account_id": requestedAccount])
        portfolioAccount = requestedAccount.isEmpty ? nil : requestedAccount
        if status.hasPrefix("Couldn’t") || statusKind == .error { status = "" }
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
            throw NSError(domain: "TradePilot", code: 25, userInfo: [NSLocalizedDescriptionKey: "The order list didn’t match the selected server, account and environment. Refresh and try again."])
        }
        executions = ledger
        journal("execution_sync", "Loaded \(ledger.orders.count) APP-TRACKED ONLY execution records; \(ledger.totals.filled_orders) filled and \(ledger.totals.partial_orders) partial.", accountID: requestedAccount, environment: expectedEnvironment)
    }
    private func confirm(_ review: BrokerReview) async throws {
        guard !attempted else { return }
        guard reviewBinding?.matches(endpoint: store.aiEndpoint, token: store.aiToken) == true else { throw mismatchError() }
        try validateReview(review, account: account)
        guard let clientOrder = review.order["client_order_id"], !clientOrder.isEmpty else { throw mismatchError() }
        // Persist the recovery lock before any approval record or network access.
        pendingID = review.id
        pendingEndpoint = store.aiEndpoint
        pendingAccount = review.account_id
        pendingEnvironment = review.environment
        pendingClientOrder = clientOrder
        cancellation = nil; cancellationBinding = nil
        attempted = true
        journal("approval", "Approve \(reviewedOrderText(review))", reference: review.id, accountID: review.account_id, environment: review.environment)
        guard store.journal.error == nil else {
            self.review = nil
            status = "Locked for reconciliation: the journal approval could not be saved. \(store.journal.error ?? "")"; statusKind = .error; return
        }
        var approval: [String: Any] = ["id": review.id, "confirmation_token": review.confirmation_token, "approved": true]
        if review.environment == "production" {
            guard let digest = review.digest else { throw WorkspaceError(message: "Request the review again to get its digest.") }
            approval["digest"] = digest
        }
        let candidate: BrokerReceipt = try await api("confirm", approval)
        try validateReceipt(candidate)
        receipt = candidate
        journal("submission_result", candidate.state + " " + candidate.detail, reference: review.id, accountID: pendingAccount, environment: pendingEnvironment)
        self.review = nil
        status = "Order sent. Check its status for the broker’s result."; statusKind = .success
    }
    private func refreshOrder() async throws {
        guard pendingEndpoint == store.aiEndpoint else {
            status = "This order was placed from a different server. Reconnect to it to check the status."; statusKind = .warning; return
        }
        guard !pendingAccount.isEmpty, !pendingEnvironment.isEmpty else {
            status = "This pending order lacks the account and environment needed for safe reconciliation. It stays locked."; statusKind = .error; return
        }
        var candidate: BrokerReceipt = try await api("status", ["id": pendingID])
        try validateReceipt(candidate)
        if candidate.state == "REVIEW" {
            candidate = try await api("dismiss", ["id": pendingID])
            try validateReceipt(candidate)
        }
        receipt = candidate
        journal("broker_status", candidate.state + " " + candidate.detail, reference: pendingID, accountID: pendingAccount, environment: pendingEnvironment)
        if ["FILLED", "CANCELLED", "FAILED", "EXPIRED", "CANCELLED_REVIEW"].contains(candidate.state) {
            pendingID = ""; pendingEndpoint = ""; pendingAccount = ""; pendingEnvironment = ""; pendingClientOrder = ""
            review = nil; attempted = false; cancellation = nil; cancellationBinding = nil
        }
        status = ""
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
            throw NSError(domain: "TradePilot", code: 21, userInfo: [NSLocalizedDescriptionKey: "The broker receipt didn’t match the pending order. It stays locked for reconciliation."])
        }
    }
    private func reviewedOrderText(_ review: BrokerReview) -> String {
        "\(review.order["side"] ?? "") \(review.order["quantity"] ?? "") \(review.order["symbol"] ?? "")"
    }
    private func mismatchError() -> NSError {
        NSError(domain: "TradePilot", code: 20, userInfo: [NSLocalizedDescriptionKey: "The review didn’t match the requested order. Request a new review."])
    }
}
