import SwiftUI
import Charts

// Presentation-only building blocks for the Markets tab and symbol pages.

/// Price path for one session, with an optional dotted previous-close line.
struct Sparkline: View {
    let values: [Double]
    var baseline: Double? = nil
    var tone: Tone = .neutral
    var body: some View {
        ZStack {
            if let baseline, values.count >= 2 {
                SparklinePath(values: values, baseline: baseline, guide: true)
                    .stroke(Theme.textTertiary.opacity(0.55), style: StrokeStyle(lineWidth: 1, dash: [2, 2.5]))
            }
            SparklinePath(values: values, baseline: baseline, guide: false)
                .stroke(tone.color, style: StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
        }
        .accessibilityHidden(true)
    }
}

private struct SparklinePath: Shape {
    let values: [Double]
    let baseline: Double?
    let guide: Bool
    func path(in rect: CGRect) -> Path {
        let finite = values.filter(\.isFinite)
        guard finite.count >= 2, let low = finite.min(), let high = finite.max() else { return Path() }
        let lo = min(low, baseline ?? low), hi = max(high, baseline ?? high)
        let span = max(hi - lo, abs(hi) * 0.0005, .ulpOfOne)
        func y(_ value: Double) -> CGFloat { rect.maxY - rect.height * CGFloat((value - lo) / span) }
        var path = Path()
        if guide, let baseline {
            path.move(to: CGPoint(x: rect.minX, y: y(baseline)))
            path.addLine(to: CGPoint(x: rect.maxX, y: y(baseline)))
            return path
        }
        for (index, value) in finite.enumerated() {
            let point = CGPoint(x: rect.minX + rect.width * CGFloat(index) / CGFloat(finite.count - 1), y: y(value))
            if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
        }
        return path
    }
}

/// Signed percentage on a tinted capsule, as on broker watchlists.
struct ChangePill: View {
    let percent: Double?
    var minWidth: CGFloat = 76
    var body: some View {
        let tone = MarketFormat.tone(percent)
        Text(MarketFormat.percent(percent))
            .font(.subheadline.weight(.semibold)).monospacedDigit()
            .lineLimit(1).minimumScaleFactor(0.8)
            .padding(.horizontal, Spacing.s).padding(.vertical, 5)
            .frame(minWidth: minWidth, alignment: .trailing)
            .foregroundStyle(tone == .neutral ? Theme.textSecondary : tone.color)
            .background(tone.color.opacity(tone == .neutral ? 0.10 : 0.14), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

/// Live-session indicator: "Market open · Closes 4:00 PM ET".
struct MarketSessionPill: View {
    let status: MarketStatus
    var body: some View {
        let session = MarketFormat.session(status)
        HStack(spacing: Spacing.s) {
            Circle().fill(session.tone.color).frame(width: 7, height: 7).accessibilityHidden(true)
            Text(session.label).font(.footnote.weight(.semibold)).foregroundStyle(Theme.textPrimary)
            if let detail = session.detail {
                Text(detail).font(.footnote).foregroundStyle(Theme.textSecondary)
            }
            if status.estimated {
                Text("estimated").font(.caption).foregroundStyle(Theme.textTertiary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Low–high range with the current price marked, e.g. the 52-week range.
struct PriceRangeBar: View {
    let title: String
    let low: Double?
    let high: Double?
    let current: Double?
    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Eyebrow(title)
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(Theme.surfaceRaised).frame(height: 4)
                    if let fraction {
                        Capsule().fill(Theme.accent.opacity(0.35))
                            .frame(width: max(4, geometry.size.width * fraction), height: 4)
                        Circle().fill(Theme.accent)
                            .overlay(Circle().strokeBorder(Theme.surface, lineWidth: 2))
                            .frame(width: 12, height: 12)
                            .offset(x: (geometry.size.width - 12) * fraction)
                    }
                }
                .frame(maxHeight: .infinity)
            }
            .frame(height: 12)
            HStack {
                Text(MarketFormat.price(low))
                Spacer()
                Text(MarketFormat.price(high))
            }
            .font(.caption).monospacedDigit().foregroundStyle(Theme.textSecondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title): low \(MarketFormat.price(low)), high \(MarketFormat.price(high)), current \(MarketFormat.price(current))")
    }
    private var fraction: CGFloat? {
        guard let low, let high, let current, high > low else { return nil }
        return CGFloat(min(max((current - low) / (high - low), 0), 1))
    }
}

/// Interactive line chart: drag across it to read any point.
struct PriceChart: View {
    let points: [ChartPoint]
    let baseline: Double?
    let range: ChartRange
    @Binding var selection: Int?

    var body: some View {
        let closes = points.map(\.c)
        let reference = baseline ?? closes.first ?? 0
        let tone: Tone = (closes.last ?? reference) >= reference ? .positive : .negative
        let low = min(closes.min() ?? 0, baseline ?? .infinity)
        let high = max(closes.max() ?? 0, baseline ?? -.infinity)
        let pad = max((high - low) * 0.08, high * 0.0008, 0.01)
        let floor = low - pad
        Chart {
            ForEach(Array(points.enumerated()), id: \.offset) { index, point in
                AreaMark(x: .value("Time", index), yStart: .value("Floor", floor), yEnd: .value("Price", point.c))
                    .foregroundStyle(LinearGradient(colors: [tone.color.opacity(0.20), tone.color.opacity(0.0)],
                                                    startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("Time", index), y: .value("Price", point.c))
                    .foregroundStyle(tone.color)
                    .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
            }
            if let baseline, range == .day {
                RuleMark(y: .value("Previous close", baseline))
                    .foregroundStyle(Theme.textTertiary.opacity(0.7))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
            }
            if let selection, points.indices.contains(selection) {
                RuleMark(x: .value("Time", selection))
                    .foregroundStyle(Theme.textSecondary.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                PointMark(x: .value("Time", selection), y: .value("Price", points[selection].c))
                    .foregroundStyle(tone.color)
                    .symbolSize(70)
            }
        }
        .chartXScale(domain: 0...max(points.count - 1, 1))
        .chartYScale(domain: floor...(high + pad))
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .trailing, values: .automatic(desiredCount: 4)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Theme.separator)
                AxisValueLabel {
                    if let price = value.as(Double.self) {
                        Text(price.formatted(.number.precision(.fractionLength(price < 10 ? 2 : 0))))
                            .font(.caption2).monospacedDigit().foregroundStyle(Theme.textTertiary)
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .gesture(
                        LongPressGesture(minimumDuration: 0.12)
                            .sequenced(before: DragGesture(minimumDistance: 0))
                            .onChanged { value in
                                guard case .second(true, let drag?) = value, let frame = proxy.plotFrame else { return }
                                let x = drag.location.x - geometry[frame].origin.x
                                if let position = proxy.value(atX: x, as: Double.self), !points.isEmpty {
                                    selection = min(max(Int(position.rounded()), 0), points.count - 1)
                                }
                            }
                            .onEnded { _ in selection = nil }
                    )
            }
        }
        .sensoryFeedback(.selection, trigger: selection)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Price chart, \(range.changeLabel.lowercased())")
        .accessibilityValue(summary)
    }

    private var summary: String {
        guard let first = points.first?.c, let last = points.last?.c else { return "No data" }
        let start = baseline ?? first
        let change = start > 0 ? (last - start) / start * 100 : 0
        return "From \(MarketFormat.price(start)) to \(MarketFormat.price(last)), \(MarketFormat.percent(change))"
    }
}

/// Monogram badge used where a company logo would sit.
struct SymbolMonogram: View {
    let symbol: String
    var size: CGFloat = 36
    var body: some View {
        Text(String(symbol.prefix(symbol.count > 4 ? 1 : 2)))
            .font(.system(size: size * 0.36, weight: .bold, design: .rounded))
            .foregroundStyle(Theme.accent)
            .frame(width: size, height: size)
            .background(Theme.accent.opacity(0.12), in: Circle())
            .accessibilityHidden(true)
    }
}
