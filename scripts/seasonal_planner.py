#!/usr/bin/env python3
"""
Seasonal planner + question backlog (real data only).

* Seasonal planner: real event dates (computed, or from config for lunar
  holidays, flagged approx). For each event it asks Google Autocomplete
  "<event> fonts", "<event> templates", "<event> svg", ... and lists only
  what Google actually returns, so you see real search demand. Publish-by
  dates follow the lead time needed to get indexed and ranked before the peak.
* Question backlog: real Google autocomplete questions for design seeds,
  flagged when designerslab.io already has a matching post.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from fetch_trends import CONFIG, STATUS, coverage, design_match, load_site_posts, slugify, suggest_many


def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (Mon=0) of a month; n=-1 for last."""
    if n > 0:
        d = date(y, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(y + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def events_for(y: int) -> list[dict]:
    thanks = nth_weekday(y, 11, 3, 4)
    fixed = [
        ("New Year", date(y, 1, 1), "new year"),
        ("Super Bowl", nth_weekday(y, 2, 6, 2), "super bowl"),
        ("Valentine's Day", date(y, 2, 14), "valentines day"),
        ("Women's Day", date(y, 3, 8), "womens day"),
        ("St Patrick's Day", date(y, 3, 17), "st patricks day"),
        ("Easter", easter(y), "easter"),
        ("Earth Day", date(y, 4, 22), "earth day"),
        ("Mother's Day", nth_weekday(y, 5, 6, 2), "mothers day"),
        ("Memorial Day", nth_weekday(y, 5, 0, -1), "memorial day"),
        ("Graduation", date(y, 5, 25), "graduation"),
        ("Father's Day", nth_weekday(y, 6, 6, 3), "fathers day"),
        ("4th of July", date(y, 7, 4), "4th of july"),
        ("Back to School", date(y, 8, 15), "back to school"),
        ("Labor Day", nth_weekday(y, 9, 0, 1), "labor day"),
        ("Halloween", date(y, 10, 31), "halloween"),
        ("Thanksgiving", thanks, "thanksgiving"),
        ("Black Friday", thanks + timedelta(days=1), "black friday"),
        ("Cyber Monday", thanks + timedelta(days=4), "cyber monday"),
        ("Christmas", date(y, 12, 25), "christmas"),
    ]
    return [{"name": n, "date": d, "query": q, "approx": False} for n, d, q in fixed]


def upcoming_events(today: date) -> list[dict]:
    cfg = CONFIG["planner"]
    evs = events_for(today.year) + events_for(today.year + 1)
    for m in cfg["manual_events"]:
        evs.append({"name": m["name"], "date": date.fromisoformat(m["date"]),
                    "query": m.get("query", m["name"].lower()), "approx": m.get("approx", True)})
    horizon = today + timedelta(days=cfg["lookahead_days"])
    evs = [e for e in evs if today <= e["date"] <= horizon]
    return sorted(evs, key=lambda e: e["date"])


def seasonal(posts: list[dict], deadline: float) -> list[dict]:
    cfg = CONFIG["planner"]
    today = date.today()
    evs = upcoming_events(today)
    queries = [(e["name"], e["query"] + s, "us") for e in evs for s in cfg["design_suffixes"]]
    res = suggest_many(queries, deadline=deadline)
    out = []
    for e in evs:
        ideal = e["date"] - timedelta(days=cfg["publish_lead_days"])
        latest = e["date"] - timedelta(days=cfg["latest_useful_days"])
        if today < ideal:
            status = "plan"
        elif today <= latest:
            status = "publish-now"
        else:
            status = "last-minute"
        demand = []
        for s in cfg["design_suffixes"]:
            q = e["query"] + s
            sugg = res.get((e["name"], q))
            if sugg is None:
                continue
            real = [x for x in sugg if x.strip().lower() != q.lower()]
            if real:
                demand.append({"query": q.strip(), "suggestions": real[:8], "count": len(real),
                               "covered": coverage(q, posts)})
        demand.sort(key=lambda d: d["count"], reverse=True)
        out.append({
            "id": "ev-" + slugify(e["name"] + str(e["date"])),
            "name": e["name"], "date": e["date"].isoformat(), "approx": e["approx"],
            "days_left": (e["date"] - today).days,
            "publish_by": ideal.isoformat(), "latest_useful": latest.isoformat(), "status": status,
            "demand": demand,
            "uncovered": sum(1 for d in demand if not d["covered"]),
        })
    return out


def questions(posts: list[dict], deadline: float) -> list[dict]:
    seeds = CONFIG["question_seeds"]
    queries = [(s, s + " ", "us") for s in seeds]
    res = suggest_many(queries, deadline=deadline)
    out, seen = [], set()
    for s in seeds:
        for i, q in enumerate(res.get((s, s + " ")) or []):
            k = q.strip().lower()
            if k in seen or k == s.lower():
                continue
            seen.add(k)
            m = design_match(q, [], [])
            out.append({"id": "q-" + slugify(q), "question": q, "seed": s, "rank": i + 1,
                        "group": m["group"] if m else "", "covered": coverage(q, posts)})
    return out


def collect() -> dict:
    STATUS.clear()
    t0 = time.time()
    posts = load_site_posts()
    ev = seasonal(posts, deadline=t0 + 30)
    qs = questions(posts, deadline=t0 + 45)
    STATUS["planner"] = {"ok": bool(ev or qs), "events": len(ev), "questions": len(qs),
                         "seconds": round(time.time() - t0, 1)}
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "today": date.today().isoformat(),
            "status": STATUS, "events": ev, "questions": qs,
            "site": {"posts": len(posts), "post_urls": [p["url"] for p in posts]}}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    out = collect()
    p = Path(__file__).resolve().parent.parent / "docs" / "data" / "planner.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out['events'])} events, {len(out['questions'])} questions", file=sys.stderr)
