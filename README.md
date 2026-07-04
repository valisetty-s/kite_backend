# Kite Backend — for The Morning Ledger

This backend now does **four** things:

1. Safely completes Kite login (unchanged)
2. Fetches news via Google News RSS (unchanged since v9)
3. **`GET /api/quotes?symbols=AARTIIND,VBL,...`** — returns live last price and day-over-day % change for a batch of stocks
4. `/healthz` (health check)

## Viewing Logs

All API activity is now logged for debugging. Access logs via:

```
https://your-backend-url/logs
```

This returns the last 200 lines of logs. To get more:
```
https://your-backend-url/logs?tail=500
```

**Log locations by platform:**
- **Render**: Logs automatically stream to `stdout`, visible in Render's "Logs" tab in your dashboard
- **Railway**: Same as above
- **Local (`/tmp/morning-ledger.log`)**: Check the file directly on the server

**What's logged:**
- News fetch requests and results
- Price fetch requests per symbol (current, previous close, change %)
- Volume data and flags
- Any errors with full stack traces
- Summary of successful vs failed stock price fetches

## How quotes work — and the one real constraint

Kite access tokens expire daily (this is Kite's own rule, not something
this app invents). So:

- After you log in via Kite (Settings → "Log in to Kite & import
  holdings"), the access token is cached **in this server's memory only**
  — never written to disk, never logged, never sent back to your phone
- `/api/quotes` reuses that cached token for the rest of the day
- If you haven't logged in this session (or the Render service restarted,
  which can happen on the free tier), quotes simply won't be available —
  the app shows news normally regardless and just omits prices, with a
  small note explaining why
- If Kite's API says the token has actually expired, the cache is cleared
  automatically and the next attempt will ask you to log in again

**This means prices are a "nice to have when you've logged in," not a
guaranteed feature on every single fetch** — that trade-off is inherent to
how Kite's tokens work, not a shortcut taken here.

## Redeploy needed

Since `server.py` changed again, push the updated `server.py` (no new
dependencies this time — still just Flask, flask-cors, requests, gunicorn,
feedparser) to your GitHub repo and let Render redeploy automatically, same
as before.

## Testing the new endpoint

After the app is running, test directly in a browser:
```
https://your-backend-url/api/quotes?symbols=AARTIIND,VBL,CGPOWER
```

Should return JSON like:
```json
{"status": "success", "quotes": {
  "AARTIIND": {"last_price": 498.15, "prev_close": 484.75, "change_pct": 2.76},
  "VBL": {"last_price": 850.50, "prev_close": 845.00, "change_pct": 0.65},
  "CGPOWER": {"last_price": 892.55, "prev_close": 700.00, "change_pct": 27.50}
}}
```

If a stock fails to fetch, it will have an `"error"` field instead of price data.

## Debugging price issues

If you suspect incorrect change percentages:

1. **Check logs**: Visit `https://your-backend-url/logs` and search for your stock ticker
2. **Look for the line**: `CGPOWER - Raw closes (first 5): [...]`
3. **Verify calculation**: The log shows which day's close was used as baseline
4. **Manual test**: Try fetching directly from Yahoo Finance to confirm data is correct

## Why some stocks don't have prices

Stocks return errors if:
- Yahoo Finance doesn't have data for that ticker (BSE-only stocks, delisted companies, wrong ticker format)
- Network timeout (very rare, will retry next fetch)
- Symbol doesn't exist on NSE (we default to NSE, BSE symbols won't auto-convert)

Check `/logs` for which stocks failed and why.
