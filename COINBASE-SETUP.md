# Expanded source capabilities

The account-balances route below remains read-only. Separately confirmed trading and internal portfolio transfers are implemented and deployed; see [BROKER-ACCESS.md](BROKER-ACCESS.md). The configured key has no Trade or Transfer permission, and gateway writes remain disabled.

## Verified November 5, 2026

The user-approved ECDSA key is restricted to View access for the Primary portfolio and the gateway's public IPv4 address. Coinbase's permission endpoint confirms `can_view=true`, `can_trade=false`, and `can_transfer=false`. The authenticated, certificate-pinned gateway returned 26 asset accounts, and **Load Coinbase accounts** rendered balances on the physical USB iPhone at 6:26 PM. The iPhone 16 Pro was used only for the SMS verification through Mirroring. No transactions were performed. See [setup evidence](reports/coinbase-setup-2026-11-05.md).

# Coinbase read-only accounts

TradePilot includes a personal Coinbase Advanced Trade account adapter in `server/coinbase_service.py`. It fetches every permitted account page and displays available, held and total quantities in each account's own currency. These are asset quantities, not USD valuations. Key restrictions may expose only a subset of the user's portfolios. No trading, transfer, deposit, withdrawal or key-creation method is implemented.

Automated tests use synthetic responses and temporary signing keys. Production read access was separately verified during the user-authorized setup above.

## Private configuration

Use a personal Coinbase App/CDP key with **ECDSA P-256**, restricted to **View** permissions and the intended portfolio. Do not grant trade or transfer permissions for this connector. Store these values only in the gateway's existing private configuration, never in source, an iPhone bundle, a screenshot committed to Git, or a report:

- `COINBASE_API_KEY_NAME`: the complete `organizations/.../apiKeys/...` name.
- `COINBASE_API_PRIVATE_KEY`: PEM private key, preserving newlines (literal escaped `\n` is also accepted).

Optional `COINBASE_IPV4_ONLY=enabled` supports IPv4-only key allowlists. This binds only Coinbase connections to IPv4 and bypasses configured proxies for those requests; normal hostname/certificate verification and redirect refusal remain in force. Other providers and the default transport are unchanged.

The deployed gateway uses this option because its default IPv6 route was rejected by the IPv4-restricted key. If the gateway's public IPv4 changes, update the key's allowlist before expecting read access to recover. This restriction is separate from the phone-to-Mac LAN pairing.

The gateway interpreter requires `cryptography`; this is already used by the project's private TLS setup. Missing credentials or dependency produce explicit unavailable errors. An empty account list is only returned after a successful authenticated response, never as a substitute for failed configuration.

The key signs a fresh ES256 JWT per request, with a random nonce and 120-second expiry. Its URI restricts it to `GET api.coinbase.com/api/v3/brokerage/accounts`; the App API's documented claims use issuer `cdp` and key-name subject, without an audience claim. The key remains on the Mac. See [Coinbase App authentication](https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication).

## Data behavior

The adapter requests 250 accounts per page, follows continuation cursors, and refuses repeated cursors, duplicate account identities, conflicting currencies, malformed balances, inconsistent page sizes, oversized responses and more than 100 pages. Failed/incomplete pagination does not return a partial portfolio. HTTPS origin and GET path are fixed; redirects are disabled. Balances use decimal arithmetic, without a floating-point conversion. The snapshot time is local fetch completion, not a provider valuation time. See [Coinbase List Accounts](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/accounts/list-accounts).

Account pages are not guaranteed to be an atomic snapshot across a concurrently changing account. They provide balance visibility, not a trade authorization or execution receipt. Read-only operation describes this adapter; it cannot prove that an externally created key lacks wider permissions.

## Fidelity boundary

Fidelity's documented Fidelity Access connection provides authorized account-data sharing through integrated third-party applications. Its institutional Integration Xchange serves a different integration context. Those sources do not establish a generally available, self-service retail trading API that this app can implement with personal credentials. TradePilot therefore marks Fidelity unsupported instead of inventing an endpoint or using website scraping. A future approved data-provider integration would require its own contract, authorization and tests. Sources: [Fidelity Access and data security](https://scs.fidelity.com/security/fidelity-access-data-security), [Fidelity Integration Xchange](https://clearingcustody.fidelity.com/app/item/RD_9883092/integration-xchange.html).

## Verification

`python3 -m unittest discover -s server -p test_coinbase.py -v` covers pagination, currency isolation, precise decimal addition, invalid data, secret-safe errors, response cleanup, redirect refusal and signing configuration. The actual ES256 test verifies a temporary key signature and exact claims; it is skipped only when that interpreter lacks `cryptography`. Run it with the configured gateway interpreter to include signing verification. No live account call is part of these tests.
