"""GET /api/trends?hours=4|24|48|168 -> real Google Trends / News / Reddit data (CDN-cached 15 min)."""
import urllib.parse
from http.server import BaseHTTPRequestHandler

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import send_json  # noqa: E402  (also puts scripts/ on sys.path)

import fetch_trends  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            hours = int(qs.get("hours", ["4"])[0])
        except ValueError:
            hours = 4
        send_json(self, lambda: fetch_trends.collect(hours), 900)
