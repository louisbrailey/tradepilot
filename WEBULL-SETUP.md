# Webull integration and iPhone setup

TradePilot includes a private backend adapter for Webull account/position reads, stock-order previews, explicit confirmation, durable submission records, and status refresh. It is not yet a verified live trading connection.

## Current status

- Webull approved **TradePilot Personal** and a key has been generated. The backend private key is saved outside `outputs/TradePilot`.
- Read-only Webull configuration succeeds. Mobile token creation currently returns `417 NO_AVAILABLE_DEVICE`.
- Next action: open or update the Webull iPhone app, sign in, and retry token creation. Do not put broker credentials in the iOS app or in this repository.
- Xcode setup is complete enough for a generic unsigned build and signed simulator build: the license is accepted and Personal Team `ANWNGW59GP` is selected. The simulator launched and was visually checked. The physical iPhone 16 Pro is unavailable/unpaired, so no signed device install has been completed.

## Private backend configuration

Keep the runtime JSON and all keys outside the source and deliverables, with restrictive permissions:

```json
{
  "APP_ACCESS_TOKEN": "REPLACE_WITH_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS",
  "WEBULL_APP_KEY": "YOUR_KEY",
  "WEBULL_APP_SECRET": "YOUR_SECRET",
  "WEBULL_ENV": "production",
  "WEBULL_LIVE_TRADING": "disabled",
  "TRADEPILOT_RUNTIME": "/absolute/private/path/tradepilot-runtime"
}
```

Run the server with the private config and the existing private market-data environment:

```sh
/path/to/venv/bin/python server/server.py \
  --config /absolute/private/path/config.json \
  --market-env /Users/louisbrailey/signal-forge/.env
```

The server defaults to loopback. Optional TLS CLI flags are available for private LAN use; non-loopback access requires TLS. Local phone use requires the Mac to stay awake on the same LAN. There is no permanent hosted deployment. Local authenticated/unauthenticated checks returned `200`/`401` as expected.

For repeatable LAN startup, use the helper with the private runtime directory, the Mac's LAN address, and the market environment file. Set `VENV_PYTHON` when using a private virtual environment; the default is `python3`:

```sh
VENV_PYTHON=/absolute/private/venv/bin/python \
  scripts/start-private-server.sh \
  /absolute/private/path/tradepilot-runtime \
  192.168.1.20 \
  /absolute/private/path/market.env
```

The private directory must contain `config.json`, `server.pem`, and `server.key`. The helper passes the private paths to the server and does not print their contents.

## Order behavior and limits

The Webull screen supports exact portfolio commands and a manual stock-order form. The backend validates account authorization and long-stock holdings, obtains a cost preview, and requires a fresh explicit confirmation. It records submission intent before contacting Webull, uses stable review identity, and exposes provider states including unknown and partial fill. A submitted order is not necessarily filled.

Regular-session DAY stock orders (market or limit) are the supported scope. Short opening, options, crypto, transfers, and broker-order cancellation are not implemented. Keep live execution disabled until read-only access, provider preview, mobile pairing, and reconciliation have all been tested.

## Secure phone connection

The iOS client accepts HTTPS, stores the gateway token in Keychain, and can pin the paired local certificate. The certificate-pairing flow is implemented and pairing import succeeds in the simulator. Complete the phone test only after the physical device is paired and available.

In Accounts, enter only the private HTTPS server URL and app access token. Never enter the Webull app secret, private key, Massive key, or OpenAI key on the phone. Pairing files and credentials must remain outside source archives.

## Install on a physical iPhone

The physical device must be trusted and paired with this Mac, have Developer Mode enabled when requested, and be available to the Apple signing account selected in Xcode. The helper builds into `/private/tmp` to avoid signing issues in iCloud-synced folders, installs the app, and launches it. Pass the device identifier as the first argument. A private pairing file is optional; if supplied, it is copied into the app data container without printing its contents:

```sh
scripts/install-iphone.sh DEVICE_IDENTIFIER
scripts/install-iphone.sh DEVICE_IDENTIFIER /absolute/private/TradePilotPairing.json
```

The script uses `xcodebuild` with provisioning updates enabled and `xcrun devicectl` for install, optional pairing-file copy, and launch. It does not create or expose credentials. No physical installation is complete until the iPhone is available and trusted.

Official references: [Webull SDK](https://developer.webull.com/apis/docs/sdk/), [order preview](https://developer.webull.com/apis/docs/reference/common-order-preview/), [order detail](https://developer.webull.com/apis/docs/reference/order-detail/).
