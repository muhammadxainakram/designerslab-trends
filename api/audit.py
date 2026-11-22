"""GET /api/audit -> live SEO/AEO/GEO audit of designerslab.io (CDN-cached 12 h)."""
from http.server import BaseHTTPRequestHandler

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import send_json  # noqa: E402

import site_audit  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        send_json(self, site_audit.collect, 12 * 3600)
