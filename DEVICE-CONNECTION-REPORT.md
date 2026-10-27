# iPhone connection troubleshooting report

## Update — October 26, 2026

The September blocker below is resolved. With the phone connected over USB-C, unlocked and trusted, `xcrun devicectl list devices` now lists it as `available (paired)` with a wired tunnel, and `xcodebuild -destination id=00008140-001C0D242638801C` recognises the device. The remaining blocker is on the phone:

- **Developer Mode is off.** xcodebuild waits about two minutes and then fails with `Developer Mode disabled. To use my iphone for development, enable Developer Mode in Settings → Privacy & Security.` Because the Mac now has a working CoreDevice connection, the Developer Mode switch should be visible on the phone (it is hidden until a Mac has connected at least once). Turning it on restarts the phone and then asks for the passcode; nothing on the Mac can do this.
- **No device is registered to the team yet.** A signed `generic/platform=iOS` build fails with `Your team has no devices from which to generate a provisioning profile`, so TradePilot has never been installed on the phone. `scripts/install-iphone.sh` passes `-allowProvisioningDeviceRegistration`, which registers the phone and creates the profile on the first build once Developer Mode is on. The Apple Development identity and the team's Apple account session work.

Once Developer Mode is on and the phone is unlocked, run:

```bash
scripts/install-iphone.sh 00008140-001C0D242638801C "$HOME/Library/Application Support/TradePilot/gateway-20260923/private/TradePilotPairing.json"
```

The gateway itself still needs the Mac on home Wi-Fi (`192.168.68.0/24`) before the phone can reach it.

## Original report — September 10, 2026

## Blocker

A physical iPhone 16 Pro is visible to macOS over USB and Finder can load its General page, but Xcode cannot discover it as a development destination. TradePilot has not been installed on the phone.

## Environment

- macOS 26.6.2 (25G83)
- Xcode 26.6 (17F113), CoreDevice/devicectl 518.33
- iPhone 16 Pro, iOS 26.6.1
- Apple Development signing identity available; project uses automatic signing
- Developer Mode is not listed on the phone, as reported by the user

## Verified checks

- Mac restarted; Xcode restarted during troubleshooting.
- User completed Reset Location & Privacy and reconnected/trusted the Mac. Logs explicitly recorded successful pairing; Finder subsequently loaded device details.
- User reports no connected iPhone VPN. Mac Network settings showed no VPN/filter entry and Firewall Inactive.
- User tried another cable. IORegistry confirms the phone is now attached to a different USB controller/port from the preceding connection.
- The latest USB check lists an active iPhone IOUSBHostDevice, while devicectl still reports the remembered iPhone as unavailable.
- Xcode Devices window is empty, and Add Device reports No Devices Found.
- Generic iOS architecture build and signed simulator build previously succeeded; simulator app behavior was verified.

## Interpretation and next step

The cause remains unconfirmed. Successful Finder trust does not establish a working Xcode developer connection. Logged disconnects coincide with user reconnections and must not be treated as proof of an intermittent cable fault. An inactive iPhone USB network interface also does not by itself prove VPN interference.

Seek Apple Developer Support or submit Feedback with this report and a fresh diagnostic captured during reproduction. Device logs may contain private data; inspect them before sharing. Do not erase the phone or repeat privacy resets without new evidence.

Official references:
- https://developer.apple.com/documentation/technotes/tn3158-resolving-xcode-15-device-connection-issues
- https://support.apple.com/en-us/108643
- https://support.apple.com/en-us/109054
