# server.py — Morning Ledger backend
# Handles: (1) Kite Connect OAuth exchange for holdings import
#           (2) Yahoo Finance price + volume fetch — NO auth required
#
# Deploy on Render (free tier). Set these env vars in Render dashboard:
#   KITE_API_KEY     — your Kite Connect app's API key
#   KITE_API_SECRET  — your Kite Connect app's API secret
#   FRONTEND_ORIGIN  — e.g. https://4valisetty-s.github.io

import os, time, logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import yfinance as yf
import pandas as pd

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, origins=FRONTEND_ORIGIN, supports_credentials=True)

KITE_API_KEY    = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")

KITE_EXCHANGE_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

# In-memory cache — only used for the holdings import flow
_session_cache = {"access_token": None}


# ── Ticker conversion ──────────────────────────────────────────────────────
# NSE tickers:  VBL        → VBL.NS
# BSE/BE stocks: STLTECH-BE → STLTECH.BO  (BE-series only trade on BSE)
# Kite prefix format (from frontend): NSE:VBL → VBL.NS

def to_yahoo_ticker(raw: str) -> str:
    """Convert NSE/BSE ticker to Yahoo Finance format."""
    t = raw.strip().upper()
    # Strip exchange prefix if sent as NSE:XXX or BSE:XXX
    if ":" in t:
        t = t.split(":", 1)[1]
    # BE-series (book-entry, BSE odd-lot board) → .BO
    if t.endswith("-BE"):
        return t[:-3] + ".BO"
    # Default to NSE
    return t + ".NS"


# ── /healthz ──────────────────────────────────────────────────────────────
@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


# ── /api/kite/exchange — trade request_token for access_token (holdings) ──
@app.route("/api/kite/exchange", methods=["POST"])
def kite_exchange():
    """
    Exchange a Kite request_token for an access_token, then fetch holdings.
    Called only during the holdings-import flow — not needed for prices.
    """
    body = request.get_json(silent=True) or {}
    request_token = body.get("request_token", "").strip()
    if not request_token:
        return jsonify({"error": "request_token missing"}), 400
    if not KITE_API_KEY or not KITE_API_SECRET:
        return jsonify({"error": "KITE_API_KEY / KITE_API_SECRET not set on server"}), 500

    import hashlib
    checksum = hashlib.sha256(f"{KITE_API_KEY}{request_token}{KITE_API_SECRET}".encode()).hexdigest()
    resp = requests.post(KITE_EXCHANGE_URL, data={
        "api_key": KITE_API_KEY,
        "request_token": request_token,
        "checksum": checksum,
    }, timeout=15)
    data = resp.json()
    if resp.status_code != 200 or data.get("status") != "success":
        return jsonify({"error": "Exchange failed", "kite_response": data}), 400

    access_token = data["data"]["access_token"]
    _session_cache["access_token"] = access_token

    # Immediately fetch holdings while we have the token
    h_resp = requests.get(KITE_HOLDINGS_URL, headers={
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


# ── /api/quotes — Yahoo Finance prices, NO auth required ─────────────────
@app.route("/api/quotes")
def get_quotes():
    """
    Fetch current price, % change, volume, RVOL, 52-week H/L for a list of stocks.
    Query param: symbols=VBL,TARIL,KAYNES,...  (plain NSE tickers, comma-separated)
    Or:          symbols=NSE:VBL,NSE:TARIL,...  (with exchange prefix — stripped)

    Uses Yahoo Finance — completely free, no API key, no login.
    One yf.download() call covers all stocks (fast even for 96 stocks).

    Returns per symbol:
      last_price    — latest close (or current price if market is open)
      change_pct    — % change vs previous close
      day_high      — today's intraday high
      day_low       — today's intraday low
      volume        — today's traded volume
      avg_vol_20d   — 20-session average volume
      rvol          — relative volume = volume / avg_vol_20d
      week52_high   — 52-week high
      week52_low    — 52-week low
      range_pct     — where in today's H-L range the price sits (0%=low, 100%=high)
    """
    raw_symbols = request.args.get("symbols", "")
    if not raw_symbols:
        return jsonify({"error": "symbols param missing"}), 400

    tickers = [s.strip() for s in raw_symbols.split(",") if s.strip()]
    if not tickers:
        return jsonify({"error": "no valid symbols"}), 400

    # Convert to Yahoo format
    yahoo_map = {}   # yahoo_ticker → original_ticker
    for t in tickers:
        yt = to_yahoo_ticker(t)
        # strip exchange prefix for the key we return to the frontend
        clean = t.split(":", 1)[1] if ":" in t else t
        yahoo_map[yt] = clean

    yahoo_tickers = list(yahoo_map.keys())
    log.info(f"Fetching quotes for {len(yahoo_tickers)} tickers via Yahoo Finance")

    try:
        # One call: 1 year of daily OHLCV — gives us 52-week range + 20d avg vol
        # auto_adjust=True means Close is adjusted for splits/dividends
        df = yf.download(
            yahoo_tickers,
            period="1y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.error(f"yfinance download error: {e}")
        return jsonify({"error": f"Yahoo Finance fetch failed: {str(e)}"}), 502

    if df.empty:
        return jsonify({"error": "Yahoo Finance returned no data"}), 502

    quotes = {}

    # Handle single vs multi-ticker DataFrame structure
    single = len(yahoo_tickers) == 1

    for yt, original in yahoo_map.items():
        try:
            if single:
                close_series  = df["Close"]
                high_series   = df["High"]
                low_series    = df["Low"]
                volume_series = df["Volume"]
            else:
                # MultiIndex: (field, ticker)
                if yt not in df["Close"].columns:
                    quotes[original] = None
                    continue
                close_series  = df["Close"][yt]
                high_series   = df["High"][yt]
                low_series    = df["Low"][yt]
                volume_series = df["Volume"][yt]

            # Drop NaN rows
            close_series  = close_series.dropna()
            high_series   = high_series.dropna()
            low_series    = low_series.dropna()
            volume_series = volume_series.dropna()

            if len(close_series) < 2:
                quotes[original] = None
                continue

            last_price  = float(close_series.iloc[-1])
            prev_close  = float(close_series.iloc[-2])
            day_high    = float(high_series.iloc[-1])
            day_low     = float(low_series.iloc[-1])
            today_vol   = int(volume_series.iloc[-1])

            # 20-session average volume (exclude today)
            vol_history = volume_series.iloc[-21:-1]  # up to 20 sessions before today
            avg_vol_20d = int(vol_history.mean()) if len(vol_history) >= 5 else None

            rvol = round(today_vol / avg_vol_20d, 2) if avg_vol_20d else None

            change_pct = round(((last_price - prev_close) / prev_close) * 100, 2) if prev_close else None

            # 52-week range from the full 1-year download
            week52_high = float(high_series.max())
            week52_low  = float(low_series.min())

            # Where in today's H-L range does the price sit?
            range_pct = None
            if day_high != day_low:
                range_pct = round(((last_price - day_low) / (day_high - day_low)) * 100, 1)

            quotes[original] = {
                "last_price":  round(last_price, 2),
                "prev_close":  round(prev_close, 2),
                "change_pct":  change_pct,
                "day_high":    round(day_high, 2),
                "day_low":     round(day_low, 2),
                "volume":      today_vol,
                "avg_vol_20d": avg_vol_20d,
                "rvol":        rvol,
                "week52_high": round(week52_high, 2),
                "week52_low":  round(week52_low, 2),
                "range_pct":   range_pct,
            }

        except Exception as e:
            log.warning(f"Error processing {yt}: {e}")
            quotes[original] = None

    return jsonify({"status": "success", "quotes": quotes})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
