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

if [[ "$DEVICE_ID" == "-h" || "$DEVICE_ID" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -lt 1 || $# -gt 2 || -z "$DEVICE_ID" ]]; then
  usage
  exit 2
fi
if [[ -n "$PAIRING_FILE" ]]; then
  if [[ -L "$PAIRING_FILE" || ! -f "$PAIRING_FILE" || ! -r "$PAIRING_FILE" ]]; then
    echo "Pairing file must be an ordinary readable file: $PAIRING_FILE" >&2
    exit 2
  fi
  # The pairing file embeds the access token; refuse one other users can read,
  # matching the private-file checks in manage-local-service.py.
  PAIRING_MODE="$(stat -f '%Lp' "$PAIRING_FILE")"
  if [[ "$PAIRING_MODE" != 600 && "$PAIRING_MODE" != 400 ]]; then
    echo "Pairing file must be owner-only (chmod 600): $PAIRING_FILE" >&2
    exit 2
  fi
fi
if [[ ! -d "$DEVELOPER_DIR" ]]; then
  echo "Xcode developer directory not found: $DEVELOPER_DIR" >&2
  exit 2
fi

# Fail fast on a phone xcodebuild cannot use, instead of letting it wait minutes
# for a destination that never becomes available.
DEVICE_INFO="$(xcrun devicectl device info details --device "$DEVICE_ID" 2>&1 || true)"
if ! grep -q "Device Reality: physical" <<<"$DEVICE_INFO"; then
  echo "Device $DEVICE_ID is not a connected physical device; check 'xcrun devicectl list devices'." >&2
  exit 2
fi
if grep -q "Developer Mode Status: Disabled" <<<"$DEVICE_INFO"; then
  echo "Developer Mode is off on the phone. On the phone open Settings > Privacy & Security > Developer Mode, turn it on, restart, confirm with the passcode, unlock the phone, then rerun." >&2
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
