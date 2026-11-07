import SwiftUI
import TradeCore
import Charts

struct EmptyWorkspaceRequest: Encodable, Sendable {}
struct PaperApproval: Encodable, Sendable { let id: String; let token: String; let approved = true }
struct PaperIntentRequest: Encodable, Sendable {
    let symbol: String; let side: String; let quantity: String; let client_id: String
}
struct WorkspaceError: LocalizedError { let message: String; var errorDescription: String? { message } }

enum WorkspaceAPI {
    static func request<T: Decodable & Sendable, B: Encodable & Sendable>(_ path: String, body: B,
        endpoint: String, token: String) async throws -> T {
        guard token.count >= 32 else { throw WorkspaceError(message: "Connect to your server in Settings first.") }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"; request.timeoutInterval = 120
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let error = (try? JSONDecoder().decode([String: String].self, from: data))?["error"]
            throw WorkspaceError(message: error ?? "Couldn’t reach your server (HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)). Refresh before placing another order.")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

struct PaperPosition: Decodable, Sendable, Identifiable {
    var id: String { symbol }
    let symbol: String; let quantity: String; let cost_basis: String; let market_value: String
    let unrealized_pnl: String; let reference_as_of: Double
    let average_cost: String?
}
struct PaperReview: Decodable, Sendable, Identifiable {
    let id: String; let token: String?; let mode: String; let status: String
    let symbol: String; let side: String; let quantity: String
    let reference_price: String; let reference_as_of: Double; let source: String
    let fill_price: String; let notional: String; let cash_change: String
    let expires_at: Double; let label: String
}
struct PaperEventDetails: Decodable, Sendable {
    let text: String?; let symbol: String?; let side: String?; let quantity: String?; let notional: String?
}
struct PaperEvent: Decodable, Sendable, Identifiable {
    let id: Int; let kind: String; let at: Double; let data: PaperEventDetails
    var summary: String { data.text ?? [data.side?.capitalized, data.quantity, data.symbol].compactMap { $0 }.joined(separator: " ") }
}
struct PaperValuation: Decodable, Sendable, Identifiable {
    let id: Int
    let recorded_at: Double
    let equity: String
}
struct PaperSnapshot: Decodable, Sendable {
    let mode: String; let cash: String; let equity: String; let realized_pnl: String
    let max_drawdown: String; let mark_to_market_notice: String
    let positions: [PaperPosition]; let reviews: [PaperReview]; let orders: [PaperReview]; let journal: [PaperEvent]
    let initial_cash: String?; let valuation_as_of: Double?; let valuations: [PaperValuation]?
}
func workspaceMoney(_ value: String, signed: Bool = false) -> String { gatewayMoney(value, signed: signed) }
func workspaceDate(_ value: Double) -> String { gatewayDate(value) }

struct PaperEquitySummary: View {
    let snapshot: PaperSnapshot

    private var change: Decimal? {
        guard let balance = strictDecimal(snapshot.equity), let opening = snapshot.initial_cash.flatMap({ strictDecimal($0) }), opening > 0 else { return nil }
        return balance - opening
    }

    var body: some View {
        let points = (snapshot.valuations ?? []).compactMap(EquityPoint.init).sorted {
            $0.date == $1.date ? $0.id < $1.id : $0.date < $1.date
        }
        HeroMetric(label: "Total equity", value: workspaceMoney(snapshot.equity),
                   delta: change.map { "\(signedMoney($0)) since start" },
                   deltaTone: change.map { $0 > 0 ? .positive : $0 < 0 ? .negative : .neutral } ?? .neutral)
        if let first = points.first, let last = points.last, first.date < last.date {
            let low = points.map(\.equity).min() ?? first.equity
            let high = points.map(\.equity).max() ?? last.equity
            let padding = max(1, (high - low) * 0.15)
            let fractionalDigits = high - low < 4 ? 2 : 0
            let sameDay = Calendar.current.isDate(first.date, inSameDayAs: last.date)
            let timeFormat: Date.FormatStyle = sameDay ? .dateTime.hour().minute() : .dateTime.month(.abbreviated).day()
            Chart {
                ForEach(points) { point in
                    LineMark(x: .value("Recorded", point.date), y: .value("Equity", point.equity))
                        .foregroundStyle(Theme.accent).lineStyle(StrokeStyle(lineWidth: 2))
                }
                PointMark(x: .value("Recorded", last.date), y: .value("Equity", last.equity))
                    .foregroundStyle(Theme.accent).symbolSize(32)
            }
            .chartYScale(domain: max(0, low - padding)...(high + padding))
            .chartYAxis {
                AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                    AxisGridLine().foregroundStyle(Theme.separator)
                    AxisValueLabel {
                        if let amount = value.as(Double.self) {
                            Text(amount, format: .currency(code: "USD").precision(.fractionLength(fractionalDigits)))
                                .font(.caption2).foregroundStyle(Theme.textSecondary)
                        }
                    }
                }
            }
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 3)) {
                    AxisValueLabel(format: timeFormat).foregroundStyle(Theme.textSecondary)
                }
            }
            .frame(height: 126)
            .accessibilityLabel("Saved paper account equity")
            .accessibilityValue("\(points.count) observations from \(first.date.formatted(timeFormat)) to \(last.date.formatted(timeFormat))")
        } else {
            Footnote("The equity chart appears after two saved valuations.")
        }
        if let asOf = snapshot.valuation_as_of, asOf.isFinite, asOf > 0 {
            Footnote("Oldest saved price · \(gatewayDate(asOf))")
        } else if snapshot.positions.isEmpty {
            Footnote("Cash only · USD")
        }
    }

    private struct EquityPoint: Identifiable {
        let id: Int
        let date: Date
        let equity: Double

        init?(_ valuation: PaperValuation) {
            guard valuation.recorded_at.isFinite, valuation.recorded_at > 0,
                  let decimal = strictDecimal(valuation.equity, allowNegative: false) else { return nil }
            let value = NSDecimalNumber(decimal: decimal).doubleValue
            guard value.isFinite else { return nil }
            id = valuation.id
            date = Date(timeIntervalSince1970: valuation.recorded_at)
            equity = value
        }
    }
}

enum PaperValidation {
    static func decimal(_ text: String) -> Decimal? { strictDecimal(text) }
    static func reviewMatches(_ review: PaperReview, request: PaperIntentRequest, now: Double = Date().timeIntervalSince1970) -> Bool {
        guard review.mode == "paper", review.status == "REVIEW", !review.id.isEmpty, !(review.token ?? "").isEmpty,
              review.symbol == request.symbol, review.side == request.side, ["buy", "sell"].contains(review.side),
              let q = decimal(review.quantity), let wanted = decimal(request.quantity), q == wanted, q > 0,
              let price = decimal(review.reference_price), price > 0,
              let fill = decimal(review.fill_price), fill > 0,
              let total = decimal(review.notional), total > 0, let cash = decimal(review.cash_change),
              review.expires_at.isFinite, review.expires_at > now, review.expires_at <= now + 305,
              review.reference_as_of.isFinite, review.reference_as_of <= now, review.reference_as_of >= now - 96 * 3600 else { return false }
        let factor = review.side == "buy" ? Decimal(string: "1.001")! : Decimal(string: "0.999")!
        return fill == price * factor && total == q * fill && cash == (review.side == "buy" ? -total : total)
    }
    static func receiptMatches(_ receipt: PaperReview, review: PaperReview) -> Bool {
        receipt.mode == "paper" && receipt.status == "FILLED" && receipt.id == review.id &&
        receipt.symbol == review.symbol && receipt.side == review.side && receipt.quantity == review.quantity &&
        receipt.reference_price == review.reference_price && receipt.reference_as_of == review.reference_as_of &&
        receipt.fill_price == review.fill_price && receipt.notional == review.notional && receipt.cash_change == review.cash_change
    }
}

struct CoinbaseAccount: Decodable, Sendable, Identifiable {
    let id: String; let currency: String; let name: String; let available: String; let hold: String; let total: String
    var hasZeroBalance: Bool {
        [available, hold, total].allSatisfy { value in
            guard let match = value.range(of: #"^0+(?:\.0+)?$"#, options: .regularExpression) else { return false }
            return match.upperBound == value.endIndex
        }
    }
}
struct CoinbaseSnapshot: Decodable, Sendable {
    let broker: String; let read_only: Bool; let as_of: Double; let accounts: [CoinbaseAccount]
}

struct StrategyMetrics: Decodable, Sendable {
    let return_pct: Double; let max_drawdown_pct: Double; let benchmark_price_return_pct: Double; let fills: Int
}
struct StrategyStage: Decodable, Sendable { let baseline: StrategyMetrics; let cost_scenarios: [String: StrategyMetrics] }
struct StrategyResult: Decodable, Sendable, Identifiable {
    var id: String { strategy }
    let strategy: String; let rule: String; let validation: StrategyStage; let final: StrategyStage
}
struct StrategyComparison: Decodable, Sendable { let ticker: String; let evidence: String; let scope: String; let strategies: [StrategyResult] }

// Typed broker actions stay outside the assistant tool path. The saved server
// review is immutable; changing any field invalidates the local approval.
struct AccessReview: Decodable, Sendable {
    let id: String; let token: String?; let digest: String; let summary: String
    let expires_at: Double; let state: String
}
struct AccessPortfolio: Decodable, Sendable, Identifiable { let id: String; let type: String }
struct AccessPermissions: Decodable, Sendable {
    let can_view: Bool; let can_trade: Bool; let can_transfer: Bool; let portfolio_uuid: String
}
struct AccessCapabilities: Decodable, Sendable {
    let provider: String; let environment: String; let granted: AccessPermissions
    let trading_enabled: Bool; let cancellation_enabled: Bool; let transfers_enabled: Bool; let limitations: [String]
    let portfolios: [AccessPortfolio]
    func permits(_ action: String, account: String) -> Bool {
        guard provider == "coinbase", environment == "production", granted.can_view,
              account == granted.portfolio_uuid, portfolios.contains(where: { $0.id == account && ["DEFAULT", "CONSUMER"].contains($0.type) }) else { return false }
        switch action {
        case "limit_order": return granted.can_trade && trading_enabled
        case "cancel_order": return granted.can_trade && cancellation_enabled
        case "internal_transfer": return granted.can_transfer && transfers_enabled
        default: return false
        }
    }
}
struct AccessApproval: Encodable, Sendable {
    let id: String; let token: String; let digest: String; let approved: Bool
}
struct AccessOrder: Decodable, Sendable, Identifiable {
    var id: String { order_id }
    let order_id: String; let product_id: String; let side: String; let status: String
}
struct AccessOrders: Decodable, Sendable { let orders: [AccessOrder] }


// Separate from manual paper reviews: starting a fixed protocol authorizes only
// its future simulated fills. This API has no broker/account identifier input.
struct AutomatedPaperStart: Encodable, Sendable {
    let client_id: String
    let approved = true
}
struct AutomatedPaperProtocol: Decodable, Sendable {
    let version: String; let rule: String; let schedule: String
    let initial_cash: String; let entry_fraction: String; let max_entry: String; let cost_bps: Int
}
struct AutomatedPaperDecision: Decodable, Sendable {
    let long: Bool; let session: String; let recorded_at: Double; let budget: String
}
struct AutomatedPaperEvent: Decodable, Sendable, Identifiable {
    let id: Int; let at: Double; let kind: String; let message: String
}
struct AutomatedPaperRun: Decodable, Sendable, Identifiable {
    let id: String; let strategy: String; let symbol: String; let status: String; let reason: String
    let cash: String; let quantity: String; let equity: String; let realized: String; let costs: String
    let max_drawdown: String; let last_session: String?; let next_session: String
    let observations: Int; let fills: Int; let created_at: Double; let updated_at: Double
    let pending: AutomatedPaperDecision?; let events: [AutomatedPaperEvent]
    let `protocol`: AutomatedPaperProtocol
    var active: Bool { ["running", "waiting_data"].contains(status) }
    var title: String {
        switch strategy {
        case "trend_sma_20_50": return "Trend · SMA 20 / 50"
        case "breakout_20": return "Breakout · 20 sessions"
        case "mean_reversion_20": return "Mean reversion · SMA 20"
        default: return strategy
        }
    }
    var statusLabel: String {
        switch status {
        case "running": return "Running"
        case "waiting_data": return "Waiting for data"
        case "data_hold": return "Stopped · data check"
        case "risk_paused": return "Stopped · drawdown limit"
        case "paused": return "Stopped by you"
        default: return status
        }
    }
    var drawdownPercent: String {
        guard let value = PaperValidation.decimal(max_drawdown) else { return "Unavailable" }
        return NSDecimalNumber(decimal: value * 100).stringValue + "%"
    }
}
struct AutomatedPaperSnapshot: Decodable, Sendable {
    let mode: String; let version: String; let notice: String; let runs: [AutomatedPaperRun]
    let worker_checked_at: Double?; let checked_at: Double
}


// MARK: - Paper account

struct PaperTradingView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: PaperSnapshot?
    @State private var review: PaperReview?
    @State private var reviewBinding: BrokerConnectionBinding?
    @State private var symbol = ""
    @State private var side = "buy"
    @State private var quantity = ""
    @State private var command = ""
    @State private var note = ""
    @State private var status = ""
    @State private var statusKind: NoticeKind = .info
    @State private var sheetStatus = ""
    @State private var busy = false
    @State private var requestID = UUID().uuidString
    /// A symbol page can open this screen with its symbol already filled in. Nothing is reviewed until the user asks.
    init(prefillSymbol: String = "") { _symbol = State(initialValue: prefillSymbol) }
    var body: some View {
        SubScreen(title: "Paper account", refresh: { await load() }) {
            HStack { StatusBadge("Paper", tone: .paper); Spacer(); if busy { ProgressView() } }
            if let snapshot {
                SectionCard {
                    PaperEquitySummary(snapshot: snapshot)
                    Divider().overlay(Theme.separator)
                    MetricsGrid {
                        MetricTile(label: "Cash", value: workspaceMoney(snapshot.cash))
                        MetricTile(label: "Realized P/L", value: workspaceMoney(snapshot.realized_pnl, signed: true), tone: toneFor(snapshot.realized_pnl))
                        MetricTile(label: "Max drawdown", value: drawdown(snapshot.max_drawdown))
                    }
                    Button("Refresh prices") { Task { await load(mark: true) } }.buttonStyle(SecondaryButtonStyle()).disabled(busy)
                }
                SectionCard(title: "Positions") {
                    if snapshot.positions.isEmpty {
                        EmptyState(title: "No positions", message: "Filled paper orders appear here.", icon: "chart.pie")
                    } else {
                        Eyebrow("Position value and unrealized P/L")
                        VStack(spacing: 0) {
                            ForEach(snapshot.positions) { p in
                                if p.id != snapshot.positions.first?.id { Divider().overlay(Theme.separator) }
                                let average = p.average_cost.map { " · avg \(workspaceMoney($0))" } ?? ""
                                NavigationLink { SymbolDetailView(symbol: p.symbol) } label: {
                                    HoldingRow(symbol: p.symbol, detail: "\(p.quantity) shares\(average)",
                                               value: workspaceMoney(p.market_value), change: workspaceMoney(p.unrealized_pnl, signed: true), changeTone: toneFor(p.unrealized_pnl))
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(RowButtonStyle())
                                .disabled(!WatchlistStore.valid(p.symbol))
                                .accessibilityHint("Opens the quote page")
                            }
                        }
                    }
                }
            } else if !busy {
                EmptyState(title: "Not loaded", message: "Pull down to load your paper account.", icon: "arrow.down")
            }
            OutcomeNotice(text: status, kind: statusKind)
            SectionCard(title: "Paper order", footer: "The review uses the latest market price your server can see, or the last close when none is available, plus modeled slippage.") {
                Picker("Side", selection: $side) { Text("Buy").tag("buy"); Text("Sell").tag("sell") }.pickerStyle(.segmented)
                MetricsGrid {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Eyebrow("Symbol")
                        TextField("AAPL", text: $symbol).phoneSymbolInput().fieldStyle().accessibilityLabel("Symbol")
                    }
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Eyebrow("Shares")
                        TextField("0", text: $quantity).phoneDecimalInput().fieldStyle().accessibilityLabel("Shares")
                    }
                }
                Button("Review order") { prepare() }.buttonStyle(PrimaryButtonStyle()).disabled(busy || symbol.trimmingCharacters(in: .whitespaces).isEmpty || quantity.isEmpty)
                DisclosureGroup("Enter an order as text") {
                    TextField("Buy 3 AAPL", text: $command).fieldStyle()
                        .onChange(of: command) { _, text in
                            if case .trade(let intent) = DemoAssistant.parse(text) { symbol = intent.symbol; side = intent.side.rawValue; quantity = units(intent.quantity) }
                        }
                }.font(.subheadline)
            }
            SectionCard(title: "Activity") {
                let fills = snapshot?.journal.filter { $0.kind == "simulated_fill" } ?? []
                if fills.isEmpty { Footnote("Filled paper orders appear here.") }
                ForEach(fills.prefix(10)) { event in
                    HoldingRow(symbol: event.summary, detail: relativeTime(event.at),
                               value: event.data.notional.map { workspaceMoney($0) } ?? "Filled")
                }
            }
            SectionCard(title: "Account notes") {
                TextField("Thesis, observation or lesson", text: $note, axis: .vertical).lineLimit(2...5).fieldStyle()
                Button("Save note") { saveNote() }.buttonStyle(SecondaryButtonStyle()).disabled(busy || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if let snapshot {
                    ForEach(snapshot.journal.filter { $0.kind == "note" }.prefix(20)) { event in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack { Text(titleCase(event.kind)).font(.caption.weight(.semibold)); Spacer(); Text(relativeTime(event.at)).font(.caption).foregroundStyle(Theme.textTertiary) }
                            if !event.summary.isEmpty { Text(event.summary).font(.footnote).foregroundStyle(Theme.textSecondary) }
                        }.padding(.vertical, Spacing.xs)
                    }
                }
            }
        }
        .task { if snapshot == nil { await load() } }
        .onChange(of: symbol) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onChange(of: side) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onChange(of: quantity) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onConnectionChange(store) { clearConnection() }
        // A dismissed or confirmed review never reuses its client_id for a later request.
        .sheet(item: $review, onDismiss: { requestID = UUID().uuidString; sheetStatus = "" }) { proposed in
            ConfirmationSheet(title: "Review paper order",
                              headline: "\(proposed.side.capitalized) \(proposed.quantity) \(proposed.symbol)",
                              badge: StatusBadge("Paper", tone: .paper),
                              disclaimer: "This changes only your paper account. The reference price is delayed and can differ from a live executable price.",
                              expiresAt: Date(timeIntervalSince1970: proposed.expires_at),
                              confirmTitle: "Confirm paper \(proposed.side)",
                              busy: busy, notice: sheetStatus, noticeKind: .warning,
                              rows: {
                                  DetailRow("Account", "Paper portfolio")
                                  DetailRow("Simulated fill price", workspaceMoney(proposed.fill_price))
                                  DetailRow("Reference price", workspaceMoney(proposed.reference_price))
                                  DetailRow("Price time", gatewayDate(proposed.reference_as_of))
                                  Divider().overlay(Theme.separator)
                                  DetailRow("Estimated cash change", workspaceMoney(proposed.cash_change, signed: true))
                                  Footnote("\(proposed.source) · 0.10% modeled slippage")
                              },
                              confirm: { confirm(proposed) },
                              cancel: { review = nil; requestID = UUID().uuidString })
                .interactiveDismissDisabled(busy)
        }
    }
    private func toneFor(_ value: String) -> Tone {
        guard let d = strictDecimal(value) else { return .neutral }
        return d > 0 ? .positive : d < 0 ? .negative : .neutral
    }
    private func drawdown(_ value: String) -> String {
        guard let d = strictDecimal(value) else { return "—" }
        return percent(NSDecimalNumber(decimal: d * 100).doubleValue, digits: 1)
    }
    private func binding() -> BrokerConnectionBinding { BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken) }
    private func current(_ b: BrokerConnectionBinding) -> Bool { b.matches(endpoint: store.aiEndpoint, token: store.aiToken) }
    private func clearConnection() { snapshot = nil; review = nil; reviewBinding = nil; status = "Connection changed. Refresh the paper account."; statusKind = .warning; requestID = UUID().uuidString }
    private func load(mark: Bool = false) async {
        guard !busy else { return }; busy = true
        defer { busy = false }
        let b = binding()
        do {
            let result: PaperSnapshot = try await WorkspaceAPI.request(mark ? "v1/paper/mark" : "v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
            guard current(b) else { return }
            guard result.mode == "paper" else { throw WorkspaceError(message: "Unexpected paper account response.") }
            snapshot = result; status = ""
        } catch { if current(b) { status = error.localizedDescription; statusKind = .error } }
    }
    private func prepare() {
        guard !busy else { return }; busy = true
        let b = binding()
        let intent = PaperIntentRequest(symbol: symbol.trimmingCharacters(in: .whitespacesAndNewlines).uppercased(), side: side, quantity: quantity, client_id: requestID)
        Task { defer { busy = false }
            do {
                let result: PaperReview = try await WorkspaceAPI.request("v1/paper/review", body: intent, endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                guard PaperValidation.reviewMatches(result, request: intent) else { throw WorkspaceError(message: "The review didn’t match your order. Please try again.") }
                review = result; reviewBinding = b; status = ""
            } catch { if current(b) { status = error.localizedDescription; statusKind = .error; requestID = UUID().uuidString } }
        }
    }
    private func confirm(_ proposed: PaperReview) {
        guard !busy, let b = reviewBinding, current(b), let token = proposed.token else { return }
        busy = true; requestID = UUID().uuidString  // Retries use proposed.id/token, not the form's client_id.
        Task { defer { busy = false }
            let receipt: PaperReview
            do {
                receipt = try await WorkspaceAPI.request("v1/paper/confirm", body: PaperApproval(id: proposed.id, token: token), endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                guard PaperValidation.receiptMatches(receipt, review: proposed) else { throw WorkspaceError(message: "The receipt didn’t match the review. Refresh before another order.") }
            } catch {
                if current(b) { sheetStatus = "\(error.localizedDescription) The result is unknown: retry this confirmation or refresh the account." }
                return
            }
            store.journal.append(kind: "paper_fill", text: "Paper \(receipt.side) \(receipt.quantity) \(receipt.symbol) at \(receipt.fill_price). Delayed reference simulation.", strategy: store.strategyID, accountID: "paper", holdings: [], mode: "paper")
            review = nil; requestID = UUID().uuidString; command = ""
            status = "Paper order filled and saved."; statusKind = .success
            do {
                let result: PaperSnapshot = try await WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                if current(b) {
                    guard result.mode == "paper" else { throw WorkspaceError(message: "Unexpected paper account response.") }
                    snapshot = result
                }
            } catch { if current(b) { status = "Paper order filled and saved, but the account didn’t refresh. Pull down to retry."; statusKind = .warning } }
        }
    }
    private func saveNote() {
        guard !busy else { return }; busy = true
        let b = binding(), text = note
        Task { defer { busy = false }
            do {
                let _: PaperEvent = try await WorkspaceAPI.request("v1/paper/note", body: ["text": text], endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                note = ""; status = "Note saved."; statusKind = .success
            } catch {
                if current(b) { status = error.localizedDescription; statusKind = .error }
                return
            }
            do {
                let result: PaperSnapshot = try await WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                guard result.mode == "paper" else { throw WorkspaceError(message: "Unexpected paper account response.") }
                snapshot = result
            } catch { if current(b) { status = "Note saved. Pull down to refresh the account."; statusKind = .warning } }
        }
    }
}

// MARK: - Coinbase balances

struct CoinbaseView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: CoinbaseSnapshot?
    @State private var message = ""
    @State private var busy = false
    @State private var showEmptyAccounts = false
    private var visibleAccounts: [CoinbaseAccount] {
        (snapshot?.accounts ?? []).filter { showEmptyAccounts || !$0.hasZeroBalance }
            .sorted { $0.currency == $1.currency ? $0.id < $1.id : $0.currency < $1.currency }
    }
    var body: some View {
        SubScreen(title: "Coinbase", refresh: { await refresh() }) {
            OutcomeNotice(text: message, kind: .error)
            if let snapshot {
                HStack {
                    StatusBadge("Balance view")
                    Spacer()
                    if busy { ProgressView() }
                }
                Footnote("Account loaded \(relativeTime(snapshot.as_of))")
                SectionCard(title: "Asset balances", footer: "Amounts are shown in units of each asset.") {
                    Toggle("Show zero balances", isOn: $showEmptyAccounts).font(.subheadline)
                    if snapshot.accounts.isEmpty {
                        EmptyState(title: "No accounts", message: "Coinbase returned no asset accounts for this key.")
                    } else if visibleAccounts.isEmpty {
                        EmptyState(title: "All balances are zero", message: "Turn on “Show zero balances” to see them.")
                    } else {
                        VStack(spacing: 0) {
                            ForEach(visibleAccounts) { a in
                                if a.id != visibleAccounts.first?.id { Divider().overlay(Theme.separator) }
                                let hasHold = (strictDecimal(a.hold) ?? 0) > 0
                                HoldingRow(symbol: a.currency, detail: hasHold ? "\(assetUnits(a.hold)) on hold" : a.name,
                                           value: assetUnits(a.total), change: hasHold ? "\(assetUnits(a.available)) available" : nil)
                            }
                        }
                        Footnote("\(visibleAccounts.count) of \(snapshot.accounts.count) asset accounts shown.")
                    }
                }
            } else if busy {
                ProgressView("Loading Coinbase balances")
            } else {
                EmptyState(title: "Not loaded", message: "Pull down to load balances through your server.", icon: "arrow.down")
            }
            SectionCard {
                NavigationLink { CoinbaseActionsView() } label: { NavigationRow(title: "Permissions and orders", detail: "Account access and order history", icon: "lock.shield") }
                    .buttonStyle(RowButtonStyle())
            }
        }
        .task { if snapshot == nil { await refresh() } }
        .onConnectionChange(store) { snapshot = nil; message = "" }
    }
    private func assetUnits(_ value: String) -> String { strictDecimal(value, allowNegative: false).map(units) ?? "—" }

    private func refresh() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        do {
            let result: CoinbaseSnapshot = try await WorkspaceAPI.request("v1/coinbase/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
            guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
            guard result.broker == "coinbase", result.read_only, result.as_of.isFinite, result.as_of > 0 else {
                throw WorkspaceError(message: "Coinbase returned an unexpected balance response. Pull down to refresh.")
            }
            snapshot = result; message = ""
        } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription } }
    }
}

// MARK: - Strategy lab

struct StrategyComparisonView: View {
    @Environment(AppStore.self) private var store
    @State private var ticker = "AAPL"
    @State private var result: StrategyComparison?
    @State private var message = ""
    @State private var busy = false
    var body: some View {
        SubScreen(title: "Strategy lab") {
            SectionCard(footer: "Backtests of three rule-based strategies after costs. Research only; past results are not a recommendation.") {
                HStack(spacing: Spacing.m) {
                    TextField("Symbol", text: $ticker).phoneSymbolInput().fieldStyle()
                    Button(busy ? "Running…" : "Compare") { compare() }.buttonStyle(PrimaryButtonStyle()).frame(width: 130).disabled(busy || ticker.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            OutcomeNotice(text: message, kind: .error)
            if let result {
                Footnote(result.scope)
                ForEach(result.strategies) { strategy in
                    SectionCard(title: titleCase(strategy.strategy), footer: strategy.rule) {
                        Eyebrow("Validation · 10 bps per side")
                        metrics(strategy.validation.baseline)
                        Eyebrow("Final period · 10 bps per side")
                        metrics(strategy.final.baseline)
                        Eyebrow("Final period by cost")
                        HStack(spacing: Spacing.m) {
                            ForEach(["0", "10", "25", "50"], id: \.self) { cost in
                                if let m = strategy.final.cost_scenarios[cost] {
                                    MetricTile(label: "\(cost) bps", value: percent(m.return_pct, signed: true), tone: m.return_pct >= 0 ? .positive : .negative)
                                }
                            }
                        }
                    }
                }
            }
        }
        .onConnectionChange(store) { result = nil }
    }
    @ViewBuilder private func metrics(_ m: StrategyMetrics) -> some View {
        HStack(spacing: Spacing.m) {
            MetricTile(label: "Strategy", value: percent(m.return_pct, signed: true), tone: m.return_pct >= 0 ? .positive : .negative)
            MetricTile(label: "Benchmark", value: percent(m.benchmark_price_return_pct, signed: true))
            MetricTile(label: "Drawdown", value: percent(m.max_drawdown_pct))
            MetricTile(label: "Fills", value: "\(m.fills)")
        }
    }
    private func compare() {
        busy = true; result = nil
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken), symbol = ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        Task { defer { busy = false }
            do {
                let report: StrategyComparison = try await WorkspaceAPI.request("v1/strategies", body: ["ticker": symbol], endpoint: b.endpoint, token: b.token)
                guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
                guard report.ticker == symbol, report.evidence == "exploratory_previously_observed" else { throw WorkspaceError(message: "This result couldn’t be verified.") }
                result = report; message = ""
            } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription } }
        }
    }
}

// MARK: - Coinbase permissions and actions

struct CoinbaseActionsView: View {
    @Environment(AppStore.self) private var store
    @State private var capabilities: AccessCapabilities?
    @State private var account = ""
    @State private var action = "limit_order"
    @State private var feePolicy = "accept_rechecked_estimate"
    @State private var feeCeiling = ""
    @State private var debitCeiling = ""
    @State private var headroom = ""
    @State private var feeCurrency = ""
    @State private var product = ""
    @State private var side = "BUY"
    @State private var quantity = ""
    @State private var price = ""
    @State private var destination = ""
    @State private var currency = ""
    @State private var amount = ""
    @State private var orderID = ""
    @State private var clientID = UUID().uuidString
    @State private var review: AccessReview?
    @State private var reviewedIntent: [String: String]?
    @State private var reviewedConnection: BrokerConnectionBinding?
    @State private var busy = false
    @State private var message = ""
    @State private var messageKind: NoticeKind = .info
    @State private var showApproval = false
    @State private var orders: [AccessOrder] = []
    @AppStorage("coinbaseLastActionID") private var savedID = ""
    @AppStorage("coinbaseLastActionEndpoint") private var savedEndpoint = ""

    private var intent: [String: String] {
        var p = ["client_id": clientID, "action": action, "account_id": account, "environment": "production"]
        switch action {
        case "limit_order":
            p.merge(["product_id": product, "side": side, "base_size": quantity, "limit_price": price,
                     "fee_policy": feePolicy, "fee_estimate_ceiling": feeCeiling, "debit_admission_ceiling": debitCeiling, "headroom": headroom, "fee_currency": feeCurrency]) { _, new in new }
        case "cancel_order": p["order_id"] = orderID
        default:
            p.merge(["destination": destination, "currency": currency, "amount": amount,
                     "network": "coinbase_internal", "fee_policy": "internal_no_fee_parameter"]) { _, new in new }
        }
        return p
    }
    private var canConfirm: Bool {
        guard let r = review, r.token != nil, r.state == "REVIEW", r.expires_at > Date().timeIntervalSince1970,
              reviewedIntent == intent, let connection = reviewedConnection,
              connection.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return false }
        return canPrepare
    }
    private var canPrepare: Bool { capabilities?.permits(action, account: account) == true }
    private var anyActionPermitted: Bool {
        ["limit_order", "cancel_order", "internal_transfer"].contains { capabilities?.permits($0, account: account) == true }
    }
    var body: some View {
        SubScreen(title: "Permissions", refresh: { await load() }) {
            HStack { StatusBadge("Live", tone: .live); Spacer(); if busy { ProgressView() } }
            if let c = capabilities {
                SectionCard(title: "This key may", footer: "Granted by your Coinbase API key. Your server has its own switches, shown on the right.") {
                    permissionRow("View balances", granted: c.granted.can_view, server: nil)
                    permissionRow("Trade", granted: c.granted.can_trade, server: c.trading_enabled)
                    permissionRow("Cancel orders", granted: c.granted.can_trade, server: c.cancellation_enabled)
                    permissionRow("Transfer between portfolios", granted: c.granted.can_transfer, server: c.transfers_enabled)
                    if !c.limitations.isEmpty {
                        DisclosureGroup("Limits") {
                            VStack(alignment: .leading, spacing: Spacing.s) { ForEach(c.limitations, id: \.self) { Footnote($0) } }.padding(.top, Spacing.s)
                        }.font(.footnote.weight(.semibold))
                    }
                }
                SectionCard(title: "Orders") {
                    Picker("Portfolio", selection: $account) {
                        Text("Select a portfolio").tag("")
                        ForEach(c.portfolios.filter { $0.id == c.granted.portfolio_uuid }) { Text("\($0.type.capitalized) portfolio").tag($0.id) }
                    }.pickerStyle(.menu)
                    Button("Load orders") { Task { await loadOrders() } }.buttonStyle(SecondaryButtonStyle()).disabled(busy || account.isEmpty || !c.granted.can_view)
                    if orders.isEmpty {
                        Footnote("Orders for the selected portfolio appear here.")
                    } else {
                        ForEach(orders) { order in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(order.product_id).font(.subheadline.weight(.semibold))
                                    Text(order.side.capitalized).font(.caption).foregroundStyle(Theme.textSecondary)
                                }
                                Spacer()
                                StatusBadge.orderState(order.status)
                            }.padding(.vertical, Spacing.xs)
                        }
                    }
                }
                if anyActionPermitted {
                    SectionCard(title: "New action", footer: "Any action needs a saved review and a separate confirmation.") {
                        actionForm(c)
                    }
                } else if !account.isEmpty {
                    InlineNotice(kind: .info, message: "Trading, cancellations and transfers are off for this portfolio. Both the key’s permission and your server must allow them.")
                }
            } else if !busy {
                EmptyState(title: "Not loaded", message: "Pull down to check this key’s permissions.", icon: "arrow.down")
            }
            if let r = review {
                SectionCard(title: "Saved review") {
                    HStack { StatusBadge.orderState(r.state); Spacer(); Text("Expires \(gatewayDate(r.expires_at))").font(.caption).foregroundStyle(Theme.textTertiary) }
                    Text(r.summary).font(.footnote).monospaced().textSelection(.enabled)
                    if canConfirm {
                        Button("Confirm") { showApproval = true }.buttonStyle(PrimaryButtonStyle(tone: .live)).disabled(busy)
                    }
                }
            }
            if !savedID.isEmpty && savedEndpoint == store.aiEndpoint {
                Button("Check last action’s status") { Task { await reconcile() } }.buttonStyle(SecondaryButtonStyle()).disabled(busy)
            }
            OutcomeNotice(text: message, kind: messageKind)
        }
        .disabled(busy)
        .task { if capabilities == nil { await load() } }
        .onChange(of: intent) { _, _ in review = nil; reviewedIntent = nil }
        .onConnectionChange(store) { clearConnection() }
        .confirmationDialog("Submit this reviewed action to Coinbase?", isPresented: $showApproval, titleVisibility: .visible) {
            Button("Submit", role: .destructive) { confirm() }
            Button("Keep reviewing", role: .cancel) {}
        } message: { Text("This affects real funds. Only the saved terms shown above are submitted.") }
    }
    @ViewBuilder private func actionForm(_ c: AccessCapabilities) -> some View {
        Picker("Action", selection: $action) {
            Text("Limit order").tag("limit_order")
            Text("Cancel order").tag("cancel_order")
            Text("Move between portfolios").tag("internal_transfer")
        }.pickerStyle(.segmented)
        if !canPrepare { InlineNotice(kind: .warning, message: "Not available for this portfolio.") }
        if action == "limit_order" {
            TextField("Product, e.g. BTC-USD", text: $product).phoneSymbolInput().fieldStyle()
            Picker("Side", selection: $side) { Text("Buy").tag("BUY"); Text("Sell").tag("SELL") }.pickerStyle(.segmented)
            HStack(spacing: Spacing.m) {
                TextField("Amount (base asset)", text: $quantity).phoneDecimalInput().fieldStyle()
                TextField("Limit price", text: $price).phoneDecimalInput().fieldStyle()
            }
            DisclosureGroup("Fee limits") {
                VStack(alignment: .leading, spacing: Spacing.m) {
                    Picker("Fee policy", selection: $feePolicy) {
                        Text("Accept a rechecked estimate").tag("accept_rechecked_estimate")
                        Text("Require an exact cap (Coinbase doesn’t offer one)").tag("require_provider_cap")
                    }.pickerStyle(.menu)
                    TextField("Max fee", text: $feeCeiling).phoneDecimalInput().fieldStyle()
                    TextField("Max total debit", text: $debitCeiling).phoneDecimalInput().fieldStyle()
                    TextField("Buffer", text: $headroom).phoneDecimalInput().fieldStyle()
                    TextField("Fee currency (quote currency, e.g. USD)", text: $feeCurrency).phoneSymbolInput().fieldStyle()
                    Footnote("These are pre-send checks on an estimate. Actual fees and debit can be higher; Coinbase gives no hard fee cap. Good-till-cancelled spot only; no leverage or short selling.")
                }.padding(.top, Spacing.s)
            }.font(.footnote.weight(.semibold))
        } else if action == "cancel_order" {
            TextField("Order ID", text: $orderID).fieldStyle()
            ForEach(orders) { order in
                Button { orderID = order.order_id } label: {
                    HStack { Text("\(order.product_id) · \(order.side.capitalized)").font(.footnote); Spacer(); StatusBadge.orderState(order.status) }
                }.buttonStyle(RowButtonStyle())
            }
        } else {
            Picker("Destination portfolio", selection: $destination) {
                Text("Select destination").tag("")
                ForEach(c.portfolios.filter { $0.id != account }) { Text("\($0.type.capitalized) · \($0.id.prefix(8))").tag($0.id) }
            }.pickerStyle(.menu)
            HStack(spacing: Spacing.m) {
                TextField("Asset, e.g. USDC", text: $currency).phoneSymbolInput().fieldStyle()
                TextField("Amount", text: $amount).phoneDecimalInput().fieldStyle()
            }
            Footnote("Moves funds between your own Coinbase portfolios only. This never withdraws to an address or a bank. An uncertain result locks both portfolios until it is resolved.")
        }
        Button("Review") { prepare() }.buttonStyle(PrimaryButtonStyle()).disabled(busy || !canPrepare)
    }
    private func permissionRow(_ label: String, granted: Bool, server: Bool?) -> some View {
        HStack(spacing: Spacing.s) {
            Text(label).font(.subheadline).foregroundStyle(Theme.textSecondary)
            Spacer()
            StatusBadge(granted ? "Allowed" : "Not allowed", tone: granted ? .positive : .neutral)
            if let server { StatusBadge(server ? "Server on" : "Server off", tone: server ? .live : .neutral) }
        }.accessibilityElement(children: .combine)
    }
    private func clearConnection() {
        capabilities = nil; review = nil; reviewedIntent = nil; reviewedConnection = nil
        orders = []; account = ""; showApproval = false; message = ""
    }
    private func load() async {
        guard !busy else { return }
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        busy = true; review = nil
        defer { busy = false }
        do {
            let c: AccessCapabilities = try await WorkspaceAPI.request("v1/coinbase/capabilities", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
            guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken), c.provider == "coinbase", c.environment == "production" else { return }
            capabilities = c
            account = c.granted.can_view && c.portfolios.contains(where: { $0.id == c.granted.portfolio_uuid }) ? c.granted.portfolio_uuid : ""
            orders = []; message = ""
        } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription; messageKind = .error } }
    }
    private func prepare() {
        guard !busy, canPrepare else { return }
        clientID = UUID().uuidString
        let p = intent, b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        busy = true; review = nil
        Task { defer { busy = false }
            do {
                let r: AccessReview = try await WorkspaceAPI.request("v1/coinbase/action/review", body: p, endpoint: b.endpoint, token: b.token)
                guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken), p == intent else { return }
                review = r; reviewedIntent = p; reviewedConnection = b
                message = "Check every field before confirming."; messageKind = .info
            } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription; messageKind = .error } }
        }
    }
    private func confirm() {
        guard canConfirm, let r = review, let token = r.token, let b = reviewedConnection else { return }
        // Record the attempt before the network call so an uncertain result can be reconciled later.
        savedID = r.id; savedEndpoint = b.endpoint
        busy = true; review = nil; reviewedIntent = nil; reviewedConnection = nil
        Task { defer { busy = false }
            do {
                let result: AccessReview = try await WorkspaceAPI.request("v1/coinbase/action/confirm", body: AccessApproval(id: r.id, token: token, digest: r.digest, approved: true), endpoint: b.endpoint, token: b.token)
                guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
                guard result.id == r.id else { throw WorkspaceError(message: "Unexpected reply. Check the last action’s status before doing anything else.") }
                review = result
                message = result.state == "UNKNOWN" ? "We don’t know yet whether this went through. Check its status before placing another action." : "Saved as \(StatusBadge.orderState(result.state).text.lowercased())."
                messageKind = result.state == "UNKNOWN" ? .warning : .success
            } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = "Result uncertain. Check the last action’s status. " + error.localizedDescription; messageKind = .warning } }
        }
    }
    private func reconcile() async {
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken), id = savedID
        busy = true
        defer { busy = false }
        do {
            let r: AccessReview = try await WorkspaceAPI.request("v1/coinbase/action/reconcile", body: ["id": id], endpoint: b.endpoint, token: b.token)
            guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
            guard r.id == id else { throw WorkspaceError(message: "Unexpected reply for the saved action.") }
            review = r; reviewedIntent = nil; reviewedConnection = nil
            message = r.state == "UNKNOWN" ? "Still unconfirmed. This needs resolving against Coinbase before another action." : "Last action: \(StatusBadge.orderState(r.state).text.lowercased())."
            messageKind = r.state == "UNKNOWN" ? .warning : .info
        } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription; messageKind = .error } }
    }
    private func loadOrders() async {
        guard !busy, !account.isEmpty, capabilities?.granted.can_view == true else { return }
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken), selected = account
        busy = true
        defer { busy = false }
        do {
            let r: AccessOrders = try await WorkspaceAPI.request("v1/coinbase/orders", body: ["account_id": selected], endpoint: b.endpoint, token: b.token)
            guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken), selected == account else { return }
            orders = r.orders; message = ""
        } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription; messageKind = .error } }
    }
}

// MARK: - Automated paper strategies

struct AutomatedPaperView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: AutomatedPaperSnapshot?
    @State private var busy = false
    @State private var message = ""
    @State private var showStart = false
    @State private var requestID = UUID().uuidString
    @State private var startBinding: BrokerConnectionBinding?
    var body: some View {
        SubScreen(title: "Automated strategies", refresh: { await request("state", body: EmptyWorkspaceRequest()) }) {
            HStack { StatusBadge("Paper", tone: .paper); Spacer(); if busy { ProgressView() } }
            if let snapshot {
                let proto = snapshot.runs.first?.protocol
                SectionCard(footer: proto.map { "Each strategy starts with \(workspaceMoney($0.initial_cash)) of paper money, buys at most \($0.entry_fraction) of equity or \(workspaceMoney($0.max_entry)) per entry, and pays \($0.cost_bps) bps per side." } ?? "Three rule-based strategies trade SPY with separate paper balances.") {
                    schedulerRow(snapshot)
                    HStack(spacing: Spacing.l) {
                        MetricTile(label: "Active", value: "\(snapshot.runs.filter { $0.active }.count) of \(snapshot.runs.count)")
                        MetricTile(label: "Simulated fills", value: "\(snapshot.runs.reduce(0) { $0 + $1.fills })")
                    }
                    if snapshot.runs.contains(where: \.active) {
                        Button("Stop all strategies") { Task { await request("pause", body: ["id": "all"]) } }.buttonStyle(SecondaryButtonStyle()).disabled(busy)
                    } else {
                        Button("Start strategies") {
                            startBinding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
                            showStart = true
                        }.buttonStyle(PrimaryButtonStyle()).disabled(busy)
                    }
                }
                ForEach(snapshot.runs) { run in
                    SectionCard {
                        HStack { Text(run.title).font(.headline); Spacer(); StatusBadge(run.statusLabel, tone: run.active ? .positive : .warning) }
                        HStack(spacing: Spacing.l) {
                            MetricTile(label: "Value", value: workspaceMoney(run.equity))
                            MetricTile(label: "Realised", value: workspaceMoney(run.realized, signed: true), tone: deltaTone(run.realized))
                            MetricTile(label: "Drawdown", value: run.drawdownPercent)
                        }
                        Text("\(run.observations) sessions · \(run.fills) fills · \(run.quantity) shares").font(.caption).foregroundStyle(Theme.textSecondary)
                        NavigationLink { AutomatedPaperRunDetail(run: run, stop: run.active ? { Task { await request("pause", body: ["id": run.id]) } } : nil) } label: {
                            Text("Details").font(.footnote.weight(.semibold))
                        }
                    }
                }
                if snapshot.runs.isEmpty { EmptyState(title: "Nothing running", message: "Start the three strategies to begin recording forward paper results.", icon: "clock.arrow.circlepath") }
                Footnote("Signals are computed after 8:15 PM New York time and filled at the next session’s open. Your Mac must stay on; this phone can be closed. Stopping keeps recorded holdings without new marks and does not sell them.")
            } else if !busy {
                EmptyState(title: "Not loaded", message: "Pull down to load the strategies.", icon: "arrow.down")
            }
            OutcomeNotice(text: message, kind: .error)
        }
        .task { if snapshot == nil { await request("state", body: EmptyWorkspaceRequest()) } }
        .onConnectionChange(store) { clearConnection() }
        .confirmationDialog("Start the three paper strategies?", isPresented: $showStart, titleVisibility: .visible) {
            Button("Start paper strategies") {
                guard let binding = startBinding, binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else {
                    message = "Connection changed. Refresh and review again."; return
                }
                Task { await request("start", body: AutomatedPaperStart(client_id: requestID)) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Trend, breakout and mean reversion each trade SPY with their own paper balance. A 10% drawdown or missing data stops a strategy. Future simulated fills run without individual confirmation. No real money or broker orders are involved.")
        }
    }
    @ViewBuilder private func schedulerRow(_ snapshot: AutomatedPaperSnapshot) -> some View {
        if let heartbeat = snapshot.worker_checked_at {
            let stale = Date().timeIntervalSince1970 - heartbeat > 180
            HStack(spacing: Spacing.s) {
                StatusBadge(stale ? "Scheduler not running" : "Scheduler running", tone: stale ? .warning : .positive)
                Text("checked \(relativeTime(heartbeat))").font(.caption).foregroundStyle(Theme.textTertiary)
            }
            if stale { InlineNotice(kind: .warning, message: "Your Mac may be asleep or the gateway stopped. No new decisions are recorded until it runs again.") }
        } else {
            StatusBadge("Scheduler has not run", tone: .warning)
        }
    }
    private func deltaTone(_ value: String) -> Tone {
        guard let d = strictDecimal(value) else { return .neutral }
        return d > 0 ? .positive : d < 0 ? .negative : .neutral
    }
    private func clearConnection() {
        snapshot = nil; showStart = false; startBinding = nil; requestID = UUID().uuidString; message = ""
    }
    private func request<B: Encodable & Sendable>(_ action: String, body: B) async {
        guard !busy else { return }
        busy = true; message = ""
        defer { busy = false }
        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        do {
            let result: AutomatedPaperSnapshot = try await WorkspaceAPI.request("v1/paper/automation/" + action,
                body: body, endpoint: binding.endpoint, token: binding.token)
            guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
            guard result.mode == "automated_paper", result.version == "prospective-paper-v1" else {
                throw WorkspaceError(message: "Your server needs updating to use this screen.")
            }
            snapshot = result
            if action == "start" { requestID = UUID().uuidString }
        } catch {
            if binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription }
        }
    }
}

struct AutomatedPaperRunDetail: View {
    let run: AutomatedPaperRun
    var stop: (() -> Void)?
    var body: some View {
        SubScreen(title: run.title) {
            HStack { StatusBadge(run.statusLabel, tone: run.active ? .positive : .warning); Spacer() }
            if !run.reason.isEmpty { Footnote(run.reason) }
            SectionCard(title: "Position") {
                DetailRow("Value", workspaceMoney(run.equity))
                DetailRow("Cash", workspaceMoney(run.cash))
                DetailRow("Shares", run.quantity)
                DetailRow("Realised", workspaceMoney(run.realized, signed: true))
                DetailRow("Modelled costs", workspaceMoney(run.costs))
                DetailRow("Max drawdown", run.drawdownPercent)
                if let pending = run.pending {
                    DetailRow("Next decision", "\(pending.long ? "Long" : "Cash") for \(pending.session)")
                } else if run.active {
                    DetailRow("Next observation", run.next_session)
                }
                DetailRow("Last session", run.last_session ?? "None yet")
                DetailRow("Started", gatewayDate(run.created_at))
            }
            SectionCard(title: "Rule", footer: "Protocol \(run.protocol.version) · \(run.protocol.schedule)") {
                Text(run.protocol.rule).font(.footnote).foregroundStyle(Theme.textSecondary)
            }
            SectionCard(title: "History") {
                if run.events.isEmpty {
                    EmptyState(title: "No events yet", message: "Decisions and fills are listed here as they are recorded.")
                } else {
                    ForEach(run.events) { event in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(gatewayDate(event.at)).font(.caption).foregroundStyle(Theme.textTertiary)
                            Text(event.message).font(.footnote).textSelection(.enabled)
                        }.padding(.vertical, Spacing.xs)
                    }
                }
            }
            if let stop { Button("Stop this strategy") { stop() }.buttonStyle(SecondaryButtonStyle()) }
        }
    }
}
