#!/usr/bin/env python3
"""
Live SEO / AEO / GEO audit of designerslab.io.

Fetches robots.txt, llms.txt, the sitemap, the homepage and the newest posts,
then checks what is really in the HTML (titles, meta, canonical, headings,
JSON-LD schema, images, links, AI-crawler access). Every result is measured
from the live pages; each failed check comes with the fix to make.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlparse

from fetch_trends import CONFIG, http_get

SITE = CONFIG["site"]["url"].rstrip("/")
HOST = urlparse(SITE).netloc
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot", "Google-Extended",
           "Applebot-Extended", "CCBot", "Bingbot"]
QUESTION_RE = re.compile(r"^(what|how|why|which|when|where|who|can|is|are|does|do|should)\b|\?\s*$", re.I)


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.jsonld: list[str] = []
        self.imgs = 0
        self.imgs_no_alt = 0
        self.links: list[str] = []
        self.text: list[str] = []
        self.lists = 0
        self.tables = 0
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._cap: str | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key:
                self.meta[key] = a.get("content", "")
        elif tag == "link" and "canonical" in a.get("rel", "").lower():
            self.canonical = a.get("href", "")
        elif tag == "img":
            self.imgs += 1
            if not a.get("alt", "").strip():
                self.imgs_no_alt += 1
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag in ("ul", "ol"):
            self.lists += 1
        elif tag == "table":
            self.tables += 1
        if tag == "script" and "ld+json" in a.get("type", ""):
            self._cap, self._buf = "jsonld", []
        elif tag in ("title", "h1", "h2"):
            self._cap, self._buf = tag, []
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        if self._cap and (tag == self._cap or (self._cap == "jsonld" and tag == "script")):
            txt = "".join(self._buf).strip()
            if self._cap == "title":
                self.title = self.title or re.sub(r"\s+", " ", txt)
            elif self._cap == "h1":
                self.h1.append(re.sub(r"\s+", " ", txt))
            elif self._cap == "h2":
                self.h2.append(re.sub(r"\s+", " ", txt))
            elif self._cap == "jsonld":
                self.jsonld.append(txt)
            self._cap = None

    def handle_data(self, data):
        if self._cap:
            self._buf.append(data)
        if not self._skip:
            self.text.append(data)


def schema_types(blocks: list[str]) -> set[str]:
    types: set[str] = set()

    def walk(n):
        if isinstance(n, dict):
            t = n.get("@type")
            if isinstance(t, str):
                types.add(t)
            elif isinstance(t, list):
                types.update(x for x in t if isinstance(x, str))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    for b in blocks:
        try:
            walk(json.loads(b))
        except Exception:  # noqa: BLE001
            pass
    return types


def analyse(url: str) -> dict:
    t0 = time.time()
    try:
        html = http_get(url, timeout=20, retries=0)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "error": str(e)[:120]}
    p = PageParser()
    p.feed(html)
    words = len(re.findall(r"[A-Za-z0-9']+", " ".join(p.text)))
    internal = [l for l in p.links if l.startswith("/") or HOST in l]
    external = [l for l in p.links if l.startswith("http") and HOST not in l]
    return {
        "url": url, "ms": int((time.time() - t0) * 1000), "kb": len(html) // 1024,
        "lang": p.lang, "title": p.title, "title_len": len(p.title),
        "description": p.meta.get("description", ""), "description_len": len(p.meta.get("description", "")),
        "canonical": p.canonical, "robots": p.meta.get("robots", ""),
        "h1": p.h1, "h2": p.h2[:40], "h2_questions": sum(1 for h in p.h2 if QUESTION_RE.search(h)),
        "schema": sorted(schema_types(p.jsonld)),
        "og_image": bool(p.meta.get("og:image")), "twitter_card": p.meta.get("twitter:card", ""),
        "published": p.meta.get("article:published_time", ""), "modified": p.meta.get("article:modified_time", ""),
        "author_meta": p.meta.get("author", ""),
        "images": p.imgs, "images_no_alt": p.imgs_no_alt, "words": words,
        "internal_links": len(internal), "external_links": len(external),
        "lists": p.lists, "tables": p.tables,
    }


def newest_posts(n: int = 6) -> list[str]:
    xml = http_get(CONFIG["site"]["sitemaps"][0])
    rows = re.findall(r"<url>\s*<loc>(.*?)</loc>(?:.*?<lastmod>(.*?)</lastmod>)?", xml, re.S)
    rows = [(u, m or "") for u, m in rows if "/wp-content/" not in u and u.rstrip("/") != SITE]
    rows.sort(key=lambda r: r[1], reverse=True)
    return [u for u, _ in rows[:n]]


def check(area, name, ok, detail, fix, warn=False):
    return {"area": area, "check": name, "result": "pass" if ok else ("warn" if warn else "fail"),
            "detail": detail, "fix": "" if ok else fix}


def collect() -> dict:
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_robots = ex.submit(lambda: http_get(SITE + "/robots.txt", retries=0))
        f_llms = ex.submit(lambda: http_get(SITE + "/llms.txt", retries=0))
        f_posts = ex.submit(newest_posts)
        f_home = ex.submit(analyse, SITE + "/")
        try:
            robots = f_robots.result()
        except Exception:  # noqa: BLE001
            robots = ""
        try:
            llms = f_llms.result()
            llms_ok = len(llms) > 50 and "<html" not in llms[:500].lower()
        except Exception:  # noqa: BLE001
            llms, llms_ok = "", False
        post_urls = f_posts.result()
        home = f_home.result()
    with ThreadPoolExecutor(max_workers=6) as ex:
        posts = [p for p in ex.map(analyse, post_urls) if "error" not in p]

    checks = []
    # ---- site level
    checks.append(check("Technical", "robots.txt lists the sitemap", "sitemap" in robots.lower(),
                        "Found a Sitemap: line" if "sitemap" in robots.lower() else "No Sitemap: line in robots.txt",
                        "Add 'Sitemap: https://designerslab.io/sitemap_index.xml' to robots.txt (Rank Math → General Settings → Edit robots.txt)."))
    blocked = []
    cur: list[str] = []
    for line in robots.splitlines():
        line = line.split("#")[0].strip()
        if line.lower().startswith("user-agent:"):
            cur = [line.split(":", 1)[1].strip()]
        elif line.lower().startswith("disallow:") and line.split(":", 1)[1].strip() == "/":
            blocked += [b for b in AI_BOTS if any(b.lower() == c.lower() for c in cur)]
    checks.append(check("GEO", "AI search crawlers can read the site", not blocked,
                        "Blocked: " + ", ".join(blocked) if blocked else "No AI crawler is blocked in robots.txt",
                        "Remove the 'Disallow: /' rules for these bots so ChatGPT, Perplexity, Claude, Gemini and Bing Copilot can cite your pages."))
    checks.append(check("GEO", "llms.txt file", llms_ok, "Found /llms.txt" if llms_ok else "No /llms.txt",
                        "Publish /llms.txt: a short Markdown summary of the site plus links to your best guides and resource categories. It helps AI assistants understand and cite you. A template is in the Playbook tab.",
                        warn=True))

    # ---- homepage
    if "error" not in home:
        hs = set(home["schema"])
        checks.append(check("SEO", "Homepage title length", 30 <= home["title_len"] <= 65,
                            f"{home['title_len']} chars: “{home['title']}”", "Keep the homepage title between 30 and 65 characters, with the main keyword first.", warn=True))
        checks.append(check("GEO", "Organization / WebSite schema on homepage", bool(hs & {"Organization", "WebSite"}),
                            "Schema: " + (", ".join(home["schema"]) or "none"),
                            "Add Organization (logo, sameAs social profiles) and WebSite (SearchAction) schema. In Rank Math: Titles & Meta → Local SEO / Knowledge Graph."))

    # ---- posts
    n = len(posts) or 1
    def share(fn):
        return sum(1 for p in posts if fn(p))

    if posts:
        good_title = share(lambda p: 30 <= p["title_len"] <= 65)
        checks.append(check("SEO", "Post titles 30–65 characters", good_title == len(posts),
                            f"{good_title}/{len(posts)} newest posts in range", "Shorten or lengthen titles so the full title shows in Google (≈60 characters).", warn=True))
        good_desc = share(lambda p: 110 <= p["description_len"] <= 165)
        checks.append(check("SEO", "Meta descriptions 110–165 characters", good_desc == len(posts),
                            f"{good_desc}/{len(posts)} posts in range", "Write a 140–160 character description with the keyword and a reason to click.", warn=True))
        canon = share(lambda p: bool(p["canonical"]))
        checks.append(check("SEO", "Canonical tag", canon == len(posts), f"{canon}/{len(posts)} posts have one",
                            "Every post needs a self-referencing canonical (Rank Math adds it automatically when enabled)."))
        one_h1 = share(lambda p: len(p["h1"]) == 1)
        checks.append(check("SEO", "Exactly one H1", one_h1 == len(posts), f"{one_h1}/{len(posts)} posts",
                            "Use a single H1 (the article title). Make the logo and other headings H2/H3 or plain text."))
        alt_missing = sum(p["images_no_alt"] for p in posts)
        imgs = sum(p["images"] for p in posts)
        checks.append(check("SEO", "Images have alt text", alt_missing == 0, f"{alt_missing} of {imgs} images missing alt",
                            "Describe every image (e.g. 'Free black friday instagram template PSD mockup'). Google Images is a big traffic source for design sites.", warn=alt_missing < imgs * 0.2))
        il = share(lambda p: p["internal_links"] >= 8)
        checks.append(check("SEO", "Internal links (8+ per post)", il == len(posts), f"{il}/{len(posts)} posts",
                            "Link each new post to 3–5 related posts and to the matching resource category. Use the Brief button for suggestions.", warn=True))
        mipl = share(lambda p: "max-image-preview:large" in p["robots"].lower())
        checks.append(check("SEO", "Google Discover: max-image-preview:large", mipl == len(posts),
                            f"{mipl}/{len(posts)} posts", "Enable 'max-image-preview:large' in Rank Math → Titles & Meta → Global Meta → Advanced Robots. Discover can send big traffic to design posts.", warn=True))
        og = share(lambda p: p["og_image"])
        checks.append(check("SEO", "Open Graph image", og == len(posts), f"{og}/{len(posts)} posts",
                            "Set a 1200×630+ featured image so shares on Pinterest, Facebook and X show a preview."))
        art = share(lambda p: bool(set(p["schema"]) & {"Article", "BlogPosting", "NewsArticle"}))
        checks.append(check("GEO", "Article schema", art == len(posts), f"{art}/{len(posts)} posts",
                            "Use Article/BlogPosting schema with author, datePublished, dateModified and image (Rank Math → Schema → Article)."))
        crumbs = share(lambda p: "BreadcrumbList" in p["schema"])
        checks.append(check("SEO", "Breadcrumb schema", crumbs == len(posts), f"{crumbs}/{len(posts)} posts",
                            "Enable breadcrumbs in Rank Math → General Settings → Breadcrumbs and show them in the theme.", warn=True))
        faq = share(lambda p: "FAQPage" in p["schema"])
        checks.append(check("AEO", "FAQ section with FAQPage schema", faq >= max(1, len(posts) // 2),
                            f"{faq}/{len(posts)} posts", "End how-to and 'what is' posts with 3–5 real questions (use the Questions tab), answered in 40–60 words, using the Rank Math FAQ block.", warn=True))
        qh2 = share(lambda p: p["h2_questions"] >= 2)
        checks.append(check("AEO", "Question-style H2 headings", qh2 >= max(1, len(posts) // 2),
                            f"{qh2}/{len(posts)} posts have 2+ question headings",
                            "Phrase some H2s exactly like the questions people search ('What font is the Netflix logo?') and answer in the first sentence below. This wins featured snippets and AI answers.", warn=True))
        author = share(lambda p: bool(p["author_meta"]) or "Person" in p["schema"])
        checks.append(check("GEO", "Visible author (E-E-A-T)", author == len(posts), f"{author}/{len(posts)} posts",
                            "Show a real author with a bio page (design experience, portfolio links) and add Person schema. AI engines and Google weight expertise."))
        mod = share(lambda p: bool(p["modified"]))
        checks.append(check("GEO", "dateModified shown", mod == len(posts), f"{mod}/{len(posts)} posts",
                            "Output article:modified_time and update older posts with fresh info each season; freshness matters for AI answers.", warn=True))
        depth = share(lambda p: p["words"] >= 800)
        checks.append(check("SEO", "Content depth (800+ words)", depth >= len(posts) - 1, f"{depth}/{len(posts)} posts",
                            "Roundups and guides rank best at 1,000–2,000 words with original previews, usage tips and licence notes.", warn=True))
        struct = share(lambda p: p["lists"] + p["tables"] >= 3)
        checks.append(check("AEO", "Lists / tables for scannable answers", struct >= len(posts) - 1, f"{struct}/{len(posts)} posts",
                            "Add a comparison table (font, style, licence, download link) and bullet lists. AI answers and snippets quote structured content.", warn=True))
        speed = sorted(p["ms"] for p in posts)[len(posts) // 2]
        checks.append(check("Technical", "Server response (median HTML fetch)", speed < 1200, f"{speed} ms",
                            "Use page caching + a CDN (W3 Total Cache is installed; check page cache and Cloudflare). Check Core Web Vitals in PageSpeed Insights.", warn=speed < 2500))

    order = {"fail": 0, "warn": 1, "pass": 2}
    checks.sort(key=lambda c: order[c["result"]])
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "site": SITE,
            "seconds": round(time.time() - t0, 1), "home": home, "posts": posts,
            "summary": {k: sum(1 for c in checks if c["result"] == k) for k in ("pass", "warn", "fail")},
            "checks": checks}


if __name__ == "__main__":
    import sys
    from pathlib import Path
    out = collect()
    dst = Path(__file__).resolve().parent.parent / "docs" / "data" / "audit.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(out["summary"]), file=sys.stderr)
    for c in out["checks"]:
        print(f"[{c['result']}] {c['area']}: {c['check']} - {c['detail']}", file=sys.stderr)
