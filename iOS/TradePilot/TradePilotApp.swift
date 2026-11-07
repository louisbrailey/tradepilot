import SwiftUI
import TradeCore
import UserNotifications

@main
struct TradePilotApp: App {
    @State private var store = AppStore()
    init() { UNUserNotificationCenter.current().delegate = NotificationRouter.shared }
    var body: some Scene {
        WindowGroup { landing.environment(store).tint(Theme.accent) }
        #if os(iOS)
        .backgroundTask(.appRefresh(AlertNotifier.refreshTask)) { await AlertNotifier.backgroundCheck() }
        #endif
    }
    // Debug-only screen selection for simulator visual QA; no account/action overrides.
    @ViewBuilder private var landing: some View {
        #if DEBUG
        let screen = ProcessInfo.processInfo.environment["TRADEPILOT_SCREEN"]
        if screen == "kronos" { NavigationStack { KronosView() } }
        else if screen == "paper" { NavigationStack { PaperTradingView() } }
        else if screen == "strategies" { NavigationStack { StrategyComparisonView() } }
        else if screen == "coinbase" { NavigationStack { CoinbaseView() } }
        else if screen == "markets" { MarketsView() }
        else if screen == "alerts" { NavigationStack { AlertsListView() } }
        else if screen == "alert" { AlertComposer(symbol: ProcessInfo.processInfo.environment["TRADEPILOT_SYMBOL"] ?? "AAPL", price: 342.37) { _ in } }
        else if screen == "symbol" { NavigationStack { SymbolDetailView(symbol: ProcessInfo.processInfo.environment["TRADEPILOT_SYMBOL"] ?? "AAPL") } }
        else { RootView() }
        #else
        RootView()
        #endif
    }
}

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
    var watchlist = WatchlistStore()
    var marketsPath: [String] = []
    var strategyID = "long_term"
    var researchTicker = "AAPL"
    var useMarketData = false
    var useJournalContext = false
    var tab = 0
    var showAssistant = false
    var accountID = "all"
    var input = ""
    var review: TradePreview?
    var rejectNext = false
    var aiEnabled = false
    var aiEndpoint = ConnectionSettings.endpoint
    var aiToken = ConnectionSettings.token
    var connectionError: String?
    var busy = false
    var messages = [ChatMessage(user: false, text: "This is the practice account. Try “Show my portfolio” or “Sell 3 shares of AAPL”. Nothing here reaches a broker.")] {
        didSet {
            for message in messages.dropFirst(oldValue.count) { record(message.user ? "request" : "assistant", message.text) }
        }
    }
    var visibleHoldings: [Holding] { engine.holdings.filter { accountID == "all" || $0.accountID == accountID } }
    var hasServerSettings: Bool { aiToken.count >= 32 && (try? ConnectionSettings.validatedEndpoint(aiEndpoint)) != nil }

    func record(_ kind: String, _ text: String, reference: String? = nil, order: Order? = nil) {
        journal.append(kind: kind, text: text, strategy: strategyID, accountID: order?.preview.accountID ?? accountID, reference: reference, holdings: engine.holdings, order: order)
    }

    func openAssistant(_ prompt: String? = nil) {
        showAssistant = true
        if let prompt { send(prompt) }
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
            messages.append(ChatMessage(user: false, text: "Practice holdings for the selected account.", table: true))
        case .trade(let intent):
            do {
                review = try engine.preview(intent, accountID: accountID == "all" ? nil : accountID)
                if let review { record("proposal", "Review \(intent.side.rawValue) \(units(intent.quantity)) \(intent.symbol) in \(review.accountID)", reference: review.id.uuidString) }
                messages.append(ChatMessage(user: false, text: "Review the \(intent.side.rawValue) of \(units(intent.quantity)) \(intent.symbol). Nothing is placed until you confirm."))
            } catch { messages.append(ChatMessage(user: false, text: error.localizedDescription)) }
        case .help:
            messages.append(ChatMessage(user: false, text: "Try “Show my portfolio”, “Sell 3 shares of AAPL” or “Buy 0.01 BTC”. Pick an account first if you hold the same asset in several."))
        }
    }

    private func askAI(_ text: String) {
        guard !busy else { return }
        busy = true
        let selectedAccount = accountID
        let snapshot = visibleHoldings
        let endpoint = aiEndpoint, token = aiToken
        Task {
            defer { busy = false }
            do {
                let result = try await AIService.ask(endpoint: endpoint, token: token, prompt: text,
                    holdings: snapshot, accounts: engine.accounts.filter { selectedAccount == "all" || $0.id == selectedAccount }, selectedAccount: selectedAccount, strategy: strategyID, researchTicker: useMarketData ? researchTicker : nil,
                    journal: useJournalContext ? journal.context(mode: "demo") : [])
                // Discard replies from a connection the user has since changed.
                guard aiEndpoint == endpoint, aiToken == token else { return }
                if result.kind == "trade" {
                    guard let rawSide = result.side, let side = Side(rawValue: rawSide),
                          let q = result.quantity, let quantity = strictDecimal(q, allowNegative: false),
                          let symbol = result.symbol else { throw TradeError.invalidQuantity }
                    // The model cannot submit or confirm; this uses the same independent practice engine.
                    review = try engine.preview(TradeIntent(side: side, quantity: quantity, symbol: symbol), accountID: selectedAccount == "all" ? nil : selectedAccount)
                    if let review { record("proposal", "AI proposal: \(review.side.rawValue) \(units(review.quantity)) \(review.symbol) in \(review.accountID)", reference: review.id.uuidString) }
                    messages.append(ChatMessage(user: false, text: "The assistant proposed a practice trade. Check the account, side and quantity before confirming."))
                } else {
                    messages.append(ChatMessage(user: false, text: result.message, table: result.kind == "portfolio"))
                }
            } catch {
                messages.append(ChatMessage(user: false, text: "No order created. \(error.localizedDescription)"))
            }
        }
    }

    func confirm(_ preview: TradePreview) {
        record("approval", "Confirmed practice \(preview.side.rawValue) \(units(preview.quantity)) \(preview.symbol)", reference: preview.id.uuidString)
        guard journal.error == nil else {
            engine.cancel(preview.id)
            messages.append(ChatMessage(user: false, text: "No order placed: the journal could not save the approval. Open Journal for details."))
            review = nil
            return
        }
        do {
            let result = try engine.confirm(preview.id, approved: true, simulateRejection: rejectNext)
            record("outcome", "\(result.status.rawValue): \(result.detail)", reference: result.preview.id.uuidString, order: result)
            rejectNext = false
            messages.append(ChatMessage(user: false, text: "\(result.status == .filled ? "Practice order filled" : "Practice order rejected"): \(result.preview.side.rawValue.capitalized) \(units(result.preview.quantity)) \(result.preview.symbol).\n\(result.detail)"))
        } catch {
            messages.append(ChatMessage(user: false, text: "Order not placed. \(error.localizedDescription)"))
        }
        review = nil
    }

    func cancel(_ preview: TradePreview) {
        record("cancel", "Review cancelled. No order placed.", reference: preview.id.uuidString)
        engine.cancel(preview.id)
        messages.append(ChatMessage(user: false, text: "Review dismissed. No order was placed."))
        review = nil
    }
}

struct RootView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    var body: some View {
        @Bindable var store = store
        TabView(selection: $store.tab) {
            HomeView().tabItem { Label("Home", systemImage: "house") }.tag(0)
            MarketsView().tabItem { Label("Markets", systemImage: "chart.line.uptrend.xyaxis") }.tag(4)
            AccountsView().tabItem { Label("Accounts", systemImage: "building.columns") }.tag(1)
            ResearchView().tabItem { Label("Research", systemImage: "chart.xyaxis.line") }.tag(2)
            JournalView().tabItem { Label("Journal", systemImage: "book.closed") }.tag(3)
        }
        .tint(Theme.accent)
        .safeAreaInset(edge: .top) {
            if store.journal.error != nil {
                InlineNotice(kind: .error, message: "The journal can't be saved, so orders are paused.", action: ("Open", { store.tab = 3 }))
                    .padding(.horizontal, Spacing.l).padding(.top, Spacing.xs).background(Theme.background)
            }
        }
        .sheet(isPresented: $store.showAssistant) { AssistantView() }
        .onAppear {
            NotificationRouter.shared.open = { [store] symbol in
                store.tab = 4
                store.marketsPath = [symbol]
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { AlertNotifier.schedule() }
        }
    }
}

// MARK: - Home

struct HomeView: View {
    @Environment(AppStore.self) private var store
    @State private var loaded: (binding: BrokerConnectionBinding, snapshot: PaperSnapshot, at: Date)?
    @State private var loading: BrokerConnectionBinding?
    @State private var failed: BrokerConnectionBinding?

    private var binding: BrokerConnectionBinding { .init(endpoint: store.aiEndpoint, token: store.aiToken) }
    private var current: PaperSnapshot? { loaded?.binding == binding ? loaded?.snapshot : nil }

    var body: some View {
        Screen(title: "TradePilot", refresh: { await refresh() }) {
            connectionRow
            SectionCard(title: "Paper portfolio") {
                if let current {
                    PaperEquitySummary(snapshot: current)
                    if failed == binding { Footnote("Showing the last loaded paper account.") }
                } else if loading == binding {
                    ProgressView("Loading paper portfolio").padding(.vertical, Spacing.m)
                } else {
                    Text(store.hasServerSettings ? "Your paper account is unavailable." : "Connect your server to see paper balances and activity.")
                        .font(.subheadline).foregroundStyle(Theme.textSecondary)
                }
                Divider().overlay(Theme.separator)
                VStack(spacing: 0) {
                    NavigationLink { PaperTradingView() } label: { NavigationRow(title: "Paper account", detail: "Positions and orders", icon: "chart.pie") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { AutomatedPaperView() } label: { NavigationRow(title: "Automated strategies", detail: "Scheduled paper experiments", icon: "clock.arrow.circlepath") }
                }.buttonStyle(RowButtonStyle())
            }
            HomeMarketsCard()
            SectionCard(title: "Broker accounts") {
                VStack(spacing: 0) {
                    NavigationLink { WebullView() } label: { NavigationRow(title: "Webull", detail: "Stocks and ETFs", icon: "building.columns") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { CoinbaseView() } label: { NavigationRow(title: "Coinbase", detail: "Crypto asset balances", icon: "bitcoinsign.circle") }
                }.buttonStyle(RowButtonStyle())
            }
            SectionCard(title: "Practice") {
                VStack(spacing: 0) {
                    NavigationLink { PracticeAccountView() } label: { NavigationRow(title: "Practice account", detail: "Sample holdings on this iPhone", icon: "graduationcap") }
                    Divider().overlay(Theme.separator)
                    Button { store.openAssistant() } label: { NavigationRow(title: "Practice assistant", detail: "Review sample holdings or draft an order", icon: "bubble.left.and.text.bubble.right") }
                }.buttonStyle(RowButtonStyle())
            }
        }
        .task(id: binding) { await refresh() }
    }

    private var connectionRow: some View {
        let label: String
        let tint: Color
        if !store.hasServerSettings { label = "Set up server"; tint = Theme.warning }
        else if failed == binding { label = "Server unavailable"; tint = Theme.warning }
        else if let loaded, loaded.binding == binding { label = "Server checked \(relativeTime(loaded.at))"; tint = Theme.positive }
        else { label = "Checking server"; tint = Theme.textSecondary }
        return NavigationLink { SettingsView() } label: {
            HStack(spacing: Spacing.s) {
                Circle().fill(tint).frame(width: 7, height: 7).accessibilityHidden(true)
                Text(label).font(.footnote).foregroundStyle(Theme.textSecondary)
                Spacer()
                Image(systemName: "gearshape").foregroundStyle(Theme.textSecondary).accessibilityLabel("Settings")
            }
            .padding(.horizontal, Spacing.xs).frame(minHeight: 44).contentShape(Rectangle())
        }.buttonStyle(RowButtonStyle())
    }

    private func refresh() async {
        let request = binding
        guard store.hasServerSettings, loading != request else { return }
        loading = request
        defer { if loading == request { loading = nil } }
        do {
            let snapshot: PaperSnapshot = try await WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(), endpoint: request.endpoint, token: request.token)
            guard !Task.isCancelled, request == binding else { return }
            guard snapshot.mode == "paper" else { throw WorkspaceError(message: "Unexpected paper account response.") }
            loaded = (request, snapshot, .now)
            failed = nil
        } catch {
            if !Task.isCancelled, request == binding { failed = request }
        }
    }
}

// MARK: - Practice account detail (the local sample engine)

struct PracticeAccountView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        @Bindable var store = store
        let accounts = store.engine.accounts.filter { store.accountID == "all" || $0.id == store.accountID }
        let holdings = store.visibleHoldings
        let orders = store.engine.orders.filter { store.accountID == "all" || $0.preview.accountID == store.accountID }
        let cash = accounts.reduce(0) { $0 + $1.cash }
        let total = holdings.reduce(cash) { $0 + $1.value }
        let gain = holdings.reduce(0) { $0 + $1.gain }
        SubScreen(title: "Practice account") {
            HStack { StatusBadge("Practice", tone: .practice); Spacer() }
            Footnote("Fixed sample prices in USD. Nothing here reaches a broker, and the data resets when you quit the app.")
            AccountPicker()
            SectionCard(title: "Sample portfolio") {
                HeroMetric(label: "Total value", value: money(total), delta: "\(signedMoney(gain)) unrealized",
                           deltaTone: gain > 0 ? .positive : gain < 0 ? .negative : .neutral)
                MetricTile(label: "Cash", value: money(cash))
            }
            SectionCard(title: "Holdings") {
                if holdings.isEmpty {
                    EmptyState(title: "No holdings", message: "This practice account holds only cash.")
                } else {
                    ForEach(holdings) { h in
                        HoldingRow(symbol: h.symbol, detail: "\(units(h.quantity)) · avg \(money(h.costPerUnit)) · \(store.engine.accountName(h.accountID))",
                                   value: money(h.value), change: signedMoney(h.gain), changeTone: h.gain >= 0 ? .positive : .negative)
                    }
                }
                NavigationLink { PortfolioTableScreen() } label: { Text("All columns").font(.footnote.weight(.semibold)) }
            }
            SectionCard(title: "Accounts") {
                ForEach(accounts) { a in
                    DetailRow(a.name, money(a.cash) + (a.canTrade ? "" : " · view only"))
                }
            }
            Button { store.openAssistant("Show my portfolio") } label: { Label("Ask about these holdings", systemImage: "bubble.left.and.text.bubble.right") }
                .buttonStyle(SecondaryButtonStyle())
            if !orders.isEmpty {
                SectionCard(title: "Recent practice orders") {
                    ForEach(orders.prefix(5)) { order in
                        DetailRow("\(order.preview.side.rawValue.capitalized) \(units(order.preview.quantity)) \(order.preview.symbol)",
                                  "\(StatusBadge.orderState(order.status.rawValue).text) · \(relativeTime(order.createdAt))")
                    }
                }
            }
            #if DEBUG
            SectionCard(title: "Testing", footer: "The next confirmed practice order is rejected and leaves holdings unchanged.") {
                Toggle("Reject the next practice order", isOn: $store.rejectNext).font(.subheadline)
            }
            #endif
        }
    }
}

struct AccountPicker: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        @Bindable var store = store
        Picker("Account", selection: $store.accountID) {
            Text("All accounts").tag("all")
            ForEach(store.engine.accounts) { a in Text(a.name).tag(a.id) }
        }.pickerStyle(.menu).tint(Theme.accent)
    }
}

struct PortfolioTableScreen: View {
    var body: some View {
        SubScreen(title: "All columns") {
            PortfolioTable()
            Footnote("Weight is based on the shown holdings, excluding cash. Cost basis uses a simplified average; tax lots are not modelled.")
        }
    }
}

struct PortfolioTable: View {
    @Environment(AppStore.self) private var store
    @ScaledMetric private var scale: CGFloat = 1
    private let columns: [(String, CGFloat)] = [("Asset", 80), ("Account", 180), ("Qty", 90), ("Price", 100), ("Value", 110), ("Avg cost", 100), ("Cost basis", 110), ("Unrealised", 110), ("Weight", 80)]
    var body: some View {
        ScrollView(.horizontal) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 0) { ForEach(columns.indices, id: \.self) { i in Eyebrow(columns[i].0).frame(width: columns[i].1 * scale, alignment: .leading) } }.padding(.vertical, Spacing.m)
                ForEach(store.visibleHoldings) { h in
                    Divider().overlay(Theme.separator)
                    HStack(spacing: 0) {
                        cell(h.symbol, 80, weight: .semibold)
                        cell(store.engine.accountName(h.accountID), 180)
                        cell(units(h.quantity), 90)
                        cell(money(h.price), 100)
                        cell(money(h.value), 110)
                        cell(money(h.costPerUnit), 100)
                        cell(money(h.costPerUnit * h.quantity), 110)
                        cell(signedMoney(h.gain), 110, color: deltaColor(h.gain))
                        cell(weight(h), 80)
                    }.padding(.vertical, Spacing.m)
                    .accessibilityElement(children: .combine)
                }
            }.padding(.horizontal, Spacing.l)
        }.background(Theme.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
    }
    private func cell(_ text: String, _ width: CGFloat, weight: Font.Weight = .regular, color: Color = Theme.textPrimary) -> some View {
        Text(text).font(.footnote.weight(weight)).monospacedDigit().foregroundStyle(color).frame(width: width * scale, alignment: .leading)
    }
    private func weight(_ h: Holding) -> String {
        let total = store.visibleHoldings.reduce(Decimal(0)) { $0 + $1.value }
        guard total > 0 else { return "0%" }
        return percent(NSDecimalNumber(decimal: h.value / total * 100).doubleValue, digits: 1)
    }
}

// MARK: - Assistant (sheet)

struct AssistantView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        @Bindable var store = store
        NavigationStack {
            VStack(spacing: 0) {
                HStack { StatusBadge("Practice", tone: .practice); Spacer(); AccountPicker() }.padding(.horizontal, Spacing.l).padding(.vertical, Spacing.s)
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: Spacing.m) {
                            ForEach(store.messages) { message in
                                VStack(alignment: .leading, spacing: Spacing.m) {
                                    Text(message.text).font(.subheadline).lineSpacing(3).textSelection(.enabled)
                                    if message.table { PortfolioTable() }
                                }
                                .padding(Spacing.m)
                                .frame(maxWidth: .infinity, alignment: message.user ? .trailing : .leading)
                                .background(message.user ? Theme.accent.opacity(0.18) : Theme.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                                .frame(maxWidth: .infinity, alignment: message.user ? .trailing : .leading)
                                .id(message.id)
                            }
                        }.padding(Spacing.l)
                    }
                    .onChange(of: store.messages.count) { _, _ in if let last = store.messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } } }
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: Spacing.s) {
                        suggestion("Show my portfolio")
                        suggestion("Sell 3 shares of AAPL")
                        suggestion("Buy 0.01 BTC")
                    }.padding(.horizontal, Spacing.l).padding(.vertical, Spacing.s)
                }
                if store.busy { ProgressView().padding(Spacing.s) }
                HStack(alignment: .bottom, spacing: Spacing.m) {
                    TextField("Ask about the practice account…", text: $store.input, axis: .vertical).lineLimit(1...5).font(.subheadline).submitLabel(.send).onSubmit { store.send() }
                    Button { store.send() } label: { Image(systemName: "arrow.up").font(.headline).frame(width: 44, height: 44).background(Theme.accent, in: Circle()).foregroundStyle(Theme.onAccent) }
                        .disabled(store.busy || store.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityLabel("Send")
                }.padding(Spacing.m).background(Theme.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous)).padding(.horizontal, Spacing.l).padding(.bottom, Spacing.m)
            }
            .background(Theme.background)
            .navigationTitle("Assistant").phoneInlineTitle()
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .tint(Theme.accent)
        .sheet(item: $store.review) { preview in PracticeReviewSheet(preview: preview).interactiveDismissDisabled() }
    }
    private func suggestion(_ text: String) -> some View {
        Button(text) { store.send(text) }.font(.caption.weight(.medium)).padding(.horizontal, Spacing.m).padding(.vertical, Spacing.s)
            .background(Theme.surfaceRaised, in: Capsule()).foregroundStyle(Theme.textPrimary).disabled(store.busy)
    }
}

struct PracticeReviewSheet: View {
    @Environment(AppStore.self) private var store
    let preview: TradePreview
    var body: some View {
        ConfirmationSheet(title: "Review order",
                          headline: "\(preview.side.rawValue.capitalized) \(units(preview.quantity)) \(preview.symbol)",
                          badge: StatusBadge("Practice", tone: .practice),
                          disclaimer: "Sample prices are fixed. A real market order can fill at a different price, and real fees and taxes are not included.",
                          expiresAt: preview.expiresAt,
                          confirmTitle: "Confirm practice \(preview.side.rawValue)",
                          rows: {
                              DetailRow("Account", store.engine.accountName(preview.accountID))
                              DetailRow("Order type", "Market")
                              DetailRow("Quantity", units(preview.quantity))
                              DetailRow("Sample price", money(preview.price))
                              Divider().overlay(Theme.separator)
                              DetailRow(preview.side == .sell ? "Estimated proceeds" : "Estimated cost", money(preview.gross))
                          },
                          confirm: { store.confirm(preview) },
                          cancel: { store.cancel(preview) })
    }
}

// MARK: - Accounts

struct AccountsView: View {
    @Environment(AppStore.self) private var store
    var body: some View {
        Screen(title: "Accounts") {
            SectionCard(title: "Broker accounts") {
                VStack(spacing: 0) {
                    NavigationLink { WebullView() } label: { NavigationRow(title: "Webull", detail: "Stocks and ETFs", icon: "building.columns.fill") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { CoinbaseView() } label: { NavigationRow(title: "Coinbase", detail: "Crypto balances and permissions", icon: "bitcoinsign.circle") }
                }.buttonStyle(RowButtonStyle())
            }
            SectionCard(title: "Paper") {
                VStack(spacing: 0) {
                    NavigationLink { PaperTradingView() } label: { NavigationRow(title: "Paper account", detail: "Manual simulated orders, saved on your server", icon: "doc.text") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { AutomatedPaperView() } label: { NavigationRow(title: "Automated strategies", detail: "Three rule-based SPY experiments", icon: "clock.arrow.circlepath") }
                }.buttonStyle(RowButtonStyle())
            }
            SectionCard(title: "Practice") {
                NavigationLink { PracticeAccountView() } label: { NavigationRow(title: "Practice account", detail: "Sample holdings on this phone", icon: "graduationcap") }
                    .buttonStyle(RowButtonStyle())
            }
            SectionCard {
                NavigationLink { SettingsView() } label: { NavigationRow(title: "Settings", detail: "Server connection, assistant and privacy", icon: "gearshape") }
                    .buttonStyle(RowButtonStyle())
            }
            Footnote("Credentials for Webull and Coinbase stay on your own server. Live order placement and transfers are off unless your server enables them.")
        }
    }
}

// MARK: - Settings

struct SettingsView: View {
    @Environment(AppStore.self) private var store
    @State private var endpointDraft = ""
    @State private var tokenDraft = ""
    @State private var saveNotice = ""
    @State private var saveKind: NoticeKind = .info
    @State private var setup: GatewaySetup?
    @State private var checking = false
    var body: some View {
        @Bindable var store = store
        SubScreen(title: "Settings") {
            SectionCard(title: "Your server", footer: "TradePilot talks only to your own server. The access token is stored in this iPhone’s Keychain.") {
                TextField("https://your-server", text: $endpointDraft).phoneURLInput().fieldStyle()
                SecureField("Access token", text: $tokenDraft).phoneSecretInput().fieldStyle()
                HStack(spacing: Spacing.m) {
                    Button("Save") {
                        do {
                            try ConnectionSettings.save(endpoint: endpointDraft, token: tokenDraft)
                            store.aiEndpoint = endpointDraft; store.aiToken = tokenDraft; store.connectionError = nil
                            setup = nil; saveNotice = "Saved on this device."; saveKind = .success
                        } catch { saveNotice = error.localizedDescription; saveKind = .error }
                    }.buttonStyle(PrimaryButtonStyle()).disabled(endpointDraft == store.aiEndpoint && tokenDraft == store.aiToken)
                    Button(checking ? "Checking…" : "Test connection") { check() }.buttonStyle(SecondaryButtonStyle()).disabled(checking || !store.hasServerSettings)
                }
                OutcomeNotice(text: saveNotice, kind: saveKind)
                if let connectionError = store.connectionError { InlineNotice(kind: .error, message: connectionError) }
            }
            if let setup {
                SectionCard(title: "Status", footer: "Configured means your server has credentials. Open an account to check that the provider accepts them.") {
                    statusRow("Server", "Reachable", tone: .positive)
                    statusRow("Market data", setup.market_data_configured ? "Configured" : "Not configured", tone: setup.market_data_configured ? .positive : .warning)
                    statusRow("Assistant", setup.ai_configured ? (setup.ai_provider == "ollama" ? "Local model on your server" : "OpenAI") + (setup.ai_model.map { " · \($0)" } ?? "") : "Not configured", tone: setup.ai_configured ? .positive : .warning)
                    statusRow("Webull", setup.webull_configured ? "Configured" : "Not configured", tone: setup.webull_configured ? .positive : .warning, badge: setup.webull_configured ? StatusBadge.environment(setup.webull_environment) : nil)
                    statusRow("Coinbase", setup.coinbase_configured.map { $0 ? "Configured" : "Not configured" } ?? "Not reported", tone: setup.coinbase_configured == true ? .positive : .neutral)
                    statusRow("Live Webull orders", setup.live_trading_enabled ? "On" : "Off", tone: setup.live_trading_enabled ? .live : .neutral)
                }
            }
            SectionCard(title: "Assistant", footer: store.aiEnabled ? "Questions go to the model configured on your server. Trade suggestions only fill in a form; you still review and confirm." : "Only on-device commands such as “Sell 3 shares of AAPL” are understood.") {
                Toggle("Use the model on your server", isOn: $store.aiEnabled).font(.subheadline)
                Toggle("Include market research", isOn: $store.useMarketData).font(.subheadline)
                Toggle("Include recent journal entries", isOn: $store.useJournalContext).font(.subheadline)
            }
            SectionCard(title: "About this install") {
                DetailRow("Version", "\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—"))")
                Footnote("Keep your server awake and connect this iPhone to its private network.")
            }
        }
        .onAppear { endpointDraft = store.aiEndpoint; tokenDraft = store.aiToken }
    }
    private func statusRow(_ label: String, _ value: String, tone: Tone, badge: StatusBadge? = nil) -> some View {
        HStack(spacing: Spacing.s) {
            Text(label).font(.subheadline).foregroundStyle(Theme.textSecondary)
            Spacer()
            if let badge { badge }
            Text(value).font(.subheadline.weight(.medium)).foregroundStyle(tone.color).multilineTextAlignment(.trailing)
        }.accessibilityElement(children: .combine)
    }
    private func check() {
        checking = true; setup = nil
        let endpoint = store.aiEndpoint, token = store.aiToken
        Task { @MainActor in
            defer { checking = false }
            do {
                let result = try await AIService.setup(endpoint: endpoint, token: token)
                guard endpoint == store.aiEndpoint, token == store.aiToken else { saveNotice = "Connection changed during the check."; saveKind = .warning; return }
                setup = result; saveNotice = ""
            } catch {
                if endpoint == store.aiEndpoint, token == store.aiToken { saveNotice = error.localizedDescription; saveKind = .error }
            }
        }
    }
}
