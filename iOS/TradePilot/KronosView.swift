import SwiftUI
import Charts

struct KronosRequest: Encodable, Sendable { let ticker: String; let horizon: Int }
struct KronosPoint: Decodable, Sendable, Identifiable {
    var id: String { date }
    let date: String
    let actual: Double; let predicted: Double; let low: Double; let high: Double; let baseline: Double
}
struct KronosReport: Decodable, Sendable {
    let id: String; let ticker: String; let model: String; let mode: String; let source: String
    let input_start: String; let input_end: String; let notice: String
    let lookback: Int; let horizon: Int; let samples: Int; let seed: Int
    let generated_at: Double; let mae: Double; let baseline_mae: Double
    let points: [KronosPoint]
    func matches(symbol: String, sessions: Int) -> Bool {
        mode == "historical_replay" && ticker == symbol && horizon == sessions && lookback == 128 && samples == 3 &&
        points.count == sessions && Set(points.map(\.date)).count == sessions &&
        points.map(\.date) == points.map(\.date).sorted() &&
        points.allSatisfy { p in
            p.date > input_end && [p.actual, p.predicted, p.low, p.high, p.baseline].allSatisfy { $0.isFinite && $0 > 0 } &&
            p.low <= p.predicted && p.predicted <= p.high
        } && mae.isFinite && mae >= 0 && baseline_mae.isFinite && baseline_mae >= 0
    }
}

struct KronosView: View {
    @Environment(AppStore.self) private var store
    @State private var ticker = "AAPL"
    @State private var horizon = 5
    @State private var busy = false
    @State private var report: KronosReport?
    @State private var message = ""
    @State private var saved = false

    var body: some View {
        SubScreen(title: "Forecast replay") {
            HStack { StatusBadge("Backtest", tone: .accent); Spacer() }
            SectionCard(footer: "The model reads 128 daily closes and predicts the next sessions. Those sessions are held back, then shown for comparison.") {
                HStack(spacing: Spacing.m) {
                    TextField("Symbol", text: $ticker).phoneSymbolInput().fieldStyle().disabled(busy)
                    Picker("Sessions", selection: $horizon) { Text("5").tag(5); Text("20").tag(20) }.pickerStyle(.segmented).frame(width: 120).disabled(busy)
                }
                Button(busy ? "Running…" : "Run replay") { run() }.buttonStyle(PrimaryButtonStyle()).disabled(busy || ticker.trimmingCharacters(in: .whitespaces).isEmpty)
                if busy { HStack(spacing: Spacing.s) { ProgressView(); Text("Running the local model on your Mac…").font(.footnote).foregroundStyle(Theme.textSecondary) } }
            }
            OutcomeNotice(text: message, kind: report == nil && !message.isEmpty ? .error : .info)
            if let report {
                SectionCard(title: "\(report.ticker) · \(report.horizon) sessions", footer: "Input \(report.input_start) to \(report.input_end). Lower error is better; the baseline assumes the price never changes.") {
                    Chart(report.points) { point in
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.predicted))
                            .foregroundStyle(by: .value("Series", "Forecast"))
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.actual))
                            .foregroundStyle(by: .value("Series", "Actual"))
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.baseline))
                            .foregroundStyle(by: .value("Series", "Unchanged"))
                    }
                    .chartForegroundStyleScale(["Forecast": Theme.accent, "Actual": Theme.textPrimary, "Unchanged": Theme.textTertiary])
                    .chartXAxis { AxisMarks(values: .automatic(desiredCount: 4)) { _ in AxisValueLabel().foregroundStyle(Theme.textTertiary) } }
                    .chartYAxis { AxisMarks { _ in AxisGridLine().foregroundStyle(Theme.separator); AxisValueLabel().foregroundStyle(Theme.textTertiary) } }
                    .chartYScale(domain: .automatic(includesZero: false)).frame(height: 220)
                    HStack(spacing: Spacing.l) {
                        MetricTile(label: "Forecast error", value: String(format: "$%.2f", report.mae), tone: report.mae < report.baseline_mae ? .positive : nil)
                        MetricTile(label: "Unchanged baseline", value: String(format: "$%.2f", report.baseline_mae))
                    }
                    Footnote(report.mae < report.baseline_mae ? "The forecast beat the unchanged-price baseline in this window." : "The unchanged-price baseline matched or beat the forecast in this window.")
                }
                SectionCard(title: "Daily closes") {
                    ForEach(report.points) { p in
                        HStack(alignment: .firstTextBaseline) {
                            Text(p.date).font(.footnote).foregroundStyle(Theme.textSecondary)
                            Spacer()
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(String(format: "Forecast $%.2f · Actual $%.2f", p.predicted, p.actual)).font(.footnote).monospacedDigit()
                                Text(String(format: "Range $%.2f–$%.2f", p.low, p.high)).font(.caption).monospacedDigit().foregroundStyle(Theme.textTertiary)
                            }
                        }.padding(.vertical, Spacing.xs).accessibilityElement(children: .combine)
                    }
                }
                Button(saved ? "Saved to journal" : "Save to journal") { save(report) }.buttonStyle(SecondaryButtonStyle()).disabled(saved)
                Footnote("\(report.notice) Model \(report.model), \(report.samples) samples, seed \(report.seed), data from \(report.source).")
            } else if !busy {
                Footnote("Research only. This never connects to a brokerage or places orders, and a good historical fit is not proof of future returns.")
            }
        }
        .onConnectionChange(store) { clear() }
    }

    private func clear() { report = nil; saved = false; message = "" }
    private func run() {
        let symbol = ticker.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        let sessions = horizon
        let binding = BrokerConnectionBinding(endpoint: store.aiEndpoint, token: store.aiToken)
        busy = true; report = nil; message = ""; saved = false
        Task {
            defer { busy = false }
            do {
                let result: KronosReport = try await WorkspaceAPI.request("v1/kronos/replay",
                    body: KronosRequest(ticker: symbol, horizon: sessions), endpoint: binding.endpoint, token: binding.token)
                guard binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) else { return }
                guard result.matches(symbol: symbol, sessions: sessions) else { throw WorkspaceError(message: "The forecast didn’t match this request.") }
                report = result
                message = ""
            } catch {
                if binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription }
            }
        }
    }
    private func save(_ result: KronosReport) {
        let rows = result.points.map { String(format: "%@: predicted %.4f, actual %.4f, sample range %.4f–%.4f", $0.date, $0.predicted, $0.actual, $0.low, $0.high) }.joined(separator: "\n")
        store.journal.append(kind: "research", text: "Kronos \(result.ticker), \(result.horizon) held-out sessions; input ends \(result.input_end). Model \(result.model); seed \(result.seed). MAE \(result.mae); unchanged baseline MAE \(result.baseline_mae).\n\(rows)\n\(result.notice)", strategy: "kronos", accountID: "none", reference: result.id, holdings: [], mode: "historical_research")
        saved = store.journal.error == nil
        if !saved { message = "The journal could not save this research." }
    }
}
