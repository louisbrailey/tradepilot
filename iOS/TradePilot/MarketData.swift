import SwiftUI

// Read-only market data from the private gateway. Nothing in this file can place,
// review or confirm an order; trading stays in the paper and broker flows.

// MARK: - Gateway models

struct ExtendedQuote: Decodable, Sendable, Equatable {
    let session: String; let price: Double; let change: Double; let change_percent: Double; let at: Double
}

struct MarketQuote: Decodable, Sendable, Identifiable, Equatable {
    var id: String { symbol }
    let symbol: String
    let name: String?
    let price: Double
    let change: Double?
    let change_percent: Double?
    let previous_close: Double?
    let open: Double?
    let high: Double?
    let low: Double?
    let volume: Double?
    let vwap: Double?
    let updated: Double?
    let bid: Double?
    let ask: Double?
    let sparkline: [Double]?
    let label: String?
    let extended: ExtendedQuote?
}

struct MarketStatus: Decodable, Sendable, Equatable {
    let state: String
    let as_of: Double
    let estimated: Bool
    let opens_at: Double?
    let closes_at: Double?
    var isTrading: Bool { state == "open" || state == "pre_market" || state == "after_hours" }
}

struct MarketOverview: Decodable, Sendable {
    let status: MarketStatus
    let indices: [MarketQuote]
    let gainers: [MarketQuote]
    let losers: [MarketQuote]
    let active: [MarketQuote]
    let universe: String
    let as_of: Double
}

struct QuoteBatch: Decodable, Sendable { let quotes: [MarketQuote]; let missing: [String]; let as_of: Double }

struct SymbolSearchResult: Decodable, Sendable, Identifiable, Hashable {
    var id: String { symbol }
    let symbol: String; let name: String; let type: String; let exchange: String?
}

struct SymbolSearch: Decodable, Sendable { let query: String; let results: [SymbolSearchResult] }

struct SymbolProfile: Decodable, Sendable {
    let description: String?; let homepage: String?; let employees: Double?; let industry: String?
    let listed: String?; let exchange: String?; let type: String?
}

struct SymbolStats: Decodable, Sendable {
    let open: Double?; let high: Double?; let low: Double?; let previous_close: Double?
    let volume: Double?; let vwap: Double?; let average_volume: Double?; let market_cap: Double?
    let pe_ratio: Double?; let eps: Double?; let dividend_yield: Double?; let price_to_book: Double?
    let week52_high: Double?; let week52_low: Double?; let shares_outstanding: Double?
}

struct SymbolDividend: Decodable, Sendable {
    let amount: Double; let ex_date: String; let frequency: String?; let pay_date: String?; let currency: String
}

struct NewsItem: Decodable, Sendable, Identifiable {
    let id: String; let title: String; let url: String; let publisher: String?
    let published: Double; let summary: String?; let sentiment: String?
}

struct SymbolPage: Decodable, Sendable {
    let symbol: String
    let name: String?
    let quote: MarketQuote?
    let profile: SymbolProfile
    let stats: SymbolStats
    let dividend: SymbolDividend?
    let news: [NewsItem]
    let unavailable: [String]
    let status: MarketStatus
    let as_of: Double
}

struct ChartPoint: Decodable, Sendable, Equatable {
    let t: Double; let o: Double; let h: Double; let l: Double; let c: Double; let v: Double
}

struct PriceHistory: Decodable, Sendable {
    let symbol: String; let range: String; let interval: String
    let points: [ChartPoint]; let baseline: Double?; let regular_hours_only: Bool; let as_of: Double
}

enum ChartRange: String, CaseIterable, Identifiable, Sendable {
    case day = "1D", week = "1W", month = "1M", threeMonths = "3M", sixMonths = "6M", ytd = "YTD", year = "1Y", fiveYears = "5Y"
    var id: String { rawValue }
    var isIntraday: Bool { self == .day || self == .week || self == .month }
    var changeLabel: String {
        switch self {
        case .day: "Today"
        case .week: "Past week"
        case .month: "Past month"
        case .threeMonths: "Past 3 months"
        case .sixMonths: "Past 6 months"
        case .ytd: "Year to date"
        case .year: "Past year"
        case .fiveYears: "Past 5 years"
        }
    }
}

// MARK: - Gateway requests

private struct SymbolsRequest: Encodable, Sendable { let symbols: [String]; let sparklines: Bool }
private struct QueryRequest: Encodable, Sendable { let query: String }
private struct SymbolRequest: Encodable, Sendable { let symbol: String }
private struct ChartRequest: Encodable, Sendable { let symbol: String; let range: String }

enum MarketAPI {
    static let maxSymbols = 40

    static func overview(endpoint: String, token: String) async throws -> MarketOverview {
        try await post("v1/market/overview", EmptyWorkspaceRequest(), endpoint: endpoint, token: token)
    }

    static func quotes(_ symbols: [String], sparklines: Bool, endpoint: String, token: String) async throws -> QuoteBatch {
        let requested = Array(symbols.prefix(maxSymbols))
        guard !requested.isEmpty else { return QuoteBatch(quotes: [], missing: [], as_of: Date().timeIntervalSince1970) }
        let batch: QuoteBatch = try await post("v1/market/quotes", SymbolsRequest(symbols: requested, sparklines: sparklines), endpoint: endpoint, token: token)
        let allowed = Set(requested)
        guard batch.quotes.allSatisfy({ allowed.contains($0.symbol) && MarketValidation.plausible($0) }) else {
            throw WorkspaceError(message: "Your server returned quotes that didn’t match the watchlist.")
        }
        return batch
    }

    static func search(_ query: String, endpoint: String, token: String) async throws -> SymbolSearch {
        try await post("v1/market/search", QueryRequest(query: query), endpoint: endpoint, token: token)
    }

    static func symbol(_ symbol: String, endpoint: String, token: String) async throws -> SymbolPage {
        let page: SymbolPage = try await post("v1/market/symbol", SymbolRequest(symbol: symbol), endpoint: endpoint, token: token)
        guard page.symbol == symbol, page.quote.map({ $0.symbol == symbol && MarketValidation.plausible($0) }) ?? true else {
            throw WorkspaceError(message: "Your server returned details for a different symbol.")
        }
        return page
    }

    static func chart(_ symbol: String, range: ChartRange, endpoint: String, token: String) async throws -> PriceHistory {
        let history: PriceHistory = try await post("v1/market/chart", ChartRequest(symbol: symbol, range: range.rawValue), endpoint: endpoint, token: token)
        guard history.symbol == symbol, history.range == range.rawValue,
              MarketValidation.ordered(history.points) else {
            throw WorkspaceError(message: "Your server returned an unusable price history.")
        }
        return history
    }

    static func post<T: Decodable & Sendable, B: Encodable & Sendable>(_ path: String, _ body: B,
        endpoint: String, token: String, timeout: TimeInterval = 45) async throws -> T {
        guard token.count >= 32 else { throw WorkspaceError(message: "Connect to your server in Settings to see market data.") }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent(path))
        request.httpMethod = "POST"; request.timeoutInterval = timeout
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            if status == 404 { throw WorkspaceError(message: "Your TradePilot server needs an update before it can show market data.") }
            let message = (try? JSONDecoder().decode([String: String].self, from: data))?["error"]
            throw WorkspaceError(message: message ?? "Market data isn’t available right now (HTTP \(status)).")
        }
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw WorkspaceError(message: "Your server sent market data this app couldn’t read.") }
    }
}

// MARK: - Price alerts (recorded by the gateway; they never place orders)

struct PriceAlert: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let symbol: String
    let direction: String
    let target: String
    let created_at: Double
    let status: String
    let triggered_at: Double?
    let triggered_price: String?
    let price_as_of: Double?
    var isActive: Bool { status == "active" }
    var isTriggered: Bool { status == "triggered" }
    var targetText: String { gatewayMoney(target) }
    var condition: String { "\(direction == "above" ? "Above" : "Below") \(targetText)" }
    var headline: String {
        isTriggered ? "\(symbol) \(direction == "above" ? "rose above" : "fell below") \(targetText)" : "\(symbol) \(condition.lowercased())"
    }
}

struct AlertsSnapshot: Decodable, Sendable {
    let alerts: [PriceAlert]; let active: Int; let triggered: Int; let notice: String; let as_of: Double
}

private struct AlertCreateRequest: Encodable, Sendable {
    let symbol: String; let direction: String; let target: String; let client_id: String
}
private struct AlertIDRequest: Encodable, Sendable { let id: String }

enum AlertsAPI {
    static func state(endpoint: String, token: String, timeout: TimeInterval = 45) async throws -> AlertsSnapshot {
        try await MarketAPI.post("v1/alerts/state", EmptyWorkspaceRequest(), endpoint: endpoint, token: token, timeout: timeout)
    }
    static func create(symbol: String, direction: String, target: String, clientID: String,
                       endpoint: String, token: String) async throws -> PriceAlert {
        let alert: PriceAlert = try await MarketAPI.post("v1/alerts/create",
            AlertCreateRequest(symbol: symbol, direction: direction, target: target, client_id: clientID), endpoint: endpoint, token: token)
        guard alert.symbol == symbol, alert.direction == direction,
              strictDecimal(alert.target) == strictDecimal(target) else {
            throw WorkspaceError(message: "Your server saved a different alert than requested. Check your alerts.")
        }
        return alert
    }
    static func remove(_ id: String, endpoint: String, token: String) async throws -> AlertsSnapshot {
        try await MarketAPI.post("v1/alerts/cancel", AlertIDRequest(id: id), endpoint: endpoint, token: token)
    }
    static func clearTriggered(endpoint: String, token: String) async throws -> AlertsSnapshot {
        try await MarketAPI.post("v1/alerts/clear", EmptyWorkspaceRequest(), endpoint: endpoint, token: token)
    }
}

enum MarketValidation {
    static func plausible(_ quote: MarketQuote) -> Bool {
        quote.price.isFinite && quote.price > 0 && (quote.change_percent.map { $0.isFinite && abs($0) < 100_000 } ?? true)
    }
    static func ordered(_ points: [ChartPoint]) -> Bool {
        zip(points, points.dropFirst()).allSatisfy { $0.t < $1.t } &&
            points.allSatisfy { [$0.o, $0.h, $0.l, $0.c].allSatisfy { $0.isFinite && $0 > 0 } && $0.l <= $0.h }
    }
}

// MARK: - Watchlist (stored on this iPhone)

@MainActor @Observable
final class WatchlistStore {
    static let defaultSymbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
    private static let key = "marketWatchlist.v1"
    private(set) var symbols: [String]
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.key),
           let saved = try? JSONDecoder().decode([String].self, from: data) {
            symbols = Self.clean(saved)
        } else {
            symbols = Self.defaultSymbols
        }
    }

    var isFull: Bool { symbols.count >= MarketAPI.maxSymbols }
    func contains(_ symbol: String) -> Bool { symbols.contains(symbol) }

    func toggle(_ symbol: String) { contains(symbol) ? remove(symbol) : add(symbol) }

    func add(_ symbol: String) {
        guard Self.valid(symbol), !contains(symbol), !isFull else { return }
        symbols.append(symbol); save()
    }

    func remove(_ symbol: String) { symbols.removeAll { $0 == symbol }; save() }
    func remove(atOffsets offsets: IndexSet) {
        for index in offsets.sorted(by: >) where symbols.indices.contains(index) { symbols.remove(at: index) }
        save()
    }

    func move(fromOffsets source: IndexSet, toOffset destination: Int) {
        let moving = source.sorted().compactMap { symbols.indices.contains($0) ? symbols[$0] : nil }
        guard !moving.isEmpty else { return }
        let before = source.filter { $0 < destination }.count
        var remaining = symbols
        for index in source.sorted(by: >) where remaining.indices.contains(index) { remaining.remove(at: index) }
        remaining.insert(contentsOf: moving, at: min(max(destination - before, 0), remaining.count))
        symbols = remaining; save()
    }

    func moveToTop(_ symbol: String) {
        guard let index = symbols.firstIndex(of: symbol), index > 0 else { return }
        symbols.remove(at: index); symbols.insert(symbol, at: 0); save()
    }

    private func save() {
        if let data = try? JSONEncoder().encode(symbols) { defaults.set(data, forKey: Self.key) }
    }

    nonisolated static func valid(_ symbol: String) -> Bool {
        symbol.range(of: "^[A-Z][A-Z0-9.\\-]{0,14}$", options: .regularExpression) != nil
    }

    private static func clean(_ saved: [String]) -> [String] {
        var seen = Set<String>()
        return saved.filter { valid($0) && seen.insert($0).inserted }.prefix(MarketAPI.maxSymbols).map { $0 }
    }
}

// MARK: - Formatting

enum MarketFormat {
    static let eastern = TimeZone(identifier: "America/New_York") ?? .current

    static func price(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        let digits = abs(value) < 1 ? 4 : 2
        return value.formatted(.currency(code: "USD").precision(.fractionLength(digits)))
    }

    static func change(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        let digits = abs(value) < 0.01 && value != 0 ? 4 : 2
        return value.formatted(.number.precision(.fractionLength(digits)).sign(strategy: .always(includingZero: false)))
    }

    static func percent(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return (value / 100).formatted(.percent.precision(.fractionLength(2)).sign(strategy: .always(includingZero: false)))
    }

    static func compact(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return value.formatted(.number.notation(.compactName).precision(.fractionLength(0...2)))
    }

    static func compactMoney(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return "$" + compact(value)
    }

    static func ratio(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return value.formatted(.number.precision(.fractionLength(2)))
    }

    /// Exchange time, e.g. "4:00 PM ET"; earlier days include the date.
    static func time(_ epoch: Double?, now: Date = Date()) -> String {
        guard let epoch, epoch.isFinite, epoch > 0 else { return "—" }
        let date = Date(timeIntervalSince1970: epoch)
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = eastern
        var style: Date.FormatStyle
        if calendar.isDate(date, inSameDayAs: now) {
            style = Date.FormatStyle(date: .omitted, time: .shortened)
        } else if abs(date.timeIntervalSince(now)) < 6 * 86400 {
            style = Date.FormatStyle().weekday(.abbreviated).hour().minute()
        } else {
            style = Date.FormatStyle().month(.abbreviated).day().hour().minute()
        }
        style.timeZone = eastern
        return date.formatted(style) + " ET"
    }

    static func chartTime(_ epoch: Double, range: ChartRange) -> String {
        let date = Date(timeIntervalSince1970: epoch)
        var style: Date.FormatStyle
        switch range {
        case .day: style = Date.FormatStyle(date: .omitted, time: .shortened)
        case .week, .month: style = Date.FormatStyle().month(.abbreviated).day().hour().minute()
        case .fiveYears: style = Date.FormatStyle().month(.abbreviated).day().year()
        default: style = Date.FormatStyle(date: .abbreviated, time: .omitted)
        }
        // Daily bars are dated by the trading day; keep them on that calendar date.
        style.timeZone = range.isIntraday ? eastern : TimeZone(identifier: "UTC") ?? eastern
        return date.formatted(style) + (range.isIntraday ? " ET" : "")
    }

    static func tone(_ value: Double?) -> Tone {
        guard let value, value.isFinite else { return .neutral }
        return value > 0 ? .positive : value < 0 ? .negative : .neutral
    }

    static func session(_ status: MarketStatus, now: Date = Date()) -> (label: String, detail: String?, tone: Tone) {
        switch status.state {
        case "open":
            return ("Market open", status.closes_at.map { "Closes \(time($0, now: now))" }, .positive)
        case "pre_market":
            return ("Pre-market", status.opens_at.map { "Opens \(time($0, now: now))" }, .warning)
        case "after_hours":
            return ("After hours", nil, .warning)
        default:
            return ("Market closed", status.opens_at.map { "Opens \(time($0, now: now))" }, .neutral)
        }
    }
}
