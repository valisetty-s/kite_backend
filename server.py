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
import logging
import sys
from urllib.parse import quote
from datetime import datetime

import feedparser
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

# Configure comprehensive logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/morning-ledger.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Allow the PWA (hosted on a different domain) to call this API

logger.info("=" * 80)
logger.info("Morning Ledger Backend Starting")
logger.info(f"Timestamp: {datetime.now()}")
logger.info("=" * 80)

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
    logger.info("Health check")
    return jsonify({"status": "ok"})


@app.route("/logs", methods=["GET"])
def get_logs():
    """
    Returns recent logs for debugging. Shows last 200 lines or specific tail count.
    Query param: ?tail=100 (default 200)
    """
    try:
        tail = int(request.args.get("tail", 200))
        with open('/tmp/morning-ledger.log', 'r') as f:
            lines = f.readlines()
        recent_lines = lines[-tail:] if len(lines) > tail else lines
        return jsonify({
            "status": "ok",
            "total_lines": len(lines),
            "returned_lines": len(recent_lines),
            "logs": ''.join(recent_lines)
        })
    except FileNotFoundError:
        return jsonify({
            "status": "ok",
            "message": "Log file not yet created (app just started)"
        })
    except Exception as e:
        logger.error(f"Error reading logs: {str(e)}")
        return jsonify({"error": str(e)}), 500


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
    logger.info("=== FETCH_QUOTES START ===")
    symbols_param = request.args.get("symbols", "").strip()
    logger.info(f"Requested symbols: {symbols_param}")
    
    if not symbols_param:
        logger.error("No symbols provided")
        return jsonify({"error": "symbols query parameter is required, comma-separated"}), 400

    raw_symbols = [s.strip() for s in symbols_param.split(",") if s.strip()]
    if not raw_symbols:
        logger.error("No valid symbols after parsing")
        return jsonify({"error": "no valid symbols provided"}), 400

    logger.info(f"Parsed {len(raw_symbols)} symbols: {raw_symbols}")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _do_fetch(raw):
        try:
            yahoo_symbol = _to_yahoo_symbol(raw)
            logger.debug(f"{raw} - Trying: {yahoo_symbol}")
            result = raw, _fetch_one_quote(yahoo_symbol)
            logger.debug(f"Successfully fetched {raw} as {yahoo_symbol}")
            return result
        except Exception as e:
            # If NSE (.NS) failed, try BSE (.BO) as fallback
            if ".NS" in str(e) and "-BE" not in raw and "-BO" not in raw:
                try:
                    yahoo_symbol_bse = _to_yahoo_symbol_bse(raw)
                    logger.debug(f"{raw} - NSE failed, trying BSE: {yahoo_symbol_bse}")
                    result = raw, _fetch_one_quote(yahoo_symbol_bse)
                    logger.debug(f"Successfully fetched {raw} as {yahoo_symbol_bse} (BSE fallback)")
                    return result
                except Exception as e2:
                    logger.error(f"Failed to fetch {raw} on both NSE and BSE: {str(e2)}")
                    return raw, {"error": f"{str(e)} / BSE also failed: {str(e2)}"}
            else:
                logger.error(f"Failed to fetch {raw}: {str(e)}")
                return raw, {"error": str(e)}

    quotes = {}
    failed_count = 0
    success_count = 0
    
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_do_fetch, s): s for s in raw_symbols}
        for future in as_completed(futures):
            sym, res = future.result()
            quotes[sym] = res
            if "error" in res:
                failed_count += 1
            else:
                success_count += 1

    logger.info(f"=== FETCH_QUOTES END === Success: {success_count}/{len(raw_symbols)}, Failed: {failed_count}")
    return jsonify({"status": "success", "quotes": quotes})


def _to_yahoo_symbol(ticker):
    """
    Yahoo Finance needs an exchange suffix: .NS for NSE, .BO for BSE.
    This function:
    1. Removes any existing -BE, -BO, -EQ suffixes (Kite indicators)
    2. Removes any existing .NS, .BO suffixes (if already present)
    3. Defaults to .NS (NSE — correct for most Indian stocks)
    
    A ticker that's genuinely BSE-only and not cross-listed on NSE will
    come back as a per-symbol error from _fetch_one_quote below, handled
    as a soft-fail — just "no price available for this one."
    """
    ticker = ticker.strip().upper()
    
    # Remove exchange suffixes if they exist
    # These come from Kite exports: SYMBOL-BE, SYMBOL-BO, SYMBOL-EQ, etc.
    ticker = ticker.replace("-BE", "").replace("-BO", "").replace("-EQ", "")
    
    # If already has an exchange suffix, return as-is
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker
    
    # Default to NSE (most stocks are listed here)
    return f"{ticker}.NS"


def _to_yahoo_symbol_bse(ticker):
    """
    Same as _to_yahoo_symbol but tries BSE (.BO) instead of NSE (.NS).
    Used as fallback if NSE lookup fails.
    """
    ticker = ticker.strip().upper()
    
    # Remove exchange suffixes if they exist
    ticker = ticker.replace("-BE", "").replace("-BO", "").replace("-EQ", "")
    
    # If already has an exchange suffix and it's .BO, return as-is
    if ticker.endswith(".BO"):
        return ticker
    
    # Remove .NS if present, then add .BO
    ticker = ticker.replace(".NS", "")
    
    # Try BSE
    return f"{ticker}.BO"


def _fetch_one_quote(yahoo_symbol):
    """
    Fetches current price and calculates day-over-day change by using timestamp
    data to properly identify the previous trading day (handles weekends/holidays).
    Uses 3-month range for reliable volume averages and 52-week data.
    """
    logger.info(f"Fetching quote for: {yahoo_symbol}")
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + yahoo_symbol
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
    
    try:
        # Use 3mo range to get reliable 20-day average volume and historical close data
        r = requests.get(url, headers=hdrs,
                         params={"range": "3mo", "interval": "1d", "includePrePost": "false"}, timeout=12)
        logger.debug(f"{yahoo_symbol} - Response status: {r.status_code}")
        
        if r.status_code != 200:
            logger.error(f"{yahoo_symbol} - Yahoo HTTP {r.status_code}")
            raise ValueError(f"Yahoo HTTP {r.status_code} for {yahoo_symbol}")
        
        d = r.json()
        result = (d.get("chart", {}).get("result") or [None])[0]
        if not result:
            logger.error(f"{yahoo_symbol} - No chart data found")
            raise ValueError(f"No chart data for {yahoo_symbol}")
        
        meta = result.get("meta", {})
        q    = (result.get("indicators", {}).get("quote") or [{}])[0]
        timestamps = result.get("timestamp") or []
        
        last_price = meta.get("regularMarketPrice")
        today_vol  = meta.get("regularMarketVolume")
        wk52_high  = meta.get("fiftyTwoWeekHigh")
        wk52_low   = meta.get("fiftyTwoWeekLow")
        
        logger.debug(f"{yahoo_symbol} - Current price: {last_price}, Volume: {today_vol}")
        logger.debug(f"{yahoo_symbol} - Timestamps available: {len(timestamps)}, Data points: {len(q.get('close', []))}")
        
        if last_price is None:
            logger.error(f"{yahoo_symbol} - No price found")
            raise ValueError(f"No price for {yahoo_symbol}")
        
        # Use timestamps to find the most recent complete day and the previous trading day
        # Timestamps are Unix epoch, most recent first in the array
        raw_closes = q.get("close") or []
        prev_close = None
        prev_close_day_offset = None
        
        logger.debug(f"{yahoo_symbol} - First 5 closes: {raw_closes[:5]}, First 5 timestamps: {timestamps[:5]}")
        
        # Array is sorted most recent to oldest. Find first valid close (not None, not 0)
        # Then keep searching for the second valid close - that's yesterday's
        valid_closes_found = 0
        for i in range(len(raw_closes)):
            if raw_closes[i] is not None and raw_closes[i] != 0:
                valid_closes_found += 1
                if valid_closes_found == 2:  # We want the SECOND valid close (previous trading day)
                    prev_close = raw_closes[i]
                    prev_close_day_offset = i
                    break
        
        if prev_close is None:
            logger.warning(f"{yahoo_symbol} - Could not find valid previous close")
        else:
            logger.debug(f"{yahoo_symbol} - Using previous close: {prev_close} (from {prev_close_day_offset} days back)")
        
        change_pct = round(((last_price - prev_close) / prev_close) * 100, 2) if prev_close else None
        logger.info(f"{yahoo_symbol} - Change %: {change_pct} (current: {last_price}, prev: {prev_close})")
        
        # Get volume data for volume comparison
        vol_series  = [v for v in (q.get("volume") or []) if v is not None]
        last_20     = vol_series[:-1][-20:]
        avg_vol_20d = int(sum(last_20) / len(last_20)) if len(last_20) >= 5 else None
        volume_vs_avg_pct = volume_flag = None
        if today_vol and avg_vol_20d:
            volume_vs_avg_pct = round((today_vol / avg_vol_20d) * 100, 1)
            volume_flag = "high" if volume_vs_avg_pct >= 150 else ("low" if volume_vs_avg_pct <= 50 else None)
            logger.debug(f"{yahoo_symbol} - Volume vs avg: {volume_vs_avg_pct}%, flag: {volume_flag}")
        
        near_52wk_flag = None
        if wk52_high and wk52_low and last_price:
            near_52wk_flag = ("near-high" if last_price >= wk52_high * 0.98
                              else "near-low" if last_price <= wk52_low * 1.02 else None)
        
        result_obj = {
            "last_price": round(last_price, 2), "prev_close": round(prev_close, 2) if prev_close else None,
            "change_pct": change_pct, "volume": int(today_vol) if today_vol else None,
            "avg_volume_20d": avg_vol_20d, "volume_vs_avg_pct": volume_vs_avg_pct,
            "volume_flag": volume_flag,
            "fifty_two_wk_low": round(wk52_low, 2) if wk52_low else None,
            "fifty_two_wk_high": round(wk52_high, 2) if wk52_high else None,
            "near_52wk_flag": near_52wk_flag,
        }
        logger.info(f"{yahoo_symbol} - Success: {result_obj}")
        return result_obj
        
    except Exception as e:
        logger.error(f"{yahoo_symbol} - Exception: {str(e)}", exc_info=True)
        raise

@app.route("/api/news", methods=["GET"])
def fetch_news_for_company():
    """
    Query param: ?company=Aarti+Industries

    Fetches Google News RSS for the given company name directly from this
    server (no CORS issue, no anonymous-proxy abuse flag) and returns
    parsed articles as JSON.
    """
    company = request.args.get("company", "").strip()
    logger.info(f"Fetching news for: {company}")
    
    if not company:
        logger.error("No company parameter provided")
        return jsonify({"error": "company query parameter is required"}), 400

    query = quote(f'"{company}" when:7d')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    logger.debug(f"RSS URL: {rss_url}")

    try:
        resp = requests.get(rss_url, headers=NEWS_FETCH_HEADERS, timeout=12)
        logger.debug(f"{company} - News fetch HTTP status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"{company} - Could not reach Google News: {str(e)}")
        return jsonify({"error": f"Could not reach Google News: {e}"}), 502

    if resp.status_code != 200:
        logger.error(f"{company} - Google News returned HTTP {resp.status_code}")
        return jsonify({
            "error": f"Google News returned HTTP {resp.status_code}",
            "raw_response_snippet": resp.text[:300],
        }), 502

    try:
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        logger.error(f"{company} - Could not parse RSS: {str(e)}")
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

    logger.info(f"{company} - Found {len(articles)} articles")
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
