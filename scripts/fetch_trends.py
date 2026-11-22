#!/usr/bin/env python3
"""
DesignersLab Trend Finder - data collector (real data only).

Nothing here is estimated or invented. Every number shown on the dashboard
comes straight from the source:

  * Google Trends "Trending now" (trends.google.com/trending) - the same table
    Google shows: search volume since the trend started, % increase, start time,
    active/ended, Google's own category, and the real related queries
    ("trend breakdown"). Scanned for many countries, then kept only when the
    trend title or one of Google's related queries contains a design term.
  * Google News RSS - design news headlines with the exact publish time.
  * Reddit - posts from design subreddits with real upvotes and comments
    (needs free API keys; Reddit blocks anonymous server requests).
  * designerslab.io sitemap - to flag topics the site already covers.

Standard library only.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA_DIR = ROOT / "docs" / "data"

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
BOT_UA = "designerslab-trend-finder/2.0 (personal keyword research dashboard)"

# Google Trends "Trending now" only offers these windows.
WINDOWS = (4, 24, 48, 168)

# Google's own Trending-now category ids.
GOOGLE_CATEGORIES = {
    1: "Autos & Vehicles", 2: "Beauty & Fashion", 3: "Business & Finance", 4: "Entertainment",
    5: "Food & Drink", 6: "Games", 7: "Health", 8: "Hobbies & Leisure", 9: "Jobs & Education",
    10: "Law & Government", 11: "Other", 13: "Pets & Animals", 14: "Politics", 15: "Science",
    16: "Shopping", 17: "Sports", 18: "Technology", 19: "Travel & Transportation", 20: "Climate",
}

STATUS: dict[str, dict] = {}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_get(url: str, headers: dict | None = None, timeout: int = 25, retries: int = 1,
             data: bytes | None = None) -> str:
    h = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h, data=data),
                                        timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            if getattr(e, "code", None) in (403, 404):
                break
            time.sleep(0.7 * (attempt + 1))
    raise last  # type: ignore[misc]


def iso_ts(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rfc822_ts(s: str | None) -> float | None:
    try:
        return parsedate_to_datetime(s).timestamp() if s else None
    except Exception:  # noqa: BLE001
        return None


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# --------------------------------------------------------------------------- design matching
_TERM_GROUP: list[tuple[re.Pattern, str, str]] = []
for _group, _terms in CONFIG["design_terms"].items():
    for _t in sorted(_terms, key=len, reverse=True):
        _TERM_GROUP.append((re.compile(r"(?<![\w-])" + re.escape(_t) + r"(?![\w-])", re.I), _t, _group))

# Design words that are also common team names or everyday words.
WEAK_TERMS = {"poster", "posters", "flyer", "flyers", "doodle", "png", "illustration", "template",
              "templates", "vector", "sticker", "stickers", "thumbnail"}


def design_match(title: str, queries: list[str], categories: list[int]) -> dict | None:
    """Return the real evidence for a design match, or None.

    The match must be in the trend title or in one of Google's own related
    queries. Weak words (e.g. 'flyers') don't count for Sports trends."""
    hits = []
    for source, text in [("title", title)] + [("related", q) for q in queries]:
        for rx, term, group in _TERM_GROUP:
            if rx.search(text):
                hits.append({"in": source, "query": text, "term": term, "group": group})
                break
    if not hits:
        return None
    strong = [h for h in hits if h["term"].lower() not in WEAK_TERMS]
    if 17 in categories and not strong:
        return None
    best = next((h for h in hits if h["in"] == "title"), None) or (strong or hits)[0]
    return {
        "term": best["term"],
        "group": best["group"],
        "in": best["in"],
        "query": best["query"],
        "matching_queries": [h["query"] for h in hits if h["in"] == "related"][:12],
        "match_count": len(hits),
    }


# --------------------------------------------------------------------------- site coverage
STOP = set("a an and the of for to in on with free best how what is are vs your you my top new "
           "download 2024 2025 2026 2027 guide".split())


def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def load_site_posts() -> list[dict]:
    posts = []
    for sm in CONFIG["site"]["sitemaps"]:
        try:
            for loc in re.findall(r"<loc>(.*?)</loc>", http_get(sm)):
                if "/wp-content/" in loc or loc.rstrip("/") == CONFIG["site"]["url"].rstrip("/"):
                    continue
                slug = loc.rstrip("/").rsplit("/", 1)[-1]
                posts.append({"url": loc, "tokens": tokens(slug.replace("-", " "))})
        except Exception as e:  # noqa: BLE001
            log("sitemap failed", sm, e)
    STATUS["site"] = {"ok": bool(posts), "posts": len(posts)}
    return posts


def coverage(term: str, posts: list[dict]) -> str | None:
    tk = tokens(term)
    if not tk:
        return None
    best, ratio = None, 0.0
    for p in posts:
        r = len(tk & p["tokens"]) / len(tk)
        if r > ratio:
            best, ratio = p, r
    return best["url"] if best and ratio >= 0.67 else None


# --------------------------------------------------------------------------- Google Trends
DS0 = re.compile(r"AF_initDataCallback\(\{key: 'ds:0', hash: '\d+', data:(.*?), sideChannel: \{\}\}\);</script>",
                 re.S)


def fetch_trending_now(geo: str, hours: int) -> list[list]:
    """The exact rows Google renders on trends.google.com/trending."""
    html = http_get(f"https://trends.google.com/trending?geo={geo}&hours={hours}&hl=en-US")
    m = DS0.search(html)
    if not m:
        raise ValueError("trending data not found in page")
    return json.loads(m.group(1))[1] or []


def google_trends(hours: int, posts: list[dict]) -> tuple[list[dict], list[dict], dict]:
    geos = CONFIG["countries"]

    def safe(geo):
        try:
            return geo, fetch_trending_now(geo, hours), None
        except Exception as e:  # noqa: BLE001
            log("trending failed", geo, e)
            return geo, None, str(e)[:120]

    with ThreadPoolExecutor(max_workers=len(geos)) as ex:
        results = list(ex.map(safe, geos))

    design, others = [], []
    scanned = {"total": 0, "by_country": {}, "failed": []}
    for geo, rows, _err in results:
        if rows is None:
            scanned["failed"].append(geo)
            continue
        scanned["by_country"][geo] = len(rows)
        scanned["total"] += len(rows)
        for r in rows:
            try:
                title = r[0]
                start = (r[3] or [None])[0]
                end = (r[4] or [None])[0] if r[4] else None
                volume = int(r[6] or 0)
                increase = r[8]
                queries = [q for q in (r[9] or []) if isinstance(q, str)]
                cats = [c for c in (r[10] or []) if isinstance(c, int)]
            except (IndexError, TypeError, ValueError):
                continue
            match = design_match(title, queries, cats)
            item = {
                "id": f"gt-{geo}-{slugify(title)}",
                "keyword": title,
                "country": geo,
                "searches": volume,
                "increase_pct": increase,
                "started_at": iso_ts(start),
                "ended_at": iso_ts(end),
                "active": end is None,
                "google_categories": [GOOGLE_CATEGORIES.get(c, str(c)) for c in cats],
                "related_queries": queries[:25],
                "related_count": len(queries),
                "design": match,
            }
            if match:
                item["covered"] = coverage(title, posts)
                design.append(item)
            elif volume >= 1000:
                others.append(item)

    design.sort(key=lambda x: x["searches"], reverse=True)
    others.sort(key=lambda x: x["searches"], reverse=True)
    STATUS["google_trends"] = {"ok": bool(scanned["by_country"]), "countries_ok": len(scanned["by_country"]),
                               "countries": len(geos), "failed": scanned["failed"]}
    return design, others[:250], scanned


# --------------------------------------------------------------------------- Google News
def google_news(hours: int, posts: list[dict]) -> list[dict]:
    when = "1d" if hours <= 24 else ("2d" if hours <= 48 else "7d")

    def one(q):
        url = ("https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
               + urllib.parse.quote(f"{q} when:{when}"))
        try:
            root = ET.fromstring(http_get(url))
        except Exception as e:  # noqa: BLE001
            log("news failed", q, e)
            return None
        rows = []
        for it in root.iter("item"):
            src = it.find("source")
            rows.append({"q": q, "title": unescape(it.findtext("title") or ""), "url": it.findtext("link") or "",
                         "ts": rfc822_ts(it.findtext("pubDate")), "source": src.text if src is not None else ""})
        return rows

    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(one, CONFIG["news_queries"]))
    STATUS["google_news"] = {"ok": any(r is not None for r in res),
                             "queries_ok": sum(r is not None for r in res), "queries": len(res)}
    cutoff = time.time() - hours * 3600
    seen, out = set(), []
    for rows in res:
        for r in rows or []:
            title = re.sub(r"\s+-\s+[^-]+$", "", r["title"]).strip()
            key = slugify(title)[:90]
            if not title or key in seen or not r["ts"] or r["ts"] < cutoff:
                continue
            match = design_match(title, [], [])
            if not match:
                continue
            seen.add(key)
            out.append({"id": "gn-" + key, "headline": title, "url": r["url"], "publisher": r["source"],
                        "published_at": iso_ts(r["ts"]), "search_query": r["q"], "design": match,
                        "covered": coverage(title, posts)})
    out.sort(key=lambda x: x["published_at"], reverse=True)
    return out


# --------------------------------------------------------------------------- Reddit
ATOM = "{http://www.w3.org/2005/Atom}"


def reddit_token() -> str | None:
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not sec:
        return None
    try:
        auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        body = http_get("https://www.reddit.com/api/v1/access_token",
                        headers={"Authorization": f"Basic {auth}", "User-Agent": BOT_UA,
                                 "Content-Type": "application/x-www-form-urlencoded"},
                        data=b"grant_type=client_credentials", retries=0)
        return json.loads(body).get("access_token")
    except Exception as e:  # noqa: BLE001
        log("reddit auth failed", e)
        return None


def reddit_sub(sub: str, token: str | None) -> list[dict] | None:
    try:
        if token:
            body = http_get(f"https://oauth.reddit.com/r/{sub}/new?limit=100&raw_json=1",
                            headers={"Authorization": f"Bearer {token}", "User-Agent": BOT_UA}, retries=0)
            out = []
            for c in json.loads(body)["data"]["children"]:
                d = c["data"]
                if d.get("stickied"):
                    continue
                out.append({"id": d["id"], "title": d["title"], "sub": sub,
                            "url": "https://www.reddit.com" + d["permalink"], "ts": d["created_utc"],
                            "upvotes": d.get("score", 0), "comments": d.get("num_comments", 0)})
            return out
        xml = http_get(f"https://www.reddit.com/r/{sub}/new/.rss?limit=100", headers={"User-Agent": BOT_UA},
                       retries=0)
        out = []
        for e in ET.fromstring(xml).findall(f"{ATOM}entry"):
            link = e.find(f"{ATOM}link")
            pub = e.findtext(f"{ATOM}published") or ""
            ts = datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp() if pub else None
            out.append({"id": (e.findtext(f"{ATOM}id") or "").split("_")[-1],
                        "title": unescape(e.findtext(f"{ATOM}title") or ""), "sub": sub,
                        "url": link.get("href") if link is not None else "", "ts": ts,
                        "upvotes": None, "comments": None})
        return out
    except Exception as e:  # noqa: BLE001
        log("reddit failed", sub, getattr(e, "code", e))
        return None


def reddit(hours: int, posts: list[dict]) -> list[dict]:
    token = reddit_token()
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda s: reddit_sub(s, token), CONFIG["subreddits"]))
    ok = sum(r is not None for r in res)
    STATUS["reddit"] = {"ok": ok > 0, "subs_ok": ok, "subs": len(res), "mode": "api" if token else "anonymous",
                        "needs_keys": not token}
    cutoff = time.time() - hours * 3600
    out = []
    for rows in res:
        for p in rows or []:
            if not p["ts"] or p["ts"] < cutoff:
                continue
            age_h = max((time.time() - p["ts"]) / 3600, 0.25)
            out.append({"id": f"rd-{p['sub']}-{p['id']}", "title": p["title"], "url": p["url"],
                        "subreddit": p["sub"], "posted_at": iso_ts(p["ts"]), "upvotes": p["upvotes"],
                        "comments": p["comments"],
                        "upvotes_per_hour": round(p["upvotes"] / age_h, 1) if p["upvotes"] is not None else None,
                        "covered": coverage(p["title"], posts)})
    out.sort(key=lambda x: (x["upvotes"] or 0) + 2 * (x["comments"] or 0), reverse=True)
    return out


# --------------------------------------------------------------------------- main
def collect(hours: int = 4) -> dict:
    if hours not in WINDOWS:
        hours = min(WINDOWS, key=lambda w: abs(w - hours))
    STATUS.clear()
    t0 = time.time()
    posts = load_site_posts()
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_gt = ex.submit(google_trends, hours, posts)
        f_news = ex.submit(google_news, hours, posts)
        f_rd = ex.submit(reddit, hours, posts)
        design, others, scanned = f_gt.result()
        news = f_news.result()
        rd = f_rd.result()
    log(f"collected {hours}h in {time.time() - t0:.1f}s: {len(design)} design trends "
        f"(of {scanned['total']} scanned), {len(news)} news, {len(rd)} reddit")
    return {
        "generated_at": iso_ts(time.time()),
        "window_hours": hours,
        "countries": CONFIG["countries"],
        "site": {"url": CONFIG["site"]["url"], "posts": len(posts)},
        "status": STATUS,
        "scanned": scanned,
        "google_trends": design,
        "google_trends_other": others,
        "google_news": news,
        "reddit": rd,
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for h in WINDOWS:
        out = collect(h)
        (DATA_DIR / f"trends-{h}h.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                                                     encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
