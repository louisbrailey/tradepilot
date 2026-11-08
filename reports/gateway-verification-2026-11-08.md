# Gateway verification — November 8, 2026

The existing Mac gateway is serving successfully. No deployment, restart, pairing change, account request or order was required for this verification. Windows deployment remains owned by the ongoing home-PC migration chat; the Mac remains the sole paper-ledger writer.

## Current checks

All 16 checks passed through TLS using the gateway's pinned certificate and existing token. Only summaries were retained; tokens and private configuration were not printed.

- Setup and alerts responded successfully.
- Markets overview, AAPL/SPY quotes with sparklines, symbol search, AAPL details and intraday history returned HTTP 200.
- Crypto pricing returned BTC, ETH and USD prices.
- AAPL options returned 94 contracts for November 9.
- Manual paper state and recorded research evaluation returned HTTP 200.
- The scheduler reported all three frozen strategies running, two observations each and a next session of November 9. Mean reversion retained its one simulated fill; the other strategies retained zero fills. Heartbeat age was 27 seconds.
- An unauthenticated setup request returned HTTP 401.
- The local assistant answered a synthetic empty-portfolio prompt in 19.18 seconds, HTTP 200. It received no broker snapshot.
- Kronos status reported its runtime present, and an actual five-session SPY historical replay completed in 13.51 seconds, HTTP 200.

Private receipt: `.toolkit-runs/gateway-verification-20261108/result.json`.

## Verification repair

`scripts/update-local-gateway.py verify` previously returned successfully when setup answered HTTP 200 even if the subsequent alerts or Markets request failed. It now exits unsuccessfully for a failed required route or a transport failure, and prints the overall healthy result only after all three routes succeed. Provider error bodies are no longer printed by this path. Two regression tests cover failed capabilities/transport and all-success behavior; all 70 script tests passed. Only the updater and its tests changed; gateway execution and strategy modules are unchanged.

## Reachability and remaining acceptance

At verification time the Mac's en0 address was 192.0.0.2 (CLAT); the gateway correctly served only on IPv6 loopback. These live checks therefore establish local gateway operation, not current phone-to-server connectivity. The correct physical USB iPhone has TradePilot 0.5.2 build 8 installed. Earlier same-day physical checks, recorded in `release-0.5.2-2026-11-08.md`, verified the connection, Markets, charts, options and strategy cards after repairing the paired hostname.

Pinned SSH inspection of the Windows PC found no TradePilot services, deployment root or production state at this point. Its separate staging and migration work is active. This verification neither activates that installation nor establishes reboot, restore or phone-over-Tailscale acceptance for it. The app signing renewal still requires a usable Apple ID in Xcode before the current profile expires November 11.
