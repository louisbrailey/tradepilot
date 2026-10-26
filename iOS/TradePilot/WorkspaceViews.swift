import SwiftUI
import TradeCore

struct EmptyWorkspaceRequest: Encodable, Sendable {}
struct PaperApproval: Encodable, Sendable { let id: String; let token: String; let approved = true }
struct PaperIntentRequest: Encodable, Sendable {
    let symbol: String; let side: String; let quantity: String; let client_id: String
}
struct WorkspaceError: LocalizedError { let message: String; var errorDescription: String? { message } }

enum WorkspaceAPI {
    static func request<T: Decodable & Sendable, B: Encodable & Sendable>(_ path: String, body: B,
        endpoint: String, token: String) async throws -> T {
        guard token.count >= 32 else { throw WorkspaceError(message: "Save your private gateway connection in Accounts first.") }
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
            throw WorkspaceError(message: error ?? "Gateway request failed. Refresh saved state before trying another order.")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}

struct PaperPosition: Decodable, Sendable, Identifiable {
    var id: String { symbol }
    let symbol: String; let quantity: String; let cost_basis: String; let market_value: String
    let unrealized_pnl: String; let reference_as_of: Double
}
struct PaperReview: Decodable, Sendable, Identifiable {
    let id: String; let token: String?; let mode: String; let status: String
    let symbol: String; let side: String; let quantity: String
    let reference_price: String; let reference_as_of: Double; let source: String
    let fill_price: String; let notional: String; let cash_change: String
    let expires_at: Double; let label: String
}
struct PaperEventDetails: Decodable, Sendable {
    let text: String?; let symbol: String?; let side: String?; let quantity: String?
}
struct PaperEvent: Decodable, Sendable, Identifiable {
    let id: Int; let kind: String; let at: Double; let data: PaperEventDetails
    var summary: String { data.text ?? [data.side, data.quantity, data.symbol].compactMap { $0 }.joined(separator: " ") }
}
struct PaperSnapshot: Decodable, Sendable {
    let mode: String; let cash: String; let equity: String; let realized_pnl: String
    let max_drawdown: String; let mark_to_market_notice: String
    let positions: [PaperPosition]; let reviews: [PaperReview]; let orders: [PaperReview]; let journal: [PaperEvent]
}
func workspaceMoney(_ value: String) -> String {
    guard let number = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")), !number.isNaN else { return "Unavailable" }
    return money(number)
}
func workspaceDate(_ value: Double) -> String { Date(timeIntervalSince1970: value).formatted(date: .abbreviated, time: .shortened) }

enum PaperValidation {
    static func decimal(_ text: String) -> Decimal? {
        guard text.count <= 64, text.range(of: "^-?[0-9]+(?:\\.[0-9]+)?$", options: .regularExpression) != nil,
              let value = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")), !value.isNaN else { return nil }
        return value
    }
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

struct PaperTradingView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: PaperSnapshot?
    @State private var review: PaperReview?
    @State private var reviewBinding: BrokerConnectionBinding?
    @State private var symbol = "AAPL"
    @State private var side = "buy"
    @State private var quantity = "1"
    @State private var command = ""
    @State private var note = ""
    @State private var status = ""
    @State private var busy = false
    @State private var requestID = UUID().uuidString
    var body: some View {
        Screen(title: "Paper trading", isDemo: false) {
            Text("PAPER · NO REAL MONEY").font(.caption.bold()).foregroundStyle(Palette.mint)
            Text("A persistent $10,000 practice account. Orders simulate a fill at the last completed daily close with 10 bps slippage. Prices are delayed; these are not broker fills or proof of achievable returns.").font(.subheadline).foregroundStyle(Palette.muted)
            HStack {
                Button("Refresh account") { load() }
                Spacer()
                Button("Update valuations") { load(mark: true) }
            }.disabled(busy)
            if let snapshot {
                VStack(alignment: .leading, spacing: 10) {
                    LabeledContent("Paper equity", value: workspaceMoney(snapshot.equity))
                    LabeledContent("Cash", value: workspaceMoney(snapshot.cash))
                    LabeledContent("Realized result", value: workspaceMoney(snapshot.realized_pnl))
                    Text(snapshot.mark_to_market_notice).font(.caption).foregroundStyle(Palette.muted)
                    Text("Valuations update on request; no background trading.").font(.caption).foregroundStyle(Palette.muted)
                }.card()
                if !snapshot.positions.isEmpty {
                    ScrollView(.horizontal) {
                        Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 12) {
                            GridRow { Text("Symbol"); Text("Units"); Text("Value"); Text("Unrealized"); Text("Reference date") }.font(.caption.bold())
                            ForEach(snapshot.positions) { p in
                                GridRow { Text(p.symbol); Text(p.quantity); Text(workspaceMoney(p.market_value)); Text(workspaceMoney(p.unrealized_pnl)); Text(workspaceDate(p.reference_as_of)) }.font(.caption.monospacedDigit())
                            }
                        }
                    }.card()
                }
            }
            VStack(alignment: .leading, spacing: 12) {
                Text("Prepare a paper order").font(.headline)
                TextField("Try: buy 3 shares of AAPL", text: $command)
                Button("Use command in form") {
                    switch DemoAssistant.parse(command) {
                    case .trade(let intent): symbol = intent.symbol; side = intent.side.rawValue; quantity = units(intent.quantity); status = "Check the form, then request a paper review."
                    default: status = "Use one explicit buy or sell with a quantity and stock symbol."
                    }
                }
                TextField("US stock ticker", text: $symbol).phoneSymbolInput()
                Picker("Side", selection: $side) { Text("Buy").tag("buy"); Text("Sell").tag("sell") }.pickerStyle(.segmented)
                TextField("Shares", text: $quantity).phoneSymbolInput()
                Button("Review paper order") { prepare() }.buttonStyle(MintButton()).disabled(busy)
            }.card()
            if !status.isEmpty { Text(status).font(.caption).textSelection(.enabled) }
            VStack(alignment: .leading, spacing: 12) {
                Text("Trade journal").font(.headline)
                TextField("Thesis, observation or lesson", text: $note, axis: .vertical).lineLimit(2...5)
                Button("Save reflection") { saveNote() }.disabled(busy || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if let snapshot {
                    ForEach(snapshot.journal.prefix(30)) { event in
                        VStack(alignment: .leading, spacing: 4) {
                            Text("\(event.kind.capitalized) · \(workspaceDate(event.at))").font(.caption.bold())
                            if !event.summary.isEmpty { Text(event.summary).font(.caption) }
                        }
                    }
                }
            }.card()
        }
        .task { if snapshot == nil { load() } }
        .onChange(of: symbol) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onChange(of: side) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onChange(of: quantity) { _, _ in if review == nil { requestID = UUID().uuidString } }
        .onChange(of: store.aiEndpoint) { _, _ in clearConnection() }
        .onChange(of: store.aiToken) { _, _ in clearConnection() }
        // A dismissed or confirmed review never reuses its client_id for a later request.
        .sheet(item: $review, onDismiss: { requestID = UUID().uuidString }) { proposed in
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Text("Confirm paper order").font(.title.bold())
                        Text("\(proposed.side.uppercased()) \(proposed.quantity) \(proposed.symbol)").font(.title2.monospaced())
                        LabeledContent("Simulated unit price", value: workspaceMoney(proposed.fill_price))
                        LabeledContent("Cash change", value: workspaceMoney(proposed.cash_change))
                        Text("Reference: \(workspaceMoney(proposed.reference_price)) · \(workspaceDate(proposed.reference_as_of))").font(.caption)
                        Text(proposed.source).font(.caption)
                        Text("This changes only your paper account. The reference is delayed and may differ substantially from a current executable price.").foregroundStyle(Palette.muted)
                        Button("Confirm paper order") { confirm(proposed) }.buttonStyle(MintButton()).disabled(busy)
                        Button("Dismiss review") { review = nil; requestID = UUID().uuidString }.disabled(busy)
                        Text(status).font(.caption)
                    }.padding(24)
                }.background(Palette.background)
            }.interactiveDismissDisabled(busy)
        }
    }
    private func binding() -> BrokerConnectionBinding { BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken) }
    private func current(_ b: BrokerConnectionBinding) -> Bool { b.matches(endpoint: store.aiEndpoint, token: store.aiToken) }
    private func clearConnection() { snapshot = nil; review = nil; reviewBinding = nil; status = "Connection changed. Refresh the paper account."; requestID = UUID().uuidString }
    private func load(mark: Bool = false) {
        guard !busy else { return }; busy = true
        let b = binding()
        Task { defer { busy = false }
            do {
                let result: PaperSnapshot = try await WorkspaceAPI.request(mark ? "v1/paper/mark" : "v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                guard current(b), result.mode == "paper" else { return }
                snapshot = result; status = mark ? "Saved updated paper valuations." : "Paper account loaded."
            } catch { if current(b) { status = error.localizedDescription } }
        }
    }
    private func prepare() {
        guard !busy else { return }; busy = true
        let b = binding()
        let intent = PaperIntentRequest(symbol: symbol.trimmingCharacters(in: .whitespacesAndNewlines).uppercased(), side: side, quantity: quantity, client_id: requestID)
        Task { defer { busy = false }
            do {
                let result: PaperReview = try await WorkspaceAPI.request("v1/paper/review", body: intent, endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                guard PaperValidation.reviewMatches(result, request: intent) else { throw WorkspaceError(message: "Paper review did not match the requested terms. Refresh saved state.") }
                review = result; reviewBinding = b; status = "Nothing changes until you confirm."
            } catch { if current(b) { status = error.localizedDescription; requestID = UUID().uuidString } }
        }
    }
    private func confirm(_ proposed: PaperReview) {
        guard !busy, let b = reviewBinding, current(b), let token = proposed.token else { return }
        busy = true; requestID = UUID().uuidString  // Retries use proposed.id/token, not the form's client_id.
        Task { defer { busy = false }
            do {
                let receipt: PaperReview = try await WorkspaceAPI.request("v1/paper/confirm", body: PaperApproval(id: proposed.id, token: token), endpoint: b.endpoint, token: b.token)
                guard current(b) else { return }
                guard PaperValidation.receiptMatches(receipt, review: proposed) else { throw WorkspaceError(message: "Unexpected receipt. Refresh the paper account before another order.") }
                store.journal.append(kind: "paper_fill", text: "Paper \(receipt.side) \(receipt.quantity) \(receipt.symbol) at \(receipt.fill_price). Delayed reference simulation.", strategy: store.strategyID, accountID: "paper", holdings: [], mode: "paper")
                review = nil; requestID = UUID().uuidString
                let result: PaperSnapshot = try await WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                if current(b) { snapshot = result; status = "Paper order filled and saved. No real order was sent." }
            } catch { if current(b) { status = "\(error.localizedDescription) Retry this same confirmation or refresh the account; do not assume failure." } }
        }
    }
    private func saveNote() {
        guard !busy else { return }; busy = true
        let b = binding(), text = note
        Task { defer { busy = false }
            do {
                let _: PaperEvent = try await WorkspaceAPI.request("v1/paper/note", body: ["text": text], endpoint: b.endpoint, token: b.token)
                let result: PaperSnapshot = try await WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                if current(b) { snapshot = result; note = ""; status = "Reflection saved." }
            } catch { if current(b) { status = error.localizedDescription } }
        }
    }
}

struct CoinbaseAccount: Decodable, Sendable, Identifiable {
    let id: String; let currency: String; let name: String; let available: String; let hold: String; let total: String
}
struct CoinbaseSnapshot: Decodable, Sendable {
    let broker: String; let read_only: Bool; let as_of: Double; let accounts: [CoinbaseAccount]
}
struct CoinbaseView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: CoinbaseSnapshot?
    @State private var message = ""
    @State private var busy = false
    var body: some View {
        Screen(title: "Coinbase", isDemo: false) {
            Text("READ-ONLY ACCOUNT CONNECTION").font(.caption.bold()).foregroundStyle(Palette.mint)
            Text("Balances come from Coinbase Advanced Trade through your private gateway. Configure a Coinbase ECDSA API key on the server; never paste its private key into this app. No trading or transfers are enabled here.").font(.subheadline).foregroundStyle(Palette.muted)
            Button(busy ? "Loading…" : "Load Coinbase accounts") { refresh() }.buttonStyle(MintButton()).disabled(busy)
            if let snapshot {
                Text("Updated \(workspaceDate(snapshot.as_of))").font(.caption)
                if snapshot.accounts.isEmpty { Text("No accounts returned by Coinbase.") }
                ScrollView(.horizontal) {
                    Grid(alignment: .leading, horizontalSpacing: 20, verticalSpacing: 14) {
                        GridRow { Text("Asset"); Text("Available"); Text("On hold"); Text("Total") }.font(.caption.bold())
                        ForEach(snapshot.accounts) { a in
                            GridRow { Text(a.currency); Text(a.available); Text(a.hold); Text(a.total) }.font(.caption.monospacedDigit())
                        }
                    }
                }.card()
                Text("Amounts are in each asset's own units. They are not combined into a USD portfolio value.").font(.caption).foregroundStyle(Palette.muted)
            }
            Text(message).font(.caption).textSelection(.enabled)
        }
        .onChange(of: store.aiEndpoint) { _, _ in snapshot = nil; message = "Connection changed; reload accounts." }
        .onChange(of: store.aiToken) { _, _ in snapshot = nil; message = "Connection changed; reload accounts." }
    }
    private func refresh() {
        busy = true; snapshot = nil
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        Task { defer { busy = false }
            do {
                let result: CoinbaseSnapshot = try await WorkspaceAPI.request("v1/coinbase/state", body: EmptyWorkspaceRequest(), endpoint: b.endpoint, token: b.token)
                guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
                guard result.broker == "coinbase", result.read_only else { throw WorkspaceError(message: "Unexpected Coinbase response.") }
                snapshot = result; message = ""
            } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription } }
        }
    }
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
struct StrategyComparisonView: View {
    @Environment(AppStore.self) private var store
    @State private var ticker = "AAPL"
    @State private var result: StrategyComparison?
    @State private var message = ""
    @State private var busy = false
    var body: some View {
        Screen(title: "Strategy lab", isDemo: false) {
            Text("EXPLORATORY · DAILY STOCK DATA").font(.caption.bold()).foregroundStyle(Palette.mint)
            Text("Compare fixed trend, breakout and mean-reversion rules with costs. Historical results are research, not a recommendation or permission to trade.").font(.subheadline).foregroundStyle(Palette.muted)
            TextField("US stock ticker", text: $ticker).phoneSymbolInput()
            Button(busy ? "Evaluating…" : "Compare strategies") { compare() }.buttonStyle(MintButton()).disabled(busy)
            Text(message).font(.caption)
            if let result {
                Text(result.scope).font(.caption).foregroundStyle(Palette.muted)
                ForEach(result.strategies) { strategy in
                    VStack(alignment: .leading, spacing: 12) {
                        Text(strategy.strategy.replacingOccurrences(of: "_", with: " ").capitalized).font(.headline)
                        Text(strategy.rule).font(.caption)
                        Text("Validation · 10 bps per side").font(.caption.bold())
                        metrics(strategy.validation.baseline)
                        Text("Final period · 10 bps per side").font(.caption.bold())
                        metrics(strategy.final.baseline)
                        Text("Final period cost sensitivity").font(.caption.bold())
                        ForEach(["0", "10", "25", "50"], id: \.self) { cost in
                            if let m = strategy.final.cost_scenarios[cost] {
                                LabeledContent("\(cost) bps per side", value: String(format: "%.2f%%", m.return_pct)).font(.caption.monospacedDigit())
                            }
                        }
                    }.card()
                }
            }
        }
        .onChange(of: store.aiEndpoint) { _, _ in result = nil }
        .onChange(of: store.aiToken) { _, _ in result = nil }
    }
    @ViewBuilder private func metrics(_ m: StrategyMetrics) -> some View {
        LabeledContent("Strategy / benchmark", value: String(format: "%.2f%% / %.2f%%", m.return_pct, m.benchmark_price_return_pct)).font(.caption.monospacedDigit())
        LabeledContent("Maximum drawdown / fills", value: String(format: "%.2f%% / %d", m.max_drawdown_pct, m.fills)).font(.caption.monospacedDigit())
    }
    private func compare() {
        busy = true; result = nil
        let b = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken), symbol = ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        Task { defer { busy = false }
            do {
                let report: StrategyComparison = try await WorkspaceAPI.request("v1/strategies", body: ["ticker": symbol], endpoint: b.endpoint, token: b.token)
                guard b.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
                guard report.ticker == symbol, report.evidence == "exploratory_previously_observed" else { throw WorkspaceError(message: "Unexpected evaluation provenance.") }
                result = report; message = "\(symbol) · independent portfolios per period; no automatic strategy selection."
            } catch { if b.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription } }
        }
    }
}
