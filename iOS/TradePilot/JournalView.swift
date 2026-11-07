import SwiftUI
import TradeCore

struct JournalReflection: Codable, Sendable {
    let eventID: UUID
    let thesis: String
    let expectedOutcome: String
    let observation: String
    let lesson: String

    var retrievalText: String {
        "Thesis: \(thesis)\nExpected outcome: \(expectedOutcome)\nWhat happened: \(observation)\nLesson: \(lesson)"
    }
}

struct JournalEntry: Identifiable, Codable, Sendable {
    let id: UUID
    let sessionID: UUID
    let timestamp: Date
    let kind: String
    let text: String
    let strategy: String
    let accountID: String
    let mode: String
    let reference: String?
    let holdings: [Holding]
    var order: Order?
    let reflection: JournalReflection?

    init(id: UUID, sessionID: UUID, timestamp: Date, kind: String, text: String, strategy: String, accountID: String, mode: String, reference: String?, holdings: [Holding], order: Order? = nil, reflection: JournalReflection? = nil) {
        self.id = id; self.sessionID = sessionID; self.timestamp = timestamp; self.kind = kind; self.text = text
        self.strategy = strategy; self.accountID = accountID; self.mode = mode; self.reference = reference
        self.holdings = holdings; self.order = order; self.reflection = reflection
    }

    private enum CodingKeys: String, CodingKey { case id, sessionID, timestamp, kind, text, strategy, accountID, mode, reference, holdings, order, reflection }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(UUID.self, forKey: .id)
        sessionID = try values.decode(UUID.self, forKey: .sessionID)
        timestamp = try values.decode(Date.self, forKey: .timestamp)
        kind = try values.decode(String.self, forKey: .kind)
        text = try values.decode(String.self, forKey: .text)
        strategy = try values.decodeIfPresent(String.self, forKey: .strategy) ?? "unclassified"
        accountID = try values.decodeIfPresent(String.self, forKey: .accountID) ?? "unknown"
        mode = try values.decodeIfPresent(String.self, forKey: .mode) ?? "unknown"
        reference = try values.decodeIfPresent(String.self, forKey: .reference)
        holdings = try values.decodeIfPresent([Holding].self, forKey: .holdings) ?? []
        order = try values.decodeIfPresent(Order.self, forKey: .order)
        reflection = try values.decodeIfPresent(JournalReflection.self, forKey: .reflection)
    }
}

enum JournalEvidence {
    static func matches(_ entry: JournalEntry, environment: String, strategy: String, kind: String) -> Bool {
        let environmentMatches = switch environment {
        case "all": true
        case "demo", "paper": entry.mode == environment
        case "research": entry.mode == "historical_research"
        case "webull": entry.mode.hasPrefix("webull_")
        default: false
        }
        return environmentMatches && (strategy == "all" || entry.strategy == strategy) && (kind == "all" || entry.kind == kind)
    }

    static func verifiedDemoFill(_ entry: JournalEntry) -> Bool {
        entry.mode == "demo" && entry.kind == "outcome" && entry.order?.status == .filled
    }
}

struct StrategyProfile: Identifiable {
    let id: String
    let title: String
    let horizon: String
    let question: String
    let requirements: String
    static let all: [StrategyProfile] = [
        .init(id: "long_term", title: "Long-term investing", horizon: "Months to years", question: "Diversification, allocation and valuation", requirements: "Fundamentals, total returns, dividends and a suitable benchmark."),
        .init(id: "trend", title: "Trend & momentum", horizon: "Days to months", question: "Does price persistence survive costs?", requirements: "Adjusted bars, volatility and chronological holdout evaluation."),
        .init(id: "mean_reversion", title: "Mean reversion", horizon: "Hours to weeks", question: "When do deviations reverse?", requirements: "Regime filters, spread estimates and gap risk analysis."),
        .init(id: "intraday", title: "Intraday trading", horizon: "Minutes to hours", question: "Session structure, liquidity and execution", requirements: "Timely quotes, intraday bars, exchange calendars and realistic slippage. Delayed Developer data is for research, not execution pricing."),
        .init(id: "dividend", title: "Dividend income", horizon: "Months to years", question: "Income sustainability and total return", requirements: "Payout history, corporate actions, fundamentals and tax/account context. Yield alone is insufficient."),
        .init(id: "short", title: "Short selling", horizon: "Days to months", question: "Downside thesis and asymmetric risk", requirements: "Borrow availability and fees, margin, recalls and dividends owed. Research only; execution is not implemented."),
        .init(id: "options", title: "Options & hedging", horizon: "Days to months", question: "Volatility, defined risk and protection", requirements: "Contract histories, quotes, Greeks, implied volatility, assignment and expiry. Research only; execution is not implemented."),
        .init(id: "news", title: "News & event studies", horizon: "Minutes to weeks", question: "What changed, and when was it known?", requirements: "Benzinga publication and revision timestamps, corporate events and point-in-time prices."),
        .init(id: "crypto", title: "Crypto regimes", horizon: "Hours to months", question: "24/7 momentum, liquidity and concentration", requirements: "Venue-specific prices and fees. Coinbase integration and crypto data access are still required."),
        .init(id: "fx", title: "Currencies & macro", horizon: "Days to months", question: "Relative rates, carry and macro regimes", requirements: "FX entitlements, rate histories, rollover and currency exposure. Stock/options subscriptions do not establish FX access.")
    ]
}

@MainActor @Observable
final class JournalStore {
    var entries: [JournalEntry] = []
    var error: String?
    let sessionID = UUID()
    private let url: URL
    init(url: URL = URL.applicationSupportDirectory.appendingPathComponent("TradePilot/journal.json")) {
        self.url = url
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: url.path) {
                entries = try JSONDecoder().decode([JournalEntry].self, from: Data(contentsOf: url))
            }
        } catch { self.error = "Journal could not be loaded. Existing file has been preserved. \(error.localizedDescription)" }
    }
    func append(kind: String, text: String, strategy: String, accountID: String, reference: String? = nil, holdings: [Holding], order: Order? = nil, mode: String = "demo", reflection: JournalReflection? = nil) {
        guard error == nil else { return }
        let entry = JournalEntry(id: UUID(), sessionID: sessionID, timestamp: Date(), kind: kind, text: text,
            strategy: strategy, accountID: accountID, mode: mode, reference: reference, holdings: holdings, order: order, reflection: reflection)
        let next = [entry] + entries
        do {
            let data = try JSONEncoder().encode(next)
            #if os(iOS)
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            #else
            try data.write(to: url, options: .atomic)
            #endif
            entries = next
        } catch { self.error = "Journal save failed. \(error.localizedDescription)" }
    }
    func appendReflection(for entry: JournalEntry, thesis: String, expectedOutcome: String, observation: String, lesson: String) {
        let reflection = JournalReflection(eventID: entry.id, thesis: thesis, expectedOutcome: expectedOutcome, observation: observation, lesson: lesson)
        append(kind: "reflection", text: reflection.retrievalText, strategy: entry.strategy, accountID: entry.accountID,
            reference: entry.reference, holdings: entry.holdings, mode: entry.mode, reflection: reflection)
    }
    var exportText: String {
        let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]; encoder.dateEncodingStrategy = .iso8601
        return (try? String(decoding: encoder.encode(entries), as: UTF8.self)) ?? "[]"
    }
}

extension JournalStore {
    /// The latest entries for one mode, shaped for the assistant request body.
    func context(mode: String, account: String? = nil, limit: Int = 30) -> [[String: String]] {
        entries.filter { $0.mode == mode && (account == nil || $0.accountID == account) }.prefix(limit).map {
            ["kind": $0.kind, "text": String($0.text.prefix(1000)), "strategy": $0.strategy,
             "timestamp": $0.timestamp.ISO8601Format(), "mode": $0.mode, "session": $0.sessionID.uuidString]
        }
    }
}

/// User-facing names for journal identifiers.
enum JournalLabels {
    static func mode(_ raw: String) -> String {
        switch raw {
        case "demo": "Practice"
        case "paper": "Paper"
        case "historical_research": "Research"
        case "webull_production": "Webull · Live"
        case "webull_sandbox": "Webull · Sandbox"
        default: raw.hasPrefix("webull_") ? "Webull" : titleCase(raw)
        }
    }
    static func modeTone(_ raw: String) -> Tone {
        switch raw {
        case "demo": .practice
        case "paper": .paper
        case "historical_research": .accent
        case "webull_production": .live
        default: raw.hasPrefix("webull_") ? .warning : .neutral
        }
    }
    static func kind(_ raw: String) -> String {
        switch raw {
        case "submission_result": "Sent to broker"
        case "broker_status": "Broker update"
        case "execution_sync": "Executions loaded"
        case "paper_fill": "Paper fill"
        default: titleCase(raw)
        }
    }
    static func strategy(_ id: String) -> String { StrategyProfile.all.first { $0.id == id }?.title ?? titleCase(id) }
}

// MARK: - Research tab

struct ResearchView: View {
    @Environment(AppStore.self) private var store
    @State private var researchText = ""
    @State private var researchError = ""
    @State private var researchSymbol: String?
    @State private var researching = false
    @State private var evaluation: RecordedEvaluation?
    @State private var loadingEvaluation = false
    @State private var evaluationError = ""
    var body: some View {
        @Bindable var store = store
        Screen(title: "Research") {
            SectionCard(title: "Tools") {
                VStack(spacing: 0) {
                    NavigationLink { StrategyComparisonView() } label: { NavigationRow(title: "Strategy lab", detail: "Trend, breakout and mean reversion after costs", icon: "chart.xyaxis.line") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { KronosView() } label: { NavigationRow(title: "Forecast replay", detail: "Local model against held-out sessions", icon: "waveform.path") }
                    Divider().overlay(Theme.separator)
                    NavigationLink { AutomatedPaperView() } label: { NavigationRow(title: "Automated paper strategies", detail: "Forward-recorded SPY experiments", icon: "clock.arrow.circlepath", badge: StatusBadge("Paper", tone: .paper)) }
                }.buttonStyle(RowButtonStyle())
            }
            SectionCard(title: "Market research", footer: store.aiEnabled ? "Research and the assistant run on your server." : "Turn on the server model in Settings to ask the assistant about research.") {
                HStack(spacing: Spacing.m) {
                    TextField("Symbol", text: $store.researchTicker).phoneSymbolInput().fieldStyle()
                    Button(researching ? "Loading…" : "Load") { loadResearch() }.buttonStyle(PrimaryButtonStyle()).frame(width: 110).disabled(researching || store.researchTicker.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                OutcomeNotice(text: researchError, kind: .error)
                if let researchSymbol, !researchText.isEmpty {
                    Text(researchSymbol).font(.headline).accessibilityAddTraits(.isHeader)
                    Text(researchText).font(.subheadline).textSelection(.enabled)
                }
                Picker("Focus", selection: $store.strategyID) { ForEach(StrategyProfile.all) { profile in Text(profile.title).tag(profile.id) } }.pickerStyle(.menu)
                if let profile = StrategyProfile.all.first(where: { $0.id == store.strategyID }) {
                    Text(profile.question).font(.footnote).foregroundStyle(Theme.textSecondary)
                    Footnote("\(profile.horizon). Needs: \(profile.requirements)")
                }
                Button { store.openAssistant("Research \(store.researchTicker) for the \(store.strategyID) strategy. Separate market evidence, journal observations, backtest limitations and unanswered questions. Do not propose an order.") } label: {
                    Label("Ask the assistant", systemImage: "bubble.left.and.text.bubble.right")
                }.buttonStyle(SecondaryButtonStyle()).disabled(!store.aiEnabled || store.busy)
            }
            SectionCard(title: "Recorded backtest", footer: "Loading the report does not rerun or tune anything.") {
                Button(loadingEvaluation ? "Loading…" : "View backtest") { loadEvaluation() }.buttonStyle(SecondaryButtonStyle()).disabled(loadingEvaluation)
                OutcomeNotice(text: evaluationError, kind: .error)
                if let evaluation { RecordedEvaluationCard(report: evaluation) }
            }
        }
        .onConnectionChange(store) { evaluation = nil; evaluationError = ""; researchText = ""; researchSymbol = nil; researchError = "" }
    }
    private func loadResearch() {
        researching = true; researchError = ""; researchText = ""; researchSymbol = nil
        let ticker = store.researchTicker.uppercased().trimmingCharacters(in: .whitespaces)
        let endpoint = store.aiEndpoint, token = store.aiToken
        store.record("request", "Load market research for \(ticker)")
        Task {
            defer { researching = false }
            do {
                let text = try await AIService.research(endpoint: endpoint, token: token, ticker: ticker)
                guard store.aiEndpoint == endpoint, store.aiToken == token else { return }
                researchText = text; researchSymbol = ticker
                store.record("research", researchText)
            } catch {
                guard store.aiEndpoint == endpoint, store.aiToken == token else { return }
                researchError = error.localizedDescription; store.record("error", researchError)
            }
        }
    }
    private func loadEvaluation() {
        loadingEvaluation = true; evaluation = nil; evaluationError = ""
        let endpoint = store.aiEndpoint, token = store.aiToken
        store.journal.append(kind: "request", text: "View recorded historical strategy evaluation", strategy: "trend", accountID: "none", holdings: [], mode: "historical_research")
        Task {
            defer { loadingEvaluation = false }
            do {
                let result = try await AIService.evaluation(endpoint: endpoint, token: token)
                guard EvaluationValidation.connectionMatches(endpoint: endpoint, token: token, currentEndpoint: store.aiEndpoint, currentToken: store.aiToken) else { return }
                evaluation = result
                store.journal.append(kind: "research", text: result.conclusion, strategy: "trend", accountID: "none", reference: result.protocol_sha256, holdings: [], mode: "historical_research")
            } catch {
                guard EvaluationValidation.connectionMatches(endpoint: endpoint, token: token, currentEndpoint: store.aiEndpoint, currentToken: store.aiToken) else { return }
                evaluationError = error.localizedDescription
                store.journal.append(kind: "error", text: "Recorded evaluation unavailable", strategy: "trend", accountID: "none", holdings: [], mode: "historical_research")
            }
        }
    }
}

// MARK: - Journal tab

struct JournalView: View {
    @Environment(AppStore.self) private var store
    @State private var eventFilter = "all"
    @State private var environmentFilter = "all"
    @State private var strategyFilter = "all"
    @State private var showNote = false
    @State private var reflectionTarget: JournalEntry?
    private let kinds = ["request", "proposal", "approval", "submission_result", "broker_status", "outcome", "paper_fill", "cancel", "note", "reflection", "research", "assistant", "error"]
    var body: some View {
        let filtered = store.journal.entries.filter { JournalEvidence.matches($0, environment: environmentFilter, strategy: strategyFilter, kind: eventFilter) }
        Screen(title: "Journal") {
            if let error = store.journal.error { InlineNotice(kind: .error, message: error) }
            MetricsGrid {
                MetricTile(label: "Entries", value: "\(filtered.count)")
                MetricTile(label: "Notes", value: "\(filtered.filter { $0.kind == "note" || $0.reflection != nil }.count)")
                MetricTile(label: "Broker updates", value: "\(filtered.filter { $0.kind == "broker_status" || $0.kind == "submission_result" }.count)")
                MetricTile(label: "Practice fills", value: "\(filtered.filter(JournalEvidence.verifiedDemoFill).count)")
            }
            HStack(spacing: Spacing.s) {
                Menu {
                    Picker("Account", selection: $environmentFilter) { Text("All accounts").tag("all"); Text("Paper").tag("paper"); Text("Practice").tag("demo"); Text("Webull").tag("webull"); Text("Research").tag("research") }
                    Picker("Strategy", selection: $strategyFilter) { Text("All strategies").tag("all"); ForEach(StrategyProfile.all) { Text($0.title).tag($0.id) } }
                    Picker("Event", selection: $eventFilter) { Text("All events").tag("all"); ForEach(kinds, id: \.self) { Text(JournalLabels.kind($0)).tag($0) } }
                } label: {
                    Label(filterSummary, systemImage: "line.3.horizontal.decrease.circle").font(.footnote.weight(.semibold))
                        .padding(.horizontal, Spacing.m).frame(minHeight: 44).background(Theme.surface, in: RoundedRectangle(cornerRadius: Radius.control))
                }
                Spacer()
                ShareLink(item: store.journal.exportText) { Image(systemName: "square.and.arrow.up").frame(width: 44, height: 44).accessibilityLabel("Export journal") }
                    .disabled(store.journal.entries.isEmpty)
                Button { showNote = true } label: { Image(systemName: "square.and.pencil").frame(width: 44, height: 44).accessibilityLabel("Add note") }.disabled(store.journal.error != nil)
            }
            if store.journal.entries.isEmpty {
                EmptyState(title: "No entries yet", message: "Requests, reviews, confirmations and notes are recorded here, on this phone.", icon: "book.closed")
            } else if filtered.isEmpty {
                EmptyState(title: "Nothing matches", message: "Try a different filter.", icon: "line.3.horizontal.decrease.circle")
            }
            ForEach(filtered) { entry in
                SectionCard {
                    HStack(spacing: Spacing.s) {
                        StatusBadge(JournalLabels.kind(entry.kind), tone: entry.kind == "error" ? .negative : .neutral)
                        StatusBadge(JournalLabels.mode(entry.mode), tone: JournalLabels.modeTone(entry.mode))
                        Spacer()
                        Text(relativeTime(entry.timestamp)).font(.caption).foregroundStyle(Theme.textTertiary)
                    }
                    Text(entry.text).font(.subheadline).textSelection(.enabled).lineLimit(8)
                    HStack {
                        Text([JournalLabels.strategy(entry.strategy), store.engine.accounts.contains(where: { $0.id == entry.accountID }) ? store.engine.accountName(entry.accountID) : nil].compactMap { $0 }.joined(separator: " · "))
                            .font(.caption).foregroundStyle(Theme.textTertiary)
                        Spacer()
                        if entry.kind != "reflection" {
                            Button("Reflect") { reflectionTarget = entry }.font(.caption.weight(.semibold)).disabled(store.journal.error != nil)
                        }
                    }
                }
            }
            Footnote("Broker updates record what the broker reported; they are not a verified performance record.")
        }
        .sheet(isPresented: $showNote) { NoteSheet() }
        .sheet(item: $reflectionTarget) { entry in ReflectionSheet(target: entry) }
    }
    private var filterSummary: String {
        var parts: [String] = []
        if environmentFilter != "all" { parts.append(environmentFilter == "demo" ? "Practice" : environmentFilter.capitalized) }
        if strategyFilter != "all" { parts.append(JournalLabels.strategy(strategyFilter)) }
        if eventFilter != "all" { parts.append(JournalLabels.kind(eventFilter)) }
        return parts.isEmpty ? "Filter" : parts.joined(separator: " · ")
    }
}

struct NoteSheet: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var note = ""
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: Spacing.l) {
                TextField("What did you notice?", text: $note, axis: .vertical).lineLimit(4...10).fieldStyle()
                Footnote("Saved on this phone with the current practice account and strategy focus.")
                Spacer()
            }
            .padding(Spacing.l).background(Theme.background)
            .navigationTitle("New note").phoneInlineTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        store.journal.append(kind: "note", text: note, strategy: store.strategyID, accountID: store.accountID, holdings: store.engine.holdings, mode: "demo")
                        if store.journal.error == nil { dismiss() }
                    }.disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }.tint(Theme.accent)
    }
}

struct ReflectionSheet: View {
    @Environment(AppStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    let target: JournalEntry
    @State private var thesis = ""
    @State private var expectedOutcome = ""
    @State private var observation = ""
    @State private var lesson = ""
    private var complete: Bool { ![thesis, expectedOutcome, observation, lesson].contains { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    SectionCard(title: "Reflecting on") {
                        HStack { StatusBadge(JournalLabels.kind(target.kind)); StatusBadge(JournalLabels.mode(target.mode), tone: JournalLabels.modeTone(target.mode)); Spacer(); Text(relativeTime(target.timestamp)).font(.caption).foregroundStyle(Theme.textTertiary) }
                        Text(target.text).font(.footnote).lineLimit(4)
                    }
                    TextField("Thesis", text: $thesis, axis: .vertical).lineLimit(2...4).fieldStyle()
                    TextField("Expected outcome", text: $expectedOutcome, axis: .vertical).lineLimit(2...4).fieldStyle()
                    TextField("What happened", text: $observation, axis: .vertical).lineLimit(2...4).fieldStyle()
                    TextField("Lesson", text: $lesson, axis: .vertical).lineLimit(2...4).fieldStyle()
                    Footnote("The reflection keeps this entry’s account and strategy.")
                }.padding(Spacing.l)
            }
            .background(Theme.background)
            .navigationTitle("Reflection").phoneInlineTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        store.journal.appendReflection(for: target, thesis: thesis, expectedOutcome: expectedOutcome, observation: observation, lesson: lesson)
                        if store.journal.error == nil { dismiss() }
                    }.disabled(!complete || store.journal.error != nil)
                }
            }
        }.tint(Theme.accent)
    }
}

private struct RecordedEvaluationCard: View {
    let report: RecordedEvaluation
    private func points(_ value: Double) -> String { String(format: "%+.2f pp", value) }
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.m) {
            InlineNotice(kind: .warning, message: report.conclusion)
            Footnote("\(report.rows.count) of \(report.expected_symbols) symbols, \(report.source_start) to \(report.source_end). Trained on 60%, validated on 20%, tested on the final 20%, at 10 bps per side.")
            ForEach(report.rows) { row in
                VStack(alignment: .leading, spacing: Spacing.s) {
                    HStack {
                        Text(row.symbol).font(.subheadline.weight(.semibold))
                        Text("SMA \(row.selected_window)").font(.caption).foregroundStyle(Theme.textTertiary)
                        Spacer()
                        StatusBadge(row.validation_passed ? "Validated" : "Failed validation", tone: row.validation_passed ? .positive : .neutral)
                    }
                    HStack(spacing: Spacing.m) {
                        MetricTile(label: "Final", value: percent(row.holdout_return_pct, signed: true), tone: row.holdout_return_pct >= 0 ? .positive : .negative)
                        MetricTile(label: "Benchmark", value: percent(row.benchmark_return_pct, signed: true))
                        MetricTile(label: "Difference", value: points(row.excess_return_pct), tone: row.excess_return_pct >= 0 ? .positive : .negative)
                    }
                    Footnote("\(row.bar_count) bars · \(row.fills) fills · drawdown \(percent(row.max_drawdown_pct)) · " + row.cost_sensitivity.map { "\($0.bps_per_side) bps \(percent($0.return_pct, signed: true))" }.joined(separator: ", "))
                }
                .padding(.vertical, Spacing.xs)
                Divider().overlay(Theme.separator)
            }
            if !report.unavailable_symbols.isEmpty {
                InlineNotice(kind: .warning, message: "Unavailable: \(report.unavailable_symbols.joined(separator: ", ")). Missing results are not replaced with simulated data.")
            }
            ForEach(report.limitations, id: \.self) { Footnote($0) }
            Footnote("Recorded \(report.evaluated_at.prefix(10)) · protocol \(report.protocol_sha256.prefix(12))")
        }
    }
}
