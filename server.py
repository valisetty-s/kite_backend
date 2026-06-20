"""
server.py — The Morning Ledger's minimal Kite backend

Does exactly two things, and nothing else:
  1. POST /api/kite/exchange  — takes a request_token, exchanges it for an
     access_token using your api_secret (which lives ONLY here, as an
     environment variable — never sent to or stored in the browser), then
     immediately uses that access_token to fetch your holdings and returns
     them to the app. The access_token itself is never sent back to the
     browser, by design — it's used once, server-side, then discarded from
     memory when the request finishes. Nothing is written to disk.
  2. GET /healthz — a trivial endpoint so the hosting platform (Render/
     Railway) can confirm the service is alive.

There is no database, no session storage, no logging of tokens or secrets.
Every request is independent and stateless.
"""

import hashlib
import os

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allow the PWA (hosted on a different domain) to call this API

KITE_API_KEY = os.environ.get("KITE_API_KEY", "")
KITE_API_SECRET = os.environ.get("KITE_API_SECRET", "")

KITE_SESSION_TOKEN_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


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
