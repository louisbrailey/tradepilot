import SwiftUI

// Quote page for one symbol. Read-only; the trade button opens the existing
// paper order screen, which keeps its own review and confirmation.

struct SymbolDetailView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var typeSize
    let symbol: String
    @State private var page: SymbolPage?
    @State private var pageBinding: BrokerConnectionBinding?
    @State private var history: PriceHistory?
    @State private var range = ChartRange.day
    @State private var selection: Int?
    @State private var position: PaperPosition?
    @State private var message = ""
    @State private var chartMessage = ""
    @State private var loading = false
    @State private var chartLoading = false
    @State private var showFullDescription = false
    @State private var alerts: [PriceAlert] = []
    @State private var alertsAvailable = true
    @State private var composingAlert = false

    private var binding: BrokerConnectionBinding { .init(endpoint: store.aiEndpoint, token: store.aiToken) }
    private var current: SymbolPage? { pageBinding == binding ? page : nil }

    var body: some View {
        SubScreen(title: symbol, refresh: { await load() }) {
            header
            if !message.isEmpty { InlineNotice(kind: current == nil ? .error : .warning, message: message) }
            chartCard
            actions
            if let position { positionCard(position) }
            if alertsAvailable && store.hasServerSettings { alertsCard }
            if let current {
                statsCard(current)
                if let dividend = current.dividend { dividendCard(dividend) }
                aboutCard(current)
                newsCard(current)
                Footnote("Market data from Massive via your TradePilot server, as of \(MarketFormat.time(current.as_of)). Prices can be delayed and aren’t executable quotes. Not investment advice.")
            } else if loading {
                ProgressView("Loading \(symbol)").frame(maxWidth: .infinity).padding(.vertical, Spacing.xl)
            }
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                if alertsAvailable && store.hasServerSettings {
                    Button { composingAlert = true } label: { Image(systemName: "bell.badge") }
                        .accessibilityLabel("Add price alert for \(symbol)")
                }
                WatchButton(symbol: symbol)
            }
        }
        .sheet(isPresented: $composingAlert) {
            AlertComposer(symbol: symbol, price: current?.quote?.price) { alert in
                alerts.removeAll { $0.id == alert.id }
                alerts.insert(alert, at: 0)
            }
        }
        .task(id: PageKey(binding: binding, active: scenePhase == .active)) {
            guard scenePhase == .active else { return }
            await load()
            // Keep the price current while the page is open during trading hours.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(current?.status.isTrading == true ? 20 : 300))
                guard !Task.isCancelled else { return }
                await load(quiet: true)
            }
        }
        .task(id: ChartKey(binding: binding, range: range)) { await loadChart() }
    }

    // MARK: Header and chart

    private var header: some View {
        let quote = current?.quote
        let points = history?.points ?? []
        let scrubbed = selection.flatMap { points.indices.contains($0) ? points[$0] : nil }
        let reference = range == .day ? (quote?.previous_close ?? history?.baseline) : (history?.baseline ?? points.first?.c)
        let shown = scrubbed?.c ?? (range == .day ? quote?.price : points.last?.c ?? quote?.price)
        let change = shown.flatMap { value in reference.map { value - $0 } }
        let percent = change.flatMap { delta in reference.flatMap { $0 > 0 ? delta / $0 * 100 : nil } }
        return VStack(alignment: .leading, spacing: Spacing.s) {
            HStack(spacing: Spacing.m) {
                SymbolMonogram(symbol: symbol, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text(current?.name ?? symbol).font(.headline).foregroundStyle(Theme.textPrimary).lineLimit(2)
                    Text([symbol, current?.profile.exchange, current?.profile.type].compactMap { $0 }.joined(separator: " · "))
                        .font(.caption).foregroundStyle(Theme.textSecondary)
                }
                Spacer(minLength: 0)
                if let status = current?.status { StatusBadge(MarketFormat.session(status).label, tone: MarketFormat.session(status).tone) }
            }
            Text(MarketFormat.price(shown))
                .font(.system(.largeTitle, design: .rounded).weight(.semibold)).monospacedDigit()
                .foregroundStyle(Theme.textPrimary)
                .contentTransition(.numericText())
                .accessibilityLabel("Price \(MarketFormat.price(shown))")
            HStack(spacing: Spacing.s) {
                Text("\(MarketFormat.change(change)) (\(MarketFormat.percent(percent)))")
                    .font(.subheadline.weight(.semibold)).monospacedDigit()
                    .foregroundStyle(MarketFormat.tone(change).color)
                Text(scrubbed.map { MarketFormat.chartTime($0.t, range: range) } ?? range.changeLabel)
                    .font(.subheadline).foregroundStyle(Theme.textSecondary)
            }
            if scrubbed == nil, range == .day, let extended = quote?.extended {
                Text("After hours \(MarketFormat.price(extended.price)) \(MarketFormat.change(extended.change)) (\(MarketFormat.percent(extended.change_percent)))")
                    .font(.footnote.weight(.medium)).monospacedDigit()
                    .foregroundStyle(MarketFormat.tone(extended.change).color)
            }
            if scrubbed == nil, let quote, let state = current?.status.state {
                Text(Self.priceCaption(state: state, quote: quote))
                    .font(.caption).foregroundStyle(Theme.textTertiary)
            }
        }
    }

    private var chartCard: some View {
        VStack(alignment: .leading, spacing: Spacing.m) {
            ZStack {
                if let history, history.points.count >= 2 {
                    PriceChart(points: history.points, baseline: range == .day ? (current?.quote?.previous_close ?? history.baseline) : history.baseline,
                               range: range, selection: $selection)
                } else if chartLoading {
                    ProgressView()
                } else {
                    Text(chartMessage.isEmpty ? "No price history for this range yet." : chartMessage)
                        .font(.footnote).foregroundStyle(Theme.textSecondary).multilineTextAlignment(.center)
                }
            }
            .frame(height: 220)
            .frame(maxWidth: .infinity)
            .opacity(chartLoading && history != nil ? 0.5 : 1)
            Group {
                if typeSize.isAccessibilitySize {
                    ScrollView(.horizontal, showsIndicators: false) { rangeChips(fill: false) }
                } else {
                    rangeChips(fill: true)
                }
            }
            .sensoryFeedback(.selection, trigger: range)
            if let history, history.regular_hours_only {
                Footnote("Regular trading hours · \(history.interval) bars")
            }
        }
    }

    private func rangeChips(fill: Bool) -> some View {
        HStack(spacing: Spacing.xs) {
            ForEach(ChartRange.allCases) { option in
                Button { range = option; selection = nil } label: {
                    Text(option.rawValue).lineLimit(1).fixedSize()
                        .padding(.horizontal, fill ? 0 : Spacing.m)
                        .frame(maxWidth: fill ? .infinity : nil, minHeight: 32)
                        .contentShape(Rectangle())
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(range == option ? Theme.onAccent : Theme.textSecondary)
                .background(range == option ? Theme.accent : Color.clear, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                .buttonStyle(RowButtonStyle())
                .accessibilityLabel(option.changeLabel)
                .accessibilityAddTraits(range == option ? .isSelected : [])
            }
        }
    }

    private var actions: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: Spacing.m)) : AnyLayout(HStackLayout(spacing: Spacing.m))
        return layout {
            NavigationLink { PaperTradingView(prefillSymbol: symbol) } label: {
                Label("Trade on paper", systemImage: "arrow.left.arrow.right")
            }
            .buttonStyle(PrimaryButtonStyle())
            NavigationLink { KronosView(ticker: symbol) } label: {
                Label("Forecast lab", systemImage: "waveform.path.ecg")
            }
            .buttonStyle(SecondaryButtonStyle())
        }
    }

    // MARK: Cards

    private var alertsCard: some View {
        SectionCard(title: "Price alerts") {
            if alerts.isEmpty {
                Footnote("Get an alert in the app when \(symbol) reaches a price you choose.")
            } else {
                ForEach(alerts) { alert in
                    AlertRow(alert: alert, showsSymbol: false, remove: { removeAlert(alert) })
                }
            }
            Button { composingAlert = true } label: { Label("Add price alert", systemImage: "bell.badge") }
                .buttonStyle(SecondaryButtonStyle())
        }
    }

    private func removeAlert(_ alert: PriceAlert) {
        let request = binding
        Task {
            do {
                let updated = try await AlertsAPI.remove(alert.id, endpoint: request.endpoint, token: request.token)
                if request == binding { alerts = updated.alerts.filter { $0.symbol == symbol } }
            } catch { if request == binding { message = error.localizedDescription } }
        }
    }

    private func positionCard(_ position: PaperPosition) -> some View {
        SectionCard(title: "Your paper position") {
            MetricsGrid {
                MetricTile(label: "Shares", value: position.quantity)
                MetricTile(label: "Market value", value: workspaceMoney(position.market_value))
                MetricTile(label: "Unrealized P/L", value: workspaceMoney(position.unrealized_pnl, signed: true),
                           tone: strictDecimal(position.unrealized_pnl).map { $0 > 0 ? .positive : $0 < 0 ? .negative : .neutral })
                if let average = position.average_cost { MetricTile(label: "Average cost", value: workspaceMoney(average)) }
            }
            Footnote("Valued at the paper account’s last saved reference price, which can differ from the quote above.")
        }
    }

    private func statsCard(_ page: SymbolPage) -> some View {
        let stats = page.stats, quote = page.quote
        let rows: [(String, String)] = [
            ("Open", MarketFormat.price(stats.open)), ("Prev close", MarketFormat.price(stats.previous_close)),
            ("Day high", MarketFormat.price(stats.high)), ("Day low", MarketFormat.price(stats.low)),
            ("Volume", MarketFormat.compact(stats.volume)), ("Avg volume", MarketFormat.compact(stats.average_volume)),
            ("Market cap", MarketFormat.compactMoney(stats.market_cap)), ("P/E ratio", MarketFormat.ratio(stats.pe_ratio)),
            ("EPS (TTM)", stats.eps.map { MarketFormat.price($0) } ?? "—"),
            ("Dividend yield", stats.dividend_yield.map { String(format: "%.2f%%", $0) } ?? "—"),
            ("Bid / ask", quote.flatMap { q in q.bid.flatMap { bid in q.ask.map { "\(MarketFormat.price(bid)) / \(MarketFormat.price($0))" } } } ?? "—"),
            ("VWAP", MarketFormat.price(stats.vwap)),
        ]
        return SectionCard(title: "Key statistics") {
            if typeSize.isAccessibilitySize {
                VStack(spacing: Spacing.s) { ForEach(rows, id: \.0) { DetailRow($0.0, $0.1) } }
            } else {
                Grid(alignment: .leading, horizontalSpacing: Spacing.xl, verticalSpacing: Spacing.m) {
                    ForEach(Array(stride(from: 0, to: rows.count, by: 2)), id: \.self) { index in
                        GridRow { stat(rows[index].0, rows[index].1); stat(rows[index + 1].0, rows[index + 1].1) }
                    }
                }
            }
            Divider().overlay(Theme.separator)
            PriceRangeBar(title: "Day range", low: stats.low, high: stats.high, current: quote?.price)
            PriceRangeBar(title: "52-week range", low: stats.week52_low, high: stats.week52_high, current: quote?.price)
            if !page.unavailable.isEmpty {
                Footnote("Some details are unavailable right now: \(page.unavailable.map(Self.datasetName).joined(separator: ", ")).")
            }
        }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption).foregroundStyle(Theme.textSecondary)
            Text(value).font(.subheadline.weight(.semibold)).monospacedDigit().foregroundStyle(Theme.textPrimary)
                .lineLimit(1).minimumScaleFactor(0.75)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func dividendCard(_ dividend: SymbolDividend) -> some View {
        let upcoming = dividend.ex_date >= Self.today
        return SectionCard(title: upcoming ? "Upcoming dividend" : "Latest dividend") {
            DetailRow("Amount per share", MarketFormat.price(dividend.amount) + (dividend.frequency.map { " · \($0.lowercased())" } ?? ""))
            DetailRow("Ex-dividend date", Self.displayDate(dividend.ex_date))
            if let pay = dividend.pay_date { DetailRow("Pay date", Self.displayDate(pay)) }
            if upcoming { Footnote("Own shares before the ex-dividend date to receive this dividend.") }
        }
    }

    private func aboutCard(_ page: SymbolPage) -> some View {
        let profile = page.profile
        return SectionCard(title: "About") {
            if let description = profile.description {
                Text(description).font(.subheadline).foregroundStyle(Theme.textPrimary)
                    .lineLimit(showFullDescription ? nil : 4)
                    .fixedSize(horizontal: false, vertical: true)
                if description.count > 220 {
                    Button(showFullDescription ? "Show less" : "Show more") { withAnimation { showFullDescription.toggle() } }
                        .font(.footnote.weight(.semibold))
                }
            }
            VStack(spacing: Spacing.s) {
                if let industry = profile.industry { DetailRow("Industry", industry) }
                if let employees = profile.employees { DetailRow("Employees", employees.formatted(.number.precision(.fractionLength(0)))) }
                if let listed = profile.listed { DetailRow("Listed", Self.displayDate(listed)) }
                if let shares = page.stats.shares_outstanding { DetailRow("Shares outstanding", MarketFormat.compact(shares)) }
            }
            if let homepage = profile.homepage, let url = URL(string: homepage) {
                Link(destination: url) {
                    Label(url.host ?? homepage, systemImage: "safari").font(.footnote.weight(.semibold))
                }
            }
            if profile.description == nil && profile.industry == nil {
                Footnote("No company profile is available for this security.")
            }
        }
    }

    private func newsCard(_ page: SymbolPage) -> some View {
        SectionCard(title: "News") {
            if page.news.isEmpty {
                Footnote(page.unavailable.contains("news") ? "Headlines are unavailable right now." : "No recent headlines.")
            } else {
                VStack(spacing: 0) {
                    ForEach(page.news) { item in
                        if item.id != page.news.first?.id { Divider().overlay(Theme.separator) }
                        if let url = URL(string: item.url) {
                            Link(destination: url) { NewsRow(item: item) }.buttonStyle(RowButtonStyle())
                        }
                    }
                }
            }
        }
    }

    // MARK: Loading

    private func load(quiet: Bool = false) async {
        let request = binding
        guard store.hasServerSettings else { message = "Connect your server in Settings to see market data."; return }
        guard !loading else { return }
        loading = !quiet
        defer { loading = false }
        async let details = MarketAPI.symbol(symbol, endpoint: request.endpoint, token: request.token)
        async let paper: PaperSnapshot = WorkspaceAPI.request("v1/paper/state", body: EmptyWorkspaceRequest(),
                                                               endpoint: request.endpoint, token: request.token)
        do {
            let loaded = try await details
            guard !Task.isCancelled, request == binding else { return }
            page = loaded; pageBinding = request; message = ""
        } catch {
            guard !Task.isCancelled, request == binding else { return }
            if !quiet || page == nil { message = error.localizedDescription }
        }
        if let snapshot = try? await paper, request == binding, snapshot.mode == "paper" {
            position = snapshot.positions.first { $0.symbol == symbol }
        }
        do {
            let snapshot = try await AlertsAPI.state(endpoint: request.endpoint, token: request.token)
            if request == binding { alerts = snapshot.alerts.filter { $0.symbol == symbol }; alertsAvailable = true }
        } catch {
            // An older gateway has no alert routes; hide the feature rather than show an error.
            if request == binding, (error as? WorkspaceError)?.message.contains("needs an update") == true { alertsAvailable = false }
        }
    }

    private func loadChart() async {
        let request = binding, wanted = range
        guard store.hasServerSettings else { return }
        chartLoading = true
        defer { if wanted == range { chartLoading = false } }
        do {
            let loaded = try await MarketAPI.chart(symbol, range: wanted, endpoint: request.endpoint, token: request.token)
            guard !Task.isCancelled, request == binding, wanted == range else { return }
            history = loaded; chartMessage = ""; selection = nil
        } catch {
            guard !Task.isCancelled, request == binding, wanted == range else { return }
            history = nil; chartMessage = error.localizedDescription
        }
    }

    // MARK: Helpers

    /// The main price is the session's latest price while trading, and the official close afterwards.
    static func priceCaption(state: String, quote: MarketQuote) -> String {
        switch state {
        case "open": return quote.updated.map { "Updated \(MarketFormat.time($0))" } ?? "Live session"
        case "pre_market": return quote.updated.map { "Pre-market · updated \(MarketFormat.time($0))" } ?? "Pre-market"
        default: return quote.change == nil ? "Last close" : "At close"
        }
    }

    private static var today: String {
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = MarketFormat.eastern
        let parts = calendar.dateComponents([.year, .month, .day], from: Date())
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }

    static func displayDate(_ iso: String) -> String {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX"); parser.timeZone = TimeZone(identifier: "UTC"); parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: iso) else { return iso }
        var style = Date.FormatStyle(date: .abbreviated, time: .omitted); style.timeZone = TimeZone(identifier: "UTC") ?? .current
        return date.formatted(style)
    }

    private static func datasetName(_ key: String) -> String {
        switch key {
        case "ratios": "valuation ratios"
        case "dividends": "dividends"
        case "news": "headlines"
        case "year": "52-week range"
        case "details": "company profile"
        case "snapshot": "live quote"
        default: key
        }
    }
}

private struct PageKey: Equatable { let binding: BrokerConnectionBinding; let active: Bool }
private struct ChartKey: Equatable { let binding: BrokerConnectionBinding; let range: ChartRange }

struct NewsRow: View {
    let item: NewsItem
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.s) {
                Text([item.publisher, relativeTime(item.published)].compactMap { $0 }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(Theme.textTertiary).lineLimit(1)
                Spacer(minLength: 0)
                if let sentiment = item.sentiment, sentiment != "neutral" {
                    StatusBadge(sentiment.capitalized, tone: sentiment == "positive" ? .positive : .negative)
                }
            }
            Text(item.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, Spacing.m)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the article in Safari")
    }
}
