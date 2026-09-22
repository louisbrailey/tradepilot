import Foundation

public struct Account: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let kind: String
    public let canTrade: Bool
    public var cash: Decimal
}

public struct Holding: Identifiable, Codable, Equatable, Sendable {
    public let id: String
    public let accountID: String
    public let symbol: String
    public let name: String
    public let kind: String
    public var quantity: Decimal
    public let price: Decimal
    public let costPerUnit: Decimal
    public var value: Decimal { quantity * price }
    public var gain: Decimal { quantity * (price - costPerUnit) }
}

public enum Side: String, Codable, Sendable { case buy, sell }

public struct TradeIntent: Equatable, Sendable {
    public let side: Side
    public let quantity: Decimal
    public let symbol: String
    public init(side: Side, quantity: Decimal, symbol: String) {
        self.side = side; self.quantity = quantity; self.symbol = symbol
    }
}

public enum AssistantIntent: Equatable, Sendable {
    case portfolio
    case trade(TradeIntent)
    case help
}

/// Deliberately constrained demo parser. Arbitrary prose never becomes an order.
/// A future language-model response must be treated as an untrusted proposal.
public enum DemoAssistant {
    public static func parse(_ input: String) -> AssistantIntent {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let pattern = #"^(?:please\s+)?(buy|sell)\s+([0-9]+(?:\.[0-9]{1,8})?)\s+(?:(?:shares?|units?)\s+(?:of\s+)?)?([a-z][a-z0-9.\-]{0,14})[.!]?$"#
        if let regex = try? NSRegularExpression(pattern: pattern),
           let match = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let sideRange = Range(match.range(at: 1), in: text),
           let quantityRange = Range(match.range(at: 2), in: text),
           let symbolRange = Range(match.range(at: 3), in: text),
           let side = Side(rawValue: String(text[sideRange])),
           let quantity = Decimal(string: String(text[quantityRange]), locale: Locale(identifier: "en_US_POSIX")),
           quantity > 0, quantity <= 1_000_000_000 {
            return .trade(TradeIntent(side: side, quantity: quantity, symbol: String(text[symbolRange]).uppercased()))
        }
        if text.contains("portfolio") || text.contains("holdings") || text.contains("table") {
            return .portfolio
        }
        return .help
    }
}

public struct TradePreview: Identifiable, Codable, Equatable, Sendable {
    public let id: UUID
    public let holdingID: String
    public let accountID: String
    public let symbol: String
    public let side: Side
    public let quantity: Decimal
    public let price: Decimal
    public let createdAt: Date
    public let expiresAt: Date
    public var gross: Decimal { quantity * price }
}

public enum OrderStatus: String, Codable, Sendable {
    case submitted, partiallyFilled, filled, rejected, cancelled, unknown
}

public struct Order: Identifiable, Codable, Equatable, Sendable {
    public let id: UUID
    public let preview: TradePreview
    public let status: OrderStatus
    public let createdAt: Date
    public let detail: String
}

public enum TradeError: LocalizedError, Equatable {
    case unknownHolding, ambiguousAccount, readOnly, invalidQuantity, insufficientHolding, insufficientCash
    case expired, invalidPreview, confirmationRequired
    public var errorDescription: String? {
        switch self {
        case .unknownHolding: "That asset is not available in the selected demo account. Choose an account and a symbol from Holdings."
        case .ambiguousAccount: "This asset is held in more than one account. Select one account before requesting a trade."
        case .readOnly: "This account allows viewing only. Trading is unavailable."
        case .invalidQuantity: "Enter a positive quantity with no more than eight decimal places."
        case .insufficientHolding: "You do not have enough available units in this account."
        case .insufficientCash: "This account does not have enough demo cash for this purchase."
        case .expired: "This review has expired. Request a fresh trade review."
        case .invalidPreview: "This review is no longer active. Request a new one."
        case .confirmationRequired: "Review and confirm this exact order before submitting it."
        }
    }
}

/// In-memory simulator only. No credentials, networking, or real broker execution.
/// Keep authoritative validation, durable idempotency, and reconciliation server-side in production.
public struct DemoEngine: Sendable {
    public private(set) var accounts: [Account]
    public private(set) var holdings: [Holding]
    public private(set) var orders: [Order] = []
    private var previews: [UUID: TradePreview] = [:]

    public init() {
        accounts = [
            Account(id: "stocks", name: "Demo brokerage · 1042", kind: "Stocks & ETFs", canTrade: true, cash: 8200),
            Account(id: "crypto", name: "Demo exchange · 2091", kind: "Crypto", canTrade: true, cash: 2450),
            Account(id: "retirement", name: "Demo retirement · 8830", kind: "Retirement", canTrade: false, cash: 1200)
        ]
        holdings = [
            Holding(id: "stocks-aapl", accountID: "stocks", symbol: "AAPL", name: "Apple", kind: "Stock", quantity: 24, price: 215, costPerUnit: 180),
            Holding(id: "stocks-nvda", accountID: "stocks", symbol: "NVDA", name: "NVIDIA", kind: "Stock", quantity: 40, price: 125, costPerUnit: 95),
            Holding(id: "stocks-voo", accountID: "stocks", symbol: "VOO", name: "Vanguard S&P 500 ETF", kind: "ETF", quantity: 15, price: 510, costPerUnit: 450),
            Holding(id: "crypto-btc", accountID: "crypto", symbol: "BTC", name: "Bitcoin", kind: "Crypto", quantity: Decimal(string: "0.12")!, price: 65000, costPerUnit: 52000),
            Holding(id: "crypto-eth", accountID: "crypto", symbol: "ETH", name: "Ethereum", kind: "Crypto", quantity: Decimal(string: "1.8")!, price: 3200, costPerUnit: 2800),
            Holding(id: "retirement-voo", accountID: "retirement", symbol: "VOO", name: "Vanguard S&P 500 ETF", kind: "ETF", quantity: 32, price: 510, costPerUnit: 420)
        ]
    }

    public var totalValue: Decimal { holdings.reduce(0) { $0 + $1.value } + accounts.reduce(0) { $0 + $1.cash } }
    public var totalGain: Decimal { holdings.reduce(0) { $0 + $1.gain } }
    public func accountName(_ id: String) -> String { accounts.first { $0.id == id }?.name ?? "Unknown account" }

    public mutating func preview(_ intent: TradeIntent, accountID: String? = nil, now: Date = Date()) throws -> TradePreview {
        let candidates = holdings.filter { $0.symbol == intent.symbol && (accountID == nil || $0.accountID == accountID) }
        guard !candidates.isEmpty else { throw TradeError.unknownHolding }
        guard candidates.count == 1 else { throw TradeError.ambiguousAccount }
        let holding = candidates[0]
        try validate(side: intent.side, quantity: intent.quantity, holdingID: holding.id)
        let result = TradePreview(id: UUID(), holdingID: holding.id, accountID: holding.accountID,
                                  symbol: holding.symbol, side: intent.side, quantity: intent.quantity,
                                  price: holding.price, createdAt: now, expiresAt: now.addingTimeInterval(60))
        // Only one active review: a new proposal invalidates the previous one.
        previews = [result.id: result]
        return result
    }

    public mutating func cancel(_ id: UUID) { previews.removeValue(forKey: id) }

    public mutating func confirm(_ id: UUID, approved: Bool, simulateRejection: Bool = false, now: Date = Date()) throws -> Order {
        guard approved else { throw TradeError.confirmationRequired }
        // A repeated tap returns the same receipt without changing the portfolio again.
        if let existing = orders.first(where: { $0.preview.id == id }) { return existing }
        guard let preview = previews[id] else { throw TradeError.invalidPreview }
        guard now < preview.expiresAt else { previews.removeValue(forKey: id); throw TradeError.expired }
        try validate(side: preview.side, quantity: preview.quantity, holdingID: preview.holdingID)
        guard let hi = holdings.firstIndex(where: { $0.id == preview.holdingID }),
              let ai = accounts.firstIndex(where: { $0.id == preview.accountID }) else { throw TradeError.unknownHolding }
        let status: OrderStatus = simulateRejection ? .rejected : .filled
        if status == .filled {
            let sign: Decimal = preview.side == .buy ? 1 : -1
            // Preserve weighted average cost when adding units in the demo.
            let old = holdings[hi]
            let newQuantity = old.quantity + sign * preview.quantity
            let cost = preview.side == .buy ? (old.quantity * old.costPerUnit + preview.gross) / newQuantity : old.costPerUnit
            holdings[hi] = Holding(id: old.id, accountID: old.accountID, symbol: old.symbol, name: old.name,
                                  kind: old.kind, quantity: newQuantity, price: old.price, costPerUnit: cost)
            accounts[ai].cash -= sign * preview.gross
        }
        let order = Order(id: UUID(), preview: preview, status: status, createdAt: now,
                          detail: simulateRejection ? "Simulated rejection. No holdings or cash changed." : "Simulated fill at the fixed sample price. No real trade was placed.")
        orders.insert(order, at: 0)
        previews.removeValue(forKey: id)
        return order
    }

    private func validate(side: Side, quantity: Decimal, holdingID: String) throws {
        var input = quantity
        var rounded = Decimal()
        NSDecimalRound(&rounded, &input, 8, .plain)
        guard !quantity.isNaN, quantity > 0, quantity <= 1_000_000_000, rounded == quantity else { throw TradeError.invalidQuantity }
        guard let h = holdings.first(where: { $0.id == holdingID }), let a = accounts.first(where: { $0.id == h.accountID }) else { throw TradeError.unknownHolding }
        guard a.canTrade else { throw TradeError.readOnly }
        if side == .sell && quantity > h.quantity { throw TradeError.insufficientHolding }
        if side == .buy && quantity * h.price > a.cash { throw TradeError.insufficientCash }
    }
}
