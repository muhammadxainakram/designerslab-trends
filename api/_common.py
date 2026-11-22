"""Shared JSON response helper for the Vercel functions (files starting with _ are not routes)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def send_json(handler, fn, s_maxage: int):
    try:
        body = json.dumps(fn(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        status, cache = 200, f"public, max-age=0, s-maxage={s_maxage}, stale-while-revalidate={s_maxage * 2}"
    except Exception as e:  # noqa: BLE001
        body = json.dumps({"error": str(e)[:300]}).encode("utf-8")
        status, cache = 500, "no-store"
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", cache)
    handler.send_header("CDN-Cache-Control", cache)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
