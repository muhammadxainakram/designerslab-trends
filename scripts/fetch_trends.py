#!/usr/bin/env python3
"""
DesignersLab Trend Finder - data collector.

Pulls free, public trend signals and scores them as article opportunities
for designerslab.io:

  * Google Trends  - "Trending now" RSS per country (real trending searches)
  * Google Search  - Autocomplete suggestions for niche seed keywords
  * Google News    - fresh news (last 24h) for design-related queries
  * Reddit         - hot posts from design subreddits (RSS, or the free
                     Reddit API when REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are set)

It keeps a small history file so it can tell how long something has been
trending ("trending for 2h 15m") and which Google suggestions are new.

Standard library only - no pip install needed.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA_DIR = ROOT / "docs" / "data"
TRENDS_FILE = DATA_DIR / "trends.json"
HISTORY_FILE = DATA_DIR / "history.json"

NOW = datetime.now(timezone.utc)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
BOT_UA = "designerslab-trend-finder/1.0 (personal keyword research dashboard)"
HISTORY_KEEP_HOURS = 72

STATUS: dict[str, dict] = {}
# LIVE mode = running as an on-demand web function (Vercel): no history file,
# everything in parallel with short timeouts so a full refresh takes ~15-25s.
LIVE = os.environ.get("TREND_LIVE") == "1"


# --------------------------------------------------------------------------- utils
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_get(url: str, headers: dict | None = None, timeout: int = 20, retries: int = 2,
             data: bytes | None = None) -> str:
    if LIVE:
        timeout, retries = min(timeout, 8), min(retries, 1)
    h = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
            code = getattr(e, "code", None)
            if code in (403, 404):
                break
            time.sleep(0.5 if LIVE else 1.5 * (attempt + 1) + (3 if code == 429 else 0))
    raise last  # type: ignore[misc]


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_rfc822(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def hours_since(dt: datetime | None) -> float | None:
    return None if dt is None else max(0.0, (NOW - dt).total_seconds() / 3600)


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(s or ""))).strip()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


ACRONYMS = {"psd", "svg", "ai", "ui", "ux", "png", "pdf", "3d", "cmyk", "rgb", "diy", "usa", "uk",
             "nfl", "nba", "mlb", "ufc", "wwe", "gta", "tv", "ios", "eps", "jpg", "gif", "css", "html",
             "dtf", "dtg", "sdxl", "f1", "ipl", "nyc", "la", "fc", "cf", "afc", "vi", "ii", "iii"}


def title_case(s: str) -> str:
    small = {"a", "an", "and", "of", "for", "the", "in", "on", "to", "vs", "or", "with"}
    words = s.split()
    out = []
    for i, w in enumerate(words):
        if w.lower() in ACRONYMS:
            out.append(w.upper())
        elif w.lower() in ("iphone", "ipad", "imac", "macbook"):
            out.append({"iphone": "iPhone", "ipad": "iPad", "imac": "iMac", "macbook": "MacBook"}[w.lower()])
        elif w.isupper() and len(w) > 1:
            out.append(w)
        elif i and w.lower() in small:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def parse_traffic(label: str | None) -> int:
    if not label:
        return 0
    m = re.match(r"([\d.,]+)\s*([KkMm]?)", label.strip())
    if not m:
        return 0
    n = float(m.group(1).replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(n * mult)


# --------------------------------------------------------------------------- niche scoring
NICHE: list[tuple[re.Pattern, int, str]] = []
for weight, terms in CONFIG["niche_terms"].items():
    for t in terms:
        NICHE.append((re.compile(r"\b" + re.escape(t) + r"\b", re.I), int(weight), t))

HOLIDAY_NAMES = [h["name"] for h in CONFIG["holidays"]] + [
    "Halloween", "Christmas", "Xmas", "Hanukkah", "Kwanzaa", "Diwali", "Holi", "Eid",
    "Ramadan", "Lunar New Year", "Chinese New Year", "Memorial Day", "Labor Day",
    "Veterans Day", "Juneteenth", "Earth Day", "Pride", "Black History Month",
    "Women's Day", "Super Bowl", "Oscars", "Grammys", "Met Gala"]
HOLIDAY_RE = re.compile(r"\b(" + "|".join(re.escape(h) for h in HOLIDAY_NAMES) + r")\b", re.I)
DEVICE_RE = re.compile(r"\b(iphone\s?\d*\s?(pro|max|air|plus)?|ipad\s?\w*|macbook\s?\w*|imac|"
                       r"apple watch\s?\w*|vision pro|galaxy\s?[sz]\d+\w*|pixel\s?\d+\w*|"
                       r"airpods\s?\w*|switch 2|ps5\s?\w*|xbox\s?\w*|steam deck)\b", re.I)
TOOL_RE = re.compile(r"\b(photoshop|illustrator|indesign|lightroom|premiere|after effects|"
                     r"firefly|canva|figma|affinity|procreate|midjourney|dall-?e|chatgpt|"
                     r"gemini|nano banana|imagen|sora|veo|stable diffusion|flux|ideogram|"
                     r"krea|leonardo ai|framer|webflow|blender|coreldraw|gimp|inkscape)\b", re.I)
LOGO_RE = re.compile(r"\b(new logo|logo|rebrand\w*|brand identity|redesign\w*|wordmark)\b", re.I)
FONT_RE = re.compile(r"\b(fonts?|typefaces?|typography|lettering)\b", re.I)
SPORTS_RE = re.compile(r"\b(vs\.?|nfl|nba|mlb|nhl|mls|ncaa|ufc|wwe|premier league|"
                       r"champions league|la liga|serie a|bundesliga|ipl|cricket|world cup|"
                       r"playoffs?|super bowl|grand prix|f1|football|basketball|baseball|"
                       r"soccer|match|game score|tournament|bowl game|fc|cf|afc|darts|standings|"
                       r"golf|tennis|grand slam|league|cup|race)\b", re.I)
ENT_RE = re.compile(r"\b(movie|film|trailer|box office|season \d+|netflix|disney\+?|hbo|"
                    r"prime video|hulu|marvel|dc studios|pixar|album|world tour|concert|"
                    r"premiere|anime|manga|video game|gta( vi| 6)?|nintendo|playstation|"
                    r"esports|tv series)\b", re.I)


def niche_score(text: str, context: str = "") -> tuple[int, list[str]]:
    """0-100 relevance to a design-resources site. Matches in the keyword
    itself count double compared to matches in the surrounding context."""
    hits, score = [], 0
    for rx, w, t in NICHE:
        if rx.search(text):
            score += w * 2
            hits.append(t)
        elif context and rx.search(context):
            score += w * 0.6
            hits.append(t)
    return min(100, int(round(score * 9))), sorted(set(hits))


def classify(term: str, context: str = "") -> str:
    blob = f"{term} {context}"
    if FONT_RE.search(term):
        return "fonts"
    if HOLIDAY_RE.search(term):
        return "seasonal"
    if DEVICE_RE.search(term):
        return "device"
    if re.search(r"\bmockups?\b|\bpsd\b|\btemplates?\b|\bsvg\b|\bclipart\b|\btextures?\b|\bbrush(es)?\b",
                 term, re.I):
        return "resources"
    if re.search(r"\bprompts?\b", term, re.I):
        return "ai-prompts"
    if TOOL_RE.search(term) or TOOL_RE.search(context[:300]):
        return "design-tool"
    if LOGO_RE.search(blob):
        return "logo-brand"
    if SPORTS_RE.search(blob):
        return "sports"
    if ENT_RE.search(blob):
        return "entertainment"
    return "general"


def query_ideas(q: str, category: str) -> list[str]:
    """Ideas for a real Google search query: keep the query, shape it into a title."""
    yr = NOW.year + (1 if NOW.month == 12 else 0)
    q = re.sub(r"\s+", " ", q.strip())
    t = title_case(q)
    low = q.lower()
    ideas: list[str] = []
    m = re.match(r"(what|which) font (is|does|for|used)\s*(.*)", low)
    if m:
        subj = title_case(re.sub(r"^(the|used in|used for|use)\s+", "", m.group(3)))
        ideas += [f"What Font Is {subj}? (+ Free Alternatives)" if subj else f"{t}? Answered",
                  f"{subj or t} Font: Free Download & Closest Matches"]
    elif low.startswith(("how to", "how do")):
        ideas += [f"{t} (Step-by-Step Guide, {yr})", f"{t}: Beginner Tutorial with Free Files"]
    elif " vs " in low:
        ideas += [f"{t}: Which Should Designers Use in {yr}?", f"{t} - Honest Comparison"]
    elif low.startswith("best "):
        ideas += [f"10 {t} in {yr} (Free & Paid)", f"{t} - Tested and Ranked"]
    elif re.search(r"\b(fonts?|typefaces?)\b", low):
        ideas += [f"15 {t} (Free Download, {yr})", f"{t}: Free & Commercial-Use Picks"]
    elif re.search(r"\bprompts?\b", low):
        ideas += [f"25 {t} (Copy & Paste)", f"{t}: Best Examples and Results"]
    elif category == "resources" or re.search(
            r"\b(mockups?|psd|templates?|svg|clipart|textures?|brushes|graphics)\b", low):
        core = re.sub(r"(?i)\bfree\b\s*", "", t).strip()
        ideas += [f"20 Free {core} ({yr})", f"{core}: Free Download + How to Use It"]
    else:
        ideas += [f"{t}: Complete Guide for Designers ({yr})", f"{t} - Free Resources & Examples"]
    return ideas


def article_ideas(term: str, category: str, context: str = "", kind: str = "trend") -> list[str]:
    """Concrete, SEO-shaped article titles that fit designerslab.io.
    kind: 'trend' (a short trending search), 'query' (a Google suggestion),
          'headline' (news headline or Reddit post title)."""
    t = title_case(term.strip())
    yr = NOW.year + (1 if NOW.month == 12 and category != "seasonal" else 0)
    if kind == "query":
        return query_ideas(term, category)
    if kind == "headline":
        ideas = []
        h, d, tool = HOLIDAY_RE.search(term), DEVICE_RE.search(term), TOOL_RE.search(term)
        if h:
            hol = title_case(h.group(1))
            ideas += [f"Free {hol} Fonts & Templates for Designers ({yr})"]
        if d:
            ideas += [f"Free {title_case(d.group(0))} Mockup (PSD) - Download"]
        if tool:
            ideas += [f"{title_case(tool.group(0))}: What's New and How Designers Can Use It"]
        if LOGO_RE.search(term):
            ideas += ["Logo redesign breakdown: what changed, the font used, free alternatives"]
        if FONT_RE.search(term):
            ideas += ["Font spotlight: identify the typeface + list free alternatives"]
        ideas += [f"Designer's take: {short_topic(term)}"]
        return ideas[:3]
    if category == "fonts":
        return [f"{t}: Best Free Options ({yr})", f"{t} - Free Download & Commercial Use Guide",
                f"Top 10 Free Alternatives for {t}"]
    if category == "seasonal":
        h = HOLIDAY_RE.search(term)
        hol = title_case(h.group(1)) if h else t
        return [f"Free {hol} Fonts for Posters, Cards & Social Posts ({yr})",
                f"{hol} Social Media & Flyer Templates (Free PSD)",
                f"Free {hol} Mockups for Branding & Promotions",
                f"AI Image Prompts for {hol} Ad Posters (Copy & Paste)"]
    if category == "device":
        d = DEVICE_RE.search(term)
        dev = title_case(d.group(0)) if d else t
        return [f"Free {dev} Mockup (PSD) - Download", f"{dev} Mockup Templates for App & UI Designers",
                f"{dev} Wallpapers: Free Download + How to Design Your Own"]
    if category == "design-tool":
        return [f"{t}: What Designers Need to Know", f"How to Use {t} for Graphic Design (Step by Step)",
                f"{t} - Best Free Resources, Templates & Prompts"]
    if category == "logo-brand":
        return [f"{t} New Logo: Design Breakdown & Font Used", f"What Font Is the {t} Logo? (+ Free Alternatives)",
                f"{t} Rebrand: What Designers Can Learn"]
    if category == "resources":
        return [f"{t}: Free Download Collection ({yr})", f"Best {t} for Designers - Free & Commercial Use",
                f"How to Use {t} in Photoshop & Canva"]
    if category == "sports":
        return [f"{t} Font: Jersey & Logo Typeface Explained", f"Free Sports Fonts Inspired by {t}",
                f"Game Day Flyer & Social Templates: {t}"]
    if category == "entertainment":
        return [f"What Font Is Used in {t}? (Poster & Logo Font)", f"{t} Font - Free Download & Alternatives",
                f"{t}-Inspired Poster: AI Prompts + Free PSD Template"]
    return [f"{t}: Social Media Post Templates (Free)", f"AI Image Prompts Inspired by {t}",
            f"What Font Is Used for {t}?"]


# --------------------------------------------------------------------------- site coverage
STOP = set("a an and the of for to in on with free best how what is are vs your you my top new "
           "download 2024 2025 2026 2027 guide".split())


def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


def load_site_posts() -> list[dict]:
    posts = []
    for sm in CONFIG["site"]["sitemaps"]:
        try:
            xml = http_get(sm)
            for loc in re.findall(r"<loc>(.*?)</loc>", xml):
                if "/wp-content/" in loc or loc.rstrip("/") == CONFIG["site"]["url"].rstrip("/"):
                    continue
                slug = loc.rstrip("/").rsplit("/", 1)[-1]
                posts.append({"url": loc, "slug": slug, "tokens": tokens(slug.replace("-", " "))})
        except Exception as e:  # noqa: BLE001
            log("sitemap failed", sm, e)
    STATUS["site"] = {"ok": bool(posts), "count": len(posts)}
    return posts


def coverage(term: str, posts: list[dict]) -> dict | None:
    tk = tokens(term)
    if not tk:
        return None
    best, best_ratio = None, 0.0
    for p in posts:
        ratio = len(tk & p["tokens"]) / len(tk)
        if ratio > best_ratio:
            best, best_ratio = p, ratio
    if best and best_ratio >= 0.67:
        return {"url": best["url"], "match": round(best_ratio, 2)}
    return None


# --------------------------------------------------------------------------- history
def load_history() -> dict:
    try:
        h = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        h = {}
    h.setdefault("trends", {})
    h.setdefault("suggest", {})
    h.setdefault("reddit", {})
    h.setdefault("runs", [])
    return h


def prune_history(h: dict) -> None:
    cutoff = NOW - timedelta(hours=HISTORY_KEEP_HOURS)
    h["trends"] = {k: v for k, v in h["trends"].items()
                   if (parse_iso(v.get("last_seen")) or NOW) >= cutoff}
    # suggestions: keep 14 days so "new" means genuinely new
    s_cut = NOW - timedelta(days=14)
    h["suggest"] = {k: v for k, v in h["suggest"].items()
                    if (parse_iso(v.get("last_seen")) or NOW) >= s_cut}
    h["reddit"] = {k: v for k, v in h["reddit"].items()
                   if (parse_iso(v.get("last_seen")) or NOW) >= cutoff}
    h["runs"] = h["runs"][-200:]


# --------------------------------------------------------------------------- Google Trends
HT = "{https://trends.google.com/trending/rss}"


def fetch_google_trends(geo: str) -> list[dict]:
    xml = http_get(f"https://trends.google.com/trending/rss?geo={geo}")
    root = ET.fromstring(xml)
    out = []
    for it in root.iter("item"):
        news = []
        for n in it.findall(f"{HT}news_item"):
            news.append({
                "title": unescape(n.findtext(f"{HT}news_item_title") or ""),
                "url": n.findtext(f"{HT}news_item_url") or "",
                "source": n.findtext(f"{HT}news_item_source") or "",
            })
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "traffic_label": it.findtext(f"{HT}approx_traffic") or "",
            "pub": parse_rfc822(it.findtext("pubDate")),
            "picture": it.findtext(f"{HT}picture") or "",
            "news": news,
        })
    return out


def google_trends_items(hist: dict, posts: list[dict]) -> list[dict]:
    items, seen_keys, ok = [], set(), 0

    def safe(geo):
        try:
            return geo, fetch_google_trends(geo)
        except Exception as e:  # noqa: BLE001
            log("trends failed", geo, e)
            return geo, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        fetched = list(ex.map(safe, CONFIG["google_trends_geos"]))
    for geo, rows in fetched:
        if rows is None:
            continue
        ok += 1
        for r in rows:
            if not r["title"]:
                continue
            key = f"{geo}|{r['title'].lower()}"
            seen_keys.add(key)
            traffic = parse_traffic(r["traffic_label"])
            h = hist["trends"].get(key)
            if not h:
                start = r["pub"] or NOW
                h = {"first_seen": iso(NOW), "started": iso(min(start, NOW)), "peak": traffic,
                     "title": r["title"], "geo": geo}
            h["last_seen"] = iso(NOW)
            h["peak"] = max(h.get("peak", 0), traffic)
            h["traffic_label"] = r["traffic_label"]
            h["news"] = r["news"][:3]
            h["picture"] = r["picture"]
            hist["trends"][key] = h
    STATUS["google_trends"] = {"ok": ok > 0, "geos_ok": ok, "geos": len(CONFIG["google_trends_geos"])}

    # Build items from history (active + ended within the last 24h)
    for key, h in hist["trends"].items():
        last = parse_iso(h.get("last_seen"))
        active = key in seen_keys
        if not active and (hours_since(last) or 99) > 24:
            continue
        started = parse_iso(h.get("started")) or parse_iso(h.get("first_seen")) or NOW
        end = NOW if active else (last or NOW)
        dur_h = max(0.0, (end - started).total_seconds() / 3600)
        ctx = " ".join(n["title"] for n in h.get("news", []))
        rel, hits = niche_score(h["title"], ctx)
        cat = classify(h["title"], ctx)
        if cat in ("seasonal", "device", "design-tool", "logo-brand", "fonts", "resources"):
            rel = max(rel, 55)
        elif cat == "entertainment":
            rel = max(rel, 30)   # "what font is used in X" angle
        elif cat == "sports":
            rel = max(rel, 18)
        peak = h.get("peak", 0)
        momentum = min(100, int(math.log10(max(peak, 10)) / math.log10(2_000_000) * 100))
        age_h = hours_since(started) or 0
        freshness = int(max(0, 100 - age_h * 6))
        score = int(0.55 * rel + 0.25 * momentum + 0.20 * freshness * (1 if active else 0.4))
        cov = coverage(h["title"], posts)
        if cov:
            score = max(0, score - 15)
        items.append({
            "id": "gt-" + slugify(key),
            "source": "google_trends",
            "keyword": h["title"],
            "title": h["title"],
            "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(h['title'])}",
            "trends_url": f"https://trends.google.com/trends/explore?date=now%201-d&geo={h['geo']}&q={urllib.parse.quote_plus(h['title'])}",
            "geo": h["geo"],
            "started_at": iso(started),
            "last_seen": h.get("last_seen"),
            "active": active,
            "duration_h": round(dur_h, 2),
            "traffic": peak,
            "traffic_label": h.get("traffic_label", ""),
            "picture": h.get("picture", ""),
            "news": h.get("news", []),
            "category": cat,
            "relevance": rel,
            "niche_hits": hits,
            "score": score,
            "ideas": article_ideas(h["title"], cat, ctx),
            "covered": cov,
        })
    return items


# --------------------------------------------------------------------------- Google Autocomplete
def upcoming_holidays() -> list[str]:
    out = []
    today = NOW.date()
    for hday in CONFIG["holidays"]:
        for yr in (today.year, today.year + 1):
            try:
                d = date(yr, hday["month"], hday["day"])
            except ValueError:
                continue
            if 0 <= (d - today).days <= CONFIG["holiday_lookahead_days"]:
                out.append(hday["name"])
                break
    return out


def suggest(q: str) -> list[str]:
    url = ("https://suggestqueries.google.com/complete/search?client=firefox&hl=en&gl=us&q="
           + urllib.parse.quote(q))
    try:
        data = json.loads(http_get(url, retries=1))
        return [s for s in data[1] if isinstance(s, str)]
    except Exception:  # noqa: BLE001
        return []


def google_suggest_items(hist: dict, posts: list[dict]) -> list[dict]:
    queries = []
    for s in CONFIG["suggest_seeds"]:
        for m in (CONFIG.get("suggest_modifiers_live") if LIVE else None) or CONFIG["suggest_modifiers"]:
            m = m.replace("{year}", str(NOW.year)).replace("{next_year}", str(NOW.year + 1))
            queries.append((s, (s + m).strip()))
    hol = upcoming_holidays()
    for h in hol:
        for tail in (" fonts", " templates", " mockup", " flyer", " ai prompt", " svg", " poster"):
            queries.append((f"{h.lower()} (upcoming)", h.lower() + tail))

    with ThreadPoolExecutor(max_workers=16 if LIVE else 4) as ex:
        results = list(ex.map(lambda q: (q[0], q[1], suggest(q[1])), queries))

    ok = sum(1 for _, _, r in results if r)
    STATUS["google_suggest"] = {"ok": ok > 0, "queries_ok": ok, "queries": len(queries),
                                "upcoming_holidays": hol}

    agg: dict[str, dict] = {}
    for seed, q, sugg in results:
        for rank, s in enumerate(sugg):
            s_norm = s.strip().lower()
            if s_norm == q.lower() or len(s_norm) < 4:
                continue
            a = agg.setdefault(s_norm, {"seed": seed, "queries": set(), "best_rank": rank})
            a["queries"].add(q)
            a["best_rank"] = min(a["best_rank"], rank)

    items = []
    for s, a in agg.items():
        h = hist["suggest"].get(s)
        if not h:
            # on the very first run nothing counts as "new"
            h = {"first_seen": iso(NOW), "new": bool(hist["runs"])}
        h["last_seen"] = iso(NOW)
        hist["suggest"][s] = h
        first = parse_iso(h["first_seen"]) or NOW
        age_h = hours_since(first) or 0
        rel, hits = niche_score(s)
        rel = max(rel, 45)
        cat = classify(s)
        cov = coverage(s, posts)
        popularity = max(0, 100 - a["best_rank"] * 9) + min(30, (len(a["queries"]) - 1) * 10)
        newness = (100 if age_h < 4 else max(0, 100 - age_h * 2)) if h.get("new") else 35
        score = int(0.40 * rel + 0.30 * min(100, popularity) + 0.30 * newness)
        if cov:
            score = max(0, score - 20)
        score = min(100, score + min(6, len(a["queries"]) - 1))
        items.append({
            "id": "gs-" + slugify(s),
            "source": "google_suggest",
            "keyword": s,
            "title": s,
            "url": f"https://www.google.com/search?q={urllib.parse.quote_plus(s)}",
            "trends_url": f"https://trends.google.com/trends/explore?date=today%203-m&q={urllib.parse.quote_plus(s)}",
            "seed": a["seed"],
            "rank": a["best_rank"] + 1,
            "started_at": h["first_seen"],
            "last_seen": h["last_seen"],
            "active": True,
            "duration_h": round(age_h, 2),
            "is_new": bool(h.get("new")) and age_h < 24,
            "category": cat,
            "relevance": rel,
            "niche_hits": hits,
            "score": score,
            "ideas": article_ideas(s, cat, kind="query"),
            "covered": cov,
        })
    # Keep the dashboard light: best 450 suggestions plus everything new.
    items.sort(key=lambda x: (x["is_new"], x["score"], -x["rank"]), reverse=True)
    keep = [i for i in items if i["is_new"]]
    keep += [i for i in items if not i["is_new"]][:max(0, 450 - len(keep))]
    return keep


# --------------------------------------------------------------------------- Google News
def google_news_items(posts: list[dict]) -> list[dict]:
    def one(q):
        url = ("https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
               + urllib.parse.quote(f"{q} when:1d"))
        try:
            root = ET.fromstring(http_get(url))
            rows = []
            for it in root.iter("item"):
                src = it.find("source")
                rows.append({
                    "q": q,
                    "title": unescape(it.findtext("title") or ""),
                    "url": it.findtext("link") or "",
                    "pub": parse_rfc822(it.findtext("pubDate")),
                    "source": src.text if src is not None else "",
                })
            return rows
        except Exception as e:  # noqa: BLE001
            log("news failed", q, e)
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(one, CONFIG["news_queries"]))
    ok = sum(1 for r in res if r is not None)
    STATUS["google_news"] = {"ok": ok > 0, "queries_ok": ok, "queries": len(CONFIG["news_queries"])}

    seen, items = set(), []
    for rows in res:
        for r in rows or []:
            title = re.sub(r"\s+-\s+[^-]+$", "", r["title"]).strip()  # drop " - Publisher"
            k = slugify(title)[:80]
            if not title or k in seen:
                continue
            seen.add(k)
            age_h = hours_since(r["pub"]) or 24
            rel, hits = niche_score(title)
            if rel < 15:
                continue
            cat = classify(title)
            freshness = int(max(0, 100 - age_h * 4))
            score = int(0.6 * rel + 0.4 * freshness)
            items.append({
                "id": "gn-" + k,
                "source": "google_news",
                "keyword": title,
                "title": title,
                "url": r["url"],
                "publisher": r["source"],
                "query": r["q"],
                "started_at": iso(r["pub"]),
                "active": True,
                "duration_h": round(age_h, 2),
                "category": cat,
                "relevance": rel,
                "niche_hits": hits,
                "score": score,
                "ideas": article_ideas(title, cat, kind="headline"),
                "covered": coverage(title, posts),
            })
    return items


def short_topic(title: str) -> str:
    """Turn a headline into a short topic phrase for idea templates."""
    t = re.split(r"[:|–—]| - ", title)[0]
    words = t.split()
    return " ".join(words[:7])


# --------------------------------------------------------------------------- Reddit
def reddit_token() -> str | None:
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if not cid or not sec:
        return None
    try:
        auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        body = http_get("https://www.reddit.com/api/v1/access_token",
                        headers={"Authorization": f"Basic {auth}", "User-Agent": BOT_UA,
                                 "Content-Type": "application/x-www-form-urlencoded"},
                        data=b"grant_type=client_credentials", retries=1)
        return json.loads(body).get("access_token")
    except Exception as e:  # noqa: BLE001
        log("reddit auth failed", e)
        return None


ATOM = "{http://www.w3.org/2005/Atom}"


def reddit_posts(sub: str, token: str | None) -> list[dict] | None:
    try:
        if token:
            body = http_get(f"https://oauth.reddit.com/r/{sub}/hot?limit=30&raw_json=1",
                            headers={"Authorization": f"Bearer {token}", "User-Agent": BOT_UA},
                            retries=1)
            out = []
            for c in json.loads(body)["data"]["children"]:
                d = c["data"]
                if d.get("stickied"):
                    continue
                out.append({"id": d["id"], "title": d["title"], "sub": sub,
                            "url": "https://www.reddit.com" + d["permalink"],
                            "created": datetime.fromtimestamp(d["created_utc"], timezone.utc),
                            "score": d.get("score", 0), "comments": d.get("num_comments", 0),
                            "flair": d.get("link_flair_text") or ""})
            return out
        xml = http_get(f"https://www.reddit.com/r/{sub}/.rss?limit=30",
                       headers={"User-Agent": BOT_UA}, retries=1)
        root = ET.fromstring(xml)
        out = []
        for e in root.findall(f"{ATOM}entry"):
            link = e.find(f"{ATOM}link")
            out.append({"id": (e.findtext(f"{ATOM}id") or "").split("_")[-1],
                        "title": unescape(e.findtext(f"{ATOM}title") or ""), "sub": sub,
                        "url": link.get("href") if link is not None else "",
                        "created": parse_iso(e.findtext(f"{ATOM}published")) or NOW,
                        "score": None, "comments": None, "flair": ""})
        return out
    except Exception as e:  # noqa: BLE001
        log("reddit failed", sub, getattr(e, "code", e))
        return None


QUESTION_RE = re.compile(r"\?|^(how|what|which|why|where|is|are|can|does|do|should|any)\b|"
                         r"\b(help|looking for|recommend|identify|anyone know)\b", re.I)


def reddit_items(hist: dict, posts: list[dict]) -> list[dict]:
    token = reddit_token()
    res, ok = [], 0
    if LIVE:
        with ThreadPoolExecutor(max_workers=6) as ex:
            fetched = list(ex.map(lambda sub: reddit_posts(sub, token), CONFIG["subreddits"]))
    else:
        fetched = []
        for sub in CONFIG["subreddits"]:
            fetched.append(reddit_posts(sub, token))
            time.sleep(1.2 if token else 2.5)
    for r in fetched:
        if r is not None:
            ok += 1
            res.extend(r)
    STATUS["reddit"] = {"ok": ok > 0, "subs_ok": ok, "subs": len(CONFIG["subreddits"]),
                        "mode": "api" if token else "rss"}
    items = []
    for p in res:
        age_h = hours_since(p["created"]) or 0.1
        if age_h > 48:
            continue
        key = f"{p['sub']}|{p['id']}"
        h = hist["reddit"].setdefault(key, {"first_seen": iso(NOW)})
        h["last_seen"] = iso(NOW)
        rel, hits = niche_score(p["title"])
        rel = max(rel, 40)
        q = bool(QUESTION_RE.search(p["title"]))
        if p["score"] is not None:
            velocity = (p["score"] + 2 * p["comments"]) / max(age_h, 0.5)
            momentum = min(100, int(math.log10(max(velocity, 1)) / 2.5 * 100))
        else:
            momentum = 50
        freshness = int(max(0, 100 - age_h * 3))
        score = int(0.40 * rel + 0.35 * momentum + 0.25 * freshness + (8 if q else 0))
        cat = classify(p["title"])
        items.append({
            "id": "rd-" + slugify(key),
            "source": "reddit",
            "keyword": p["title"],
            "title": p["title"],
            "url": p["url"],
            "subreddit": p["sub"],
            "upvotes": p["score"],
            "comments": p["comments"],
            "flair": p["flair"],
            "is_question": q,
            "started_at": iso(p["created"]),
            "active": True,
            "duration_h": round(age_h, 2),
            "category": cat,
            "relevance": rel,
            "niche_hits": hits,
            "score": min(100, score),
            "ideas": ([f"Answer it as an article: {p['title']}"] if q else []) + article_ideas(p["title"], cat, kind="headline"),
            "covered": coverage(p["title"], posts),
        })
    return items


# --------------------------------------------------------------------------- main
def collect(hist: dict) -> dict:
    """Fetch every source and return the dashboard payload. Updates `hist` in place."""
    global NOW
    NOW = datetime.now(timezone.utc)
    STATUS.clear()
    posts = load_site_posts()

    def run(name, fn):
        t0 = time.time()
        try:
            got = fn()
            log(f"{name}: {len(got)} items in {time.time() - t0:.1f}s")
            return got
        except Exception as e:  # noqa: BLE001
            STATUS[name] = {"ok": False, "error": str(e)[:200]}
            log(f"{name} crashed: {e}")
            return []

    jobs = (("google_trends", lambda: google_trends_items(hist, posts)),
            ("google_suggest", lambda: google_suggest_items(hist, posts)),
            ("google_news", lambda: google_news_items(posts)),
            ("reddit", lambda: reddit_items(hist, posts)))
    items: list[dict] = []
    if LIVE:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for got in ex.map(lambda j: run(*j), jobs):
                items.extend(got)
    else:
        for j in jobs:
            items.extend(run(*j))

    items.sort(key=lambda x: x["score"], reverse=True)
    hist["runs"].append(iso(NOW))
    prune_history(hist)

    return {
        "generated_at": iso(NOW),
        "mode": "live" if LIVE else "scheduled",
        "site": {"name": CONFIG["site"]["name"], "url": CONFIG["site"]["url"],
                 "posts_indexed": len(posts)},
        "status": STATUS,
        "counts": {s: sum(1 for i in items if i["source"] == s)
                   for s in ("google_trends", "google_suggest", "google_news", "reddit")},
        "items": items,
    }


def empty_history() -> dict:
    return {"trends": {}, "suggest": {}, "reddit": {}, "runs": []}


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    hist = load_history()
    out = collect(hist)
    items = out["items"]
    TRENDS_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"wrote {len(items)} items -> {TRENDS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
