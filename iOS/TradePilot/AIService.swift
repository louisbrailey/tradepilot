import Foundation
import TradeCore

struct GatewaySetup: Decodable, Sendable {
    let version: String
    let checked_at: Double
    let ai_configured: Bool
    let ai_provider: String?
    let ai_model: String?
    let market_data_configured: Bool
    let webull_configured: Bool
    let webull_environment: String
    let live_trading_enabled: Bool
    let configuration_only: Bool
}

struct AIReply: Decodable, Sendable {
    let kind: String
    let message: String
    let side: String?
    let quantity: String?
    let symbol: String?
    let account_id: String?
    let environment: String?
    let snapshot_as_of: Double?
}

struct WebullAIRequest: Encodable {
    let prompt: String
    let selected_account: String
    let expected_environment: String
    let strategy: String
    let journal: [[String: String]]
    let mode = "webull"
}

struct AIRequest: Encodable {
    let prompt: String
    let holdings: [Holding]
    let accounts: [Account]
    let selected_account: String
    let strategy: String
    let research_ticker: String?
    let journal: [[String: String]]
    let mode = "demo"
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

enum AIService {
    static func setup(endpoint: String, token: String) async throws -> GatewaySetup {
        guard token.count >= 32 else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Save your private server address and access token first."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/setup"))
        request.httpMethod = "POST"; request.timeoutInterval = 15
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw NSError(domain: "TradePilot", code: 2, userInfo: [NSLocalizedDescriptionKey: "Connection check failed. Check your server address, saved pairing, and access token."])
        }
        return try JSONDecoder().decode(GatewaySetup.self, from: data)
    }

    static func askWebull(endpoint: String, token: String, prompt: String, selectedAccount: String,
                          expectedEnvironment: String, strategy: String,
                          journal: [[String: String]]) async throws -> AIReply {
        guard !token.isEmpty else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Set a valid HTTPS AI server URL and its access token in Accounts."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/assistant"))
        request.httpMethod = "POST"; request.timeoutInterval = 120
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(WebullAIRequest(prompt: prompt, selected_account: selectedAccount,
            expected_environment: expectedEnvironment, strategy: strategy, journal: journal))
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let message = (try? JSONDecoder().decode([String: String].self, from: data))?["error"] ?? "The AI server did not return a usable response. No order was created."
            throw NSError(domain: "TradePilot", code: 2, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return try JSONDecoder().decode(AIReply.self, from: data)
    }

    static func research(endpoint: String, token: String, ticker: String) async throws -> String {
        guard !token.isEmpty else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Configure an HTTPS server URL and access token in Accounts first."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/research"))
        request.httpMethod = "POST"; request.timeoutInterval = 120
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["ticker": ticker.uppercased()])
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw NSError(domain: "TradePilot", code: 3, userInfo: [NSLocalizedDescriptionKey: "Research unavailable. Check the server token, ticker and Massive configuration."])
        }
        return try JSONDecoder().decode([String: String].self, from: data)["summary"] ?? "No research returned."
    }

    static func ask(endpoint: String, token: String, prompt: String, holdings: [Holding], accounts: [Account], selectedAccount: String, strategy: String, researchTicker: String?, journal: [[String: String]]) async throws -> AIReply {
        guard !token.isEmpty else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Set a valid HTTPS AI server URL and its access token in Accounts."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/assistant"))
        request.httpMethod = "POST"
        request.timeoutInterval = 120
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(AIRequest(prompt: prompt, holdings: holdings, accounts: accounts, selected_account: selectedAccount, strategy: strategy, research_ticker: researchTicker, journal: journal))
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw NSError(domain: "TradePilot", code: 2, userInfo: [NSLocalizedDescriptionKey: "The AI server did not return a usable response. Check its configuration and token. No order was created."])
        }
        return try JSONDecoder().decode(AIReply.self, from: data)
    }
}

// Only the private gateway token is stored here; brokerage secrets never enter the app.
import Security

enum ConnectionSettings {
    static var endpoint: String { UserDefaults.standard.string(forKey: "gatewayEndpoint") ?? "" }
    static var pairedOrigin: String { UserDefaults.standard.string(forKey: "gatewayPinnedOrigin") ?? "" }
    static var hasPairingArtifacts: Bool {
        !pairedOrigin.isEmpty || !(UserDefaults.standard.string(forKey: "gatewayPinnedHost") ?? "").isEmpty || FileManager.default.fileExists(atPath: certificateURL.path)
    }
    static var token: String {
        var item: CFTypeRef?
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "TradePilot.gateway", kSecAttrAccount as String: "access-token",
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }
    static func save(endpoint: String, token: String) throws {
        let url = try validatedEndpoint(endpoint)
        let pairedOrigin = try resolvedPairedOrigin()
        if !pairedOrigin.isEmpty, origin(for: url) != pairedOrigin {
            throw NSError(domain: "TradePilot", code: 11, userInfo: [NSLocalizedDescriptionKey: "This device is paired to a different gateway origin. Import a new pairing to change servers."])
        }
        try saveTokenAndEndpoint(endpoint: endpoint, token: token)
    }
    static func authorizedEndpoint(_ endpoint: String) throws -> URL {
        let url = try validatedEndpoint(endpoint)
        if !matchesPairedOrigin(url, pairedOrigin: try resolvedPairedOrigin()) {
            throw NSError(domain: "TradePilot", code: 12, userInfo: [NSLocalizedDescriptionKey: "This request is blocked because the gateway origin does not match the paired device."])
        }
        return url
    }
    static func matchesPairedOrigin(_ url: URL, pairedOrigin: String) -> Bool {
        pairedOrigin.isEmpty || origin(for: url) == pairedOrigin
    }
    static func resolvedPairedOrigin() throws -> String {
        if !pairedOrigin.isEmpty { return pairedOrigin }
        guard hasPairingArtifacts else { return "" }
        guard let url = try? validatedEndpoint(endpoint), let host = url.host,
              let pinnedHost = UserDefaults.standard.string(forKey: "gatewayPinnedHost"),
              host.caseInsensitiveCompare(pinnedHost) == .orderedSame else {
            throw NSError(domain: "TradePilot", code: 13, userInfo: [NSLocalizedDescriptionKey: "Gateway pairing metadata is incomplete. Import a new pairing before sending a request."])
        }
        let migratedOrigin = origin(for: url)
        UserDefaults.standard.set(migratedOrigin, forKey: "gatewayPinnedOrigin")
        return migratedOrigin
    }
    static func validatedEndpoint(_ endpoint: String) throws -> URL {
        guard let url = URL(string: endpoint), url.scheme?.lowercased() == "https", url.host != nil,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil else {
            throw NSError(domain: "TradePilot", code: 1, userInfo: [NSLocalizedDescriptionKey: "Configure a valid HTTPS server URL in Accounts first."])
        }
        return url
    }
    static func origin(for url: URL) -> String {
        let host = url.host!.lowercased()
        return "https://\(host):\(url.port ?? 443)"
    }
    private static func saveTokenAndEndpoint(endpoint: String, token: String) throws {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "TradePilot.gateway", kSecAttrAccount as String: "access-token"]
        let values: [String: Any] = [kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var result = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if result == errSecItemNotFound {
            result = SecItemAdd(query.merging(values) { _, new in new } as CFDictionary, nil)
        }
        guard result == errSecSuccess else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(result), userInfo: [NSLocalizedDescriptionKey: "The gateway token could not be saved in Keychain."])
        }
        UserDefaults.standard.set(endpoint, forKey: "gatewayEndpoint")
    }
}

struct DevicePairing: Codable {
    let endpoint: String
    let token: String
    let certificate: String
}

extension ConnectionSettings {
    static var certificateURL: URL { URL.applicationSupportDirectory.appendingPathComponent("TradePilot/gateway.cer") }
    static func importPairing() throws {
        let file = URL.documentsDirectory.appendingPathComponent("TradePilotPairing.json")
        guard FileManager.default.fileExists(atPath: file.path) else { return }
        let pairing = try JSONDecoder().decode(DevicePairing.self, from: Data(contentsOf: file))
        guard let url = try? validatedEndpoint(pairing.endpoint),
              let certificate = Data(base64Encoded: pairing.certificate), SecCertificateCreateWithData(nil, certificate as CFData) != nil,
              pairing.token.count >= 32 else {
            throw NSError(domain: "TradePilot", code: 10, userInfo: [NSLocalizedDescriptionKey: "Invalid device pairing file."])
        }
        let previousCertificate = try? Data(contentsOf: certificateURL)
        do {
            try FileManager.default.createDirectory(at: certificateURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try certificate.write(to: certificateURL, options: .atomic)
            try saveTokenAndEndpoint(endpoint: pairing.endpoint, token: pairing.token)
            UserDefaults.standard.set(url.host, forKey: "gatewayPinnedHost")
            UserDefaults.standard.set(origin(for: url), forKey: "gatewayPinnedOrigin")
        } catch {
            if let previousCertificate { try? previousCertificate.write(to: certificateURL, options: .atomic) }
            else { try? FileManager.default.removeItem(at: certificateURL) }
            throw error
        }
        try FileManager.default.removeItem(at: file)
    }
}

// Trust only the certificate paired through local device installation, for its exact host.
// Requests to any other origin are rejected before a token can be sent.
final class GatewaySessionDelegate: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust else {
            completionHandler(.performDefaultHandling, nil); return
        }
        let pairedOrigin = ConnectionSettings.pairedOrigin
        guard !pairedOrigin.isEmpty else {
            completionHandler(ConnectionSettings.hasPairingArtifacts ? .cancelAuthenticationChallenge : .performDefaultHandling, nil); return
        }
        guard challenge.protectionSpace.host.caseInsensitiveCompare(UserDefaults.standard.string(forKey: "gatewayPinnedHost") ?? "") == .orderedSame else {
            completionHandler(.cancelAuthenticationChallenge, nil); return
        }
        guard let trust = challenge.protectionSpace.serverTrust,
              let data = try? Data(contentsOf: ConnectionSettings.certificateURL),
              let certificate = SecCertificateCreateWithData(nil, data as CFData),
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate], let peer = chain.first,
              (SecCertificateCopyData(peer) as Data) == data else {
            completionHandler(.cancelAuthenticationChallenge, nil); return
        }
        SecTrustSetAnchorCertificates(trust, [certificate] as CFArray)
        SecTrustSetAnchorCertificatesOnly(trust, true)
        guard SecTrustEvaluateWithError(trust, nil) else {
            completionHandler(.cancelAuthenticationChallenge, nil); return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}

struct RecordedEvaluationCost: Decodable, Sendable {
    let bps_per_side: Int
    let return_pct: Double
    let benchmark_return_pct: Double
}

struct RecordedEvaluationRow: Decodable, Sendable, Identifiable {
    var id: String { symbol }
    let symbol: String
    let bar_count: Int
    let selected_window: Int
    let source_start: String
    let source_end: String
    let validation_passed: Bool
    let validation_excess_pct: Double
    let holdout_start: String
    let holdout_end: String
    let holdout_return_pct: Double
    let benchmark_return_pct: Double
    let excess_return_pct: Double
    let max_drawdown_pct: Double
    let fills: Int
    let cost_sensitivity: [RecordedEvaluationCost]
}

struct RecordedEvaluation: Decodable, Sendable {
    let schema_version: Int
    let historical_only: Bool
    let previously_observed: Bool
    let scope: String
    let evaluated_at: String
    let protocol_sha256: String
    let baseline_cost_bps: Int
    let source_start: String
    let source_end: String
    let expected_symbols: Int
    let unavailable_symbols: [String]
    let rows: [RecordedEvaluationRow]
    let conclusion: String
    let limitations: [String]
}

enum EvaluationValidation {
    static func isValid(_ report: RecordedEvaluation) -> Bool {
        func day(_ value: String) -> Bool { value.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil }
        guard report.schema_version == 1, report.historical_only, report.previously_observed,
              report.scope == "sma-long-cash", report.baseline_cost_bps == 10,
              report.protocol_sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              day(report.source_start), day(report.source_end), report.source_start <= report.source_end,
              !report.rows.isEmpty, report.rows.count <= 30,
              Set(report.rows.map(\.symbol) + report.unavailable_symbols).count == report.expected_symbols,
              report.rows.count + report.unavailable_symbols.count == report.expected_symbols,
              !report.conclusion.isEmpty, !report.limitations.isEmpty else { return false }
        return report.rows.allSatisfy { row in
            guard row.symbol.range(of: "^[A-Z][A-Z0-9.\\-]{0,14}$", options: .regularExpression) != nil,
                  row.bar_count >= 500, [10, 20, 50].contains(row.selected_window), row.fills >= 0,
                  [row.validation_excess_pct, row.holdout_return_pct, row.benchmark_return_pct,
                   row.excess_return_pct, row.max_drawdown_pct].allSatisfy(\.isFinite),
                  (0...100).contains(row.max_drawdown_pct),
                  abs(row.holdout_return_pct - row.benchmark_return_pct - row.excess_return_pct) < 1e-7,
                  [row.source_start, row.source_end, row.holdout_start, row.holdout_end].allSatisfy(day),
                  report.source_start <= row.source_start, row.source_start <= row.holdout_start,
                  row.holdout_start <= row.holdout_end, row.holdout_end <= row.source_end,
                  row.source_end <= report.source_end,
                  row.cost_sensitivity.map(\.bps_per_side) == [0, 10, 25, 50],
                  row.cost_sensitivity.allSatisfy({ $0.return_pct.isFinite && $0.benchmark_return_pct.isFinite }),
                  row.cost_sensitivity[1].return_pct == row.holdout_return_pct,
                  row.cost_sensitivity[1].benchmark_return_pct == row.benchmark_return_pct else { return false }
            return true
        }
    }

    static func connectionMatches(endpoint: String, token: String, currentEndpoint: String, currentToken: String) -> Bool {
        endpoint == currentEndpoint && token == currentToken
    }
}

extension AIService {
    static func evaluation(endpoint: String, token: String) async throws -> RecordedEvaluation {
        guard token.count >= 32 else {
            throw NSError(domain: "TradePilot", code: 21, userInfo: [NSLocalizedDescriptionKey: "Save your private gateway connection in Accounts first."])
        }
        let base = try ConnectionSettings.authorizedEndpoint(endpoint)
        var request = URLRequest(url: base.appendingPathComponent("v1/research/evaluation"))
        request.httpMethod = "POST"; request.timeoutInterval = 15
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        let session = URLSession(configuration: .ephemeral, delegate: GatewaySessionDelegate(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 200_000 else {
            throw NSError(domain: "TradePilot", code: 22, userInfo: [NSLocalizedDescriptionKey: "The recorded evaluation is unavailable. Check the private gateway connection and installed research report."])
        }
        let report = try JSONDecoder().decode(RecordedEvaluation.self, from: data)
        guard EvaluationValidation.isValid(report) else {
            throw NSError(domain: "TradePilot", code: 23, userInfo: [NSLocalizedDescriptionKey: "The recorded evaluation failed its data checks. No strategy was activated."])
        }
        return report
    }
}
