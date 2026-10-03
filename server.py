"""
server.py — The Morning Ledger's backend

Endpoints:
  1. POST /api/kite/exchange — Completes Kite Connect OAuth.
  2. GET /api/news — Fetches Google News RSS for one company.
  3. GET /api/quotes — Returns live price and % change from Yahoo Finance.
  4. GET /api/fundamentals — Returns trailing PE, P/B, etc.
  5. GET /api/fundamentals/roce — Returns ROCE & Debt Ratio calculated from balance sheets.
  6. GET /api/market/global-cues — Overnight macro cues synthesized by Gemini.
  7. POST /api/ai/briefing — Single-stock 1-minute AI briefing using Gemini.
"""

import hashlib
import os
import logging
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from urllib.parse import quote
from datetime import datetime

import feedparser
import requests
import yfinance as yf
from flask import Flask, jsonify, request
from flask_cors import CORS

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
CORS(app)

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

KITE_SESSION_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

NEWS_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

global_cues_cache = {"timestamp": 0, "data": None}


def call_gemini(prompt, max_retries=3):
    """
    Calls Gemini API with automatic exponential backoff to handle temporary
    503 (high demand) and timeout spikes.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is missing on backend")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Calling Gemini API (attempt {attempt}/{max_retries})...")
            resp = requests.post(url, json=payload, timeout=40)

            if resp.status_code in (503, 429):
                wait_time = attempt * 2
                logger.warning(f"Gemini {resp.status_code} spike on attempt {attempt}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            data = resp.json()
            if resp.status_code != 200:
                raise Exception(f"Gemini API error: {data}")

            return data["candidates"][0]["content"]["parts"][0]["text"]

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            wait_time = attempt * 2
            logger.warning(f"Gemini connection issue on attempt {attempt}: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)
        except Exception as e:
            raise e

    raise Exception(f"Gemini service unavailable after {max_retries} attempts: {last_error or '503 Unavailable'}")


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


@app.route("/logs", methods=["GET"])
def get_logs():
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
        return jsonify({"status": "ok", "message": "Log file not yet created"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/market/global-cues", methods=["GET"])
def global_cues():
    global global_cues_cache
    if time.time() - global_cues_cache["timestamp"] < 1800 and global_cues_cache["data"]:
        return jsonify(global_cues_cache["data"])

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the backend"}), 500

    indices = {
        "USA_S&P500": "^GSPC",
        "USA_Nasdaq": "^IXIC",
        "Japan_Nikkei": "^N225",
        "China_HangSeng": "^HSI",
        "Korea_Kospi": "^KS11"
    }

    market_data = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_one_quote, sym): name for name, sym in indices.items()}
        for fut in futures:
            name = futures[fut]
            try:
                res = fut.result()
                market_data[name] = res
            except Exception:
                market_data[name] = "Data unavailable"

    query = quote('"global markets" OR "US tech stocks" OR "Federal Reserve" when:1d')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    news_titles = []
    try:
        resp = requests.get(rss_url, headers=NEWS_FETCH_HEADERS, timeout=10)
        parsed = feedparser.parse(resp.content)
        news_titles = [e.get("title") for e in parsed.entries[:5]]
    except Exception:
        pass

    prompt = f"Market Data Snapshots: {market_data}\nRecent Macro News: {news_titles}\n"
    prompt += """
You are an institutional macro equity strategist for Indian equity markets.
Analyze the provided global market closes and overnight headlines. Synthesize the cross-market spillover into Indian sectors.
Provide a JSON response EXACTLY matching this schema:
{
  "global_headlines": ["Concise bullet 1 on global theme", "Concise bullet 2"],
  "indian_impact": "Expected sentiment for Nifty opening and specific impacted sectors in 1 sentence.",
  "usa_market": "1 sentence S&P/Nasdaq recap.",
  "china_market": "1 sentence Hang Seng summary.",
  "japan_market": "1 sentence Nikkei summary.",
  "korea_market": "1 sentence KOSPI summary."
}
"""
    try:
        response_text = call_gemini(prompt)
        result = json.loads(response_text)
        final_data = {"status": "success", "cues": result}
        global_cues_cache["timestamp"] = time.time()
        global_cues_cache["data"] = final_data
        return jsonify(final_data)
    except Exception as e:
        logger.error(f"Global cues error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ai/briefing", methods=["POST"])
def ai_briefing():
    body = request.get_json() or {}
    symbol = body.get("symbol", "").strip()
    company = body.get("company", "").strip()
    tier = body.get("tier", "Watch").strip()
    fundamentals = body.get("fundamentals", {})
    news = body.get("news", [])

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the backend"}), 500

    # FIX: Properly distinguish between an API failure (empty dict) and actual bad metrics.
    is_missing_data = not fundamentals or len(fundamentals) == 0
    fund_str = "Data temporarily unavailable (API timeout)" if is_missing_data else json.dumps(fundamentals)

    prompt = f"Analyze Indian stock {company} ({symbol}) for an investor based on the following verified data:\n"
    prompt += f"Portfolio Classification Tier: {tier} (Context: Top30=Accumulate, Top31-50=Hold, Top51-75=Trim, Watch=High Risk / Speculative / Exit)\n"
    prompt += f"Fundamentals (Trailing P/E, P/B, Debt, ROE, etc.): {fund_str}\n"
    prompt += "Recent News Headlines:\n"
    for n in news[:5]:
        prompt += f"- {n.get('title')}\n"

    prompt += """
Provide a structured JSON response EXACTLY matching this schema:
{
  "business_summary": "1 concise sentence explaining what the company produces or does.",
  "financial_health": "1 concise sentence evaluating financial health based on PE, debt, profitability, and capital structure. State clearly if the company is loss-making, over-leveraged, or if metrics are missing.",
  "sentiment": "BULLISH, BEARISH, or NOISE",
  "key_catalyst": "1 concise sentence on the most impactful recent development or headline.",
  "key_risk": "1 concise sentence on potential solvency, regulatory, margin, or operational risks."
}

CRITICAL RULES FOR SENTIMENT CLASSIFICATION:
1. Base sentiment on solvency, valuation, business health, and financial viability FIRST, not short-term corporate PR announcements or isolated operational wins.
2. If fundamentals clearly indicate severe distress (e.g. persistent net losses, negative P/E, heavy debt), DO NOT mark sentiment as BULLISH based purely on positive headlines. Mark it BEARISH.
3. If Fundamentals are 'Data temporarily unavailable (API timeout)', base your sentiment primarily on the recent news headlines and the Portfolio Tier. Do not invent or assume the company is loss-making or distressed just because data is missing.
"""
    try:
        response_text = call_gemini(prompt)
        result = json.loads(response_text)
        return jsonify({"status": "success", "briefing": result})
    except Exception as e:
        logger.error(f"AI briefing error: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/fundamentals", methods=["GET"])
def fetch_fundamentals():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol query parameter is required"}), 400

    yahoo_symbol = _to_yahoo_symbol(symbol)

    def _blocking_fetch():
        stock = yf.Ticker(yahoo_symbol)
        return stock.info

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_blocking_fetch)
            info = future.result(timeout=20)
    except FuturesTimeoutError:
        return jsonify({"error": "Fundamentals lookup timed out."}), 504
    except Exception as e:
        return jsonify({"error": f"Could not fetch fundamentals: {e}"}), 502

    if not info or (info.get("trailingPE") is None and info.get("regularMarketPrice") is None):
        return jsonify({"error": f"No fundamentals data found for {yahoo_symbol}"}), 404

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "fundamentals": {
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "peg_ratio": info.get("trailingPegRatio") or info.get("pegRatio"),
            "return_on_equity": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "profit_margin": info.get("profitMargins"),
        },
    })


@app.route("/api/fundamentals/roce", methods=["GET"])
def fetch_roce():
    symbol = request.args.get("symbol", "").strip()
    if not symbol:
        return jsonify({"error": "symbol query parameter is required"}), 400

    yahoo_symbol = _to_yahoo_symbol(symbol)

    def _blocking_fetch():
        stock = yf.Ticker(yahoo_symbol)
        try:
            balance_sheet = stock.balance_sheet
        except Exception:
            balance_sheet = None
        try:
            income_stmt = stock.income_stmt
        except Exception:
            income_stmt = None
        return balance_sheet, income_stmt

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_blocking_fetch)
            balance_sheet, income_stmt = future.result(timeout=20)
    except FuturesTimeoutError:
        return jsonify({"error": "ROCE lookup timed out."}), 504
    except Exception as e:
        return jsonify({"error": f"Could not fetch ROCE/Debt Ratio: {e}"}), 502

    roce, debt_ratio = _compute_roce_and_debt_ratio(balance_sheet, income_stmt)

    if roce is None and debt_ratio is None:
        return jsonify({"error": f"Data not available for {yahoo_symbol}"}), 404

    return jsonify({"status": "success", "symbol": symbol, "roce": roce, "debt_ratio": debt_ratio})


def _first_matching_row(df, candidate_labels):
    if df is None or df.empty:
        return None
    for label in candidate_labels:
        if label in df.index:
            try:
                val = df.loc[label].iloc[0]
                return float(val) if val is not None else None
            except (ValueError, TypeError, IndexError):
                continue
    return None


def _compute_roce_and_debt_ratio(balance_sheet, income_stmt):
    total_assets = _first_matching_row(balance_sheet, ["Total Assets"])
    current_liabilities = _first_matching_row(balance_sheet, ["Current Liabilities", "Total Current Liabilities"])
    total_debt = _first_matching_row(balance_sheet, ["Total Debt"])
    ebit = _first_matching_row(income_stmt, ["EBIT", "Operating Income"])

    roce = None
    if ebit is not None and total_assets is not None and current_liabilities is not None:
        capital_employed = total_assets - current_liabilities
        if capital_employed:
            roce = round(ebit / capital_employed, 4)

    debt_ratio = None
    if total_debt is not None and total_assets:
        debt_ratio = round(total_debt / total_assets, 4)

    return roce, debt_ratio


@app.route("/api/quotes", methods=["GET"])
def fetch_quotes():
    symbols_param = request.args.get("symbols", "").strip()
    if not symbols_param:
        return jsonify({"error": "symbols query parameter is required"}), 400

    raw_symbols = [s.strip() for s in symbols_param.split(",") if s.strip()]
    if not raw_symbols:
        return jsonify({"error": "no valid symbols provided"}), 400

    def _do_fetch(raw):
        try:
            yahoo_symbol = _to_yahoo_symbol(raw)
            result = raw, _fetch_one_quote(yahoo_symbol)
            return result
        except Exception as e:
            if ".NS" in str(e) and "-BE" not in raw and "-BO" not in raw:
                try:
                    yahoo_symbol_bse = _to_yahoo_symbol_bse(raw)
                    result = raw, _fetch_one_quote(yahoo_symbol_bse)
                    return result
                except Exception as e2:
                    return raw, {"error": f"{str(e)} / BSE also failed: {str(e2)}"}
            else:
                return raw, {"error": str(e)}

    quotes = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_do_fetch, s): s for s in raw_symbols}
        for future in futures:
            sym, res = future.result()
            quotes[sym] = res

    return jsonify({"status": "success", "quotes": quotes})


def _to_yahoo_symbol(ticker):
    ticker = ticker.strip().upper()
    ticker = ticker.replace("-BE", "").replace("-BO", "").replace("-EQ", "")
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker
    return f"{ticker}.NS"


def _to_yahoo_symbol_bse(ticker):
    ticker = ticker.strip().upper()
    ticker = ticker.replace("-BE", "").replace("-BO", "").replace("-EQ", "")
    if ticker.endswith(".BO"):
        return ticker
    ticker = ticker.replace(".NS", "")
    return f"{ticker}.BO"


def _fetch_one_quote(yahoo_symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + yahoo_symbol
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}

    r = requests.get(url, headers=hdrs, params={"range": "3mo", "interval": "1d", "includePrePost": "false"}, timeout=12)
    if r.status_code != 200:
        raise ValueError(f"Yahoo HTTP {r.status_code} for {yahoo_symbol}")

    d = r.json()
    result = (d.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"No chart data for {yahoo_symbol}")

    meta = result.get("meta", {})
    q = (result.get("indicators", {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []

    last_price = meta.get("regularMarketPrice")
    today_vol = meta.get("regularMarketVolume")
    wk52_high = meta.get("fiftyTwoWeekHigh")
    wk52_low = meta.get("fiftyTwoWeekLow")

    if last_price is None:
        raise ValueError(f"No price for {yahoo_symbol}")

    from datetime import datetime, timedelta, timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(IST).date()
    raw_closes = q.get("close") or []
    prev_close = meta.get("previousClose")

    if not prev_close:
        for i in range(len(timestamps) - 1, -1, -1):
            if i >= len(raw_closes): continue
            c = raw_closes[i]
            if c is None or c == 0: continue
            bar_date = datetime.fromtimestamp(timestamps[i], tz=IST).date()
            if bar_date < today_ist:
                prev_close = c
                break

    change_pct = round(((last_price - prev_close) / prev_close) * 100, 2) if prev_close else None
    vol_series = [v for v in (q.get("volume") or []) if v is not None]
    last_20 = vol_series[:-1][-20:]
    avg_vol_20d = int(sum(last_20) / len(last_20)) if len(last_20) >= 5 else None
    volume_vs_avg_pct = volume_flag = None
    if today_vol and avg_vol_20d:
        volume_vs_avg_pct = round((today_vol / avg_vol_20d) * 100, 1)
        volume_flag = "high" if volume_vs_avg_pct >= 150 else ("low" if volume_vs_avg_pct <= 50 else None)

    near_52wk_flag = None
    if wk52_high and wk52_low and last_price:
        near_52wk_flag = ("near-high" if last_price >= wk52_high * 0.98 else "near-low" if last_price <= wk52_low * 1.02 else None)

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
    company = request.args.get("company", "").strip().removesuffix("-BE")
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
    if not KITE_API_KEY or not KITE_API_SECRET:
        return jsonify({"error": "Missing KITE_API_KEY / KITE_API_SECRET"}), 500

    body = request.get_json(silent=True) or {}
    request_token = body.get("request_token", "").strip()
    if not request_token:
        return jsonify({"error": "request_token is required"}), 400

    checksum = hashlib.sha256((KITE_API_KEY + request_token + KITE_API_SECRET).encode("utf-8")).hexdigest()

    try:
        token_resp = requests.post(
            KITE_SESSION_TOKEN_URL,
            headers={"X-Kite-Version": "3"},
            data={"api_key": KITE_API_KEY, "request_token": request_token, "checksum": checksum},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach Kite: {e}"}), 502

    try:
        token_data = token_resp.json()
    except ValueError:
        return jsonify({"error": "Kite returned invalid JSON during exchange."}), 502

    if token_resp.status_code != 200 or token_data.get("status") != "success":
        return jsonify({"error": "Kite rejected the token exchange.", "kite_response": token_data}), 400

    access_token = token_data.get("data", {}).get("access_token")
    if not access_token:
        return jsonify({"error": "Missing access_token."}), 502

    try:
        holdings_resp = requests.get(
            KITE_HOLDINGS_URL,
            headers={"X-Kite-Version": "3", "Authorization": f"token {KITE_API_KEY}:{access_token}"},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Holdings fetch failed: {e}"}), 502

    try:
        holdings_data = holdings_resp.json()
    except ValueError:
        return jsonify({"error": "Kite returned invalid JSON during holdings fetch."}), 502

    if holdings_resp.status_code != 200 or holdings_data.get("status") != "success":
        return jsonify({"error": "Kite rejected the holdings request.", "kite_response": holdings_data}), 400

    simplified = [
        {
            "ticker": h.get("tradingsymbol", ""),
            "exchange": h.get("exchange", ""),
            "quantity": h.get("quantity", 0),
            "average_price": h.get("average_price", 0),
            "last_price": h.get("last_price", 0),
            "pnl": h.get("pnl", 0),
        }
        for h in holdings_data.get("data", [])
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