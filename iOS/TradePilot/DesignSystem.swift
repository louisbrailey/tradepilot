import SwiftUI
#if os(iOS)
import UIKit
#endif

// Presentation layer only. Nothing here touches order, confirmation or connection logic.

enum Theme {
    static let background = adaptive(0xF3F5F9, 0x101620)
    static let surface = adaptive(0xFFFFFF, 0x192333)
    static let surfaceRaised = adaptive(0xEBF0F6, 0x243246)
    static let separator = adaptive(0xDCE3ED, 0x34445B)
    static let textPrimary = adaptive(0x141E30, 0xF2F5FA)
    static let textSecondary = adaptive(0x435469, 0xB7C4D5)
    static let textTertiary = adaptive(0x53667E, 0x9AAAC0)
    static let accent = adaptive(0x1A4F99, 0x91BCFF)
    static let onAccent = adaptive(0xFFFFFF, 0x101620)
    static let positive = adaptive(0x0E6E4B, 0x6FD7A3)
    static let negative = adaptive(0xAE293D, 0xFF99A6)
    static let warning = adaptive(0x804D04, 0xF4C369)
    static let live = adaptive(0xA52B38, 0xFF99A6)
    static let paper = accent
    static let practice = textSecondary

    private static func adaptive(_ light: UInt32, _ dark: UInt32) -> Color {
        #if os(iOS)
        Color(uiColor: UIColor { traits in
            let rgb = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((rgb >> 16) & 255) / 255,
                           green: CGFloat((rgb >> 8) & 255) / 255,
                           blue: CGFloat(rgb & 255) / 255, alpha: 1)
        })
        #else
        Color(red: Double((light >> 16) & 255) / 255,
              green: Double((light >> 8) & 255) / 255,
              blue: Double(light & 255) / 255)
        #endif
    }
}

enum Spacing {
    static let xs: CGFloat = 4, s: CGFloat = 8, m: CGFloat = 12, l: CGFloat = 16, xl: CGFloat = 24, xxl: CGFloat = 32
}

enum Radius {
    static let card: CGFloat = 12, control: CGFloat = 8
}

// MARK: - Formatting

func money(_ number: Decimal, currency: String = "USD") -> String {
    let f = NumberFormatter()
    f.locale = Locale.current
    f.numberStyle = .currency
    f.currencyCode = currency
    return f.string(from: number as NSDecimalNumber) ?? "—"
}

func signedMoney(_ number: Decimal, currency: String = "USD") -> String {
    number > 0 ? "+" + money(number, currency: currency) : money(number, currency: currency)
}

func units(_ number: Decimal) -> String { NSDecimalNumber(decimal: number).stringValue }

func percent(_ value: Double, digits: Int = 2, signed: Bool = false) -> String {
    guard value.isFinite else { return "—" }
    return String(format: signed ? "%+.\(digits)f%%" : "%.\(digits)f%%", value)
}

func relativeTime(_ date: Date, now: Date = Date()) -> String {
    let seconds = now.timeIntervalSince(date)
    guard seconds.isFinite else { return "—" }
    if seconds < -60 { return date.formatted(date: .abbreviated, time: .shortened) }
    if seconds < 60 { return "just now" }
    if seconds < 24 * 3600 {
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .short
        return f.localizedString(for: date, relativeTo: now)
    }
    return date.formatted(date: .abbreviated, time: .shortened)
}

func relativeTime(_ epoch: Double) -> String { relativeTime(Date(timeIntervalSince1970: epoch)) }

/// Strict decimal from a gateway string. Rejects exponents, prefixes and NaN.
func strictDecimal(_ text: String, allowNegative: Bool = true) -> Decimal? {
    let pattern = allowNegative ? "^-?[0-9]+(?:\\.[0-9]+)?$" : "^[0-9]+(?:\\.[0-9]+)?$"
    guard text.count <= 64, text.range(of: pattern, options: .regularExpression) != nil,
          let value = Decimal(string: text, locale: Locale(identifier: "en_US_POSIX")), !value.isNaN else { return nil }
    return value
}

/// Money from a gateway decimal string; "—" when the value is missing or malformed.
func gatewayMoney(_ text: String, currency: String = "USD", signed: Bool = false) -> String {
    guard let value = strictDecimal(text) else { return "—" }
    return signed ? signedMoney(value, currency: currency) : money(value, currency: currency)
}

func gatewayDate(_ epoch: Double) -> String { Date(timeIntervalSince1970: epoch).formatted(date: .abbreviated, time: .shortened) }

func titleCase(_ identifier: String) -> String {
    identifier.replacingOccurrences(of: "_", with: " ").capitalized
}

func deltaColor(_ text: String) -> Color {
    guard let value = strictDecimal(text) else { return Theme.textSecondary }
    return value > 0 ? Theme.positive : value < 0 ? Theme.negative : Theme.textSecondary
}

func deltaColor(_ value: Decimal) -> Color { value > 0 ? Theme.positive : value < 0 ? Theme.negative : Theme.textSecondary }

// MARK: - Text styles

struct Eyebrow: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text).font(.footnote.weight(.medium)).foregroundStyle(Theme.textSecondary)
    }
}

struct Footnote: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View { Text(text).font(.footnote).foregroundStyle(Theme.textTertiary).fixedSize(horizontal: false, vertical: true) }
}

// MARK: - Status badge

enum Tone { case neutral, accent, positive, negative, warning, live, paper, practice
    var color: Color {
        switch self {
        case .neutral: Theme.textSecondary
        case .accent: Theme.accent
        case .positive: Theme.positive
        case .negative: Theme.negative
        case .warning: Theme.warning
        case .live: Theme.live
        case .paper: Theme.paper
        case .practice: Theme.practice
        }
    }
}

struct StatusBadge: View {
    let text: String
    let tone: Tone
    init(_ text: String, tone: Tone = .neutral) { self.text = text; self.tone = tone }
    var body: some View {
        Text(text).font(.caption.weight(.semibold))
            .padding(.horizontal, Spacing.s).padding(.vertical, Spacing.xs)
            .background(tone.color.opacity(0.10), in: RoundedRectangle(cornerRadius: 5))
            .foregroundStyle(tone.color)
            .accessibilityLabel(Text(text))
    }
    /// Gateway environment and account-type words mapped to user-facing labels.
    static func environment(_ raw: String?) -> StatusBadge {
        switch raw {
        case "production": StatusBadge("Live", tone: .live)
        case "sandbox": StatusBadge("Sandbox", tone: .warning)
        case "paper", "automated_paper": StatusBadge("Paper", tone: .paper)
        case "demo": StatusBadge("Practice", tone: .practice)
        case nil, "": StatusBadge("Not connected")
        default: StatusBadge(titleCase(raw ?? ""))
        }
    }
    /// Order and review states reported by the gateway.
    static func orderState(_ raw: String) -> StatusBadge {
        switch raw.uppercased() {
        case "FILLED": StatusBadge("Filled", tone: .positive)
        case "PARTIALLY_FILLED", "PARTIAL": StatusBadge("Partly filled", tone: .accent)
        case "REVIEW": StatusBadge("Awaiting confirmation", tone: .accent)
        case "SUBMITTING", "SUBMITTED", "ACCEPTED", "PENDING": StatusBadge("Sent", tone: .accent)
        case "UNKNOWN": StatusBadge("Unconfirmed", tone: .warning)
        case "CANCELLED", "CANCELLED_REVIEW", "DISMISSED": StatusBadge("Cancelled")
        case "FAILED", "REJECTED": StatusBadge("Rejected", tone: .negative)
        case "EXPIRED": StatusBadge("Expired")
        default: StatusBadge(titleCase(raw.lowercased()))
        }
    }
}

// MARK: - Cards and tiles

struct SectionCard<Content: View>: View {
    var title: String? = nil
    var footer: String? = nil
    @ViewBuilder var content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.m) {
            if let title { Text(title).font(.headline).foregroundStyle(Theme.textPrimary).accessibilityAddTraits(.isHeader) }
            content
            if let footer { Footnote(footer) }
        }
        .padding(Spacing.l)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous).strokeBorder(Theme.separator, lineWidth: 1))
    }
}

struct MetricTile: View {
    let label: String
    let value: String
    var tone: Tone? = nil
    var caption: String? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Eyebrow(label)
            Text(value).font(.title3.weight(.semibold)).monospacedDigit().fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(tone?.color ?? Theme.textPrimary)
            if let caption { Text(caption).font(.caption).foregroundStyle(Theme.textTertiary) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

struct MetricsGrid<Content: View>: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    @ViewBuilder var content: Content
    var body: some View {
        let columns = typeSize.isAccessibilitySize ? [GridItem(.flexible())] : [GridItem(.adaptive(minimum: 108), spacing: Spacing.l)]
        LazyVGrid(columns: columns, alignment: .leading, spacing: Spacing.m) { content }
    }
}

struct HeroMetric: View {
    let label: String
    let value: String
    var delta: String? = nil
    var deltaTone: Tone = .neutral
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.s) {
            Eyebrow(label)
            Text(value).font(.system(.largeTitle, design: .rounded).weight(.semibold)).monospacedDigit().minimumScaleFactor(0.6).lineLimit(1)
            if let delta { Text(delta).font(.subheadline.weight(.medium)).monospacedDigit().foregroundStyle(deltaTone.color) }
        }
        .accessibilityElement(children: .combine)
    }
}

struct DetailRow: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let label: String
    let value: String
    var tone: Tone? = nil
    init(_ label: String, _ value: String, tone: Tone? = nil) { self.label = label; self.value = value; self.tone = tone }
    var body: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Spacing.xs))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: Spacing.m))
        layout {
            Text(label).foregroundStyle(Theme.textSecondary)
            if !typeSize.isAccessibilitySize { Spacer(minLength: 0) }
            Text(value).monospacedDigit().multilineTextAlignment(typeSize.isAccessibilitySize ? .leading : .trailing)
                .foregroundStyle(tone?.color ?? Theme.textPrimary).textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .font(.subheadline)
        .accessibilityElement(children: .combine)
    }
}

/// Symbol + description on the left, value + signed change on the right.
struct HoldingRow: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let symbol: String
    let detail: String
    let value: String
    var change: String? = nil
    var changeTone: Tone = .neutral
    var body: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: Spacing.xs))
            : AnyLayout(HStackLayout(alignment: .firstTextBaseline, spacing: Spacing.m))
        layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(symbol).font(.subheadline.weight(.semibold))
                Text(detail).font(.caption).foregroundStyle(Theme.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
            if !typeSize.isAccessibilitySize { Spacer(minLength: 0) }
            VStack(alignment: typeSize.isAccessibilitySize ? .leading : .trailing, spacing: 2) {
                Text(value).font(.subheadline.weight(.semibold)).monospacedDigit()
                if let change { Text(change).font(.caption).monospacedDigit().foregroundStyle(changeTone.color) }
            }
            .multilineTextAlignment(typeSize.isAccessibilitySize ? .leading : .trailing)
            .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, Spacing.s)
        .accessibilityElement(children: .combine)
    }
}

struct NavigationRow: View {
    let title: String
    var detail: String? = nil
    var icon: String
    var badge: StatusBadge? = nil
    var body: some View {
        HStack(spacing: Spacing.m) {
            Image(systemName: icon).font(.body.weight(.medium)).foregroundStyle(Theme.accent).frame(width: 24).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.textPrimary)
                if let detail { Text(detail).font(.caption).foregroundStyle(Theme.textSecondary) }
            }
            Spacer(minLength: Spacing.s)
            if let badge { badge }
            Image(systemName: "chevron.right").font(.caption.weight(.semibold)).foregroundStyle(Theme.textTertiary).accessibilityHidden(true)
        }
        .padding(.vertical, Spacing.s)
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }
}

// MARK: - Notices and empty states

enum NoticeKind { case info, success, warning, error
    var icon: String {
        switch self {
        case .info: "info.circle"
        case .success: "checkmark.circle"
        case .warning: "exclamationmark.triangle"
        case .error: "xmark.octagon"
        }
    }
    var color: Color {
        switch self {
        case .info: Theme.textSecondary
        case .success: Theme.positive
        case .warning: Theme.warning
        case .error: Theme.negative
        }
    }
}

struct InlineNotice: View {
    let kind: NoticeKind
    let message: String
    var action: (title: String, run: () -> Void)? = nil
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.s) {
            Image(systemName: kind.icon).foregroundStyle(kind.color).accessibilityHidden(true)
            Text(message).font(.footnote).foregroundStyle(Theme.textPrimary).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            Spacer(minLength: 0)
            if let action { Button(action.title, action: action.run).font(.footnote.weight(.semibold)) }
        }
        .padding(Spacing.m)
        .background(kind.color.opacity(0.10), in: RoundedRectangle(cornerRadius: Radius.control, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// One slot per screen for the latest outcome. Empty text renders nothing.
struct OutcomeNotice: View {
    let text: String
    var kind: NoticeKind = .info
    var body: some View {
        if !text.isEmpty { InlineNotice(kind: kind, message: text) }
    }
}

struct EmptyState: View {
    let title: String
    let message: String
    var icon: String = "tray"
    var body: some View {
        VStack(spacing: Spacing.s) {
            Image(systemName: icon).font(.title2).foregroundStyle(Theme.textTertiary).accessibilityHidden(true)
            Text(title).font(.subheadline.weight(.semibold))
            Text(message).font(.footnote).foregroundStyle(Theme.textSecondary).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity).padding(.vertical, Spacing.xl)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Buttons

struct PrimaryButtonStyle: ButtonStyle {
    var tone: Tone = .accent
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, Spacing.m).padding(.vertical, Spacing.s)
            .frame(maxWidth: .infinity, minHeight: 44)
            .foregroundStyle(isEnabled ? Theme.onAccent : Theme.textSecondary)
            .background((tone.color).opacity(configuration.isPressed ? 0.75 : isEnabled ? 1 : 0.35), in: RoundedRectangle(cornerRadius: Radius.control, style: .continuous))
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .padding(.horizontal, Spacing.m).padding(.vertical, Spacing.s)
            .frame(maxWidth: .infinity, minHeight: 44)
            .foregroundStyle(Theme.textPrimary.opacity(isEnabled ? 1 : 0.4))
            .background(Theme.surfaceRaised.opacity(configuration.isPressed ? 0.7 : 1), in: RoundedRectangle(cornerRadius: Radius.control, style: .continuous))
    }
}

struct RowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.opacity(configuration.isPressed ? 0.6 : 1)
    }
}

// MARK: - Screen scaffold

struct Screen<Content: View>: View {
    let title: String
    var refresh: (() async -> Void)? = nil
    @ViewBuilder var content: Content
    var body: some View {
        NavigationStack { screenBody }
    }
    private var screenBody: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.l) { content }
                .padding(.horizontal, Spacing.l).padding(.top, Spacing.s).padding(.bottom, Spacing.xxl)
        }
        .background(Theme.background)
        .navigationTitle(title)
        .phoneInlineTitle()
        .phoneNavigationTheme()
        .modifier(OptionalRefresh(action: refresh))
    }
}

/// Same scaffold for pushed screens, which already live inside a NavigationStack.
struct SubScreen<Content: View>: View {
    let title: String
    var refresh: (() async -> Void)? = nil
    @ViewBuilder var content: Content
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.l) { content }
                .padding(.horizontal, Spacing.l).padding(.top, Spacing.s).padding(.bottom, Spacing.xxl)
        }
        .background(Theme.background)
        .navigationTitle(title)
        .phoneInlineTitle()
        .phoneNavigationTheme()
        .modifier(OptionalRefresh(action: refresh))
    }
}

private struct OptionalRefresh: ViewModifier {
    let action: (() async -> Void)?
    func body(content: Content) -> some View {
        if let action { content.refreshable { await action() } } else { content }
    }
}

/// Shared layout for every order confirmation. Callers keep their own validation and submit logic.
struct ConfirmationSheet<Rows: View>: View {
    let title: String
    let headline: String
    let badge: StatusBadge
    var disclaimer: String? = nil
    var expiresAt: Date? = nil
    var confirmTitle: String
    var destructive = false
    var busy = false
    var notice: String = ""
    var noticeKind: NoticeKind = .info
    @ViewBuilder var rows: Rows
    let confirm: () -> Void
    let cancel: () -> Void
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.l) {
                    HStack { badge; Spacer() }
                    Text(headline).font(.title.weight(.semibold)).monospacedDigit()
                    SectionCard { VStack(spacing: Spacing.m) { rows } }
                    if let disclaimer { Footnote(disclaimer) }
                    OutcomeNotice(text: notice, kind: noticeKind)
                }
                .padding(Spacing.l)
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                VStack(spacing: Spacing.s) {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let remaining = expiresAt.map { deadline -> Int in
                            let seconds = deadline.timeIntervalSince(context.date)
                            guard seconds.isFinite, seconds > 0, seconds < Double(Int.max) else { return 0 }
                            return Int(seconds.rounded(.up))
                        }
                        let expired = remaining == 0
                        VStack(spacing: Spacing.s) {
                            if let remaining {
                                Text(expired ? "This review has expired. Request a new one." : "Expires in \(remaining / 60):\(String(format: "%02d", remaining % 60))")
                                    .font(.footnote).monospacedDigit().foregroundStyle(expired ? Theme.warning : Theme.textTertiary)
                            }
                            Button(confirmTitle, action: confirm)
                                .buttonStyle(PrimaryButtonStyle(tone: destructive ? .live : .accent))
                                .disabled(busy || expired)
                        }
                    }
                    Button("Cancel", action: cancel).buttonStyle(SecondaryButtonStyle()).disabled(busy)
                }
                .padding(Spacing.l)
                .background(Theme.surface)
                .overlay(alignment: .top) { Divider().overlay(Theme.separator) }
            }
            .background(Theme.background)
            .navigationTitle(title)
            .phoneInlineTitle()
            .phoneNavigationTheme()
        }
        .tint(Theme.accent)
    }
}

// MARK: - Platform shims (shared views stay type-checkable on macOS; the target is iPhone)

extension View {
    @ViewBuilder func phoneNavigationTheme() -> some View {
        #if os(iOS)
        toolbarBackground(Theme.background, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneInlineTitle() -> some View {
        #if os(iOS)
        navigationBarTitleDisplayMode(.inline)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneURLInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
        #else
        self
        #endif
    }
    @ViewBuilder func phoneSecretInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.never).autocorrectionDisabled()
        #else
        self
        #endif
    }
    @ViewBuilder func phoneSymbolInput() -> some View {
        #if os(iOS)
        textInputAutocapitalization(.characters).autocorrectionDisabled()
        #else
        self
        #endif
    }
    @ViewBuilder func phoneDecimalInput() -> some View {
        #if os(iOS)
        keyboardType(.decimalPad).autocorrectionDisabled()
        #else
        self
        #endif
    }
    func fieldStyle() -> some View {
        padding(Spacing.m).background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: Radius.control, style: .continuous))
    }
    /// Reset view state whenever the saved gateway connection changes.
    func onConnectionChange(_ store: AppStore, perform: @escaping () -> Void) -> some View {
        self.onChange(of: store.aiEndpoint) { _, _ in perform() }
            .onChange(of: store.aiToken) { _, _ in perform() }
    }
}
