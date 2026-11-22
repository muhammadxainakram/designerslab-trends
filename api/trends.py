"""Vercel serverless function: GET /api/trends -> live dashboard JSON.

Vercel's CDN caches the response for 30 minutes (s-maxage), so the sources are
hit at most about twice an hour no matter how often the page is opened.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

os.environ["TREND_LIVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_trends  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = fetch_trends.collect(fetch_trends.empty_history())
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            status = 200
            cache = "public, max-age=0, s-maxage=1800, stale-while-revalidate=3600"
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"error": str(e)[:300]}).encode("utf-8")
            status, cache = 500, "no-store"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", cache)
        self.send_header("CDN-Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
