"""
server.py — The Morning Ledger's backend

Does four things:
  1. POST /api/kite/exchange — takes a request_token, exchanges it for an
     access_token using your api_secret (which lives ONLY here, as an
     environment variable — never sent to or stored in the browser), then
     uses that access_token to fetch your holdings and returns them to
     the app. Nothing is written to disk; the api_secret never leaves
     this server.
  2. GET /api/news?company=... — fetches Google News RSS for one company
     and returns parsed articles as JSON. Routed through this backend
     (rather than a free anonymous proxy) because the two proxies this
     app originally relied on both became unreliable: CodeTabs started
     rejecting many users with 400s, and r.jina.ai explicitly blocks
     anonymous traffic to news.google.com due to abuse from other users
     of their shared service. A server making its own direct request has
     no CORS restriction (a browser-only rule) and isn't exposed to
     either failure.
  3. GET /api/quotes?symbols=AARTIIND,VBL,TARIL — returns live price,
     day-over-day % change, today's volume, 20-day average volume, and
     52-week high/low for a batch of stocks, sourced from Yahoo Finance
     via the `yfinance` library.

     WHY YAHOO FINANCE AND NOT KITE: Kite Connect's quote API
     (api.kite.trade/quote) requires a paid market-data subscription —
     it returned a permissions error in practice, confirmed directly
     during testing. Kite Connect also does not provide 52-week high/low
     or a historical volume average at all, confirmed from Zerodha's own
     developer forum ("Kite Connect is purely an execution platform").
     Yahoo Finance, accessed via the unofficial `yfinance` library, is
     free and provides both — at the cost of being an unofficial,
     screen-scraping-style integration that isn't guaranteed stable if
     Yahoo changes their site. Holdings still come from Kite, which is
     the one thing only Kite can correctly tell us (your own portfolio).
  4. GET /healthz — confirms the service is alive.

There is no database. Nothing is ever written to disk. No tokens or
secrets are logged.
"""

import hashlib
import os
from urllib.parse import quote

import feedparser
import requests
import yfinance as yf
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


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/quotes", methods=["GET"])
def fetch_quotes():
    """
    Query param: ?symbols=AARTIIND,VBL,TARIL  (bare NSE tickers — this
    endpoint adds the .NS suffix itself; see _to_yahoo_symbol below)

    For each symbol, returns:
      last_price, prev_close, change_pct, volume,
      avg_volume_20d, volume_vs_avg_pct, volume_flag,
      fifty_two_wk_low, fifty_two_wk_high, near_52wk_flag

    No Kite login or access_token needed for this endpoint at all — Yahoo
    Finance via yfinance requires no authentication. This is a meaningful
    simplification versus earlier versions, which tried (and repeatedly
    struggled) to pass a Kite access_token through to a paid endpoint
    Kite never actually granted access to in the first place.
    """
    symbols_param = request.args.get("symbols", "").strip()
    if not symbols_param:
        return jsonify({"error": "symbols query parameter is required, comma-separated"}), 400

    raw_symbols = [s.strip() for s in symbols_param.split(",") if s.strip()]
    if not raw_symbols:
        return jsonify({"error": "no valid symbols provided"}), 400

    quotes = {}
    for raw_symbol in raw_symbols:
        yahoo_symbol = _to_yahoo_symbol(raw_symbol)
        try:
            quotes[raw_symbol] = _fetch_one_quote(yahoo_symbol)
        except Exception as e:
            # Fail soft, per-symbol — one bad/delisted/mistyped ticker must
            # never break the whole batch. The frontend already treats a
            # missing entry as "no price available for this one," same as
            # it did for Kite's own documented missing-symbol behavior.
            quotes[raw_symbol] = {"error": str(e)}

    return jsonify({"status": "success", "quotes": quotes})


def _to_yahoo_symbol(ticker):
    """
    Yahoo Finance needs an exchange suffix: .NS for NSE, .BO for BSE.
    Tickers from Kite holdings don't carry that suffix at all, so this
    defaults to NSE (.NS) — correct for the large majority of a typical
    portfolio. A ticker that's genuinely BSE-only and not cross-listed on
    NSE will come back as a per-symbol error from _fetch_one_quote below,
    handled the same soft-fail way as any other lookup miss — not a crash,
    just "no price available for this one."
    """
    ticker = ticker.strip().upper()
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker
    return f"{ticker}.NS"


def _fetch_one_quote(yahoo_symbol):
    stock = yf.Ticker(yahoo_symbol)
    info = stock.info  # yfinance's richer dict — includes 52wk range, avg volume

    last_price = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    volume = info.get("volume") or info.get("regularMarketVolume")
    avg_volume_20d = info.get("averageVolume10days") or info.get("averageVolume")
    fifty_two_wk_low = info.get("fiftyTwoWeekLow")
    fifty_two_wk_high = info.get("fiftyTwoWeekHigh")

    if last_price is None:
        raise ValueError("no price data returned (symbol may be wrong, delisted, or unsupported)")

    change_pct = None
    if prev_close:
        change_pct = round(((last_price - prev_close) / prev_close) * 100, 2)

    volume_vs_avg_pct = None
    volume_flag = None
    if volume is not None and avg_volume_20d:
        volume_vs_avg_pct = round((volume / avg_volume_20d) * 100, 1)
        if volume_vs_avg_pct >= 150:
            volume_flag = "high"
        elif volume_vs_avg_pct <= 50:
            volume_flag = "low"

    near_52wk_flag = None
    if fifty_two_wk_low and fifty_two_wk_high and last_price:
        # Within 2% of the 52-week high or low counts as "near" — a simple,
        # fixed threshold rather than anything more elaborate.
        if last_price >= fifty_two_wk_high * 0.98:
            near_52wk_flag = "near-high"
        elif last_price <= fifty_two_wk_low * 1.02:
            near_52wk_flag = "near-low"

    return {
        "last_price": last_price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "volume": volume,
        "avg_volume_20d": avg_volume_20d,
        "volume_vs_avg_pct": volume_vs_avg_pct,
        "volume_flag": volume_flag,
        "fifty_two_wk_low": fifty_two_wk_low,
        "fifty_two_wk_high": fifty_two_wk_high,
        "near_52wk_flag": near_52wk_flag,
    }


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
    and returns the holdings to the caller.
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

    # access_token is intentionally NOT returned to the browser anymore —
    # it was only ever needed for the old Kite-based quotes path, which is
    # gone now that prices come from Yahoo Finance (no auth needed at all).
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
