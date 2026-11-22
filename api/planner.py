"""GET /api/planner -> seasonal planner + question backlog (CDN-cached 6 h)."""
from http.server import BaseHTTPRequestHandler

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import send_json  # noqa: E402

import seasonal_planner  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        send_json(self, seasonal_planner.collect, 6 * 3600)
