# Markets

The Markets tab is the app's market data workspace: session status, index ETFs, a watchlist, large-cap movers, symbol search and a quote page for every US-listed stock or ETF. It is read-only. Nothing on these screens can place, review or confirm an order; **Trade on paper** opens the existing paper order screen with the symbol filled in, and that screen keeps its own review and confirmation.

## What the app shows

- **Session status**: open, pre-market, after hours or closed, with the next open or today's close in Eastern time. The provider's live status is used; if it is unavailable the pinned NYSE calendar supplies an estimate, and the app labels it as such.
- **Indices**: S&P 500, Nasdaq 100, Dow Jones and Russell 2000 through their ETFs (SPY, QQQ, DIA, IWM), because the data plan does not include index values.
- **Watchlist**: up to 40 symbols, saved on the iPhone. Rows show the latest price, the change from the previous close and the latest regular session as a sparkline with a dotted previous-close line. **Edit** reorders or removes symbols; long-press a row to move it to the top or remove it. The default list is AAPL, MSFT, NVDA, AMZN, GOOGL, META and TSLA.
- **Movers**: gainers, losers and most active by dollar volume, ranked within 50 widely held US large caps so that thinly traded warrants and penny stocks never headline the screen.
- **Search**: by ticker or company name. Exact ticker matches rank first, then common stock and ETFs; warrants, rights and units rank last. The star adds or removes a result from the watchlist.
- **Quote page**: price and change for the selected range, the after-hours price when one exists, an interactive chart (press and hold, then drag to read any point) for 1D, 1W, 1M, 3M, 6M, YTD, 1Y and 5Y, key statistics (open, previous close, day range, volume, average volume, market cap, P/E, EPS, dividend yield, bid/ask, VWAP), day and 52-week range bars, the paper position in that symbol, the latest or upcoming dividend, a company profile and recent headlines with the provider's sentiment for that ticker. Headlines open in Safari.

Holdings in the paper account and stock positions in Webull open the same quote page.

## Price alerts

The bell on a quote page sets an alert above or below a price; the composer offers ±5% and ±10% steps from the last price. The gateway checks active alerts about once a minute during pre-market, regular and after-hours trading, and only prices observed after an alert was set can trigger it. Up to 50 alerts can be active. Alerts never create, review or place orders.

The app posts a notification for each new trigger and shows the triggered count on its icon. Tapping the notification opens that symbol. Without a paid Apple Developer account there is no push service, so the app relies on iOS background refresh, which iOS schedules at its own discretion and only while the iPhone is unlocked, because the gateway token stays in unlocked-only Keychain storage. The app also checks whenever Markets or the alert list is open. Notification permission is requested after the first alert is created.

## Data and freshness

All figures come from Massive (Polygon-compatible) through the private gateway; the app never contacts the provider directly and the provider key never leaves the gateway. Each quote carries the provider's timestamp. The day's change is measured from the previous close; the after-hours line comes from minute bars after the close. Intraday charts (1D, 1W, 1M) show regular trading hours only. The data plan's latency is not verified, so prices are described as possibly delayed and are never presented as executable quotes.

The gateway caches responses briefly (quotes about 10 seconds, sparklines 2 minutes, company details a day). If the provider fails, the last good response stands in for up to 15 minutes and the screen says it is showing the last prices loaded. While the Markets tab is open it refreshes every 15 seconds during trading sessions and every 2 minutes otherwise; a quote page refreshes every 20 seconds during trading.

## Gateway routes

All routes are authenticated `POST` requests with exact JSON bodies, like the rest of the gateway.

| Route | Body | Returns |
| --- | --- | --- |
| `/v1/market/overview` | `{}` | Session status, index ETF quotes with sparklines, gainers, losers, most active |
| `/v1/market/quotes` | `{"symbols": [...], "sparklines": bool}` | Quotes in request order, plus symbols with no quote |
| `/v1/market/search` | `{"query": "..."}` | Up to 15 ranked matches |
| `/v1/market/symbol` | `{"symbol": "AAPL"}` | Quote, profile, statistics, dividend, headlines, and any datasets that were unavailable |
| `/v1/market/chart` | `{"symbol": "AAPL", "range": "1D"}` | OHLCV bars and the baseline for the range's change |
| `/v1/alerts/state` | `{}` | Triggered and active alerts, with counts |
| `/v1/alerts/create` | `{"symbol", "direction": "above"\|"below", "target", "client_id"}` | The saved alert; the same `client_id` returns it again |
| `/v1/alerts/cancel` | `{"id"}` | Removes an active alert or clears a triggered one |
| `/v1/alerts/clear` | `{}` | Clears all triggered alerts |

Invalid requests return HTTP 400 with a readable message; provider outages, rate limits and plan restrictions return HTTP 503. An older gateway without these routes returns 404, and the app asks for a server update.

## Paper prices

Paper reviews and marks use the same provider: the consolidated price for the current or just-finished session (the official close after 4:00 p.m. ET), or the latest completed daily close when no current day bar exists. See [PAPER-TRADING.md](PAPER-TRADING.md).

## Tests

`server/test_market.py` covers quote normalisation, timestamps, after-hours lines, name cleanup, request validation, ranking, movers, session status and calendar fallback, symbol pages with partial outages, chart ranges and baselines, caching with stale fallback, provider error mapping and gateway authentication. It uses a fake provider; no network or credentials are needed.
