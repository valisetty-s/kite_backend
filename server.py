"""
server.py — The Morning Ledger's backend

Endpoints:
  1. POST /api/kite/exchange — Completes Kite Connect OAuth (multi-profile).
  2. GET /api/groww/holdings — Fetches Groww holdings (multi-profile).
  3. GET /api/news — Fetches Google News RSS for one company.
  4. GET /api/quotes — Returns live price and % change from Yahoo Finance.
  5. GET /api/fundamentals — Returns trailing PE, P/B, Debt, ROCE, OPM, CFO/EBITDA, Capex/CWIP.
  6. GET /api/fundamentals/roce — Returns ROCE & Debt Ratio calculated from balance sheets.
  7. GET /api/market/global-cues — Overnight macro cues synthesized by Gemini.
  8. POST /api/ai/briefing — Single-stock 1-minute AI briefing using Gemini.
"""

import hashlib
import os
import logging
import sys
import json
import time
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import yfinance as yf
from flask import Flask, jsonify, request
from flask_cors import CORS
from bs4 import BeautifulSoup

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

KITE_API_KEY = os.environ.get("KITE_API_KEY", "").strip()
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

KITE_SESSION_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"

# In-memory session store per profile: { "self": {"access_token": ..., "api_key": ...}, "wife": ... }
profile_sessions = {}


def _normalize_profile(raw_profile):
    p = (raw_profile or "self").strip().lower()
    if p in ("spouse", "wife", "deepthi"):
        return "wife"
    if p in ("self", "satish"):
        return "self"
    return re.sub(r"[^a-z0-9_-]", "_", p) or "self"


def _resolve_kite_credentials(profile="self"):
    p_norm = _normalize_profile(profile)
    p_upper = p_norm.upper()

    api_key = (
        os.environ.get(f"KITE_API_KEY_{p_upper}", "").strip()
        or (os.environ.get("KITE_API_KEY_SELF", "").strip() if p_norm == "self" else "")
        or KITE_API_KEY
    )
    api_secret = (
        os.environ.get(f"KITE_API_SECRET_{p_upper}", "").strip()
        or (os.environ.get("KITE_API_SECRET_SELF", "").strip() if p_norm == "self" else "")
        or KITE_API_SECRET
    )
    return p_norm, api_key, api_secret


NEWS_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

UNK_SOURCES = [
    "simply wall st", "zacks", "investorplace", "tipranks",
    "motley fool", "dsij", "dalal street investment journal",
    "tradingview", "goodreturns", "good returns", "scanx",
    "scanx.trade", "equitybulls", "capital market"
]

global_cues_cache = {"timestamp": 0, "data": None}
fundamentals_cache = {}  # { symbol: {"timestamp": float, "data": dict} }


def call_gemini(prompt):
    """
    Calls Gemini API with automatic model routing:
    Attempts primary gemini-3.8-flash, falls back to gemini-3.5-flash-lite on 503/timeout.
    """
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY environment variable is missing on backend")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json"
        }
    }

    endpoints = [
        ("gemini-3.8-flash", f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={GEMINI_API_KEY}", 35),
        ("gemini-3.5-flash-lite", f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}", 25)
    ]

    last_error = None
    for model_name, url, timeout_secs in endpoints:
        logger.info(f"Attempting Gemini API using {model_name}...")
        try:
            resp = requests.post(url, json=payload, timeout=timeout_secs)

            if resp.status_code in (503, 429):
                logger.warning(f"{model_name} returned {resp.status_code}. Routing to fallback...")
                last_error = f"HTTP {resp.status_code}"
                continue

            data = resp.json()
            if resp.status_code != 200:
                logger.error(f"{model_name} error: {data}")
                last_error = str(data)
                continue

            return data["candidates"][0]["content"]["parts"][0]["text"]

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning(f"Connection/Timeout on {model_name}: {e}. Routing to fallback...")
            last_error = str(e)
            continue
        except Exception as e:
            raise e

    raise Exception(f"All Gemini models unavailable. Last error: {last_error}")


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
    garp_score = body.get("garp_score")
    trend = body.get("trend", "unknown")
    action_signal = body.get("action_signal")
    fundamentals = body.get("fundamentals", {})
    news = body.get("news", [])

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the backend"}), 500

    fund_str = json.dumps(fundamentals) if fundamentals else "Live metrics unavailable"

    prompt = f"You are an institutional equity research assistant doing a fast Thesis-Check on Indian stock {company} ({symbol}).\n"
    prompt += f"Dashboard Signals: GARP Score={garp_score}/100 | Trend={trend} | Action Signal={action_signal or 'None'} | Tier={tier}\n"
    prompt += f"Screener Fundamentals: {fund_str}\n"
    prompt += "Recent News Headlines:\n"
    if news:
        for n in news[:5]:
            prompt += f"- {n.get('title')}\n"
    else:
        prompt += "- No recent headlines found.\n"

    prompt += """
Provide a structured JSON response EXACTLY matching this schema:
{
  "news_materiality": "HIGH or LOW",
  "business_summary": "1 concise sentence explaining what the company produces or does.",
  "what_changed": "1 concise sentence summarizing ONLY material news (earnings, order wins, capex, regulatory/governance action). If headlines are routine price chatter or empty, state 'No material thesis-changing news in recent headlines.'",
  "key_watchpoint": "1 specific, actionable watchpoint grounded in the actual numbers provided (e.g. stretched PEG, weak CFO/EBITDA <50%, heavy CWIP/capex execution, debt, or broken 200-DMA trend)."
}

RULES:
- Set news_materiality to "HIGH" ONLY if headlines contain earnings results, major contract/order wins, capex/expansion milestones, M&A, promoter/governance flags, or regulatory actions. Otherwise set "LOW".
- Do NOT invent numbers. Reference the provided fundamentals (P/E, PEG, ROCE, OPM, CFO/EBITDA, Capex/CWIP) when writing key_watchpoint.
"""
    try:
        response_text = call_gemini(prompt)
        result = json.loads(response_text)
        return jsonify({"status": "success", "briefing": result})
    except Exception as e:
        logger.error(f"AI briefing error: {str(e)}")
        return jsonify({"error": str(e)}), 500


def _parse_screener_num(text):
    if not text:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _fetch_screener_fundamentals(symbol):
    """Scrapes public Screener.in page (consolidated first, then standalone)."""
    clean_sym = re.sub(r"-(BE|SM|IL|BL|N1|N2)$", "", symbol.upper())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    soup = None
    for url in (
        f"https://www.screener.in/company/{clean_sym}/consolidated/",
        f"https://www.screener.in/company/{clean_sym}/",
    ):
        resp = requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            candidate = BeautifulSoup(resp.text, "html.parser")
            if candidate.select("#top-ratios li"):
                soup = candidate
                break

    if not soup:
        return None

    ratios = {}
    for li in soup.select("#top-ratios li"):
        name_el = li.select_one(".name")
        val_el = li.select_one(".value")
        if name_el and val_el:
            ratios[name_el.get_text(strip=True)] = _parse_screener_num(val_el.get_text(" ", strip=True))

    trailing_pe = ratios.get("Stock P/E")
    roce = ratios["ROCE"] / 100.0 if ratios.get("ROCE") is not None else None
    roe = ratios["ROE"] / 100.0 if ratios.get("ROE") is not None else None
    curr_price = ratios.get("Current Price")
    book_val = ratios.get("Book Value")
    price_to_book = round(curr_price / book_val, 2) if (curr_price and book_val and book_val > 0) else None
    market_cap = ratios["Market Cap"] * 1e7 if ratios.get("Market Cap") is not None else None

    rev_growth_ttm = None
    earn_growth_ttm = None
    rev_growth_3y = None
    earn_growth_3y = None
    for table in soup.select("table.ranges-table"):
        header_el = table.select_one("th")
        if not header_el:
            continue
        title = header_el.get_text(strip=True)
        rows = {}
        for tr in table.select("tr")[1:]:
            tds = tr.select("td")
            if len(tds) == 2:
                rows[tds[0].get_text(strip=True).rstrip(":")] = _parse_screener_num(tds[1].get_text(strip=True))
        ttm_val = rows.get("TTM")
        y3_val = rows.get("3 Years")
        if "Sales Growth" in title:
            if ttm_val is not None:
                rev_growth_ttm = ttm_val / 100.0
            if y3_val is not None:
                rev_growth_3y = y3_val / 100.0
        elif "Profit Growth" in title:
            if ttm_val is not None:
                earn_growth_ttm = ttm_val / 100.0
            if y3_val is not None:
                earn_growth_3y = y3_val / 100.0

    rev_growth_2q = None
    earn_growth_2q = None
    q_section = soup.select_one("#quarters")
    if q_section:
        for tr in q_section.select("tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue
            label = tds[0].get_text(strip=True).replace("+", "").strip()
            vals = [_parse_screener_num(td.get_text(strip=True)) for td in tds[1:]]
            if len(vals) >= 6 and all(vals[i] is not None for i in (-1, -2, -5, -6)):
                curr_2q = vals[-1] + vals[-2]
                prev_2q = vals[-5] + vals[-6]
                if prev_2q > 0:
                    yoy_2q = round((curr_2q - prev_2q) / prev_2q, 4)
                    if label in ("Sales", "Revenue"):
                        rev_growth_2q = yoy_2q
                    elif label == "Net Profit":
                        earn_growth_2q = yoy_2q

    rev_growth = rev_growth_2q if rev_growth_2q is not None else (rev_growth_ttm if rev_growth_ttm is not None else rev_growth_3y)
    earn_growth = earn_growth_2q if earn_growth_2q is not None else (earn_growth_ttm if earn_growth_ttm is not None else earn_growth_3y)

    operating_margin = None
    ebitda_3y_vals = []
    pl_section = soup.select_one("#profit-loss")
    if pl_section:
        pl_headers = [th.get_text(strip=True).upper() for th in pl_section.select("thead th")][1:]
        has_ttm = bool(pl_headers and "TTM" in pl_headers[-1])
        for tr in pl_section.select("tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue
            row_label = tds[0].get_text(strip=True).replace("+", "").strip()
            if "OPM %" in row_label:
                vals = [_parse_screener_num(td.get_text(strip=True)) for td in tds[1:]]
                valid = [v for v in vals if v is not None]
                if valid:
                    operating_margin = valid[-1] / 100.0
            elif row_label == "Operating Profit":
                raw_tds = tds[1:-1] if has_ttm else tds[1:]
                vals = [_parse_screener_num(td.get_text(strip=True)) for td in raw_tds]
                valid = [v for v in vals if v is not None]
                if len(valid) >= 2:
                    ebitda_3y_vals = valid[-3:]

    cfo_to_ebitda = None
    cf_section = soup.select_one("#cash-flow")
    if cf_section and ebitda_3y_vals:
        for tr in cf_section.select("tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue
            row_label = tds[0].get_text(strip=True).replace("+", "").strip()
            if "Cash from Operating Activity" in row_label:
                vals = [_parse_screener_num(td.get_text(strip=True)) for td in tds[1:]]
                valid = [v for v in vals if v is not None]
                n = min(len(valid), len(ebitda_3y_vals))
                if n >= 2:
                    cfo_sum = sum(valid[-n:])
                    ebitda_sum = sum(ebitda_3y_vals[-n:])
                    if ebitda_sum > 0:
                        cfo_to_ebitda = round(cfo_sum / ebitda_sum, 2)
                break

    debt_ratio = None
    debt_to_equity = None
    total_debt = None
    fixed_asset_ratio = None
    cwip_ratio = None
    is_capex_heavy = False
    bs_section = soup.select_one("#balance-sheet")
    if bs_section:
        bs_rows = {}
        for tr in bs_section.select("tbody tr"):
            tds = tr.select("td")
            if len(tds) > 1:
                label = tds[0].get_text(strip=True).replace("+", "").strip()
                vals = [_parse_screener_num(td.get_text(strip=True)) for td in tds[1:]]
                valid = [v for v in vals if v is not None]
                if valid:
                    bs_rows[label] = valid[-1]
        borrowings = bs_rows.get("Borrowings")
        eq_cap = bs_rows.get("Equity Capital", 0.0) or 0.0
        reserves = bs_rows.get("Reserves", 0.0) or 0.0
        net_worth = eq_cap + reserves
        if borrowings is not None:
            total_debt = borrowings * 1e7
            if net_worth > 0:
                debt_ratio = round(borrowings / net_worth, 2)
                debt_to_equity = round(debt_ratio * 100, 2)

        fixed_assets = bs_rows.get("Fixed Assets", 0.0) or 0.0
        cwip = bs_rows.get("CWIP", 0.0) or 0.0
        total_assets = bs_rows.get("Total Assets")
        if total_assets and total_assets > 0:
            fixed_asset_ratio = round((fixed_assets + cwip) / total_assets, 2)
        if fixed_assets > 0 and cwip > 0:
            cwip_ratio = round(cwip / fixed_assets, 2)
        if (fixed_asset_ratio is not None and fixed_asset_ratio >= 0.40) or (cwip_ratio is not None and cwip_ratio >= 0.15):
            is_capex_heavy = True

    peg_ratio = None
    if trailing_pe and trailing_pe > 0:
        growth_for_peg = None
        candidates = [
            earn_growth_3y,
            rev_growth_3y,
            earn_growth_ttm if (earn_growth_ttm is not None and earn_growth_ttm <= 1.50) else None,
            rev_growth_ttm,
            rev_growth,
        ]
        for candidate in candidates:
            if candidate is not None and candidate > 0:
                growth_for_peg = min(candidate, 1.50)
                break
        if growth_for_peg:
            val = round(trailing_pe / (growth_for_peg * 100), 2)
            peg_ratio = val if val > 0 else None

    return {
        "trailing_pe": trailing_pe,
        "forward_pe": None,
        "price_to_book": price_to_book,
        "peg_ratio": peg_ratio,
        "return_on_equity": roe,
        "roce": roce,
        "debt_to_equity": debt_to_equity,
        "debt_ratio": debt_ratio,
        "profit_margin": None,
        "operating_margin": operating_margin,
        "total_debt": total_debt,
        "market_cap": market_cap,
        "industry_pe": None,
        "revenue_growth": rev_growth,
        "earnings_growth": earn_growth,
        "cfo_to_ebitda": cfo_to_ebitda,
        "fixed_asset_ratio": fixed_asset_ratio,
        "cwip_ratio": cwip_ratio,
        "is_capex_heavy": is_capex_heavy,
    }


@app.route("/api/fundamentals", methods=["GET"])
def fetch_fundamentals():
    symbol = request.args.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "symbol query parameter is required"}), 400

    cached = fundamentals_cache.get(symbol)
    if cached and (time.time() - cached["timestamp"] < 43200):
        return jsonify(cached["data"])

    try:
        screener_data = _fetch_screener_fundamentals(symbol)
        if screener_data:
            payload = {
                "status": "success",
                "symbol": symbol,
                "source": "screener",
                "fundamentals": screener_data,
            }
            fundamentals_cache[symbol] = {"timestamp": time.time(), "data": payload}
            return jsonify(payload)
    except Exception as e:
        print(f"Screener lookup failed for {symbol}: {e}")

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

    has_price = any(info.get(k) is not None for k in ["currentPrice", "regularMarketPrice", "previousClose", "open"])
    if not info or not has_price:
        return jsonify({"error": f"No data found for {yahoo_symbol}"}), 404

    trailing_pe = info.get("trailingPE")
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")

    peg_ratio = info.get("trailingPegRatio") or info.get("pegRatio")
    if peg_ratio is None and trailing_pe and trailing_pe > 0:
        growth_for_peg = earn_growth if (earn_growth and earn_growth > 0) else rev_growth
        if growth_for_peg and growth_for_peg > 0:
            peg_ratio = round(trailing_pe / (growth_for_peg * 100), 2)

    payload = {
        "status": "success",
        "symbol": symbol,
        "source": "yahoo",
        "fundamentals": {
            "trailing_pe": trailing_pe,
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "peg_ratio": peg_ratio,
            "return_on_equity": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "total_debt": info.get("totalDebt"),
            "market_cap": info.get("marketCap"),
            "industry_pe": info.get("industryTrailingPE") or info.get("sectorTrailingPE"),
            "revenue_growth": rev_growth,
            "earnings_growth": earn_growth
        },
    }

    fundamentals_cache[symbol] = {"timestamp": time.time(), "data": payload}
    return jsonify(payload)


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

    r = requests.get(url, headers=hdrs, params={"range": "1y", "interval": "1d", "includePrePost": "false"}, timeout=12)
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

    IST = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(IST).date()
    raw_closes = q.get("close") or []
    prev_close = meta.get("regularMarketPreviousClose") or meta.get("previousClose")

    if not prev_close:
        for i in range(len(timestamps) - 1, -1, -1):
            if i >= len(raw_closes):
                continue
            c = raw_closes[i]
            if c is None or c == 0:
                continue
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

    valid_closes = [c for c in raw_closes if c is not None and c > 0]
    dma_20 = round(sum(valid_closes[-20:]) / 20, 2) if len(valid_closes) >= 20 else None
    dma_50 = round(sum(valid_closes[-50:]) / 50, 2) if len(valid_closes) >= 50 else None
    dma_200 = round(sum(valid_closes[-200:]) / 200, 2) if len(valid_closes) >= 200 else None

    return {
        "last_price": round(last_price, 2), "prev_close": round(prev_close, 2) if prev_close else None,
        "change_pct": change_pct, "volume": int(today_vol) if today_vol else None,
        "avg_volume_20d": avg_vol_20d, "volume_vs_avg_pct": volume_vs_avg_pct,
        "volume_flag": volume_flag,
        "fifty_two_wk_low": round(wk52_low, 2) if wk52_low else None,
        "fifty_two_wk_high": round(wk52_high, 2) if wk52_high else None,
        "near_52wk_flag": near_52wk_flag,
        "dma_20": dma_20,
        "dma_50": dma_50,
        "dma_200": dma_200,
    }


@app.route("/api/news", methods=["GET"])
def fetch_news_for_company():
    JUNK_SOURCES = [
        "simply wall st", "zacks", "investorplace", "tipranks",
        "motley fool", "dsij", "dalal street investment journal",
        "tradingview", "goodreturns", "good returns", "scanx",
        "scanx.trade", "equitybulls", "capital market"
    ]

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
    now_utc = datetime.utcnow()

    for entry in parsed.entries:
        if len(articles) >= 5:
            break

        raw_title = (entry.get("title") or "").strip()
        title, source = raw_title, "Google News"
        sep_idx = raw_title.rfind(" - ")
        if sep_idx > 0:
            title = raw_title[:sep_idx].strip()
            source = raw_title[sep_idx + 3:].strip()

        if any(junk in source.lower() for junk in JUNK_SOURCES):
            continue

        published_parsed = entry.get("published_parsed")
        if published_parsed:
            try:
                article_dt = datetime(*published_parsed[:6])
                if now_utc - article_dt > timedelta(days=14):
                    continue
            except Exception:
                pass

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


@app.route("/api/groww/holdings", methods=["GET"])
def fetch_groww_holdings():
    profile = _normalize_profile(request.args.get("profile"))
    p_upper = profile.upper()
    groww_token = (
        os.environ.get(f"GROWW_API_TOKEN_{p_upper}", "").strip()
        or os.environ.get(f"GROWW_ACCESS_TOKEN_{p_upper}", "").strip()
        or os.environ.get("GROWW_API_TOKEN", "").strip()
        or os.environ.get("GROWW_ACCESS_TOKEN", "").strip()
    )

    if not groww_token:
        return jsonify({
            "status": "error",
            "profile": profile,
            "broker": "groww",
            "error": f"Groww token not configured on Render for profile '{profile}'. Set GROWW_API_TOKEN_{p_upper}."
        }), 400

    groww_url = os.environ.get("GROWW_HOLDINGS_URL", "https://api.groww.in/v1/holdings/user").strip()
    try:
        g_resp = requests.get(
            groww_url,
            headers={
                "Authorization": f"Bearer {groww_token}",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "error", "profile": profile, "broker": "groww", "error": f"Could not reach Groww API: {e}"}), 502

    if g_resp.status_code != 200:
        return jsonify({
            "status": "error",
            "profile": profile,
            "broker": "groww",
            "error": f"Groww API returned HTTP {g_resp.status_code}",
            "groww_response": g_resp.text[:300],
        }), 400

    try:
        payload = g_resp.json()
    except ValueError:
        return jsonify({"status": "error", "profile": profile, "broker": "groww", "error": "Invalid JSON from Groww API"}), 502

    raw_items = (
        payload.get("holdings")
        or payload.get("data", {}).get("holdings")
        or (payload.get("data") if isinstance(payload.get("data"), list) else [])
        or []
    )
    simplified = []
    for h in raw_items:
        if not isinstance(h, dict):
            continue
        sym = (h.get("trading_symbol") or h.get("tradingsymbol") or h.get("symbol") or h.get("ticker") or "").strip().upper()
        if not sym:
            continue
        qty = float(h.get("quantity") or h.get("qty") or 0)
        avg = float(h.get("average_price") or h.get("avg_price") or h.get("avgPrice") or 0)
        ltp = float(h.get("last_price") or h.get("ltp") or 0)
        simplified.append({
            "ticker": sym,
            "company": h.get("company_name") or h.get("name") or sym,
            "quantity": qty,
            "average_price": avg,
            "last_price": ltp,
            "pnl": round((ltp - avg) * qty, 2) if ltp and avg else 0,
        })

    return jsonify({
        "status": "success",
        "profile": profile,
        "broker": "groww",
        "count": len(simplified),
        "holdings": simplified,
    })


@app.route("/api/kite/exchange", methods=["POST"])
def exchange_and_fetch_holdings():
    body = request.get_json(silent=True) or {}
    request_token = body.get("request_token", "").strip()
    if not request_token:
        return jsonify({"error": "request_token is required"}), 400

    profile_norm, active_key, active_secret = _resolve_kite_credentials(body.get("profile"))
    broker_name = (body.get("broker") or "kite").strip().lower()

    if not active_key or not active_secret:
        return jsonify({
            "error": f"Missing Kite API key / secret for profile '{profile_norm}'. Set KITE_API_KEY_{profile_norm.upper()} and KITE_API_SECRET_{profile_norm.upper()} on Render."
        }), 500

    logger.info(
        "Kite token exchange: profile=%s broker=%s key_prefix=%s secret_len=%d",
        profile_norm,
        broker_name,
        active_key[:6],
        len(active_secret),
    )

    checksum = hashlib.sha256((active_key + request_token + active_secret).encode("utf-8")).hexdigest()

    try:
        token_resp = requests.post(
            KITE_SESSION_TOKEN_URL,
            headers={"X-Kite-Version": "3"},
            data={"api_key": active_key, "request_token": request_token, "checksum": checksum},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Could not reach Kite: {e}"}), 502

    try:
        token_data = token_resp.json()
    except ValueError:
        return jsonify({"error": "Kite returned invalid JSON during exchange."}), 502

    if token_resp.status_code != 200 or token_data.get("status") != "success":
        logger.warning(
            "Kite token exchange rejected (%s) for profile=%s key_prefix=%s: %s",
            token_resp.status_code,
            profile_norm,
            active_key[:6],
            token_data,
        )
        return jsonify({
            "error": f"Kite rejected the token exchange (HTTP {token_resp.status_code}) for profile '{profile_norm}' using key '{active_key[:6]}...'. Verify this API key & secret belong to the Zerodha account logging in and have not expired.",
            "profile": profile_norm,
            "kite_response": token_data,
        }), 400

    access_token = token_data.get("data", {}).get("access_token")
    if not access_token:
        return jsonify({"error": "Missing access_token."}), 502

    profile_sessions[profile_norm] = {
        "access_token": access_token,
        "api_key": active_key,
        "updated_at": time.time(),
    }

    try:
        holdings_resp = requests.get(
            KITE_HOLDINGS_URL,
            headers={"X-Kite-Version": "3", "Authorization": f"token {active_key}:{access_token}"},
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
        "profile": profile_norm,
        "broker": broker_name,
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
