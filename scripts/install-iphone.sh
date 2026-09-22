#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEVICE_ID="${1:-}"
PAIRING_FILE="${2:-}"
DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
export DEVELOPER_DIR

usage() {
  echo "Usage: $0 DEVICE_IDENTIFIER [PRIVATE_PAIRING_FILE]" >&2
  echo "Builds, installs, and launches TradePilot on a trusted iPhone." >&2
}

if [[ -z "$DEVICE_ID" || "$DEVICE_ID" == "-h" || "$DEVICE_ID" == "--help" ]]; then
  usage
  exit 0
fi
if [[ -n "$PAIRING_FILE" && ! -f "$PAIRING_FILE" ]]; then
  echo "Pairing file not found: $PAIRING_FILE" >&2
  exit 2
fi
if [[ ! -d "$DEVELOPER_DIR" ]]; then
  echo "Xcode developer directory not found: $DEVELOPER_DIR" >&2
  exit 2
fi

DERIVED_DATA="$(mktemp -d /private/tmp/tradepilot-iphone.XXXXXX)"
trap 'rm -rf "$DERIVED_DATA"' EXIT

xcodebuild \
  -project "$PROJECT_DIR/iOS/TradePilot.xcodeproj" \
  -scheme TradePilot \
  -destination "id=$DEVICE_ID" \
  -derivedDataPath "$DERIVED_DATA" \
  -allowProvisioningUpdates \
  -allowProvisioningDeviceRegistration \
  build

APP_PATH="$DERIVED_DATA/Build/Products/Debug-iphoneos/TradePilot.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "Build completed without an app at the expected path." >&2
  exit 1
fi

xcrun devicectl device install app --device "$DEVICE_ID" "$APP_PATH"

if [[ -n "$PAIRING_FILE" ]]; then
  xcrun devicectl device copy to \
    --device "$DEVICE_ID" \
    --source "$PAIRING_FILE" \
    --destination Documents/TradePilotPairing.json \
    --domain-type appDataContainer \
    --domain-identifier com.louisbrailey.TradePilot
fi

xcrun devicectl device process launch --device "$DEVICE_ID" com.louisbrailey.TradePilot
