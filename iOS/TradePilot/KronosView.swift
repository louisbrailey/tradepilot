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
        Screen(title: "Kronos lab", isDemo: false) {
            VStack(alignment: .leading, spacing: 10) {
                Text("LOCAL MODEL · HISTORICAL REPLAY").font(.caption.bold()).foregroundStyle(Palette.mint)
                Text("See how the forecast compares.").font(.title2.bold())
                Text("Kronos reads 128 daily candles, then predicts the next 5 or 20 sessions. Those prices are held back from inference and shown afterward for comparison.").font(.subheadline).foregroundStyle(Palette.muted)
            }
            VStack(alignment: .leading, spacing: 14) {
                TextField("US stock ticker", text: $ticker).phoneSymbolInput().disabled(busy)
                Picker("Held-out sessions", selection: $horizon) {
                    Text("5 sessions").tag(5); Text("20 sessions").tag(20)
                }.pickerStyle(.segmented).disabled(busy)
                Button(busy ? "Running local model…" : "Run historical replay") { run() }
                    .buttonStyle(MintButton()).disabled(busy)
                if busy { ProgressView("Fetching daily history and sampling 3 forecasts. Keep the Mac awake.").font(.caption) }
                if !message.isEmpty { Text(message).font(.caption).foregroundStyle(Palette.muted) }
            }.card()
            if let report {
                VStack(alignment: .leading, spacing: 14) {
                    Text("\(report.ticker) · \(report.horizon)-session replay").font(.headline)
                    Text("Input: \(report.input_start) – \(report.input_end)").font(.caption).foregroundStyle(Palette.muted)
                    Chart(report.points) { point in
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.predicted))
                            .foregroundStyle(by: .value("Series", "Kronos"))
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.actual))
                            .foregroundStyle(by: .value("Series", "Actual"))
                        LineMark(x: .value("Session", point.date), y: .value("Close", point.baseline))
                            .foregroundStyle(by: .value("Series", "Unchanged"))
                    }
                    .chartForegroundStyleScale(["Kronos": Palette.mint, "Actual": Color.orange, "Unchanged": Color.gray])
                    .chartYScale(domain: .automatic(includesZero: false)).frame(height: 230)
                    LabeledContent("Kronos close-price error", value: String(format: "$%.3f MAE", report.mae))
                    LabeledContent("Unchanged-price error", value: String(format: "$%.3f MAE", report.baseline_mae))
                    Text(report.mae < report.baseline_mae ? "Kronos has lower error in this window." : "The unchanged-price baseline matches or beats Kronos in this window.")
                        .font(.caption).foregroundStyle(Palette.muted)
                }.card()
                VStack(alignment: .leading, spacing: 10) {
                    Text("Daily closes").font(.headline)
                    Text("Date · forecast · actual · sample range").font(.caption).foregroundStyle(Palette.muted)
                    ForEach(report.points) { p in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(p.date).font(.caption.bold())
                            Text(String(format: "$%.2f · $%.2f · $%.2f–$%.2f", p.predicted, p.actual, p.low, p.high))
                                .font(.caption.monospacedDigit())
                        }
                    }
                }.card()
                Text("\(report.source) · \(report.model) · 3 samples · seed \(report.seed)").font(.caption).foregroundStyle(Palette.muted)
                Text(report.notice).font(.caption).foregroundStyle(Palette.muted)
                Button(saved ? "Saved to research journal" : "Save research to journal") { save(report) }
                    .buttonStyle(MintButton()).disabled(saved)
            } else {
                Text("Research only. This does not connect a brokerage or place orders. Model training overlap is unverified; a good historical fit is not proof of future returns.").font(.caption).foregroundStyle(Palette.muted)
            }
        }
        .onChange(of: store.aiEndpoint) { _, _ in clear() }
        .onChange(of: store.aiToken) { _, _ in clear() }
    }

    private func clear() { report = nil; saved = false; message = "Connection changed. Run a new replay." }
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
                guard result.matches(symbol: symbol, sessions: sessions) else { throw WorkspaceError(message: "Forecast response did not match this replay.") }
                report = result
                message = "Completed " + workspaceDate(result.generated_at)
            } catch {
                if binding.matches(endpoint: store.aiEndpoint, token: store.aiToken) { message = error.localizedDescription }
            }
        }
    }
    private func save(_ result: KronosReport) {
        let rows = result.points.map { String(format: "%@: predicted %.4f, actual %.4f, sample range %.4f–%.4f", $0.date, $0.predicted, $0.actual, $0.low, $0.high) }.joined(separator: "\n")
        store.journal.append(kind: "research", text: "Kronos \(result.ticker), \(result.horizon) held-out sessions; input ends \(result.input_end). Model \(result.model); seed \(result.seed). MAE \(result.mae); unchanged baseline MAE \(result.baseline_mae).\n\(rows)\n\(result.notice)", strategy: "kronos", accountID: "none", reference: result.id, holdings: [], mode: "historical_research")
        saved = store.journal.error == nil
        if !saved { message = "The journal could not save this research. Check Research → Journal." }
    }
}
