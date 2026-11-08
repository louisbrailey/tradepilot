import SwiftUI

// Read-only option chain for research. TradePilot cannot place option orders; nothing here can.

struct OptionsChainView: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dynamicTypeSize) private var typeSize
    let symbol: String
    @State private var chain: OptionChain?
    @State private var expiration: String?
    @State private var side = "call"
    @State private var showAll = false
    @State private var message = ""
    @State private var loading = false
    @State private var selected: OptionContract?
    @State private var loadID = UUID()

    private var binding: BrokerConnectionBinding { .init(endpoint: store.aiEndpoint, token: store.aiToken) }

    var body: some View {
        SubScreen(title: "\(symbol) options", refresh: {
            if expiration == nil { await load() } else { expiration = nil }
        }) {
            HStack { StatusBadge("Research only", tone: .accent); Spacer(); if loading { ProgressView() } }
            if !message.isEmpty { InlineNotice(kind: chain == nil ? .error : .warning, message: message) }
            if let chain {
                if chain.expirations.isEmpty {
                    EmptyState(title: "No listed options", message: "\(symbol) has no option contracts with upcoming expirations.", icon: "chart.bar.doc.horizontal")
                } else {
                    header(chain)
                    expirations(chain)
                    Picker("Side", selection: $side) { Text("Calls").tag("call"); Text("Puts").tag("put") }
                        .pickerStyle(.segmented)
                    table(chain)
                }
                Footnote("Chain fetched from Massive at \(MarketFormat.time(chain.as_of)). Quotes can be delayed. Contract sizes and deliverables can vary; see contract details. TradePilot cannot trade options.")
            } else if loading {
                ProgressView("Loading option chain").frame(maxWidth: .infinity).padding(.vertical, Spacing.xl)
            }
        }
        .task(id: OptionsKey(binding: binding, expiration: expiration)) { await load() }
        .sheet(item: $selected) { OptionContractSheet(contract: $0, symbol: symbol, underlying: chain?.underlying) }
    }

    private func header(_ chain: OptionChain) -> some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Eyebrow("\(symbol) last price")
                Text(MarketFormat.price(chain.underlying)).font(.title2.weight(.semibold)).monospacedDigit()
            }
            Spacer()
            if let date = chain.expiration {
                VStack(alignment: .trailing, spacing: 2) {
                    Eyebrow("Expires")
                    Text(Self.label(date)).font(.subheadline.weight(.semibold))
                }
            }
        }
    }

    private func expirations(_ chain: OptionChain) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.s) {
                ForEach(chain.expirations, id: \.self) { date in
                    let active = date == chain.expiration
                    Button { expiration = date } label: {
                        VStack(spacing: 1) {
                            Text(Self.shortDate(date)).font(.caption.weight(.semibold))
                            Text(Self.daysOut(date)).font(.caption2)
                        }
                        .padding(.horizontal, Spacing.m).padding(.vertical, Spacing.xs)
                        .foregroundStyle(active ? Theme.onAccent : Theme.textSecondary)
                        .background(active ? Theme.accent : Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(RowButtonStyle())
                    .accessibilityLabel("Expires \(Self.label(date))")
                    .accessibilityAddTraits(active ? .isSelected : [])
                }
            }
        }
        .sensoryFeedback(.selection, trigger: chain.expiration)
    }

    @ViewBuilder private func table(_ chain: OptionChain) -> some View {
        let rows = visibleStrikes(chain)
        SectionCard {
            if !typeSize.isAccessibilitySize {
                HStack {
                    column("Strike", leading: true); column("Bid"); column("Ask"); column("IV"); column("Delta")
                }
                .font(.caption.weight(.semibold)).foregroundStyle(Theme.textTertiary)
            }
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if let price = chain.underlying, index > 0, rows[index - 1].strike < price, row.strike >= price {
                        PriceMarker(price: price)
                    }
                    if let contract = side == "call" ? row.call : row.put {
                        Button { selected = contract } label: { OptionRow(contract: contract, inTheMoney: inTheMoney(contract, chain)) }
                            .buttonStyle(RowButtonStyle())
                    }
                }
            }
            if chain.strikes.count > rows.count || showAll {
                Button(showAll ? "Show strikes near the price" : "Show all \(chain.strikes.count) strikes") { showAll.toggle() }
                    .font(.footnote.weight(.semibold))
            }
            Footnote("Tinted rows are in the money. Tap a contract for its Greeks, volume and open interest.")
        }
    }

    private func column(_ title: String, leading: Bool = false) -> some View {
        Text(title).frame(maxWidth: .infinity, alignment: leading ? .leading : .trailing)
    }

    /// Twelve strikes either side of the last price unless the whole chain is requested.
    private func visibleStrikes(_ chain: OptionChain) -> [OptionStrike] {
        guard !showAll, let price = chain.underlying, chain.strikes.count > 24 else { return chain.strikes }
        let center = chain.strikes.firstIndex { $0.strike >= price } ?? chain.strikes.count - 1
        let lower = max(0, center - 12), upper = min(chain.strikes.count, center + 12)
        return Array(chain.strikes[lower..<upper])
    }

    private func inTheMoney(_ contract: OptionContract, _ chain: OptionChain) -> Bool {
        guard let price = chain.underlying else { return false }
        return contract.type == "call" ? contract.strike < price : contract.strike > price
    }

    private func load() async {
        let request = binding, wanted = expiration
        let attempt = UUID(); loadID = attempt
        guard store.hasServerSettings else { chain = nil; message = "Connect your server in Settings to see options."; loading = false; return }
        loading = true
        defer { if attempt == loadID { loading = false } }
        do {
            let loaded = try await MarketAPI.options(symbol, expiration: wanted, endpoint: request.endpoint, token: request.token)
            guard attempt == loadID, request == binding, wanted == expiration else { return }
            chain = loaded; message = ""
        } catch {
            guard attempt == loadID, request == binding, wanted == expiration else { return }
            message = error.localizedDescription
        }
    }

    static func date(_ iso: String) -> Date? {
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX"); parser.timeZone = MarketFormat.eastern; parser.dateFormat = "yyyy-MM-dd"
        return parser.date(from: iso)
    }

    static func shortDate(_ iso: String) -> String {
        guard let date = date(iso) else { return iso }
        var style = Date.FormatStyle().month(.abbreviated).day(); style.timeZone = MarketFormat.eastern
        return date.formatted(style)
    }

    static func label(_ iso: String) -> String { "\(SymbolDetailView.displayDate(iso)) · \(daysOut(iso))" }

    static func daysOut(_ iso: String) -> String {
        guard let date = date(iso) else { return "" }
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = MarketFormat.eastern
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: Date()), to: date).day ?? 0
        return days <= 0 ? "today" : "\(days)d"
    }
}

private struct OptionsKey: Equatable { let binding: BrokerConnectionBinding; let expiration: String? }

private struct OptionRow: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let contract: OptionContract
    let inTheMoney: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Strike \(MarketFormat.price(contract.strike))").font(.subheadline.weight(.semibold))
                    Text("Bid \(MarketFormat.premium(contract.bid)) · Ask \(MarketFormat.premium(contract.ask))").font(.subheadline)
                    Text("IV \(iv) · Delta \(delta)").font(.subheadline).foregroundStyle(Theme.textSecondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                HStack {
                    cell(MarketFormat.price(contract.strike), leading: true, weight: .semibold)
                    cell(MarketFormat.premium(contract.bid))
                    cell(MarketFormat.premium(contract.ask))
                    cell(iv)
                    cell(delta)
                }
                .font(.subheadline).monospacedDigit()
            }
            if contract.standard_contract == false {
                Text("\(contract.series ?? "Adjusted") · nonstandard contract")
                    .font(.caption2).foregroundStyle(Theme.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.vertical, Spacing.s).padding(.horizontal, Spacing.xs)
        .background(inTheMoney ? Theme.accent.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        .contentShape(Rectangle())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(contract.type == "call" ? "Call" : "Put") strike \(MarketFormat.price(contract.strike)), bid \(MarketFormat.premium(contract.bid)), ask \(MarketFormat.premium(contract.ask)), implied volatility \(iv)\(inTheMoney ? ", in the money" : "")\(contract.standard_contract == false ? ", nonstandard contract \(contract.series ?? "")" : "")")
        .accessibilityHint("Shows contract details")
    }
    private var iv: String { contract.implied_volatility.map { String(format: "%.1f%%", $0) } ?? "—" }
    private var delta: String { contract.delta.map { String(format: "%.2f", $0) } ?? "—" }
    private func cell(_ text: String, leading: Bool = false, weight: Font.Weight = .regular) -> some View {
        Text(text).fontWeight(weight).lineLimit(1).minimumScaleFactor(0.75)
            .frame(maxWidth: .infinity, alignment: leading ? .leading : .trailing)
            .foregroundStyle(Theme.textPrimary)
    }
}

private struct PriceMarker: View {
    let price: Double
    var body: some View {
        HStack(spacing: Spacing.s) {
            Rectangle().fill(Theme.accent).frame(height: 1)
            Text("Last \(MarketFormat.price(price))").font(.caption.weight(.semibold)).foregroundStyle(Theme.accent).fixedSize()
            Rectangle().fill(Theme.accent).frame(height: 1)
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityLabel("Last price \(MarketFormat.price(price))")
    }
}

struct OptionContractSheet: View {
    @Environment(\.dismiss) private var dismiss
    let contract: OptionContract
    let symbol: String
    let underlying: Double?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    HStack { StatusBadge(contract.type == "call" ? "Call" : "Put", tone: .accent); StatusBadge("Research only"); Spacer() }
                    Text("\(symbol) \(MarketFormat.price(contract.strike)) \(contract.type)").font(.title2.weight(.semibold))
                    SectionCard(title: "Contract") {
                        DetailRow("Symbol", contract.contract.replacingOccurrences(of: "O:", with: ""))
                        DetailRow("Shares per contract", MarketFormat.compact(contract.shares_per_contract))
                        if contract.standard_contract != true {
                            Footnote("Standard contract terms are not confirmed. Deliverables may include other shares or cash; a contract premium estimate is unavailable.")
                        }
                    }
                    SectionCard(title: "Quote") {
                        DetailRow("Bid", MarketFormat.premium(contract.bid))
                        DetailRow("Ask", MarketFormat.premium(contract.ask))
                        DetailRow("Mid", MarketFormat.premium(contract.mid))
                        DetailRow("Last trade", MarketFormat.premium(contract.last))
                        DetailRow("Change today", MarketFormat.percent(contract.change_percent))
                        DetailRow("Volume", MarketFormat.compact(contract.volume))
                        DetailRow("Open interest", MarketFormat.compact(contract.open_interest))
                        DetailRow("Break-even", MarketFormat.price(contract.break_even))
                        if let premium = contract.estimatedPremium { DetailRow("Estimated premium at mid", MarketFormat.price(premium)) }
                        DetailRow("Quote updated", MarketFormat.time(contract.quote_updated))
                    }
                    SectionCard(title: "Greeks", footer: "Model estimates from the data provider; they change with price, time and volatility.") {
                        DetailRow("Implied volatility", contract.implied_volatility.map { String(format: "%.1f%%", $0) } ?? "—")
                        DetailRow("Delta", contract.delta.map { String(format: "%.3f", $0) } ?? "—")
                        DetailRow("Gamma", contract.gamma.map { String(format: "%.4f", $0) } ?? "—")
                        DetailRow("Theta (per day)", contract.theta.map { String(format: "%.3f", $0) } ?? "—")
                        DetailRow("Vega", contract.vega.map { String(format: "%.3f", $0) } ?? "—")
                    }
                    Footnote("Contract \(contract.contract.replacingOccurrences(of: "O:", with: "")), updated \(MarketFormat.time(contract.updated)). TradePilot cannot trade options.")
                }
                .padding(Spacing.l)
            }
            .background(Theme.background)
            .navigationTitle("Contract")
            .phoneInlineTitle()
            .phoneNavigationTheme()
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .tint(Theme.accent)
    }
}
