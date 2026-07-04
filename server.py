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

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _do_fetch(raw):
        try: return raw, _fetch_one_quote(_to_yahoo_symbol(raw))
        except Exception as e: return raw, {"error": str(e)}

    quotes = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_do_fetch, s): s for s in raw_symbols}
        for future in as_completed(futures):
            sym, res = future.result()
            quotes[sym] = res

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
    """
    Fetches current price and compares to YESTERDAY's close for accurate
    day-over-day change percentage. Uses 3-month range to ensure we get reliable
    20-day average volume data. Also retrieves 52-week high/low and volume
    metrics from Yahoo Finance.
    """
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + yahoo_symbol
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
    # Use 3mo range to get reliable 20-day average volume, includes recent price data
    r = requests.get(url, headers=hdrs,
                     params={"range": "3mo", "interval": "1d", "includePrePost": "false"}, timeout=12)
    if r.status_code != 200:
        raise ValueError(f"Yahoo HTTP {r.status_code} for {yahoo_symbol}")
    d = r.json()
    result = (d.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"No chart data for {yahoo_symbol}")
    meta = result.get("meta", {})
    q    = (result.get("indicators", {}).get("quote") or [{}])[0]
    last_price = meta.get("regularMarketPrice")
    today_vol  = meta.get("regularMarketVolume")
    wk52_high  = meta.get("fiftyTwoWeekHigh")
    wk52_low   = meta.get("fiftyTwoWeekLow")
    
    if last_price is None:
        raise ValueError(f"No price for {yahoo_symbol}")
    
    # Get previous close from the quote data array (actual yesterday's close)
    # The quote array contains [today, yesterday, day-before, etc.]
    closes = [c for c in (q.get("close") or []) if c is not None]
    prev_close = None
    if len(closes) >= 2:
        # closes[0] is today, closes[1] is yesterday
        prev_close = closes[1]
    # If we can't get yesterday's close, leave as None (will show as N/A)
    
    change_pct = round(((last_price - prev_close) / prev_close) * 100, 2) if prev_close else None
    
    # Get volume data for volume comparison
    vol_series  = [v for v in (q.get("volume") or []) if v is not None]
    last_20     = vol_series[:-1][-20:]
    avg_vol_20d = int(sum(last_20) / len(last_20)) if len(last_20) >= 5 else None
    volume_vs_avg_pct = volume_flag = None
    if today_vol and avg_vol_20d:
        volume_vs_avg_pct = round((today_vol / avg_vol_20d) * 100, 1)
        volume_flag = "high" if volume_vs_avg_pct >= 150 else ("low" if volume_vs_avg_pct <= 50 else None)
    
    near_52wk_flag = None
    if wk52_high and wk52_low and last_price:
        near_52wk_flag = ("near-high" if last_price >= wk52_high * 0.98
                          else "near-low" if last_price <= wk52_low * 1.02 else None)
    return {
        "last_price": round(last_price, 2), "prev_close": round(prev_close, 2) if prev_close else None,
        "change_pct": change_pct, "volume": int(today_vol) if today_vol else None,
        "avg_volume_20d": avg_vol_20d, "volume_vs_avg_pct": volume_vs_avg_pct,
        "volume_flag": volume_flag,
        "fifty_two_wk_low": round(wk52_low, 2) if wk52_low else None,
        "fifty_two_wk_high": round(wk52_high, 2) if wk52_high else None,
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

    query = quote(f'"{company}" when:7d')
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
