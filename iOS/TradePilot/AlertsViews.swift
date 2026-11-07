import SwiftUI

// Price alerts: set on a quote page, watched by the gateway, listed in Markets.
// An alert only records that a price was reached; it never prepares or places an order.

struct AlertComposer: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let symbol: String
    let price: Double?
    var created: (PriceAlert) -> Void
    @State private var direction = "above"
    @State private var target = ""
    @State private var message = ""
    @State private var busy = false
    @State private var requestID = UUID().uuidString

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    Text("Alert me when \(symbol) is").font(.headline)
                    Picker("Direction", selection: $direction) {
                        Text("Above").tag("above"); Text("Below").tag("below")
                    }
                    .pickerStyle(.segmented)
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Eyebrow("Price")
                        TextField("0.00", text: $target).phoneDecimalInput().fieldStyle()
                            .font(.title3.weight(.semibold)).monospacedDigit()
                            .accessibilityLabel("Alert price")
                    }
                    if let price {
                        HStack(spacing: Spacing.s) {
                            ForEach([-10, -5, 5, 10], id: \.self) { step in
                                Button("\(step > 0 ? "+" : "")\(step)%") { apply(step: step, from: price) }
                                    .font(.footnote.weight(.semibold)).monospacedDigit()
                                    .frame(maxWidth: .infinity, minHeight: 36)
                                    .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: Radius.control, style: .continuous))
                                    .buttonStyle(RowButtonStyle())
                            }
                        }
                        Footnote("Last price \(MarketFormat.price(price)).\(reached ? " \(symbol) is already \(direction) this price, so the alert will trigger at the next check." : "")")
                    }
                    OutcomeNotice(text: message, kind: .error)
                    Footnote("Your server checks about once a minute during pre-market, regular and after-hours trading, and only prices after you create the alert count. Alerts never place orders. Open the app to see triggered alerts.")
                }
                .padding(Spacing.l)
            }
            .background(Theme.background)
            .safeAreaInset(edge: .bottom) {
                Button(busy ? "Creating…" : "Create alert") { create() }
                    .buttonStyle(PrimaryButtonStyle())
                    .disabled(busy || value == nil)
                    .padding(Spacing.l)
                    .background(Theme.surface)
            }
            .navigationTitle("Price alert")
            .phoneInlineTitle()
            .phoneNavigationTheme()
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(busy) } }
            .onAppear { if target.isEmpty, let price { apply(step: 5, from: price) } }
            .onChange(of: direction) { _, _ in requestID = UUID().uuidString }
            .onChange(of: target) { _, _ in requestID = UUID().uuidString; message = "" }
        }
        .tint(Theme.accent)
    }

    private var value: Decimal? {
        let text = target.trimmingCharacters(in: .whitespaces)
        guard let number = strictDecimal(text, allowNegative: false), number > 0,
              (text.split(separator: ".").dropFirst().first?.count ?? 0) <= 8 else { return nil }
        return number
    }

    private var reached: Bool {
        guard let value, let price else { return false }
        let level = NSDecimalNumber(decimal: value).doubleValue
        return direction == "above" ? price >= level : price <= level
    }

    private func apply(step: Int, from price: Double) {
        direction = step > 0 ? "above" : "below"
        let level = price * (1 + Double(step) / 100)
        target = String(format: level < 1 ? "%.4f" : "%.2f", level)
    }

    private func create() {
        guard let value, !busy else { return }
        busy = true
        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        let level = NSDecimalNumber(decimal: value).stringValue
        Task {
            defer { busy = false }
            do {
                let alert = try await AlertsAPI.create(symbol: symbol, direction: direction, target: level, clientID: requestID,
                                                       endpoint: binding.endpoint, token: binding.token)
                created(alert)
                dismiss()
            } catch { message = error.localizedDescription }
        }
    }
}

/// One alert row with an optional remove button.
struct AlertRow: View {
    let alert: PriceAlert
    var showsSymbol = true
    var remove: (() -> Void)? = nil
    var body: some View {
        HStack(spacing: Spacing.m) {
            Image(systemName: alert.isTriggered ? "bell.badge.fill" : "bell")
                .foregroundStyle(alert.isTriggered ? Theme.warning : Theme.textSecondary)
                .frame(width: 24).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(showsSymbol ? alert.headline : alert.condition).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                Text(detail).font(.caption).foregroundStyle(Theme.textSecondary)
            }
            Spacer(minLength: Spacing.s)
            if let remove {
                Button(action: remove) {
                    Image(systemName: "xmark.circle.fill").font(.title3).foregroundStyle(Theme.textTertiary)
                        .frame(width: 44, height: 44).contentShape(Rectangle())
                }
                .buttonStyle(RowButtonStyle())
                .accessibilityLabel(alert.isTriggered ? "Dismiss alert" : "Remove alert")
            }
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityElement(children: .combine)
    }
    private var detail: String {
        if alert.isTriggered, let at = alert.triggered_at {
            let price = alert.triggered_price.map { " at \(gatewayMoney($0))" } ?? ""
            return "Reached\(price) · \(MarketFormat.time(alert.price_as_of ?? at))"
        }
        return "Set \(relativeTime(alert.created_at)) · watching"
    }
}

/// All alerts: triggered first, then active, each removable.
struct AlertsListView: View {
    @Environment(AppStore.self) private var store
    @State private var snapshot: AlertsSnapshot?
    @State private var message = ""
    @State private var busy = false

    private var binding: BrokerConnectionBinding { .init(endpoint: store.aiEndpoint, token: store.aiToken) }

    var body: some View {
        SubScreen(title: "Price alerts", refresh: { await load() }) {
            OutcomeNotice(text: message, kind: .error)
            if let snapshot {
                let triggered = snapshot.alerts.filter(\.isTriggered)
                let active = snapshot.alerts.filter(\.isActive)
                if snapshot.alerts.isEmpty {
                    EmptyState(title: "No alerts", message: "Open a quote page and tap the bell to be alerted when a price is reached.", icon: "bell")
                }
                if !triggered.isEmpty {
                    SectionCard(title: "Triggered") {
                        ForEach(triggered) { alert in
                            NavigationLink { SymbolDetailView(symbol: alert.symbol) } label: {
                                AlertRow(alert: alert, remove: { remove(alert) })
                            }.buttonStyle(RowButtonStyle())
                        }
                        Button("Clear all triggered") { clear() }.buttonStyle(SecondaryButtonStyle()).disabled(busy)
                    }
                }
                if !active.isEmpty {
                    SectionCard(title: "Watching", footer: "\(active.count) of 50 active alerts.") {
                        ForEach(active) { alert in
                            NavigationLink { SymbolDetailView(symbol: alert.symbol) } label: {
                                AlertRow(alert: alert, remove: { remove(alert) })
                            }.buttonStyle(RowButtonStyle())
                        }
                    }
                }
                Footnote(snapshot.notice + " Your server checks about once a minute during trading sessions; open the app to see triggered alerts.")
            } else if busy {
                ProgressView().frame(maxWidth: .infinity).padding(.vertical, Spacing.xl)
            }
        }
        .task(id: binding) { await load() }
    }

    private func load() async {
        let request = binding
        guard store.hasServerSettings else { message = "Connect your server in Settings to use alerts."; return }
        busy = true
        defer { busy = false }
        do {
            let loaded = try await AlertsAPI.state(endpoint: request.endpoint, token: request.token)
            guard request == binding else { return }
            snapshot = loaded; message = ""
        } catch { if request == binding { message = error.localizedDescription } }
    }

    private func remove(_ alert: PriceAlert) {
        let request = binding
        Task {
            do {
                let updated = try await AlertsAPI.remove(alert.id, endpoint: request.endpoint, token: request.token)
                if request == binding { snapshot = updated; message = "" }
            } catch { if request == binding { message = error.localizedDescription } }
        }
    }

    private func clear() {
        let request = binding
        busy = true
        Task {
            defer { busy = false }
            do {
                let updated = try await AlertsAPI.clearTriggered(endpoint: request.endpoint, token: request.token)
                if request == binding { snapshot = updated; message = "" }
            } catch { if request == binding { message = error.localizedDescription } }
        }
    }
}
