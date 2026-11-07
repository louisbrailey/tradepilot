import SwiftUI

// Markets tab: session status, index ETFs, the watchlist, large-cap movers and symbol search.

struct MarketsView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @State private var overview: MarketOverview?
    @State private var quotes: [String: MarketQuote] = [:]
    @State private var missing: Set<String> = []
    @State private var loadedBinding: BrokerConnectionBinding?
    @State private var refreshedAt: Date?
    @State private var message = ""
    @State private var loading = false
    @State private var query = ""
    @State private var results: [SymbolSearchResult] = []
    @State private var searchMessage = ""
    @State private var searching = false
    @State private var movers = MoverList.gainers
    @State private var editing = false
    @State private var alerts: AlertsSnapshot?

    private var binding: BrokerConnectionBinding { .init(endpoint: store.aiEndpoint, token: store.aiToken) }
    private var trimmedQuery: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    if trimmedQuery.isEmpty { dashboard } else { searchResults }
                }
                .padding(.horizontal, Spacing.l).padding(.top, Spacing.s).padding(.bottom, Spacing.xxl)
            }
            .background(Theme.background)
            .navigationTitle("Markets")
            .phoneInlineTitle()
            .phoneNavigationTheme()
            .refreshable { await refresh() }
            .searchable(text: $query, prompt: "Symbol or company")
            .navigationDestination(for: String.self) { SymbolDetailView(symbol: $0) }
            .toolbar {
                ToolbarItem(placement: .topBarLeadingIfAvailable) {
                    NavigationLink { AlertsListView() } label: {
                        Image(systemName: (alerts?.triggered ?? 0) > 0 ? "bell.badge.fill" : "bell")
                            .symbolRenderingMode((alerts?.triggered ?? 0) > 0 ? .multicolor : .monochrome)
                    }
                    .accessibilityLabel((alerts?.triggered ?? 0) > 0 ? "Price alerts, \(alerts?.triggered ?? 0) triggered" : "Price alerts")
                }
                ToolbarItem(placement: .primaryAction) {
                    Button("Edit") { editing = true }.disabled(store.watchlist.symbols.isEmpty)
                }
            }
            .sheet(isPresented: $editing) { WatchlistEditor() }
            .task(id: RefreshKey(binding: binding, symbols: store.watchlist.symbols, active: scenePhase == .active)) {
                guard scenePhase == .active else { return }
                while !Task.isCancelled {
                    await refresh()
                    let seconds = overview?.status.isTrading == false ? 120 : 15
                    try? await Task.sleep(for: .seconds(seconds))
                }
            }
            .task(id: trimmedQuery) { await search() }
        }
    }

    // MARK: Dashboard

    @ViewBuilder private var dashboard: some View {
        statusRow
        if !store.hasServerSettings {
            InlineNotice(kind: .info, message: "Connect your TradePilot server in Settings to see live market data.")
        } else if !message.isEmpty {
            InlineNotice(kind: overview == nil ? .error : .warning,
                         message: overview == nil ? message : "\(message) Showing the last prices loaded.")
        }
        triggeredAlerts
        indexGrid
        watchlistCard
        moversCard
        Footnote("Market data from Massive via your TradePilot server. Prices can be delayed and aren’t executable quotes. Index values are shown with their ETFs.")
    }

    @ViewBuilder private var triggeredAlerts: some View {
        let triggered = (loadedBinding == binding ? alerts?.alerts : nil)?.filter(\.isTriggered) ?? []
        if !triggered.isEmpty {
            SectionCard {
                HStack {
                    Label("Price alerts", systemImage: "bell.badge.fill").font(.headline).foregroundStyle(Theme.warning)
                    Spacer()
                    NavigationLink("See all") { AlertsListView() }.font(.footnote.weight(.semibold))
                }
                ForEach(triggered.prefix(3)) { alert in
                    NavigationLink(value: alert.symbol) {
                        AlertRow(alert: alert, remove: { dismissAlert(alert) })
                    }.buttonStyle(RowButtonStyle())
                }
            }
        }
    }

    private func dismissAlert(_ alert: PriceAlert) {
        let request = binding
        Task {
            if let updated = try? await AlertsAPI.remove(alert.id, endpoint: request.endpoint, token: request.token), request == binding {
                alerts = updated
            }
        }
    }

    private var statusRow: some View {
        HStack(spacing: Spacing.s) {
            if let status = overview?.status { MarketSessionPill(status: status) }
            else if loading { ProgressView().controlSize(.small); Text("Loading markets").font(.footnote).foregroundStyle(Theme.textSecondary) }
            Spacer(minLength: 0)
            if let refreshedAt {
                Text("Updated \(refreshedAt.formatted(date: .omitted, time: .shortened))")
                    .font(.caption).foregroundStyle(Theme.textTertiary)
            }
        }
        .frame(minHeight: 28)
    }

    @ViewBuilder private var indexGrid: some View {
        let indices = currentOverview?.indices ?? []
        if !indices.isEmpty {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: Spacing.m), GridItem(.flexible(), spacing: Spacing.m)], spacing: Spacing.m) {
                ForEach(indices) { quote in
                    NavigationLink(value: quote.symbol) { IndexTile(quote: quote) }.buttonStyle(RowButtonStyle())
                }
            }
        }
    }

    private var watchlistCard: some View {
        SectionCard {
            HStack(alignment: .firstTextBaseline) {
                Text("Watchlist").font(.headline).accessibilityAddTraits(.isHeader)
                Spacer()
                Text("\(store.watchlist.symbols.count) symbols").font(.caption).foregroundStyle(Theme.textTertiary)
            }
            if store.watchlist.symbols.isEmpty {
                EmptyState(title: "Your watchlist is empty", message: "Search for a symbol or company, then tap + to follow it.", icon: "star")
            } else {
                VStack(spacing: 0) {
                    ForEach(store.watchlist.symbols, id: \.self) { symbol in
                        if symbol != store.watchlist.symbols.first { Divider().overlay(Theme.separator) }
                        NavigationLink(value: symbol) {
                            QuoteRow(symbol: symbol, quote: currentQuotes[symbol], unavailable: missing.contains(symbol))
                        }
                        .buttonStyle(RowButtonStyle())
                        .contextMenu {
                            Button { store.watchlist.moveToTop(symbol) } label: { Label("Move to top", systemImage: "arrow.up.to.line") }
                            Button(role: .destructive) { store.watchlist.remove(symbol) } label: { Label("Remove from watchlist", systemImage: "star.slash") }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var moversCard: some View {
        if let overview = currentOverview {
            SectionCard(footer: "Ranked within \(overview.universe), not the whole market.") {
                Text("Top movers").font(.headline).accessibilityAddTraits(.isHeader)
                Picker("Movers", selection: $movers) {
                    ForEach(MoverList.allCases) { Text($0.title).tag($0) }
                }.pickerStyle(.segmented)
                let list = movers.quotes(in: overview)
                if list.isEmpty {
                    Footnote(overview.status.state == "open" ? "Nothing to show yet." : "Movers appear once trading begins.")
                } else {
                    VStack(spacing: 0) {
                        ForEach(list) { quote in
                            if quote.id != list.first?.id { Divider().overlay(Theme.separator) }
                            NavigationLink(value: quote.symbol) {
                                QuoteRow(symbol: quote.symbol, quote: quote, unavailable: false, showsSparkline: false,
                                         detail: movers == .active ? "\(MarketFormat.compactMoney((quote.volume ?? 0) * quote.price)) traded" : nil)
                            }.buttonStyle(RowButtonStyle())
                        }
                    }
                }
            }
        }
    }

    // MARK: Search

    @ViewBuilder private var searchResults: some View {
        if searching && results.isEmpty {
            HStack { ProgressView(); Text("Searching").font(.subheadline).foregroundStyle(Theme.textSecondary) }
                .frame(maxWidth: .infinity).padding(.vertical, Spacing.xl)
        } else if !searchMessage.isEmpty {
            InlineNotice(kind: .warning, message: searchMessage)
        } else if results.isEmpty {
            EmptyState(title: "No matches", message: "Try a ticker such as AAPL or a company name.", icon: "magnifyingglass")
        } else {
            SectionCard {
                VStack(spacing: 0) {
                    ForEach(results) { result in
                        if result.id != results.first?.id { Divider().overlay(Theme.separator) }
                        HStack(spacing: Spacing.m) {
                            NavigationLink(value: result.symbol) {
                                HStack(spacing: Spacing.m) {
                                    SymbolMonogram(symbol: result.symbol, size: 34)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(result.symbol).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                                        Text(result.name).font(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
                                    }
                                    Spacer(minLength: Spacing.s)
                                    Text([result.type, result.exchange].compactMap { $0 }.joined(separator: " · "))
                                        .font(.caption).foregroundStyle(Theme.textTertiary).lineLimit(1)
                                }
                                .contentShape(Rectangle())
                            }.buttonStyle(RowButtonStyle())
                            WatchButton(symbol: result.symbol)
                        }
                        .padding(.vertical, Spacing.s)
                    }
                }
            }
        }
    }

    private func search() async {
        let text = trimmedQuery
        guard !text.isEmpty else { results = []; searchMessage = ""; return }
        try? await Task.sleep(for: .milliseconds(300))
        guard !Task.isCancelled, text == trimmedQuery else { return }
        guard store.hasServerSettings else { searchMessage = "Connect your server in Settings to search."; return }
        searching = true
        defer { if text == trimmedQuery { searching = false } }
        let request = binding
        do {
            let found = try await MarketAPI.search(text, endpoint: request.endpoint, token: request.token)
            guard !Task.isCancelled, text == trimmedQuery, request == binding else { return }
            results = found.results; searchMessage = ""
        } catch {
            guard !Task.isCancelled, text == trimmedQuery else { return }
            results = []; searchMessage = error.localizedDescription
        }
    }

    // MARK: Loading

    /// Data loaded for another connection is never shown.
    private var currentOverview: MarketOverview? { loadedBinding == binding ? overview : nil }
    private var currentQuotes: [String: MarketQuote] { loadedBinding == binding ? quotes : [:] }

    private func refresh() async {
        let request = binding
        guard store.hasServerSettings, !loading else { return }
        loading = true
        defer { loading = false }
        let symbols = store.watchlist.symbols
        async let summary = MarketAPI.overview(endpoint: request.endpoint, token: request.token)
        async let watched = MarketAPI.quotes(symbols, sparklines: true, endpoint: request.endpoint, token: request.token)
        async let alertState = AlertsAPI.state(endpoint: request.endpoint, token: request.token)
        var problems: [String] = []
        let loadedSummary: MarketOverview?
        do { loadedSummary = try await summary } catch { loadedSummary = nil; problems.append(error.localizedDescription) }
        let loadedQuotes: QuoteBatch?
        do { loadedQuotes = try await watched } catch { loadedQuotes = nil; problems.append(error.localizedDescription) }
        guard !Task.isCancelled, request == binding else { return }
        if loadedBinding != request { overview = nil; quotes = [:]; missing = [] }
        loadedBinding = request
        if let loadedSummary { overview = loadedSummary }
        if let loadedQuotes {
            quotes = Dictionary(loadedQuotes.quotes.map { ($0.symbol, $0) }, uniquingKeysWith: { $1 })
            missing = Set(loadedQuotes.missing)
        }
        if let latest = try? await alertState, request == binding { alerts = latest }
        if loadedSummary != nil || loadedQuotes != nil { refreshedAt = .now }
        message = Array(Set(problems)).sorted().first ?? ""
    }
}

private struct RefreshKey: Equatable {
    let binding: BrokerConnectionBinding
    let symbols: [String]
    let active: Bool
}

enum MoverList: String, CaseIterable, Identifiable {
    case gainers, losers, active
    var id: String { rawValue }
    var title: String {
        switch self {
        case .gainers: "Gainers"
        case .losers: "Losers"
        case .active: "Most active"
        }
    }
    func quotes(in overview: MarketOverview) -> [MarketQuote] {
        switch self {
        case .gainers: overview.gainers
        case .losers: overview.losers
        case .active: overview.active
        }
    }
}

// MARK: - Rows and tiles

struct QuoteRow: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let symbol: String
    let quote: MarketQuote?
    let unavailable: Bool
    var showsSparkline = true
    var detail: String? = nil

    var body: some View {
        HStack(spacing: Spacing.m) {
            VStack(alignment: .leading, spacing: 2) {
                Text(symbol).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                Text(detail ?? quote?.name ?? (unavailable ? "No quote available" : " "))
                    .font(.caption).foregroundStyle(Theme.textSecondary).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if showsSparkline && !typeSize.isAccessibilitySize, let line = quote?.sparkline, line.count >= 2 {
                Sparkline(values: line, baseline: quote?.previous_close, tone: MarketFormat.tone(quote?.change))
                    .frame(width: 64, height: 28)
            }
            VStack(alignment: .trailing, spacing: 3) {
                if let quote {
                    Text(MarketFormat.price(quote.price)).font(.subheadline.weight(.semibold)).monospacedDigit()
                        .foregroundStyle(Theme.textPrimary)
                    ChangePill(percent: quote.change_percent, minWidth: 70)
                } else if unavailable {
                    Text("—").font(.subheadline).foregroundStyle(Theme.textTertiary)
                } else {
                    Text("$000.00").font(.subheadline.weight(.semibold)).redacted(reason: .placeholder)
                    ChangePill(percent: nil, minWidth: 70).redacted(reason: .placeholder)
                }
            }
        }
        .padding(.vertical, Spacing.s)
        .frame(minHeight: 52)
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
        .accessibilityHint("Opens the quote page")
    }

    private var accessibilityText: String {
        guard let quote else { return "\(symbol), \(unavailable ? "no quote available" : "loading")" }
        let direction = (quote.change_percent ?? 0) >= 0 ? "up" : "down"
        let change = quote.change_percent.map { ", \(direction) \(String(format: "%.2f", abs($0))) percent" } ?? ""
        return "\(quote.name ?? symbol), \(symbol), \(MarketFormat.price(quote.price))\(change)"
    }
}

struct IndexTile: View {
    let quote: MarketQuote
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(alignment: .firstTextBaseline) {
                Text(quote.label ?? quote.symbol).font(.footnote.weight(.semibold)).foregroundStyle(Theme.textPrimary).lineLimit(1)
                Spacer(minLength: 0)
                Text(quote.symbol).font(.caption2).foregroundStyle(Theme.textTertiary)
            }
            Text(MarketFormat.price(quote.price)).font(.headline).monospacedDigit().foregroundStyle(Theme.textPrimary)
            Text("\(MarketFormat.change(quote.change)) (\(MarketFormat.percent(quote.change_percent)))")
                .font(.caption.weight(.medium)).monospacedDigit().foregroundStyle(MarketFormat.tone(quote.change).color)
                .lineLimit(1).minimumScaleFactor(0.8)
            if let line = quote.sparkline, line.count >= 2 {
                Sparkline(values: line, baseline: quote.previous_close, tone: MarketFormat.tone(quote.change)).frame(height: 30)
            }
        }
        .padding(Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Theme.separator, lineWidth: 1))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(quote.label ?? quote.symbol) via \(quote.symbol), \(MarketFormat.price(quote.price)), \(MarketFormat.percent(quote.change_percent))")
    }
}

/// Star toggle for adding or removing a symbol from the watchlist.
struct WatchButton: View {
    @Environment(AppStore.self) private var store
    let symbol: String
    var body: some View {
        let watching = store.watchlist.contains(symbol)
        Button { store.watchlist.toggle(symbol) } label: {
            Image(systemName: watching ? "star.fill" : "star")
                .font(.body.weight(.semibold))
                .foregroundStyle(watching ? Theme.warning : Theme.textSecondary)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(RowButtonStyle())
        .disabled(!watching && store.watchlist.isFull)
        .sensoryFeedback(.selection, trigger: watching)
        .accessibilityLabel(watching ? "Remove \(symbol) from watchlist" : "Add \(symbol) to watchlist")
    }
}

// MARK: - Watchlist editor

struct WatchlistEditor: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(store.watchlist.symbols, id: \.self) { symbol in
                        Text(symbol).font(.body.weight(.semibold)).monospaced()
                    }
                    .onDelete { store.watchlist.remove(atOffsets: $0) }
                    .onMove { store.watchlist.move(fromOffsets: $0, toOffset: $1) }
                } footer: {
                    Text("Drag to reorder, or swipe left to remove. The watchlist is saved on this iPhone.")
                }
            }
            .navigationTitle("Edit watchlist")
            .phoneInlineTitle()
            #if os(iOS)
            .environment(\.editMode, .constant(.active))
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
        }
    }
}
