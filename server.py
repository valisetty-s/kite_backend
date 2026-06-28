# server.py — Morning Ledger backend v20
# Handles: (1) Kite Connect OAuth for holdings import
#           (2) Yahoo Finance price/volume data — NO auth, NO pandas, NO numpy
#
# Zero compiled dependencies — works on any Python version Render provides.
# Set these env vars in Render dashboard:
#   KITE_API_KEY     — your Kite Connect app API key
#   KITE_API_SECRET  — your Kite Connect app API secret
#   FRONTEND_ORIGIN  — e.g. https://4valisetty-s.github.io

import os, hashlib, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests as req

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, origins=FRONTEND_ORIGIN, supports_credentials=True)

KITE_API_KEY    = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
KITE_EXCHANGE_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

# Yahoo Finance chart API — undocumented but stable, used by countless tools
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

_session_cache = {"access_token": None}


# ── Ticker helpers ────────────────────────────────────────────────────────

def to_yahoo_ticker(raw: str) -> str:
    """VBL → VBL.NS   |   STLTECH-BE → STLTECH.BO   |   NSE:VBL → VBL.NS"""
    t = raw.strip().upper()
    if ":" in t:
        t = t.split(":", 1)[1]
    if t.endswith("-BE"):
        return t[:-3] + ".BO"
    return t + ".NS"


# ── Yahoo Finance single-ticker fetch (no pandas) ─────────────────────────

def fetch_yahoo(ticker_raw: str) -> dict | None:
    """
    Fetch 1 year of daily OHLCV for one ticker from Yahoo Finance chart API.
    Returns a dict with price/volume/range data, or None on failure.
    Pure requests — no pandas, no numpy, no compilation needed.
    """
    yt = to_yahoo_ticker(ticker_raw)
    url = YAHOO_CHART_URL.format(ticker=yt)
    try:
        resp = req.get(
            url,
            headers=YAHOO_HEADERS,
            params={"range": "1y", "interval": "1d", "includePrePost": "false"},
            timeout=12,
        )
        if resp.status_code != 200:
            log.warning(f"{yt}: HTTP {resp.status_code}")
            return None

        data = resp.json()
        result = (data.get("chart", {}).get("result") or [None])[0]
        if not result:
            return None

        meta = result.get("meta", {})
        quotes_raw = (result.get("indicators", {}).get("quote") or [{}])[0]

        # --- Current price info from meta (always present) ---
        last_price  = meta.get("regularMarketPrice")
        prev_close  = meta.get("previousClose") or meta.get("chartPreviousClose")
        day_high    = meta.get("regularMarketDayHigh")
        day_low     = meta.get("regularMarketDayLow")
        today_vol   = meta.get("regularMarketVolume")
        wk52_high   = meta.get("fiftyTwoWeekHigh")
        wk52_low    = meta.get("fiftyTwoWeekLow")

        if last_price is None:
            return None

        # --- 20-day average volume from historical bars ---
        vol_series = [v for v in (quotes_raw.get("volume") or []) if v is not None]
        # Exclude today's bar (last element) to get a clean historical avg
        historical_vols = vol_series[:-1] if vol_series else []
        last_20 = historical_vols[-20:] if len(historical_vols) >= 5 else []
        avg_vol_20d = int(sum(last_20) / len(last_20)) if last_20 else None
        rvol = round(today_vol / avg_vol_20d, 2) if (avg_vol_20d and today_vol) else None

        # --- Derived metrics ---
        change_pct = None
        if last_price is not None and prev_close:
            change_pct = round(((last_price - prev_close) / prev_close) * 100, 2)

        range_pct = None
        if day_high is not None and day_low is not None and day_high != day_low and last_price is not None:
            range_pct = round(((last_price - day_low) / (day_high - day_low)) * 100, 1)

        return {
            "last_price":  round(last_price, 2),
            "prev_close":  round(prev_close, 2) if prev_close else None,
            "change_pct":  change_pct,
            "day_high":    round(day_high, 2) if day_high else None,
            "day_low":     round(day_low, 2) if day_low else None,
            "volume":      int(today_vol) if today_vol else None,
            "avg_vol_20d": avg_vol_20d,
            "rvol":        rvol,
            "week52_high": round(wk52_high, 2) if wk52_high else None,
            "week52_low":  round(wk52_low, 2) if wk52_low else None,
            "range_pct":   range_pct,
        }

    except Exception as e:
        log.warning(f"{yt}: {e}")
        return None


# ── /healthz ──────────────────────────────────────────────────────────────

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ── /api/kite/exchange — holdings import only ────────────────────────────

@app.route("/api/kite/exchange", methods=["POST"])
def kite_exchange():
    body = request.get_json(silent=True) or {}
    request_token = body.get("request_token", "").strip()
    if not request_token:
        return jsonify({"error": "request_token missing"}), 400
    if not KITE_API_KEY or not KITE_API_SECRET:
        return jsonify({"error": "KITE_API_KEY / KITE_API_SECRET not set on server"}), 500

    checksum = hashlib.sha256(
        f"{KITE_API_KEY}{request_token}{KITE_API_SECRET}".encode()
    ).hexdigest()

    resp = req.post(KITE_EXCHANGE_URL, data={
        "api_key": KITE_API_KEY,
        "request_token": request_token,
        "checksum": checksum,
    }, timeout=15)
    data = resp.json()

    if resp.status_code != 200 or data.get("status") != "success":
        return jsonify({"error": "Exchange failed", "kite_response": data}), 400

    access_token = data["data"]["access_token"]
    _session_cache["access_token"] = access_token

    h_resp = req.get(KITE_HOLDINGS_URL, headers={
        "Authorization": f"token {KITE_API_KEY}:{access_token}",
        "X-Kite-Version": "3",
    }, timeout=15)
    h_data = h_resp.json()
    holdings = []
    if h_resp.status_code == 200 and h_data.get("status") == "success":
        for h in h_data.get("data", []):
            holdings.append({
                "ticker":   h.get("tradingsymbol", ""),
                "exchange": h.get("exchange", "NSE"),
                "quantity": h.get("quantity", 0),
                "avg_cost": h.get("average_price", 0),
            })

    return jsonify({
        "status": "success",
        "access_token": access_token,
        "holdings": holdings,
    })


# ── /api/quotes — Yahoo Finance, no auth, no pandas ──────────────────────

@app.route("/api/quotes")
def get_quotes():
    """
    Fetch price + volume data for a list of NSE tickers via Yahoo Finance.
    Query param: symbols=VBL,TARIL,KAYNES,...  (comma-separated, no exchange prefix needed)

    Uses 10 parallel threads so 96 stocks complete in ~15-20 seconds
    rather than 96 × 2s = 3+ minutes sequentially.

    No pandas. No numpy. No compilation. Works on any Python version.
    """
    raw_symbols = request.args.get("symbols", "")
    if not raw_symbols:
        return jsonify({"error": "symbols param missing"}), 400

    tickers = [s.strip() for s in raw_symbols.split(",") if s.strip()]
    if not tickers:
        return jsonify({"error": "no valid symbols"}), 400

    log.info(f"Fetching {len(tickers)} tickers from Yahoo Finance")
    quotes = {}

    # 10 parallel threads — respectful of Yahoo's rate limits while still fast
    with ThreadPoolExecutor(max_workers=10) as pool:
        future_to_ticker = {pool.submit(fetch_yahoo, t): t for t in tickers}
        for future in as_completed(future_to_ticker):
            original = future_to_ticker[future]
            try:
                quotes[original] = future.result()
            except Exception as e:
                log.warning(f"{original}: future error {e}")
                quotes[original] = None

    fetched = sum(1 for v in quotes.values() if v is not None)
    log.info(f"Yahoo Finance: {fetched}/{len(tickers)} tickers fetched successfully")

    return jsonify({"status": "success", "quotes": quotes})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
