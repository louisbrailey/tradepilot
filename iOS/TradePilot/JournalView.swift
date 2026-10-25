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
        let environmentMatches = environment == "all" || (environment == "demo" ? entry.mode == "demo" : environment == "research" ? entry.mode == "historical_research" : entry.mode.hasPrefix("webull_"))
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

struct JournalView: View {
    @Environment(AppStore.self) private var store
    @State private var section = 0
    @State private var reflectionTarget: UUID?
    @State private var note = ""
    @State private var thesis = ""
    @State private var expectedOutcome = ""
    @State private var observation = ""
    @State private var lesson = ""
    @State private var eventFilter = "all"
    @State private var environmentFilter = "all"
    @State private var strategyFilter = "all"
    @State private var researchText = ""
    @State private var researching = false
    @State private var evaluation: RecordedEvaluation?
    @State private var loadingEvaluation = false
    @State private var evaluationError = ""
    var body: some View {
        @Bindable var store = store
        Screen(title: "Research & journal", isDemo: false) {
            Picker("Section", selection: $section) { Text("Strategies").tag(0); Text("Journal").tag(1) }.pickerStyle(.segmented)
            if let error = store.journal.error { Text(error).font(.caption).foregroundStyle(.orange) }
            if section == 0 {
                NavigationLink { KronosView() } label: { Label("Kronos forecasting lab", systemImage: "waveform.path") }.buttonStyle(MintButton())
                NavigationLink { StrategyComparisonView() } label: { Label("Open strategy lab", systemImage: "chart.xyaxis.line") }.buttonStyle(MintButton())
                NavigationLink { PaperTradingView() } label: { Label("Paper account & journal", systemImage: "book.pages") }
                VStack(alignment: .leading, spacing: 12) {
                    Text("Build evidence,\nthen build conviction.").font(.title.bold())
                    Text("Strategy profiles guide research. Journal retrieval gives the AI context from previous actions; it does not retrain the model or prove that a strategy works.").font(.subheadline).foregroundStyle(Palette.muted)
                }
                Picker("Research strategy", selection: $store.strategyID) { ForEach(StrategyProfile.all) { profile in Text(profile.title).tag(profile.id) } }.tint(Palette.mint)
                VStack(alignment: .leading, spacing: 14) {
                    TextField("Research ticker, e.g. AAPL", text: $store.researchTicker).phoneSymbolInput()
                    Button(researching ? "Loading research…" : "Load Massive research") {
                        researching = true
                        let ticker = store.researchTicker
                        store.record("request", "Load Massive research for \(ticker)")
                        Task {
                            defer { researching = false }
                            do {
                                researchText = try await AIService.research(endpoint: store.aiEndpoint, token: store.aiToken, ticker: ticker)
                                store.record("research", researchText)
                            } catch { researchText = error.localizedDescription; store.record("error", researchText) }
                        }
                    }.disabled(researching)
                    if !researchText.isEmpty { Text(researchText).font(.caption).textSelection(.enabled) }
                    Toggle("Include Massive market research", isOn: $store.useMarketData).tint(Palette.mint)
                    Toggle("Include recent journal context", isOn: $store.useJournalContext).tint(Palette.mint)
                    Text("Requires your configured AI server. Massive stock history, dividends, options and Benzinga access are checked when requested. Quotes and snapshots may be delayed. Only the latest 30 journal entries are sent when enabled.").font(.caption).foregroundStyle(Palette.muted)
                    Button {
                        store.tab = 1
                        store.send("Research \(store.researchTicker) for the \(store.strategyID) strategy. Separate market evidence, journal observations, backtest limitations and unanswered questions. Do not propose an order.")
                    } label: { Label("Research with AI", systemImage: "sparkles").frame(maxWidth: .infinity) }.buttonStyle(MintButton()).disabled(!store.aiEnabled || store.busy)
                }.card()
                VStack(alignment: .leading, spacing: 14) {
                    Text("Tested strategy results").font(.headline)
                    Text("Review the recorded training, validation and final test. Loading this report does not rerun or tune the strategy.").font(.caption).foregroundStyle(Palette.muted)
                    Button(loadingEvaluation ? "Loading recorded results…" : "View tested strategy results") {
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
                    }.disabled(loadingEvaluation)
                    if !evaluationError.isEmpty { Text(evaluationError).font(.caption).foregroundStyle(.orange) }
                    if let evaluation { RecordedEvaluationCard(report: evaluation) }
                }.card()
                ForEach(StrategyProfile.all) { profile in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack { Text(profile.title).font(.headline); Spacer(); if store.strategyID == profile.id { Image(systemName: "checkmark.circle.fill").foregroundStyle(Palette.mint) } }
                        Text(profile.horizon.uppercased()).font(.caption2.monospaced()).foregroundStyle(Palette.mint)
                        Text(profile.question).font(.subheadline)
                        Text(profile.requirements).font(.caption).foregroundStyle(Palette.muted)
                    }.card().onTapGesture { store.strategyID = profile.id }
                }
            } else {
                Text("A record of every decision.").font(.title2.bold())
                Text("Requests, reviews, approvals, outcomes and reflections are stored on this iPhone. Each event keeps its own demo or Webull environment, account, strategy and app session. No automatic retraining runs in the background.").font(.caption).foregroundStyle(Palette.muted)
                VStack(spacing: 12) {
                    Picker("Link reflection to event", selection: $reflectionTarget) {
                        Text("Choose an existing event").tag(UUID?.none)
                        ForEach(store.journal.entries.filter { $0.kind != "reflection" }) { entry in
                            Text("\(entry.kind.capitalized) · \(entry.mode) · \(entry.accountID) · \(entry.timestamp.formatted(date: .abbreviated, time: .shortened)): \(entry.text.prefix(38))").tag(Optional(entry.id))
                        }
                    }
                    if let targetID = reflectionTarget, let target = store.journal.entries.first(where: { $0.id == targetID }) {
                        Text("Reflecting on: \(target.kind) · \(target.mode) · \(target.accountID) · \(target.timestamp.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(Palette.muted)
                    }
                    TextField("Thesis", text: $thesis, axis: .vertical).lineLimit(2...4)
                    TextField("Expected outcome", text: $expectedOutcome, axis: .vertical).lineLimit(2...4)
                    TextField("What happened", text: $observation, axis: .vertical).lineLimit(2...4)
                    TextField("Lesson", text: $lesson, axis: .vertical).lineLimit(2...4)
                    Button("Save structured reflection") {
                        guard let targetID = reflectionTarget, let target = store.journal.entries.first(where: { $0.id == targetID }) else { return }
                        store.journal.appendReflection(for: target, thesis: thesis, expectedOutcome: expectedOutcome, observation: observation, lesson: lesson)
                        if store.journal.error == nil { thesis = ""; expectedOutcome = ""; observation = ""; lesson = ""; reflectionTarget = nil }
                    }.disabled(store.journal.error != nil || reflectionTarget == nil || [thesis, expectedOutcome, observation, lesson].contains { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty })
                }.card()
                VStack(spacing: 12) {
                    TextField("General note for the demo workspace…", text: $note, axis: .vertical).lineLimit(2...5)
                    Button("Save demo workspace note") {
                        store.journal.append(kind: "note", text: note, strategy: store.strategyID, accountID: store.accountID, holdings: store.engine.holdings, mode: "demo")
                        if store.journal.error == nil { note = "" }
                    }.disabled(store.journal.error != nil || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    Text("To reflect on a Webull action, link a structured reflection to that specific event above; it keeps the event’s Webull environment and account.").font(.caption2).foregroundStyle(Palette.muted)
                }.card()
                let filteredEntries = store.journal.entries.filter { JournalEvidence.matches($0, environment: environmentFilter, strategy: strategyFilter, kind: eventFilter) }
                let requests = filteredEntries.filter { $0.kind == "request" }.count
                let notesAndReflections = filteredEntries.filter { $0.kind == "note" || $0.reflection != nil }.count
                let brokerObservations = filteredEntries.filter { $0.kind == "broker_status" || $0.kind == "submission_result" }.count
                let verifiedDemoFills = filteredEntries.filter(JournalEvidence.verifiedDemoFill).count
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Picker("Environment", selection: $environmentFilter) { Text("All environments").tag("all"); Text("Demo").tag("demo"); Text("Webull").tag("webull"); Text("Historical research").tag("research") }
                        Picker("Strategy", selection: $strategyFilter) { Text("All strategies").tag("all"); ForEach(StrategyProfile.all) { Text($0.title).tag($0.id) } }
                    }
                    Picker("Event filter", selection: $eventFilter) { ForEach(["all", "request", "proposal", "approval", "submission_result", "broker_status", "outcome", "cancel", "note", "reflection", "assistant", "error"], id: \.self) { Text($0 == "all" ? "All events" : $0.capitalized).tag($0) } }
                    Text("Activity: \(filteredEntries.count) · Requests: \(requests) · Notes & reflections: \(notesAndReflections) · Broker observations: \(brokerObservations) · Simulated fills: \(verifiedDemoFills)").font(.caption).foregroundStyle(Palette.muted)
                    Text("Observations record what was reported. Simulated fills are shown separately. Broker status updates are not a verified trading performance record.").font(.caption2).foregroundStyle(Palette.muted)
                }
                HStack {
                    ShareLink(item: store.journal.exportText) { Label("Export", systemImage: "square.and.arrow.up") }
                }.font(.caption)
                ForEach(filteredEntries) { entry in
                    VStack(alignment: .leading, spacing: 9) {
                        HStack { Text(entry.kind.uppercased()).font(.caption2.bold()).foregroundStyle(Palette.mint); Spacer(); Text(entry.timestamp.formatted(date: .abbreviated, time: .shortened)).font(.caption2).foregroundStyle(Palette.muted) }
                        Text(entry.text).font(.subheadline).textSelection(.enabled)
                        Text("\(entry.strategy) · \(entry.mode) · account \(entry.accountID) · session \(entry.sessionID.uuidString.prefix(6))").font(.caption2).foregroundStyle(Palette.muted)
                        if let reflection = entry.reflection { Text("Linked event: \(reflection.eventID.uuidString.prefix(8))").font(.caption2).foregroundStyle(Palette.muted) }
                    }.card()
                }
                if store.journal.entries.isEmpty {
                    Text("Your first request will start the journal.").foregroundStyle(Palette.muted)
                } else if filteredEntries.isEmpty {
                    Text("No journal events match these filters.").foregroundStyle(Palette.muted)
                }
            }
        }
        .onChange(of: store.aiEndpoint) { _, _ in evaluation = nil; evaluationError = "" }
        .onChange(of: store.aiToken) { _, _ in evaluation = nil; evaluationError = "" }
    }
}

private struct RecordedEvaluationCard: View {
    let report: RecordedEvaluation
    private func percent(_ value: Double) -> String { String(format: "%+.2f%%", value) }
    private func points(_ value: Double) -> String { String(format: "%+.2f pp", value) }
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Recorded strategy evaluation").font(.title3.bold())
            Text(report.conclusion).font(.subheadline.bold()).foregroundStyle(.orange)
            Text("\(report.rows.count) of \(report.expected_symbols) symbols · \(report.source_start)–\(report.source_end)").font(.caption).foregroundStyle(Palette.muted)
            Text("60% training → 20% validation → 20% final test").font(.caption.bold())
            Text("Final period already observed · 10 bps cost per side").font(.caption).foregroundStyle(Palette.muted)
            Text("Swipe the table to compare results.").font(.caption2).foregroundStyle(Palette.muted)
            ScrollView(.horizontal) {
                Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 12) {
                    GridRow {
                        Text("Symbol"); Text("SMA"); Text("Validation"); Text("Final return"); Text("Benchmark"); Text("Difference")
                    }.font(.caption.bold())
                    ForEach(report.rows) { row in
                        GridRow {
                            Text(row.symbol).bold(); Text("\(row.selected_window) bars")
                            Text(row.validation_passed ? "Pass" : "Fail")
                            Text(percent(row.holdout_return_pct)); Text(percent(row.benchmark_return_pct)); Text(points(row.excess_return_pct))
                        }.font(.caption.monospacedDigit())
                    }
                }.padding(.vertical, 4)
            }
            DisclosureGroup("Sample windows and cost stress") {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(report.rows) { row in
                        VStack(alignment: .leading, spacing: 5) {
                            Text("\(row.symbol) · \(row.bar_count) daily bars · \(row.fills) final-period fills").font(.caption.bold())
                            Text("Final test: \(row.holdout_start)–\(row.holdout_end)").font(.caption)
                            Text("Validation difference: \(points(row.validation_excess_pct)) · final drawdown: \(String(format: "%.2f", row.max_drawdown_pct))%").font(.caption)
                            Text(row.cost_sensitivity.map { "\($0.bps_per_side) bps: \(percent($0.return_pct))" }.joined(separator: " · ")).font(.caption2.monospacedDigit())
                        }
                    }
                }.padding(.top, 8)
            }.font(.caption)
            if !report.unavailable_symbols.isEmpty {
                Text("Unavailable: \(report.unavailable_symbols.joined(separator: ", ")). Missing results are not replaced with simulated data.").font(.caption).foregroundStyle(.orange)
            }
            ForEach(report.limitations, id: \.self) { Text($0).font(.caption).foregroundStyle(Palette.muted) }
            Text("Recorded \(report.evaluated_at.prefix(10)) · protocol \(report.protocol_sha256.prefix(12))").font(.caption2.monospaced()).foregroundStyle(Palette.muted)
        }
    }
}
