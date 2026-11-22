"""Vercel serverless function: GET /api/trends?hours=4|24|48|168 -> live dashboard JSON.

Vercel's CDN caches each window for 15 minutes (s-maxage), then serves the
cached copy while it refreshes in the background.
"""
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_trends  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            hours = int(qs.get("hours", ["4"])[0])
        except ValueError:
            hours = 4
        try:
            payload = fetch_trends.collect(hours)
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            status = 200
            cache = "public, max-age=0, s-maxage=900, stale-while-revalidate=1800"
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
