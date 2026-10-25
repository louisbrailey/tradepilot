import SwiftUI
import TradeCore

@main
struct TradePilotApp: App {
    @State private var store = AppStore()
    var body: some Scene {
        WindowGroup { landing.environment(store).preferredColorScheme(.dark) }
    }
    // Debug-only screen selection for simulator visual QA; no account/action overrides.
    @ViewBuilder private var landing: some View {
        #if DEBUG
        let screen = ProcessInfo.processInfo.environment["TRADEPILOT_SCREEN"]
        if screen == "kronos" { KronosView() }
        else if screen == "paper" { PaperTradingView() }
        else if screen == "strategies" { StrategyComparisonView() }
        else if screen == "coinbase" { CoinbaseView() }
        else { RootView() }
        #else
        RootView()
        #endif
    }
}

enum Palette {
    static let background = Color(red: 0.035, green: 0.055, blue: 0.065)
    static let panel = Color(red: 0.075, green: 0.10, blue: 0.115)
    static let mint = Color(red: 0.64, green: 0.95, blue: 0.77)
    static let muted = Color(red: 0.59, green: 0.66, blue: 0.68)
}

func money(_ number: Decimal) -> String {
    let f = NumberFormatter(); f.numberStyle = .currency; f.currencyCode = "USD"; f.locale = Locale(identifier: "en_US")
    return f.string(from: number as NSDecimalNumber) ?? "—"
}
func units(_ number: Decimal) -> String { NSDecimalNumber(decimal: number).stringValue }

struct ChatMessage: Identifiable {
    let id = UUID()
    let user: Bool
    let text: String
    var table = false
}

@MainActor @Observable
final class AppStore {
    init() {
        do { try ConnectionSettings.importPairing(); aiEndpoint = ConnectionSettings.endpoint; aiToken = ConnectionSettings.token }
        catch { connectionError = "Device pairing failed. " + error.localizedDescription }
    }
    var engine = DemoEngine()
    var journal = JournalStore()
    var strategyID = "long_term"
    var researchTicker = "AAPL"
    var useMarketData = false
    var useJournalContext = false
    var tab = 0
    var accountID = "all"
    var input = ""
    var review: TradePreview?
    var rejectNext = false
    var aiEnabled = false
    var aiEndpoint = ConnectionSettings.endpoint
    var aiToken = ConnectionSettings.token
    var connectionError: String?
    var busy = false
    var messages = [ChatMessage(user: false, text: "Your portfolio, in one conversation. Ask to see your holdings or try “sell 3 shares of AAPL”. I’ll prepare a review for you to confirm.\n\nThis prototype uses sample data and a limited command parser. Optional AI can be configured in Accounts. Open Accounts → Webull for your separately configured broker connection.")] {
        didSet {
            for message in messages.dropFirst(oldValue.count) { record(message.user ? "request" : "assistant", message.text) }
        }
    }
    var visibleHoldings: [Holding] { engine.holdings.filter { accountID == "all" || $0.accountID == accountID } }

    func record(_ kind: String, _ text: String, reference: String? = nil, order: Order? = nil) {
        journal.append(kind: kind, text: text, strategy: strategyID, accountID: order?.preview.accountID ?? accountID, reference: reference, holdings: engine.holdings, order: order)
    }

    func send(_ prompt: String? = nil) {
        let text = (prompt ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !busy else { return }
        input = ""
        messages.append(ChatMessage(user: true, text: text))
        if aiEnabled {
            askAI(text)
            return
        }
        switch DemoAssistant.parse(text) {
        case .portfolio:
            messages.append(ChatMessage(user: false, text: "Here are your current demo holdings for the selected account filter. Swipe the table sideways for cost basis, value, gain and allocation. All prices are fixed sample values in USD.", table: true))
        case .trade(let intent):
            do {
                review = try engine.preview(intent, accountID: accountID == "all" ? nil : accountID)
                if let review { record("proposal", "Review \(intent.side.rawValue) \(units(intent.quantity)) \(intent.symbol) in \(review.accountID)", reference: review.id.uuidString) }
                messages.append(ChatMessage(user: false, text: "Review your proposed \(intent.side.rawValue) of \(units(intent.quantity)) \(intent.symbol). Nothing is submitted until you confirm."))
            } catch { messages.append(ChatMessage(user: false, text: error.localizedDescription)) }
        case .help:
            messages.append(ChatMessage(user: false, text: "In this demo, try “show my portfolio”, “sell 3 shares of AAPL”, or “buy 0.01 BTC”. Select an account above if you hold the same asset in several places. Conditional orders, recommendations and general questions need the future AI service; I haven’t created an order."))
        }
    }

    private func askAI(_ text: String) {
        guard !busy else { return }
        busy = true
        let selectedAccount = accountID
        let snapshot = visibleHoldings
        Task {
            defer { busy = false }
            do {
                let result = try await AIService.ask(endpoint: aiEndpoint, token: aiToken, prompt: text,
                    holdings: snapshot, accounts: engine.accounts.filter { selectedAccount == "all" || $0.id == selectedAccount }, selectedAccount: selectedAccount, strategy: strategyID, researchTicker: useMarketData ? researchTicker : nil,
                    journal: useJournalContext ? journal.entries.filter { $0.mode == "demo" }.prefix(30).map { ["kind": $0.kind, "text": String($0.text.prefix(1000)), "strategy": $0.strategy, "timestamp": $0.timestamp.ISO8601Format(), "mode": $0.mode, "session": $0.sessionID.uuidString] } : [])
                if result.kind == "trade" {
                    guard let rawSide = result.side, let side = Side(rawValue: rawSide),
                          let q = result.quantity, let quantity = Decimal(string: q, locale: Locale(identifier: "en_US_POSIX")),
                          let symbol = result.symbol else { throw TradeError.invalidQuantity }
                    // The model cannot submit or confirm; this uses the same independent demo engine.
                    review = try engine.preview(TradeIntent(side: side, quantity: quantity, symbol: symbol), accountID: selectedAccount == "all" ? nil : selectedAccount)
                    if let review { record("proposal", "AI proposal: \(review.side.rawValue) \(units(review.quantity)) \(review.symbol) in \(review.accountID)", reference: review.id.uuidString) }
                    messages.append(ChatMessage(user: false, text: "The AI proposed a demo trade. Check the account, side and quantity in the review. No order has been submitted."))
                } else {
                    messages.append(ChatMessage(user: false, text: result.message, table: result.kind == "portfolio"))
                }
            } catch {
                messages.append(ChatMessage(user: false, text: "No order created. \(error.localizedDescription)"))
            }
        }
    }

    func confirm(_ preview: TradePreview) {
        record("approval", "Confirmed demo \(preview.side.rawValue) \(units(preview.quantity)) \(preview.symbol)", reference: preview.id.uuidString)
        guard journal.error == nil else {
            engine.cancel(preview.id)
            messages.append(ChatMessage(user: false, text: "No order submitted because the journal could not save the approval. Check Research → Journal for details."))
            review = nil
            return
        }
        do {
            let result = try engine.confirm(preview.id, approved: true, simulateRejection: rejectNext)
            record("outcome", "\(result.status.rawValue): \(result.detail)", reference: result.preview.id.uuidString, order: result)
            rejectNext = false
            messages.append(ChatMessage(user: false, text: "\(result.status == .filled ? "Demo order filled" : "Demo order rejected"): \(result.preview.side.rawValue.capitalized) \(units(result.preview.quantity)) \(result.preview.symbol).\n\(result.detail)\nReceipt: \(result.id.uuidString.prefix(8))"))
        } catch {
            messages.append(ChatMessage(user: false, text: "Order not submitted. \(error.localizedDescription)"))
        }
        review = nil
    }

    func cancel(_ preview: TradePreview) {
        record("cancel", "Review cancelled. No order submitted.", reference: preview.id.uuidString)
        engine.cancel(preview.id)
        messages.append(ChatMessage(user: false, text: "Trade review dismissed. No order was submitted."))
        review = nil
    }
}

struct RootView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        @Bindable var store = store
        TabView(selection: $store.tab) {
            DashboardView().tabItem { Label("Overview", systemImage: "square.grid.2x2") }.tag(0)
            AssistantView().tabItem { Label("Assistant", systemImage: "sparkles") }.tag(1)
            HoldingsView().tabItem { Label("Holdings", systemImage: "chart.bar.xaxis") }.tag(2)
            JournalView().tabItem { Label("Research", systemImage: "book.closed") }.tag(4)
            AccountsView().tabItem { Label("Accounts", systemImage: "building.columns") }.tag(3)
        }
        .tint(Palette.mint)
        .safeAreaInset(edge: .top) {
            if store.journal.error != nil { Text("Journal unavailable · inspect Research → Journal").font(.caption).foregroundStyle(.orange).padding(8) }
        }
        .sheet(item: $store.review) { preview in ReviewView(preview: preview).interactiveDismissDisabled() }
    }
}

struct Screen<Content: View>: View {
    let title: String
    var isDemo = true
    @ViewBuilder var content: Content
    var body: some View {
        NavigationStack {
            ScrollView { VStack(alignment: .leading, spacing: 24) { if isDemo { DemoBanner() }; content }.padding(20) }
                .background(Palette.background)
                .navigationTitle(title)
                .phoneNavigationTheme()
        }
    }
}

struct DemoBanner: View {
    var body: some View {
        HStack(spacing: 8) {
            Circle().fill(Palette.mint).frame(width: 6, height: 6)
            Text("DEMO WORKSPACE").font(.system(size: 10, weight: .bold, design: .monospaced)).tracking(1.5)
            Spacer()
            Text("No real money").font(.caption).foregroundStyle(Palette.muted)
        }.padding(.vertical, 8)
    }
}

struct DashboardView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        Screen(title: "TradePilot") {
            VStack(alignment: .leading, spacing: 15) {
                Text("EVERY ACCOUNT. ONE VIEW.").font(.system(size: 10, weight: .semibold, design: .monospaced)).tracking(2).foregroundStyle(Palette.muted)
                Text(money(store.engine.totalValue)).font(.system(size: 43, weight: .medium, design: .rounded)).minimumScaleFactor(0.6).lineLimit(1)
                Label("\(money(store.engine.totalGain)) unrealized gain", systemImage: "arrow.up.right").font(.subheadline).foregroundStyle(Palette.mint)
                Divider().overlay(Palette.muted.opacity(0.2))
                HStack {
                    VStack(alignment: .leading, spacing: 5) { Text("Available demo cash").font(.caption).foregroundStyle(Palette.muted); Text(money(store.engine.accounts.reduce(0) { $0 + $1.cash })).font(.headline) }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 5) { Text("Accounts").font(.caption).foregroundStyle(Palette.muted); Text("3 sample accounts").font(.headline) }
                }
            }.card()
            Button { store.tab = 1 } label: {
                HStack(spacing: 14) {
                    Image(systemName: "sparkles").font(.title2)
                    VStack(alignment: .leading, spacing: 5) { Text("What would you like to do?").font(.headline); Text("Explore your portfolio. Prepare a trade.").font(.caption).opacity(0.7) }
                    Spacer(); Image(systemName: "arrow.up.right")
                }.padding(20).foregroundStyle(Palette.background).background(Palette.mint, in: RoundedRectangle(cornerRadius: 22))
            }.buttonStyle(.plain)
            HStack { Text("Your assets").font(.title3.bold()); Spacer(); Button("View table") { store.tab = 2 }.font(.caption.bold()) }
            VStack(spacing: 20) {
                ForEach(store.engine.holdings.filter { $0.quantity > 0 }.prefix(5)) { h in AssetRow(holding: h) }
            }.card()
            Text("Activity").font(.title3.bold())
            if store.engine.orders.isEmpty {
                VStack(alignment: .leading, spacing: 8) { Label("Your next move starts here", systemImage: "clock"); Text("Confirmed demo orders and their outcomes will appear here. Session data resets when the app restarts.").font(.caption).foregroundStyle(Palette.muted) }.card()
            } else {
                ForEach(store.engine.orders) { order in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack { Text("\(order.preview.side.rawValue.capitalized) \(units(order.preview.quantity)) \(order.preview.symbol)").bold(); Spacer(); Text(order.status.rawValue.capitalized).font(.caption.bold()).foregroundStyle(order.status == .filled ? Palette.mint : .orange) }
                        Text(store.engine.accountName(order.preview.accountID)).font(.caption).foregroundStyle(Palette.muted)
                        Text(order.detail).font(.caption)
                        Text("\(order.createdAt.formatted(date: .abbreviated, time: .shortened)) · \(order.id.uuidString.prefix(8))").font(.caption2).foregroundStyle(Palette.muted)
                    }.card()
                }
            }
        }
    }
}

struct AssetRow: View {
    let holding: Holding
    var body: some View {
        HStack(spacing: 12) {
            Text(String(holding.symbol.prefix(1))).font(.headline).frame(width: 42, height: 42).background(Palette.mint.opacity(0.10), in: RoundedRectangle(cornerRadius: 13)).foregroundStyle(Palette.mint)
            VStack(alignment: .leading, spacing: 4) { Text(holding.symbol).font(.subheadline.bold()); Text("\(units(holding.quantity)) units · \(holding.kind)").font(.caption).foregroundStyle(Palette.muted) }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) { Text(money(holding.value)).font(.subheadline.bold()); Text(money(holding.gain)).font(.caption).foregroundStyle(holding.gain >= 0 ? Palette.mint : .orange) }
        }
    }
}

struct AccountPicker: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        @Bindable var store = store
        HStack {
            Image(systemName: "line.3.horizontal.decrease").foregroundStyle(Palette.muted)
            Picker("Account", selection: $store.accountID) {
                Text("All demo accounts").tag("all")
                ForEach(store.engine.accounts) { a in Text(a.name).tag(a.id) }
            }.tint(Palette.mint)
            Spacer(minLength: 0)
        }
    }
}

struct HoldingsView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        Screen(title: "Holdings") {
            AccountPicker()
            HStack { Text("Portfolio table").font(.title3.bold()); Spacer(); Text("USD · SAMPLE").font(.caption2.monospaced()).foregroundStyle(Palette.muted) }
            PortfolioTable()
            Text("Swipe sideways to explore all columns. Allocation is based on the selected holdings, excluding cash. Cost basis uses a simplified average; tax lots and realized gains are not modeled.").font(.caption).foregroundStyle(Palette.muted)
            Button { store.tab = 1; store.send("Show my portfolio") } label: { Label("Ask about these holdings", systemImage: "sparkles").frame(maxWidth: .infinity) }.buttonStyle(MintButton())
        }
    }
}

struct PortfolioTable: View {
    @Environment(AppStore.self) private var store
    private let columns: [(String, CGFloat)] = [("ASSET", 90), ("ACCOUNT", 220), ("QUANTITY", 100), ("PRICE", 110), ("VALUE", 120), ("AVG COST", 110), ("COST BASIS", 120), ("UNREALIZED", 120), ("WEIGHT", 80)]
    var body: some View {
        ScrollView(.horizontal) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) { ForEach(columns.indices, id: \.self) { i in Text(columns[i].0).font(.system(size: 10, weight: .bold, design: .monospaced)).tracking(0.8).frame(width: columns[i].1, alignment: .leading) } }.foregroundStyle(Palette.muted).padding(.vertical, 15)
                ForEach(store.visibleHoldings) { h in
                    Divider()
                    HStack(spacing: 0) {
                        cell(h.symbol, 90, accent: true)
                        cell(store.engine.accountName(h.accountID), 220)
                        cell(units(h.quantity), 100)
                        cell(money(h.price), 110)
                        cell(money(h.value), 120)
                        cell(money(h.costPerUnit), 110)
                        cell(money(h.costPerUnit * h.quantity), 120)
                        cell(money(h.gain), 120, accent: h.gain >= 0)
                        cell(weight(h), 80)
                    }.padding(.vertical, 17)
                }
            }.padding(.horizontal, 16)
        }.background(Palette.panel, in: RoundedRectangle(cornerRadius: 20))
    }
    func cell(_ text: String, _ width: CGFloat, accent: Bool = false) -> some View { Text(text).font(.system(size: 13, weight: accent ? .semibold : .regular)).monospacedDigit().foregroundStyle(accent ? Palette.mint : .white).frame(width: width, alignment: .leading) }
    func weight(_ h: Holding) -> String {
        let total = store.visibleHoldings.reduce(Decimal(0)) { $0 + $1.value }
        guard total > 0 else { return "0%" }
        return String(format: "%.1f%%", NSDecimalNumber(decimal: h.value / total * 100).doubleValue)
    }
}

struct AssistantView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        @Bindable var store = store
        NavigationStack {
            VStack(spacing: 0) {
                VStack(spacing: 0) { DemoBanner(); AccountPicker() }.padding(.horizontal, 20)
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 18) {
                            ForEach(store.messages) { message in
                                VStack(alignment: .leading, spacing: 12) {
                                    Text(message.user ? "YOU" : "TRADEPILOT · DEMO").font(.system(size: 10, weight: .bold, design: .monospaced)).tracking(1.2).foregroundStyle(message.user ? Palette.muted : Palette.mint)
                                    Text(message.text).font(.system(size: 15)).lineSpacing(5).textSelection(.enabled)
                                    if message.table { PortfolioTable() }
                                }.frame(maxWidth: .infinity, alignment: .leading).padding(18).background(message.user ? Color.white.opacity(0.035) : Palette.panel, in: RoundedRectangle(cornerRadius: 20)).id(message.id)
                            }
                        }.padding(20)
                    }
                    .onChange(of: store.messages.count) { _, _ in if let last = store.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } } }
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        suggestion("Show my portfolio")
                        suggestion("Sell 3 shares of AAPL")
                        suggestion("Buy 0.01 BTC")
                    }.padding(.horizontal, 20).padding(.vertical, 10)
                }
                if store.busy { ProgressView("Thinking…").font(.caption).padding(8) }
                HStack(alignment: .bottom, spacing: 12) {
                    TextField("Ask about your portfolio…", text: $store.input, axis: .vertical).lineLimit(1...5).font(.subheadline).submitLabel(.send).onSubmit { store.send() }
                    Button { store.send() } label: { Image(systemName: "arrow.up").font(.headline).frame(width: 38, height: 38).background(Palette.mint, in: Circle()).foregroundStyle(Palette.background) }.disabled(store.busy || store.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityLabel("Send message")
                }.padding(12).background(Palette.panel, in: RoundedRectangle(cornerRadius: 24)).padding(.horizontal, 16).padding(.bottom, 12)
            }.background(Palette.background).navigationTitle("Assistant").phoneInlineTitle()
        }
    }
    func suggestion(_ text: String) -> some View {
        Button(text) { store.send(text) }.font(.caption).padding(.horizontal, 14).padding(.vertical, 10).background(Palette.panel, in: Capsule()).foregroundStyle(Palette.mint).disabled(store.busy)
    }
}

struct ReviewView: View {
    @Environment(AppStore.self) private var store
    let preview: TradePreview
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    DemoBanner()
                    Image(systemName: "checkmark.shield").font(.system(size: 36)).foregroundStyle(Palette.mint)
                    Text("Your trade.\nYour approval.").font(.system(size: 34, weight: .semibold)).tracking(-1)
                    Text("\(preview.side.rawValue.capitalized) \(units(preview.quantity)) \(preview.symbol)").font(.title2.bold())
                    VStack(spacing: 16) {
                        row("Account", store.engine.accountName(preview.accountID))
                        row("Order type", "Market · demo")
                        row("Time in force", "Immediate simulated fill")
                        row("Quantity", units(preview.quantity))
                        row("Sample price", money(preview.price))
                        row("Demo fee", "$0.00")
                        Divider()
                        row(preview.side == .sell ? "Simulated proceeds" : "Simulated cost", money(preview.gross))
                    }.card()
                    Text("Sample prices are fictional and fixed. Live market orders can execute at a different price. Real fees, tax lots and taxes are not included in this demo.").font(.caption).foregroundStyle(Palette.muted)
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let expired = context.date >= preview.expiresAt
                        VStack(alignment: .leading, spacing: 14) {
                            Text(expired ? "Review expired. Cancel and request a fresh review." : "Review expires in \(max(0, Int(preview.expiresAt.timeIntervalSince(context.date))))s").font(.caption).foregroundStyle(expired ? .orange : Palette.muted)
                            Button { store.confirm(preview) } label: { Label("Confirm demo \(preview.side.rawValue)", systemImage: "checkmark").frame(maxWidth: .infinity) }.buttonStyle(MintButton()).disabled(expired)
                        }
                    }
                    Button("Cancel review") { store.cancel(preview) }.frame(maxWidth: .infinity).foregroundStyle(Palette.muted)
                }.padding(24)
            }.background(Palette.background).navigationTitle("Review order").phoneInlineTitle()
        }
    }
    func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top) { Text(label).foregroundStyle(Palette.muted); Spacer(); Text(value).multilineTextAlignment(.trailing) }.font(.subheadline)
    }
}

struct AccountsView: View {
    @Environment(AppStore.self) private var store
    @State private var showConnections = false
    @State private var connectionMessage = ""
    @State private var setup: GatewaySetup?
    @State private var checkingSetup = false
    var body: some View {
        @Bindable var store = store
        Screen(title: "Accounts") {
            NavigationLink { WebullView() } label: { Label("Open Webull account", systemImage: "building.columns.fill") }.buttonStyle(MintButton())
            NavigationLink { CoinbaseView() } label: { Label("Coinbase balances", systemImage: "bitcoinsign.circle") }.buttonStyle(MintButton())
            NavigationLink { PaperTradingView() } label: { Label("Paper trading account", systemImage: "chart.line.uptrend.xyaxis") }.buttonStyle(MintButton())
            Text("Everything you own,\nin one place.").font(.title.bold())
            Text("These are sample accounts. Live connections will depend on the institution’s data and trading permissions.").font(.subheadline).foregroundStyle(Palette.muted)
            ForEach(store.engine.accounts) { a in
                VStack(alignment: .leading, spacing: 15) {
                    HStack { Image(systemName: a.kind == "Crypto" ? "bitcoinsign.circle" : "building.columns").font(.title2).foregroundStyle(Palette.mint); Spacer(); Text(a.canTrade ? "DEMO TRADING" : "VIEW ONLY").font(.system(size: 9, weight: .bold, design: .monospaced)).padding(7).background(Palette.mint.opacity(0.08), in: Capsule()).foregroundStyle(Palette.mint) }
                    Text(a.name).font(.headline)
                    HStack { Text(a.kind).font(.caption).foregroundStyle(Palette.muted); Spacer(); Text("\(money(a.cash)) cash").font(.caption) }
                }.card()
            }
            Button { showConnections = true } label: { Label("Explore live connections", systemImage: "plus").frame(maxWidth: .infinity) }.buttonStyle(MintButton())
            VStack(alignment: .leading, spacing: 14) {
                Text("Private server connection").font(.headline)
                Text("Your server connects market data, Webull and optional AI. Assistant-tab orders use demo data. The separate Webull screen requires a broker preview and confirmation. AI requests use your server’s selected provider: local Ollama or OpenAI. OpenAI mode sends the selected portfolio and prompt to OpenAI. Save your connection to keep the access token in this iPhone’s Keychain.").font(.caption).foregroundStyle(Palette.muted)
                TextField("https://your-private-server", text: $store.aiEndpoint).phoneURLInput()
                SecureField("Server access token", text: $store.aiToken).phoneSecretInput()
                Button("Save connection") {
                    do { try ConnectionSettings.save(endpoint: store.aiEndpoint, token: store.aiToken); store.connectionError = nil; connectionMessage = "Connection saved on this device." }
                    catch { connectionMessage = error.localizedDescription }
                }
                if !connectionMessage.isEmpty { Text(connectionMessage).font(.caption) }
                if let connectionError = store.connectionError { Text(connectionError).font(.caption).foregroundStyle(.orange) }
                Button(checkingSetup ? "Checking connection…" : "Check connection & setup") {
                    checkingSetup = true; setup = nil
                    let endpoint = store.aiEndpoint
                    let token = store.aiToken
                    Task { @MainActor in
                        defer { checkingSetup = false }
                        do {
                            let result = try await AIService.setup(endpoint: endpoint, token: token)
                            guard endpoint == store.aiEndpoint, token == store.aiToken else {
                                connectionMessage = "Connection changed during the check. Check again."; return
                            }
                            setup = result
                            connectionMessage = "Private server connection verified."
                        } catch { connectionMessage = error.localizedDescription }
                    }
                }.disabled(checkingSetup)
                if let setup {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("Private server reachable", systemImage: "checkmark.circle")
                        Text("Massive: \(setup.market_data_configured ? "configured" : "needs API configuration")")
                        Text("AI: \(setup.ai_configured ? "configured" : "needs configuration")")
                        if let provider = setup.ai_provider { Text("Provider: \(provider == "ollama" ? "Local Ollama on your Mac" : "OpenAI")") }
                        if let model = setup.ai_model { Text("Model: \(model)").font(.caption) }
                        Text("Webull: \(setup.webull_configured ? "configured · " + setup.webull_environment : "needs API configuration")")
                        Text("Live order submission: \(setup.live_trading_enabled ? "enabled" : "disabled")")
                        Text("Configuration does not verify provider access. Load research or Webull accounts to check those connections.").foregroundStyle(Palette.muted)
                    }.font(.caption)
                }
                Toggle("Use AI for new messages", isOn: $store.aiEnabled).tint(Palette.mint)
                Text(store.aiEnabled ? "AI service selected · connection not yet verified" : "Offline demo parser selected").font(.caption2).foregroundStyle(Palette.muted)
            }.card()
            VStack(alignment: .leading, spacing: 12) {
                Text("Test a rejected order").font(.headline)
                Toggle("Reject next demo submission", isOn: $store.rejectNext).font(.subheadline).tint(Palette.mint)
                Text("Use this to check the failure flow. The next confirmed demo order will leave your holdings and cash unchanged.").font(.caption).foregroundStyle(Palette.muted)
            }.card()
        }
        .sheet(isPresented: $showConnections) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        Text("Connect the accounts\nyou already use.").font(.largeTitle.bold())
                        Text("Webull is the first implemented connection. Its credentials stay on your private server. Other institutions below are planned connections.").foregroundStyle(Palette.muted)
                        Label("Brokerage aggregation", systemImage: "building.columns").font(.headline)
                        Text("For your US Fidelity account, SnapTrade currently lists view-only access. A Fidelity connection can show holdings, but cannot execute trades through that integration.")
                        Link("View SnapTrade coverage", destination: URL(string: "https://support.snaptrade.com/brokerages")!)
                        Text("Webull offers an individual Trading API application, subject to review and account eligibility. API access should be confirmed before deciding whether to fund it.")
                        Link("Webull API application guide", destination: URL(string: "https://developer.webull.com/apis/docs/authentication/IndividualApplicationAPI/")!)
                        Label("Direct exchange connections", systemImage: "bitcoinsign.circle").font(.headline)
                        Text("For your Coinbase account, Coinbase Advanced Trade is the proposed crypto connection. Portfolio viewing and trading use separate permissions. Withdrawals are outside this app’s scope.")
                        Text("Use Accounts → Open Webull account for the implemented connection. Fidelity and Coinbase linking are not yet implemented. Never enter a brokerage password in chat.").font(.subheadline).foregroundStyle(Palette.muted)
                    }.padding(24)
                }.background(Palette.background).navigationTitle("Live connections").phoneInlineTitle().toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { showConnections = false } } }
            }.tint(Palette.mint)
        }
    }
}

struct MintButton: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.bold()).padding(17).foregroundStyle(Palette.background).background(Palette.mint.opacity(configuration.isPressed ? 0.7 : 1), in: RoundedRectangle(cornerRadius: 16))
    }
}

extension View {
    func card() -> some View { padding(20).frame(maxWidth: .infinity, alignment: .leading).background(Palette.panel, in: RoundedRectangle(cornerRadius: 22)) }
}

// Keep shared views type-checkable on macOS; the delivered target is iPhone.
extension View {
    @ViewBuilder func phoneNavigationTheme() -> some View {
        #if os(iOS)
        toolbarColorScheme(.dark, for: .navigationBar)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneInlineTitle() -> some View {
        #if os(iOS)
        navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneURLInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneSecretInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        self
        #endif
    }
    @ViewBuilder func phoneSymbolInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.characters).autocorrectionDisabled()
        #else
        self
        #endif
    }
}
