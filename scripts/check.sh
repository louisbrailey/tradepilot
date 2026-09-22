#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tradepilot-check.XXXXXX")"
trap 'rm -rf "$CHECK_DIR"' EXIT
swiftc -swift-version 6 -module-cache-path "$CHECK_DIR/cache" -emit-library -emit-module -enable-testing \
  -module-name TradeCore "$PROJECT_DIR/Core/Sources/TradeCore/TradeCore.swift" \
  -o "$CHECK_DIR/libTradeCore.dylib" -emit-module-path "$CHECK_DIR/TradeCore.swiftmodule"
swiftc -swift-version 6 -D TRADEPILOT_STANDALONE_TESTS -module-cache-path "$CHECK_DIR/cache" \
  -I "$CHECK_DIR" -L "$CHECK_DIR" -lTradeCore -Xlinker -rpath -Xlinker "$CHECK_DIR" \
  "$PROJECT_DIR/Core/Tests/TradeCoreTests/TradeCoreTests.swift" "$PROJECT_DIR/scripts/main.swift" -o "$CHECK_DIR/core-tests"
"$CHECK_DIR/core-tests"
python3 -m unittest discover -s "$PROJECT_DIR/server" -p 'test_*.py' -v
python3 -m unittest discover -s "$PROJECT_DIR/scripts" -p 'test_*.py' -v
swiftc -swift-version 6 -typecheck -module-cache-path "$CHECK_DIR/cache" -I "$CHECK_DIR" "$PROJECT_DIR"/iOS/TradePilot/*.swift
mkdir -p "$CHECK_DIR/journal"
sed '/^@main$/d' "$PROJECT_DIR/iOS/TradePilot/TradePilotApp.swift" > "$CHECK_DIR/journal/TradePilotApp.swift"
cp "$PROJECT_DIR/scripts/journal-smoke.swift" "$CHECK_DIR/journal/main.swift"
swiftc -swift-version 6 -module-cache-path "$CHECK_DIR/cache" -I "$CHECK_DIR" -L "$CHECK_DIR" \
  -lTradeCore -Xlinker -rpath -Xlinker "$CHECK_DIR" "$CHECK_DIR/journal/TradePilotApp.swift" \
  "$PROJECT_DIR/iOS/TradePilot/AIService.swift" "$PROJECT_DIR/iOS/TradePilot/JournalView.swift" "$PROJECT_DIR/iOS/TradePilot/WebullView.swift" \
  "$CHECK_DIR/journal/main.swift" -o "$CHECK_DIR/journal-check"
"$CHECK_DIR/journal-check" "$CHECK_DIR/journal/test.json"
mkdir -p "$CHECK_DIR/connection"
sed '/^@main$/d' "$PROJECT_DIR/iOS/TradePilot/TradePilotApp.swift" > "$CHECK_DIR/connection/TradePilotApp.swift"
cp "$PROJECT_DIR/scripts/connection-smoke.swift" "$CHECK_DIR/connection/main.swift"
swiftc -swift-version 6 -module-cache-path "$CHECK_DIR/cache" -I "$CHECK_DIR" -L "$CHECK_DIR" \
  -lTradeCore -Xlinker -rpath -Xlinker "$CHECK_DIR" "$CHECK_DIR/connection/TradePilotApp.swift" \
  "$PROJECT_DIR/iOS/TradePilot/AIService.swift" "$PROJECT_DIR/iOS/TradePilot/JournalView.swift" "$PROJECT_DIR/iOS/TradePilot/WebullView.swift" \
  "$CHECK_DIR/connection/main.swift" -o "$CHECK_DIR/connection-check"
"$CHECK_DIR/connection-check"
plutil -lint "$PROJECT_DIR/iOS/TradePilot.xcodeproj/project.pbxproj"
echo "Checks passed. Native iPhone build still requires Xcode and the iOS SDK."
