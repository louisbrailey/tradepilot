import SwiftUI
import UserNotifications
#if os(iOS)
import BackgroundTasks
#endif

// Local notifications for price alerts the gateway has recorded. This only tells the user;
// it cannot create, review or place orders. Push notifications would need a paid Apple
// Developer account, so iOS background refresh checks the gateway instead.

enum AlertNotifier {
    static let refreshTask = "com.louisbrailey.TradePilot.alerts"
    private static let notifiedKey = "notifiedAlertIDs.v1"

    static func requestPermission() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
    }

    /// One notification per newly triggered alert; the app badge shows how many are triggered.
    static func deliver(_ snapshot: AlertsSnapshot) async {
        let center = UNUserNotificationCenter.current()
        let status = await center.notificationSettings().authorizationStatus
        let defaults = UserDefaults.standard
        var notified = defaults.stringArray(forKey: notifiedKey) ?? []
        let fresh = snapshot.alerts.filter { $0.isTriggered && !notified.contains($0.id) }
        if status == .authorized || status == .provisional {
            for alert in fresh {
                let content = UNMutableNotificationContent()
                content.title = alert.headline
                content.body = (alert.triggered_price.map { "Reached \(gatewayMoney($0)). " } ?? "") + "Alerts never place orders."
                content.sound = .default
                content.threadIdentifier = "price-alerts"
                content.userInfo = ["symbol": alert.symbol]
                try? await center.add(UNNotificationRequest(identifier: alert.id, content: content, trigger: nil))
            }
            try? await center.setBadgeCount(snapshot.triggered)
        }
        // Triggers seen while notifications are off are not announced later.
        notified.append(contentsOf: fresh.map(\.id))
        defaults.set(Array(notified.suffix(300)), forKey: notifiedKey)
    }

    static func schedule() {
        #if os(iOS)
        let request = BGAppRefreshTaskRequest(identifier: refreshTask)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
        #endif
    }

    /// Background refresh: check alerts over the paired connection, notify, then ask for the next check.
    static func backgroundCheck() async {
        schedule()
        let endpoint = ConnectionSettings.endpoint, token = ConnectionSettings.token
        // The token is readable only while the iPhone is unlocked; a locked phone skips this check.
        guard token.count >= 32,
              let snapshot = try? await AlertsAPI.state(endpoint: endpoint, token: token, timeout: 20) else { return }
        await deliver(snapshot)
    }
}

/// Shows alert banners while the app is open and opens the symbol when a notification is tapped.
final class NotificationRouter: NSObject, UNUserNotificationCenterDelegate, @unchecked Sendable {
    static let shared = NotificationRouter()
    @MainActor var open: ((String) -> Void)?

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard let symbol = response.notification.request.content.userInfo["symbol"] as? String,
              WatchlistStore.valid(symbol) else { return }
        await MainActor.run { open?(symbol) }
    }
}
