"""
server.py — The Morning Ledger's backend

Does three things:
  1. POST /api/kite/exchange  — takes a request_token, exchanges it for an
     access_token using your api_secret (which lives ONLY here, as an
     environment variable — never sent to or stored in the browser), then
     immediately uses that access_token to fetch your holdings and returns
     them to the app. The access_token itself is never sent back to the
     browser, by design — it's used once, server-side, then discarded from
     memory when the request finishes. Nothing is written to disk.
  2. GET /api/news?company=... — fetches Google News RSS for one company
     and returns parsed articles as JSON. Added because the two free
     anonymous CORS proxies the app relied on (CodeTabs, r.jina.ai) both
     started failing — CodeTabs is currently rejecting requests with 400s
     for many users (a known, reported issue, not specific to this app),
     and Jina explicitly blocks anonymous traffic to news.google.com due
     to abuse from other users of their service. A server making its own
     direct request has no CORS restriction at all (CORS is a browser-only
     rule) and isn't subject to either of those specific failures.
  3. GET /healthz — a trivial endpoint so the hosting platform (Render/
     Railway) can confirm the service is alive.

There is no database, no session storage, no logging of tokens or secrets.
Every request is independent and stateless.
"""

import hashlib
import os
from urllib.parse import quote

import feedparser
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow the PWA (hosted on a different domain) to call this API

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")

KITE_SESSION_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

# A normal browser User-Agent. Without this, some servers (including
# occasionally Google's own infrastructure) are more likely to treat the
# request as bot/scraper traffic and respond differently.
NEWS_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


"""
server.py — The Morning Ledger's backend

Does four things:
  1. POST /api/kite/exchange  — takes a request_token, exchanges it for an
     access_token using your api_secret (which lives ONLY here, as an
     environment variable — never sent to or stored in the browser), then
     immediately uses that access_token to fetch your holdings and returns
     them to the app. The access_token itself is never sent back to the
     browser, by design. It IS kept in memory on this server afterward
     (see _session_cache below) so the new /api/quotes endpoint can reuse
     it for the rest of the day without asking you to log in again for
     every single price check — but it is never written to disk, never
     logged, and is wiped immediately if this process restarts.
  2. GET /api/news?company=... — fetches Google News RSS for one company
     and returns parsed articles as JSON. Added because the two free
     anonymous CORS proxies the app relied on (CodeTabs, r.jina.ai) both
     started failing — CodeTabs is currently rejecting requests with 400s
     for many users (a known, reported issue, not specific to this app),
     and Jina explicitly blocks anonymous traffic to news.google.com due
     to abuse from other users of their service. A server making its own
     direct request has no CORS restriction at all (CORS is a browser-only
     rule) and isn't subject to either of those specific failures.
  3. GET /api/quotes?symbols=NSE:AARTIIND,NSE:VBL — returns last price and
     day-over-day change for a batch of stocks, using the access_token
     cached in memory from your most recent Kite login. Requires having
     logged in via Kite at least once this session (access tokens expire
     daily, per Kite's own rules — this app doesn't work around that).
  4. GET /healthz — a trivial endpoint so the hosting platform (Render/
     Railway) can confirm the service is alive.

There is no database. Nothing is ever written to disk. The one exception
to "no persistence" is the in-memory access_token cache described above —
explicitly scoped to RAM only, lost on every restart, never logged.
"""

import hashlib
import os
import time
from urllib.parse import quote

import feedparser
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow the PWA (hosted on a different domain) to call this API

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")

KITE_SESSION_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"
KITE_QUOTE_OHLC_URL = "https://api.kite.trade/quote/ohlc"

# In-memory only — never written to disk, never logged, wiped on restart.
# Kite access tokens are valid until ~6am IST the next day regardless of
# when they were issued, so caching this in RAM for the rest of a session
# is safe and matches Kite's own token lifetime, not something this app
# invents independently.
_session_cache = {"access_token": None, "set_at": None}

# A normal browser User-Agent. Without this, some servers (including
# occasionally Google's own infrastructure) are more likely to treat the
# request as bot/scraper traffic and respond differently.
NEWS_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/quotes", methods=["GET"])
def fetch_quotes():
    """
    Query param: ?symbols=NSE:AARTIIND,NSE:VBL,BSE:TARIL

    Returns last price and day-over-day % change for each symbol, using
    the access_token cached in memory from the most recent successful
    Kite login. If no login has happened this session (or the server
    restarted since), returns a clear error rather than guessing.
    """
    if not _session_cache["access_token"]:
        return jsonify({
            "error": "no-active-kite-session",
            "message": "Log in via Kite first (Settings → Log in to Kite) — "
                       "prices need today's access token, which isn't cached yet.",
        }), 401

    symbols_param = request.args.get("symbols", "").strip()
    if not symbols_param:
        return jsonify({"error": "symbols query parameter is required, comma-separated"}), 400

    symbols = [s.strip() for s in symbols_param.split(",") if s.strip()]
    if not symbols:
        return jsonify({"error": "no valid symbols provided"}), 400

    # Kite's API takes repeated ?i=NSE:FOO&i=NSE:BAR params, not a single
    # comma-joined one — build the query string accordingly.
    params = [("i", s) for s in symbols]

    try:
        resp = requests.get(
            KITE_QUOTE_OHLC_URL,
            params=params,
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {KITE_API_KEY}:{_session_cache['access_token']}",
            },
            timeout=12,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach Kite for quotes: {e}"}), 502

    try:
        data = resp.json()
    except ValueError:
        return jsonify({
            "error": "Kite returned a response that wasn't valid JSON for quotes.",
            "http_status": resp.status_code,
            "raw_response_snippet": resp.text[:300],
        }), 502

    if resp.status_code == 403 or data.get("error_type") == "TokenException":
        # The cached token has actually expired (e.g. it's a new day) —
        # clear it so the next attempt gives a clean "please log in again"
        # rather than repeatedly trying a dead token.
        _session_cache["access_token"] = None
        return jsonify({
            "error": "kite-session-expired",
            "message": "Your Kite session has expired — log in again via Settings.",
        }), 401

    if resp.status_code != 200 or data.get("status") != "success":
        return jsonify({"error": "Kite rejected the quotes request.", "kite_response": data}), 400

    quotes = {}
    for symbol, q in data.get("data", {}).items():
        last_price = q.get("last_price")
        prev_close = q.get("ohlc", {}).get("close")
        change_pct = None
        if last_price is not None and prev_close:
            change_pct = round(((last_price - prev_close) / prev_close) * 100, 2)
        quotes[symbol] = {
            "last_price": last_price,
            "prev_close": prev_close,
            "change_pct": change_pct,
        }

    return jsonify({"status": "success", "quotes": quotes})


@app.route("/api/news", methods=["GET"])
def fetch_news_for_company():
    """
    Query param: ?company=Aarti+Industries

    Fetches Google News RSS for the given company name directly from this
    server (no CORS issue, no anonymous-proxy abuse flag) and returns
    parsed articles as JSON.
    """
    company = request.args.get("company", "").strip()
    if not company:
        return jsonify({"error": "company query parameter is required"}), 400

    query = quote(f'"{company}" when:3d')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

    try:
        resp = requests.get(rss_url, headers=NEWS_FETCH_HEADERS, timeout=12)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach Google News: {e}"}), 502

    if resp.status_code != 200:
        return jsonify({
            "error": f"Google News returned HTTP {resp.status_code}",
            "raw_response_snippet": resp.text[:300],
        }), 502

    try:
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        return jsonify({"error": f"Could not parse RSS response: {e}"}), 502

    articles = []
    for entry in parsed.entries[:5]:
        raw_title = (entry.get("title") or "").strip()
        title, source = raw_title, "Google News"
        sep_idx = raw_title.rfind(" - ")
        if sep_idx > 0:
            title = raw_title[:sep_idx].strip()
            source = raw_title[sep_idx + 3:].strip()

        articles.append({
            "title": title,
            "source": source,
            "url": entry.get("link", ""),
            "published": entry.get("published", ""),
        })

    return jsonify({
        "status": "success",
        "company": company,
        "count": len(articles),
        "articles": articles,
    })


@app.route("/api/kite/exchange", methods=["POST"])
def exchange_and_fetch_holdings():
    """
    Body (JSON): { "request_token": "..." }

    Exchanges the request_token for an access_token (using the secret held
    only in this server's environment), fetches holdings with that token,
    and returns the holdings to the caller. The access_token is not
    returned to the browser.
    """
    if not KITE_API_KEY or not KITE_API_SECRET:
        return jsonify({
            "error": "Server is missing KITE_API_KEY / KITE_API_SECRET environment variables. "
                     "Set them in your hosting platform's dashboard, not in code."
        }), 500

    body = request.get_json(silent=True) or {}
    request_token = body.get("request_token", "").strip()
    if not request_token:
        return jsonify({"error": "request_token is required"}), 400

    # Step 1 — exchange request_token for access_token
    # checksum = SHA-256(api_key + request_token + api_secret), per Kite's spec
    checksum = hashlib.sha256(
        (KITE_API_KEY + request_token + KITE_API_SECRET).encode("utf-8")
    ).hexdigest()

    try:
        token_resp = requests.post(
            KITE_SESSION_TOKEN_URL,
            headers={"X-Kite-Version": "3"},
            data={
                "api_key": KITE_API_KEY,
                "request_token": request_token,
                "checksum": checksum,
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach Kite to exchange token: {e}"}), 502

    try:
        token_data = token_resp.json()
    except ValueError:
        return jsonify({
            "error": "Kite returned a response that wasn't valid JSON during token exchange.",
            "http_status": token_resp.status_code,
            "raw_response_snippet": token_resp.text[:300],
        }), 502

    if token_resp.status_code != 200 or token_data.get("status") != "success":
        return jsonify({
            "error": "Kite rejected the token exchange.",
            "kite_response": token_data,
        }), 400

    access_token = token_data.get("data", {}).get("access_token")
    if not access_token:
        return jsonify({
            "error": "Kite said the exchange succeeded but didn't return an access_token.",
            "kite_response": token_data,
        }), 502

    # Cache in memory (RAM only — see _session_cache docstring above) so
    # /api/quotes can reuse it for the rest of today without a fresh login.
    _session_cache["access_token"] = access_token
    _session_cache["set_at"] = time.time()

    # Step 2 — use the access_token immediately to fetch holdings
    try:
        holdings_resp = requests.get(
            KITE_HOLDINGS_URL,
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {KITE_API_KEY}:{access_token}",
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Token exchange succeeded but holdings fetch failed: {e}"}), 502

    try:
        holdings_data = holdings_resp.json()
    except ValueError:
        return jsonify({
            "error": "Kite returned a response that wasn't valid JSON during holdings fetch.",
            "http_status": holdings_resp.status_code,
            "raw_response_snippet": holdings_resp.text[:300],
        }), 502

    if holdings_resp.status_code != 200 or holdings_data.get("status") != "success":
        return jsonify({
            "error": "Logged in successfully, but Kite rejected the holdings request.",
            "kite_response": holdings_data,
        }), 400

    holdings = holdings_data.get("data", [])

    # Step 3 — return only what the app needs. No access_token, no secrets.
    simplified = [
        {
            "ticker": h.get("tradingsymbol", ""),
            "exchange": h.get("exchange", ""),
            "quantity": h.get("quantity", 0),
            "average_price": h.get("average_price", 0),
            "last_price": h.get("last_price", 0),
            "pnl": h.get("pnl", 0),
        }
        for h in holdings
    ]

    return jsonify({
        "status": "success",
        "count": len(simplified),
        "holdings": simplified,
        "user": {
            "user_name": token_data["data"].get("user_name", ""),
            "user_id": token_data["data"].get("user_id", ""),
        },
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
