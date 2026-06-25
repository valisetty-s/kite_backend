# Kite Backend — for The Morning Ledger

This backend now does **four** things:

1. Safely completes Kite login (unchanged)
2. Fetches news via Google News RSS (unchanged since v9)
3. **NEW: `GET /api/quotes?symbols=NSE:FOO,NSE:BAR`** — returns live last
   price and day-over-day % change for a batch of stocks
4. `/healthz` (unchanged)

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

After logging in via the app once, test directly in a browser:
```
https://your-backend-url/api/quotes?symbols=NSE:AARTIIND,NSE:VBL
```
Should return JSON like:
```json
{"status": "success", "quotes": {
  "NSE:AARTIIND": {"last_price": 498.15, "prev_close": 484.75, "change_pct": 2.76}
}}
```
If you haven't logged in yet this session, you'll get a clear
`no-active-kite-session` error instead — that's expected, not broken.
