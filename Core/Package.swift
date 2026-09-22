// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "TradeCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "TradeCore", targets: ["TradeCore"])],
    targets: [.target(name: "TradeCore"), .testTarget(name: "TradeCoreTests", dependencies: ["TradeCore"])]
)
