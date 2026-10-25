#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE_DIR="${1:-}"
LOCAL_IP="${2:-}"
MARKET_ENV="${3:-}"
VENV_PYTHON="${VENV_PYTHON:-python3}"

usage() {
  echo "Usage: $0 PRIVATE_RUNTIME_DIR LOCAL_IP MARKET_ENV_FILE" >&2
  echo "Optional: set VENV_PYTHON to the private virtualenv Python executable." >&2
}

if [[ "$PRIVATE_DIR" == "-h" || "$PRIVATE_DIR" == "--help" ]]; then
  usage
  exit 0
fi
if [[ $# -ne 3 || -z "$PRIVATE_DIR" || -z "$LOCAL_IP" || -z "$MARKET_ENV" ]]; then
  usage
  exit 2
fi
if [[ ! -d "$PRIVATE_DIR" ]]; then
  echo "Private runtime directory not found: $PRIVATE_DIR" >&2
  exit 2
fi
if [[ ! -f "$PRIVATE_DIR/config.json" ]]; then
  echo "Missing private config: $PRIVATE_DIR/config.json" >&2
  exit 2
fi
if [[ ! -f "$PRIVATE_DIR/server.pem" || ! -f "$PRIVATE_DIR/server.key" ]]; then
  echo "Missing TLS certificate/key in private runtime directory." >&2
  exit 2
fi
if [[ ! -f "$MARKET_ENV" ]]; then
  echo "Market environment file not found: $MARKET_ENV" >&2
  exit 2
fi
if ! command -v "$VENV_PYTHON" >/dev/null 2>&1 && [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Python executable not found: $VENV_PYTHON" >&2
  exit 2
fi

PYTHON_PATH="$(command -v "$VENV_PYTHON")"
PYTHON_PATH="$(cd "$(dirname "$PYTHON_PATH")" && pwd)/$(basename "$PYTHON_PATH")"
exec "$PYTHON_PATH" "$PROJECT_DIR/scripts/manage-local-service.py" serve \
  --private-dir "$PRIVATE_DIR" \
  --market-env "$MARKET_ENV" \
  --address "$LOCAL_IP" \
  --python "$PYTHON_PATH"
