(() => {
  "use strict";

  // ================================================================ helpers
  const COUNTRY = { US: "🇺🇸 US", GB: "🇬🇧 UK", CA: "🇨🇦 Canada", AU: "🇦🇺 Australia", IN: "🇮🇳 India", PK: "🇵🇰 Pakistan",
    NZ: "🇳🇿 New Zealand", IE: "🇮🇪 Ireland", ZA: "🇿🇦 South Africa", PH: "🇵🇭 Philippines", AE: "🇦🇪 UAE", SG: "🇸🇬 Singapore" };
  const WIN_LABEL = { 2: "in the past 2 hours", 4: "in the past 4 hours", 24: "in the past 24 hours", 48: "in the past 48 hours", 168: "in the past 7 days" };
  const QUESTION_RE = /^(what|how|why|which|when|where|who|can|is|are|does|do|should)\b|\?\s*$/i;
  const STOP = new Set("a an and the of for to in on with free best how what is are vs your you my top new download 2024 2025 2026 2027 guide".split(" "));

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("dltf3:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("dltf3:" + k, JSON.stringify(v)); } catch { /* optional */ } },
  };
  const now = () => Date.now();
  const hoursAgo = (iso) => (iso ? (now() - Date.parse(iso)) / 36e5 : null);
  function dur(h) {
    if (h == null) return "";
    if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
    if (h < 48) { const H = Math.floor(h), M = Math.round((h - H) * 60); return M && H < 10 ? `${H}h ${M}m` : `${H}h`; }
    return `${Math.round(h / 24)}d`;
  }
  const vol = (n) => (!n ? "–" : n >= 1e6 ? `${n / 1e6}M+` : n >= 1e3 ? `${n / 1e3}K+` : `${n}+`);
  const pct = (p) => (p == null ? "–" : `+${Number(p).toLocaleString()}%`);
  const exact = (iso) => (iso ? new Date(iso).toLocaleString() : "");
  const fmtDate = (d) => new Date(d + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  const tokens = (s) => new Set((String(s).toLowerCase().match(/[a-z0-9]+/g) || []).filter((w) => w.length > 1 && !STOP.has(w)));
  function highlight(text, term) {
    const i = text.toLowerCase().indexOf(String(term).toLowerCase());
    if (!term || i < 0) return esc(text);
    return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + term.length)) + "</mark>" + esc(text.slice(i + term.length));
  }
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); } catch {
      const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    toast("Copied");
  }
  const covered = (url) => (url ? `<a class="pill covered" href="${esc(url)}" target="_blank" rel="noopener">Covered ↗</a>` : '<span class="muted">Not yet</span>');

  // ================================================================ state & data
  const state = Object.assign({ tab: "today", win: 4, minSearches: 1000, country: "", activeOnly: false, showOther: false,
    sort: "searches", qUncovered: true }, store.get("state", {}));
  const trends = {};          // hours -> payload
  let planner = null, audit = null;
  const open = new Set();
  const briefs = new Map();   // id -> brief source object
  const fetchHours = () => (state.win === 2 ? 4 : state.win);
  const inWin = (iso) => state.win !== 2 || (hoursAgo(iso) ?? 999) <= 2;

  async function getJSON(api, file) {
    if (!location.hostname.endsWith("github.io")) {
      try { const r = await fetch(api); if (r.ok) { const j = await r.json(); if (!j.error) return j; } } catch { /* fall back */ }
    }
    const r = await fetch(`${file}?t=${Math.floor(now() / 60000)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  const loading = {};
  async function loadTrends(h, force) {
    if ((trends[h] && !force) || loading["t" + h]) return;
    loading["t" + h] = true; spin(true);
    try { trends[h] = await getJSON(`/api/trends?hours=${h}`, `data/trends-${h}h.json`); fillCountries(trends[h]); }
    catch { /* shown as empty */ } finally { loading["t" + h] = false; spin(false); render(); }
  }
  async function loadPlanner(force) {
    if ((planner && !force) || loading.p) return;
    loading.p = true; spin(true);
    try { planner = await getJSON("/api/planner", "data/planner.json"); } catch { /* empty */ } finally { loading.p = false; spin(false); render(); }
  }
  async function loadAudit(force) {
    if ((audit && !force) || loading.a) return;
    loading.a = true; spin(true);
    try { audit = await getJSON("/api/audit", "data/audit.json"); } catch { /* empty */ } finally { loading.a = false; spin(false); render(); }
  }
  function spin(on) { $("#refreshBtn").classList.toggle("spin", on || Object.values(loading).some(Boolean)); }
  function sitePosts() { return (trends[4] || trends[fetchHours()] || planner || {}).site?.post_urls || []; }

  // ================================================================ brief
  function relatedPosts(text) {
    const tk = tokens(text);
    return sitePosts().map((u) => {
      const slug = u.replace(/\/$/, "").split("/").pop().replace(/-/g, " ");
      const st = tokens(slug); let n = 0; tk.forEach((w) => { if (st.has(w)) n++; });
      return { url: u, slug, n };
    }).filter((p) => p.n > 0).sort((a, b) => b.n - a.n).slice(0, 6);
  }
  const DESIGN_RE = /\b(fonts?|typefaces?|typography|logos?|mockups?|templates?|svg|png|wallpapers?|posters?|flyers?|design\w*|canva|photoshop|illustrator|figma|clip ?art|vectors?|icons?|stickers?|prompts?|colou?rs?|palette|branding|illustrations?|coloring)\b/i;
  function plannerQuestionsFor(topic) {
    if (!planner || !topic) return [];
    // must share a topic word that is not itself a design word ("christmas", "netflix", ...)
    const tk = [...tokens(topic)].filter((w) => !DESIGN_RE.test(w));
    if (!tk.length) return [];
    return planner.questions.filter((q) => { const qt = tokens(q.question); return tk.some((w) => qt.has(w)); }).map((q) => q.question).slice(0, 6);
  }
  function makeBrief(src) {
    const all = [...(src.suggestions || []), ...(src.related || [])];
    const own = all.filter((q) => QUESTION_RE.test(q) && DESIGN_RE.test(q));
    const questions = [...new Set([...own, ...(src.kind.startsWith("Evergreen") ? [] : plannerQuestionsFor(src.topic))])].slice(0, 8);
    const secondary = [...new Set(all.filter((q) => q.toLowerCase() !== src.keyword.toLowerCase() && !QUESTION_RE.test(q)))].slice(0, 12);
    return { ...src, questions, secondary, links: relatedPosts(src.keyword + " " + (src.topic || "")) };
  }
  const CHECKLIST = {
    "Before writing": [
      "Google the keyword and open the top 5 results. Note what they cover and what's missing (your angle).",
      "Prepare original visuals: a preview of the font, logo, mockup or template, exported as WebP at 1200px+ wide.",
    ],
    "On-page SEO": [
      "Exact keyword in the title (≤60 characters), URL slug, H1 and first 100 words.",
      "Meta description of 140–160 characters with the keyword and a benefit.",
      "H2s based on the secondary keywords and questions below.",
      "Descriptive image file names and alt text. Set a featured image (1200×630+).",
      "3–5 internal links (listed below) and 1–2 links to the official or original source.",
    ],
    "AEO (answers)": [
      "Answer the main query in the first 2 sentences (40–60 words).",
      "Phrase 2–4 H2s as the real questions and answer each one directly.",
      "Add an FAQ block (Rank Math FAQ, which adds FAQPage schema) with 3–5 questions.",
      "Use a table or list for comparisons (name, style, licence, download).",
    ],
    "GEO (AI search)": [
      "State clear facts AI can quote (who made it, when, what it's called, the licence).",
      "Cite your sources and add one original insight or number (e.g. downloads, sizes, file formats).",
      "Show the author bio and keep dateModified current.",
    ],
    "After publishing": [
      "Search Console → URL Inspection → Request indexing.",
      "Submit through IndexNow (Rank Math Instant Indexing) for Bing and ChatGPT search.",
      "Link to it from 2–3 related older posts and the homepage.",
      "Pin 2 images on Pinterest, and share on X or Facebook design groups.",
      "Check Search Console impressions after 48 hours.",
    ],
  };
  function briefHTML(b) {
    const li = (arr) => arr.map((x) => `<li>${x}</li>`).join("");
    return `
      <div><div class="muted">${esc(b.kind)}</div><div class="kwbig">${esc(b.keyword)}</div>${b.topic && b.topic !== b.keyword ? `<div class="muted">Topic: ${esc(b.topic)}</div>` : ""}</div>
      <div><h3>Why now (real data)</h3><ul>${li(b.facts.map(esc))}</ul></div>
      ${b.secondary.length ? `<div><h3>Secondary keywords (real Google searches)</h3><div class="chips">${b.secondary.map((q) => `<span class="chip" data-copy="${esc(q)}">${esc(q)}</span>`).join("")}</div></div>` : ""}
      ${b.questions.length ? `<div><h3>Questions to answer (H2s / FAQ)</h3><ul>${li(b.questions.map(esc))}</ul></div>` : ""}
      ${b.sources?.length ? `<div><h3>Sources to read and cite</h3><ul>${li(b.sources.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>`))}</ul></div>` : ""}
      <div><h3>Internal links from your site</h3>${b.links.length ? `<ul>${li(b.links.map((p) => `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.slug)}</a>`))}</ul>` : '<div class="muted">No closely matching post yet. Link to the most relevant resource category instead.</div>'}</div>
      <div class="actions">
        <a class="btn" href="https://www.google.com/search?q=${encodeURIComponent(b.keyword)}" target="_blank" rel="noopener">See Google results</a>
        <a class="btn" href="https://trends.google.com/trends/explore?date=now%207-d&q=${encodeURIComponent(b.keyword)}" target="_blank" rel="noopener">Google Trends chart</a>
        <a class="btn" href="https://www.google.com/search?q=site%3Adesignerslab.io+${encodeURIComponent(b.topic || b.keyword)}" target="_blank" rel="noopener">Search my site</a>
      </div>
      ${Object.entries(CHECKLIST).map(([k, v]) => `<div><h3>${esc(k)}</h3><ul>${li(v.map(esc))}</ul></div>`).join("")}`;
  }
  function briefMarkdown(b) {
    const L = [`# Article brief: ${b.keyword}`, "", `_${b.kind}${b.topic && b.topic !== b.keyword ? ` · topic: ${b.topic}` : ""}_`, "", "## Why now (real data)", ...b.facts.map((f) => `- ${f}`)];
    if (b.secondary.length) L.push("", "## Secondary keywords", ...b.secondary.map((q) => `- ${q}`));
    if (b.questions.length) L.push("", "## Questions to answer (H2 / FAQ)", ...b.questions.map((q) => `- ${q}`));
    if (b.sources?.length) L.push("", "## Sources", ...b.sources.map((s) => `- [${s.title}](${s.url})`));
    L.push("", "## Internal links", ...(b.links.length ? b.links.map((p) => `- ${p.url}`) : ["- (link the closest resource category)"]));
    Object.entries(CHECKLIST).forEach(([k, v]) => L.push("", `## ${k}`, ...v.map((x) => `- [ ] ${x}`)));
    return L.join("\n");
  }
  let currentBrief = null;
  function openBrief(id) {
    const src = briefs.get(id); if (!src) return;
    currentBrief = makeBrief(src);
    $("#briefBody").innerHTML = briefHTML(currentBrief);
    $("#drawer").hidden = false;
    document.body.style.overflow = "hidden";
  }
  function closeBrief() { $("#drawer").hidden = true; document.body.style.overflow = ""; }
  const briefBtn = (id, label = "Brief") => `<button class="btn" data-brief="${esc(id)}">${label}</button>`;

  // brief sources from each data type
  function srcTrend(t) {
    const m = t.design;
    return { id: t.id, kind: "Google trend (design-related)", keyword: m && m.in === "related" ? m.query : t.keyword, topic: t.keyword,
      facts: [`“${t.keyword}”: ${vol(t.searches)} Google searches, ${pct(t.increase_pct)}, started ${dur(hoursAgo(t.started_at))} ago (${t.active ? "still trending" : "ended"}) in ${COUNTRY[t.country] || t.country}.`,
        m ? `Design match: ${m.in === "title" ? "trend title" : "Google related query"} “${m.query}”.` : ""].filter(Boolean),
      related: t.related_queries, suggestions: m?.matching_queries || [] };
  }
  function srcAngle(a) {
    return { id: a.id, kind: "Design angle on a real trend", keyword: a.design_suggestions[0], topic: a.keyword,
      facts: [`Trend “${a.keyword}”: ${vol(a.searches)} Google searches, ${pct(a.increase_pct)}, started ${dur(hoursAgo(a.started_at))} ago in ${a.countries.map((c) => COUNTRY[c] || c).join(", ")}.`,
        `Google autocomplete returns ${a.suggestion_count} design searches for it: ${a.design_suggestions.slice(0, 5).join(", ")}.`],
      related: a.related_queries, suggestions: a.design_suggestions };
  }
  function srcNews(n) {
    return { id: n.id, kind: "Fresh design news", keyword: n.headline, topic: n.design.term,
      facts: [`Published ${dur(hoursAgo(n.published_at))} ago by ${n.publisher}.`, `Matched design term: ${n.design.term} (${n.design.group}).`],
      sources: [{ title: n.headline, url: n.url }] };
  }
  function srcReddit(p) {
    return { id: p.id, kind: "Reddit discussion", keyword: p.title, topic: p.subreddit,
      facts: [`r/${p.subreddit}, posted ${dur(hoursAgo(p.posted_at))} ago${p.upvotes != null ? `, ${p.upvotes} upvotes, ${p.comments} comments` : ""}.`],
      sources: [{ title: p.title, url: p.url }] };
  }
  function srcDemand(ev, d) {
    return { id: `${ev.id}-${d.query}`, kind: `Seasonal: ${ev.name}`, keyword: d.query, topic: ev.name,
      facts: [`${ev.name}${ev.approx ? " (≈ date)" : ""} is on ${fmtDate(ev.date)}, ${ev.days_left} days away. Publish by ${fmtDate(ev.publish_by)} to rank before the peak.`,
        `Google autocomplete returns ${d.count} searches for “${d.query}”: ${d.suggestions.slice(0, 5).join(", ")}.`],
      suggestions: d.suggestions };
  }
  function srcQuestion(q) {
    return { id: q.id, kind: "Evergreen question (Google autocomplete)", keyword: q.question, topic: q.seed,
      facts: [`Google suggests this as #${q.rank} for “${q.seed}…”.`], suggestions: [q.question] };
  }

  // ================================================================ TODAY
  function renderToday() {
    const t = trends[4], p = planner;
    if (!t && !p) { $("#picks").innerHTML = '<div class="empty">Loading today\'s data… the first load can take up to 30 seconds.</div>'; return; }
    const cards = [];

    // --- fast pick
    let fast = null; const fastAlts = [];
    if (t) {
      const dt = t.google_trends.filter((x) => x.active && x.searches >= 1000 && !x.covered);
      const ang = t.design_angles.filter((x) => !x.covered);
      const news = t.google_news.filter((n) => !n.covered && hoursAgo(n.published_at) <= 12);
      const pool = [
        ...dt.map((x) => ({ src: srcTrend(x), rule: "Rule 1: an active design-related Google trend with 1K+ searches." })),
        ...ang.map((x) => ({ src: srcAngle(x), rule: "Rule 2: no design trend right now, so this is the biggest active trend where Google autocomplete shows real design searches." })),
        ...news.map((x) => ({ src: srcNews(x), rule: "Rule 3: no trend or angle available, so this is the newest uncovered design news story (under 12 hours old)." })),
      ];
      fast = pool[0]; fastAlts.push(...pool.slice(1, 4));
    }
    cards.push(pickCard("Fast article · traffic now", fast, fastAlts, t ? "Nothing qualifies right now. Check the Trends tab later today." : "Loading trends…"));

    // --- planned pick
    let plan = null; const planAlts = [];
    if (p) {
      const order = { "publish-now": 0, "last-minute": 1, plan: 2 };
      const evs = p.events.filter((e) => e.status !== "plan").sort((a, b) => order[a.status] - order[b.status] || a.days_left - b.days_left);
      const demands = [];
      evs.forEach((e) => e.demand.filter((d) => !d.covered).forEach((d) => demands.push({ e, d })));
      demands.sort((x, y) => order[x.e.status] - order[y.e.status] || y.d.count - x.d.count);
      const pool = [
        ...demands.map(({ e, d }) => ({ src: srcDemand(e, d), rule: e.status === "publish-now"
          ? "Rule 1: a seasonal event inside its publish window, with the most real Google design searches you haven't covered."
          : "Rule 2: an event that is close (last minute). Short posts can still catch late searchers." })),
        ...p.questions.filter((q) => !q.covered && q.group).map((q) => ({ src: srcQuestion(q), rule: "Rule 3: no seasonal gap, so this is the top uncovered design question from Google autocomplete." })),
      ];
      plan = pool[0]; planAlts.push(...pool.slice(1, 4));
    }
    cards.push(pickCard("Planned article · traffic later", plan, planAlts, p ? "No gaps found. Check the Questions tab." : "Loading planner…"));
    $("#picks").innerHTML = cards.join("");
  }
  function pickCard(label, pick, alts, emptyMsg) {
    if (!pick) return `<div class="pick"><div class="label">${esc(label)}</div><div class="muted">${esc(emptyMsg)}</div></div>`;
    briefs.set(pick.src.id, pick.src); alts.forEach((a) => briefs.set(a.src.id, a.src));
    return `<div class="pick">
      <div class="label">${esc(label)}</div>
      <div class="title">${esc(pick.src.keyword)}</div>
      <div class="muted">${esc(pick.src.kind)}${pick.src.topic && pick.src.topic !== pick.src.keyword ? ` · ${esc(pick.src.topic)}` : ""}</div>
      <ul class="why">${pick.src.facts.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
      <div class="why"><i>${esc(pick.rule)}</i></div>
      <div class="actions">${briefBtn(pick.src.id, "Open brief")}<a class="btn" href="https://www.google.com/search?q=${encodeURIComponent(pick.src.keyword)}" target="_blank" rel="noopener">Google results</a></div>
      ${alts.length ? `<div class="alts">Other options: ${alts.map((a) => `<a href="#" data-brief="${esc(a.src.id)}">${esc(a.src.keyword)}</a>`).join(" · ")}</div>` : ""}
    </div>`;
  }

  // ================================================================ TRENDS
  const sorters = {
    searches: (a, b) => b.searches - a.searches || (b.increase_pct || 0) - (a.increase_pct || 0),
    increase: (a, b) => (b.increase_pct || 0) - (a.increase_pct || 0) || b.searches - a.searches,
    started: (a, b) => Date.parse(b.started_at) - Date.parse(a.started_at),
  };
  const trendOk = (t, ignoreMin) => (ignoreMin || t.searches >= state.minSearches) && (!state.country || t.country === state.country || (t.countries || []).includes(state.country))
    && (!state.activeOnly || t.active) && inWin(t.started_at);
  const sortTh = (key, label, cls = "") => `<th class="${cls} sortable ${state.sort === key ? "sorted" : ""}" data-sort="${key}">${label} ${state.sort === key ? "↓" : ""}</th>`;

  function trendTable(list, withMatch) {
    const cols = withMatch ? 9 : 7;
    return `<thead><tr><th>Trend</th>${sortTh("searches", "Searches", "num")}${sortTh("increase", "Increase", "num")}${sortTh("started", "Started")}<th>Status</th><th>Country</th>
      ${withMatch ? "<th>Why it matched</th><th>On your site</th><th></th>" : "<th>Google category</th>"}</tr></thead><tbody>` +
      list.map((t) => {
        const age = hoursAgo(t.started_at), m = t.design;
        if (withMatch) briefs.set(t.id, srcTrend(t));
        const status = t.active ? '<span class="pill active">● Active</span>'
          : `<span class="pill">Ended</span><div class="muted">lasted ${dur((Date.parse(t.ended_at) - Date.parse(t.started_at)) / 36e5)}</div>`;
        return `<tr class="main-row" data-id="${esc(t.id)}">
          <td><div class="kw">${esc(t.keyword)}</div><div class="muted">${t.related_count} related queries · click for details</div></td>
          <td class="num"><b>${vol(t.searches)}</b></td><td class="num up">${pct(t.increase_pct)}</td>
          <td class="nowrap" title="${esc(exact(t.started_at))}"><span class="pill ${age <= 2 ? "hot" : ""}">${dur(age)} ago</span></td>
          <td>${status}</td><td class="nowrap">${COUNTRY[t.country] || t.country}</td>
          ${withMatch ? `<td><span class="pill match">${esc(m.group)}</span><div class="muted">${m.in === "title" ? "in the trend" : "Google related query"}: “${highlight(m.query, m.term)}”</div></td><td>${covered(t.covered)}</td><td>${briefBtn(t.id)}</td>`
            : `<td class="muted">${esc(t.google_categories.join(", ") || "–")}</td>`}
        </tr>${open.has(t.id) ? relatedRow(t.related_queries, t.related_count, new Set((m?.matching_queries || []).map((x) => x.toLowerCase())), cols) : ""}`;
      }).join("") + "</tbody>";
  }
  function relatedRow(list, total, hits, cols, title = "What people searched (Google's related queries)") {
    return `<tr class="detail"><td colspan="${cols}"><div class="detail-inner"><div><h4>${title}</h4><div class="chips">${
      list.map((r) => `<span class="chip ${hits.has(r.toLowerCase()) ? "hit" : ""}" data-copy="${esc(r)}" title="Click to copy">${esc(r)}</span>`).join("") || '<span class="muted">None listed.</span>'}</div>
      ${total > list.length ? `<div class="muted">+ ${total - list.length} more on Google Trends</div>` : ""}</div></div></td></tr>`;
  }
  function angleTable(list) {
    return `<thead><tr><th>Trend</th>${sortTh("searches", "Searches", "num")}${sortTh("increase", "Increase", "num")}${sortTh("started", "Started")}<th>Countries</th><th>Google also suggests (design)</th><th>On your site</th><th></th></tr></thead><tbody>` +
      list.map((a) => {
        briefs.set(a.id, srcAngle(a));
        return `<tr class="main-row" data-id="${esc(a.id)}">
          <td><div class="kw">${esc(a.keyword)}</div><div class="muted">${esc(a.google_categories.join(", "))}</div></td>
          <td class="num"><b>${vol(a.searches)}</b></td><td class="num up">${pct(a.increase_pct)}</td>
          <td class="nowrap"><span class="pill ${hoursAgo(a.started_at) <= 2 ? "hot" : ""}">${dur(hoursAgo(a.started_at))} ago</span></td>
          <td class="muted">${a.countries.map((c) => COUNTRY[c] || c).join(", ")}</td>
          <td><div class="chips">${a.design_suggestions.slice(0, 4).map((s) => `<span class="chip hit" data-copy="${esc(s)}">${esc(s)}</span>`).join("")}</div>
            ${a.suggestion_count > 4 ? `<div class="muted">+${a.suggestion_count - 4} more · click row</div>` : ""}</td>
          <td>${covered(a.covered)}</td><td>${briefBtn(a.id)}</td>
        </tr>${open.has(a.id) ? relatedRow(a.design_suggestions, a.design_suggestions.length, new Set(), 8, "Design searches Google suggests for this trend") : ""}`;
      }).join("") + "</tbody>";
  }

  function renderTrends() {
    syncControls();
    const d = trends[fetchHours()];
    if (!d) {
      ["#angleTable", "#gtTable", "#newsTable", "#redditTable"].forEach((s) => { $(s).innerHTML = ""; });
      $("#angleEmpty").innerHTML = `<div class="empty">Fetching live data from Google (${WIN_LABEL[fetchHours()].replace("in the ", "")})… up to 40 seconds the first time.</div>`;
      ["#gtEmpty", "#newsEmpty", "#redditEmpty"].forEach((s) => { $(s).innerHTML = ""; }); $("#summary").innerHTML = "";
      return;
    }
    const wl = WIN_LABEL[state.win];
    const allDesign = d.google_trends.filter((t) => trendOk(t, true));
    const design = allDesign.filter((t) => t.searches >= state.minSearches).sort(sorters[state.sort]);
    const angles = d.design_angles.filter((a) => trendOk(a)).sort(sorters[state.sort]);
    const news = d.google_news.filter((n) => inWin(n.published_at));
    const rd = d.reddit.filter((p) => inWin(p.posted_at));
    const rs = d.status.reddit || {};
    const scanned = state.country ? (d.scanned.by_country[state.country] || 0) : d.scanned.total;

    $("#summary").innerHTML = [
      { n: scanned.toLocaleString(), l: `Google trends checked ${wl}` },
      { n: angles.length, l: "Trends with real design searches", cls: angles.length ? "good" : "zero" },
      { n: design.length, l: `Design trends with ${state.minSearches ? vol(state.minSearches) : "any"} searches`, cls: design.length ? "good" : "zero" },
      { n: news.length, l: `Design news ${wl}`, cls: news.length ? "good" : "zero" },
    ].map((s) => `<div class="stat ${s.cls || ""}"><div class="n">${s.n}</div><div class="l">${s.l}</div></div>`).join("");

    $("#angleTable").innerHTML = angles.length ? angleTable(angles) : "";
    $("#angleEmpty").innerHTML = angles.length ? "" : `<div class="empty">None of the biggest ${state.minSearches ? vol(state.minSearches) : ""} active trends ${wl} has design searches in Google's autocomplete right now.</div>`;

    $("#gtTable").innerHTML = design.length ? trendTable(design, true) : "";
    const lower = allDesign.length - design.length;
    $("#gtEmpty").innerHTML = design.length ? "" : `<div class="empty"><b>No design-related search is trending on Google with ${vol(state.minSearches)} searches ${wl}.</b>
      Google listed ${scanned.toLocaleString()} trends and none mention a design term at this volume. This is normal; use the design angles above instead.
      <div class="actions">${lower > 0 ? `<button class="btn" data-set='{"minSearches":0}'>Show ${lower} lower-volume design trend${lower > 1 ? "s" : ""}</button>` : ""}
      ${state.win < 168 ? `<button class="btn" data-set='{"win":168}'>Check past 7 days</button>` : ""}</div></div>`;

    $("#otherBlock").hidden = !state.showOther;
    if (state.showOther) $("#otherTable").innerHTML = trendTable(d.google_trends_other.filter((t) => trendOk(t)).sort(sorters[state.sort]).slice(0, 100), false);

    $("#newsTable").innerHTML = news.length ? `<thead><tr><th>Headline</th><th>Publisher</th><th>Published</th><th>Topic</th><th>On your site</th><th></th></tr></thead><tbody>` +
      news.map((n) => { briefs.set(n.id, srcNews(n)); return `<tr>
        <td><a class="kw" href="${esc(n.url)}" target="_blank" rel="noopener">${highlight(n.headline, n.design.term)}</a></td>
        <td class="muted">${esc(n.publisher)}</td>
        <td class="nowrap" title="${esc(exact(n.published_at))}"><span class="pill ${hoursAgo(n.published_at) <= 2 ? "hot" : ""}">${dur(hoursAgo(n.published_at))} ago</span></td>
        <td><span class="pill match">${esc(n.design.group)}</span></td><td>${covered(n.covered)}</td><td>${briefBtn(n.id)}</td></tr>`; }).join("") + "</tbody>" : "";
    $("#newsEmpty").innerHTML = news.length ? "" : `<div class="empty">No design news published ${wl}.</div>`;

    $("#redditTable").innerHTML = rd.length ? `<thead><tr><th>Post</th><th>Subreddit</th><th class="num">Upvotes</th><th class="num">Comments</th><th class="num">Upvotes/h</th><th>Posted</th><th></th></tr></thead><tbody>` +
      rd.map((p) => { briefs.set(p.id, srcReddit(p)); return `<tr><td><a class="kw" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></td>
        <td class="muted">r/${esc(p.subreddit)}</td><td class="num">${p.upvotes ?? "–"}</td><td class="num">${p.comments ?? "–"}</td><td class="num">${p.upvotes_per_hour ?? "–"}</td>
        <td class="nowrap">${dur(hoursAgo(p.posted_at))} ago</td><td>${briefBtn(p.id)}</td></tr>`; }).join("") + "</tbody>" : "";
    $("#redditEmpty").innerHTML = rd.length ? "" : rs.needs_keys
      ? `<div class="empty"><b>Reddit blocks anonymous server requests, so this needs free Reddit API keys.</b><ol>
          <li>Open <a href="https://www.reddit.com/prefs/apps" target="_blank" rel="noopener">reddit.com/prefs/apps</a> → “create another app” → type <b>script</b>, redirect URL <code>http://localhost</code>.</li>
          <li>Vercel → designerslab-trends → Settings → Environment Variables: add <code>REDDIT_CLIENT_ID</code> and <code>REDDIT_CLIENT_SECRET</code>, then redeploy.</li></ol></div>`
      : `<div class="empty">No new posts ${wl}.</div>`;
  }

  // ================================================================ SEASONAL
  const STATUS_LABEL = { "publish-now": "Publish now", "last-minute": "Last minute", plan: "Plan ahead" };
  function renderSeasonal() {
    if (!planner) { $("#seasonTable").innerHTML = ""; $("#seasonEmpty").innerHTML = '<div class="empty">Loading the planner… (about 10 seconds)</div>'; return; }
    const evs = planner.events;
    $("#seasonEmpty").innerHTML = evs.length ? "" : '<div class="empty">No events in the next 120 days.</div>';
    $("#seasonTable").innerHTML = `<thead><tr><th>Event</th><th>Date</th><th class="num">Days left</th><th>Publish by</th><th>Status</th><th>Real Google design searches</th><th class="num">Not covered</th></tr></thead><tbody>` +
      evs.map((e) => {
        e.demand.forEach((d) => briefs.set(`${e.id}-${d.query}`, srcDemand(e, d)));
        const top = e.demand.slice(0, 4);
        return `<tr class="main-row" data-id="${esc(e.id)}">
          <td><div class="kw">${esc(e.name)}</div><div class="muted">click for every search</div></td>
          <td class="nowrap">${e.approx ? "≈ " : ""}${fmtDate(e.date)}</td><td class="num">${e.days_left}</td>
          <td class="nowrap">${fmtDate(e.publish_by)}</td>
          <td><span class="pill status-pill ${e.status}">${STATUS_LABEL[e.status]}</span></td>
          <td>${top.length ? `<div class="chips">${top.map((d) => `<span class="chip ${d.covered ? "" : "hit"}" data-brief="${esc(`${e.id}-${d.query}`)}" title="${d.count} real suggestions · click for a brief">${esc(d.query)} · ${d.count}</span>`).join("")}</div>` : '<span class="muted">Google returned no design suggestions</span>'}</td>
          <td class="num">${e.uncovered}</td>
        </tr>${open.has(e.id) ? `<tr class="detail"><td colspan="7"><div class="detail-inner">${e.demand.map((d) => `
          <div><h4>${esc(d.query)} · ${d.count} suggestions ${d.covered ? `· <a href="${esc(d.covered)}" target="_blank" rel="noopener">covered ↗</a>` : ""} ${briefBtn(`${e.id}-${d.query}`)}</h4>
          <div class="chips">${d.suggestions.map((s) => `<span class="chip" data-copy="${esc(s)}">${esc(s)}</span>`).join("")}</div></div>`).join("") || '<span class="muted">No suggestions.</span>'}</div></td></tr>` : ""}`;
      }).join("") + "</tbody>";
  }

  // ================================================================ QUESTIONS
  function renderQuestions() {
    if (!planner) { $("#qTable").innerHTML = ""; $("#qEmpty").innerHTML = '<div class="empty">Loading questions…</div>'; return; }
    $("#qUncovered").checked = state.qUncovered;
    const f = ($("#qSearch").value || "").toLowerCase();
    const qs = planner.questions.filter((q) => (!state.qUncovered || !q.covered) && (!f || q.question.toLowerCase().includes(f)));
    $("#qEmpty").innerHTML = qs.length ? "" : '<div class="empty">No questions match.</div>';
    $("#qTable").innerHTML = qs.length ? `<thead><tr><th>Question people search</th><th>Seed</th><th class="num">Google rank</th><th>Topic</th><th>On your site</th><th></th></tr></thead><tbody>` +
      qs.map((q) => { briefs.set(q.id, srcQuestion(q)); return `<tr><td class="kw">${esc(q.question)}</td><td class="muted">${esc(q.seed)}…</td><td class="num">#${q.rank}</td>
        <td>${q.group ? `<span class="pill match">${esc(q.group)}</span>` : '<span class="muted">general</span>'}</td><td>${covered(q.covered)}</td><td>${briefBtn(q.id)}</td></tr>`; }).join("") + "</tbody>" : "";
  }

  // ================================================================ AUDIT
  function renderAudit() {
    if (!audit) { $("#auditTable").innerHTML = ""; $("#auditPages").innerHTML = ""; $("#auditSummary").innerHTML = ""; $("#auditEmpty").innerHTML = '<div class="empty">Running the live audit… (about 10 seconds)</div>'; return; }
    $("#auditEmpty").innerHTML = "";
    const s = audit.summary;
    $("#auditSummary").innerHTML = [
      { n: s.fail, l: "Must fix", cls: s.fail ? "fail" : "good" }, { n: s.warn, l: "Should improve", cls: s.warn ? "warn" : "good" },
      { n: s.pass, l: "Passing", cls: "good" }, { n: audit.posts.length + 1, l: `Pages checked · ${dur(hoursAgo(audit.generated_at))} ago` },
    ].map((x) => `<div class="stat ${x.cls || ""}"><div class="n">${x.n}</div><div class="l">${x.l}</div></div>`).join("");
    $("#auditTable").innerHTML = `<thead><tr><th>Result</th><th>Area</th><th>Check</th><th>Measured</th><th>How to fix</th></tr></thead><tbody>` +
      audit.checks.map((c) => `<tr><td><span class="res ${c.result}">${c.result}</span></td><td class="nowrap">${esc(c.area)}</td><td class="kw">${esc(c.check)}</td>
        <td class="muted">${esc(c.detail)}</td><td>${esc(c.fix) || '<span class="muted">—</span>'}</td></tr>`).join("") + "</tbody>";
    const pages = [audit.home, ...audit.posts].filter((p) => p && !p.error);
    $("#auditPages").innerHTML = `<thead><tr><th>Page</th><th class="num">Title</th><th class="num">Meta desc.</th><th class="num">H1</th><th class="num">Words</th><th class="num">Images (no alt)</th><th>Schema</th><th class="num">Load</th></tr></thead><tbody>` +
      pages.map((p) => `<tr><td><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.url.replace(/^https?:\/\/[^/]+/, "") || "/")}</a></td>
        <td class="num">${p.title_len}</td><td class="num">${p.description_len}</td><td class="num">${p.h1.length}</td><td class="num">${p.words.toLocaleString()}</td>
        <td class="num">${p.images} (${p.images_no_alt})</td><td class="muted">${esc(p.schema.join(", "))}</td><td class="num">${p.ms} ms</td></tr>`).join("") + "</tbody>";
  }

  // ================================================================ shell
  function syncControls() {
    $$("#windowSeg button").forEach((b) => b.classList.toggle("active", +b.dataset.win === state.win));
    $("#minSearches").value = String(state.minSearches);
    $("#country").value = state.country;
    $("#activeOnly").checked = state.activeOnly;
    $("#showOther").checked = state.showOther;
  }
  function fillCountries(d) {
    const sel = $("#country"); if (sel.options.length > 1) return;
    sel.innerHTML = `<option value="">All countries</option>` + d.countries.map((c) => `<option value="${c}">${COUNTRY[c] || c}</option>`).join("");
    sel.value = state.country;
  }
  function render() {
    $$("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
    $$(".panel").forEach((p) => { p.hidden = p.id !== "panel-" + state.tab; });
    const t = trends[fetchHours()] || trends[4];
    const ts = state.tab === "audit" ? audit?.generated_at : state.tab === "seasonal" || state.tab === "questions" ? planner?.generated_at : t?.generated_at;
    if (ts) { const a = hoursAgo(ts); $("#updatedText").textContent = `Data from ${dur(a)} ago`; $("#updatedText").title = exact(ts); $("#liveDot").className = "dot " + (a < 0.5 ? "live" : "stale"); }
    else { $("#updatedText").textContent = "Loading…"; }
    ({ today: renderToday, trends: renderTrends, seasonal: renderSeasonal, questions: renderQuestions, audit: renderAudit }[state.tab] || (() => {}))();
  }
  function ensure() {
    if (state.tab === "today") { loadTrends(4); loadPlanner(); }
    if (state.tab === "trends") loadTrends(fetchHours());
    if (state.tab === "seasonal" || state.tab === "questions") loadPlanner();
    if (state.tab === "audit") loadAudit();
    render();
  }
  function setState(patch) { Object.assign(state, patch); store.set("state", state); ensure(); }

  $("#tabs").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) { setState({ tab: b.dataset.tab }); window.scrollTo(0, 0); } });
  $("#windowSeg").addEventListener("click", (e) => { const b = e.target.closest("button[data-win]"); if (b) setState({ win: +b.dataset.win }); });
  $("#minSearches").addEventListener("change", (e) => setState({ minSearches: +e.target.value }));
  $("#country").addEventListener("change", (e) => setState({ country: e.target.value }));
  $("#activeOnly").addEventListener("change", (e) => setState({ activeOnly: e.target.checked }));
  $("#showOther").addEventListener("change", (e) => setState({ showOther: e.target.checked }));
  $("#qUncovered").addEventListener("change", (e) => setState({ qUncovered: e.target.checked }));
  let qt; $("#qSearch").addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(renderQuestions, 150); });
  $("#refreshBtn").addEventListener("click", () => {
    if (state.tab === "audit") loadAudit(true);
    else if (state.tab === "seasonal" || state.tab === "questions") loadPlanner(true);
    else { loadTrends(state.tab === "today" ? 4 : fetchHours(), true); if (state.tab === "today") loadPlanner(true); }
  });
  $("#closeBrief").addEventListener("click", closeBrief);
  $("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer") closeBrief(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeBrief(); });
  $("#copyBrief").addEventListener("click", () => currentBrief && copy(briefMarkdown(currentBrief)));

  document.addEventListener("click", (e) => {
    const br = e.target.closest("[data-brief]"); if (br) { e.preventDefault(); openBrief(br.dataset.brief); return; }
    const c = e.target.closest("[data-copy]"); if (c) { copy(c.dataset.copy); return; }
    const s = e.target.closest("[data-set]"); if (s) { setState(JSON.parse(s.dataset.set)); return; }
    const th = e.target.closest("th[data-sort]"); if (th) { setState({ sort: th.dataset.sort }); return; }
    if (e.target.closest("a, button, .chip")) return;
    const tr = e.target.closest("tr.main-row");
    if (tr) { const id = tr.dataset.id; open.has(id) ? open.delete(id) : open.add(id); render(); }
  });

  ensure();
  setInterval(() => { if (state.tab === "today" || state.tab === "trends") loadTrends(state.tab === "today" ? 4 : fetchHours(), true); }, 10 * 60 * 1000);
})();
