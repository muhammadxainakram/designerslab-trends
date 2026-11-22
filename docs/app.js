(() => {
  "use strict";

  const DATA_URL = "data/trends.json";
  const PAGE = 40;
  const SRC_LABEL = {
    google_trends: "Google Trends",
    google_suggest: "Google Search",
    google_news: "Google News",
    reddit: "Reddit",
  };
  const CAT_LABEL = {
    fonts: "Fonts", seasonal: "Seasonal", device: "Device mockup", "design-tool": "Design tool",
    "logo-brand": "Logo / brand", resources: "Resources", "ai-prompts": "AI prompts",
    sports: "Sports", entertainment: "Entertainment", general: "General",
  };
  const GEO_LABEL = { US: "🇺🇸 US", GB: "🇬🇧 UK", CA: "🇨🇦 CA", AU: "🇦🇺 AU", IN: "🇮🇳 IN", PK: "🇵🇰 PK" };

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // ---------- per-viewer state (localStorage is optional) ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem("dltf:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("dltf:" + k, JSON.stringify(v)); } catch { /* ignore */ } },
  };
  let done = new Set(store.get("done", []));
  const state = Object.assign({
    tab: "top", win: 0, q: "", geo: "", cat: "", sort: "score",
    nicheOnly: true, activeOnly: false, hideCovered: true, newOnly: false,
  }, store.get("filters", {}));
  state.q = "";
  let data = null;
  let shown = PAGE;

  // ---------- helpers ----------
  const now = () => Date.now();
  const hoursAgo = (iso) => iso ? Math.max(0, (now() - Date.parse(iso)) / 36e5) : null;
  function dur(h) {
    if (h == null) return "";
    if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
    if (h < 48) { const H = Math.floor(h), M = Math.round((h - H) * 60); return M && H < 10 ? `${H}h ${M}m` : `${H}h`; }
    return `${Math.round(h / 24)}d`;
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1600);
  }
  async function copy(text) {
    try { await navigator.clipboard.writeText(text); toast("Copied"); }
    catch { const ta = document.createElement("textarea"); ta.value = text; document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove(); toast("Copied"); }
  }

  // Live age: Google Trends items keep running while active.
  function liveDuration(it) {
    if (it.source === "google_trends") {
      const start = Date.parse(it.started_at);
      const end = it.active ? now() : Date.parse(it.last_seen);
      return Math.max(0, (end - start) / 36e5);
    }
    return hoursAgo(it.started_at);
  }

  // ---------- filtering ----------
  function filtered() {
    if (!data) return [];
    const q = state.q.trim().toLowerCase();
    let items = data.items;

    if (state.tab === "done") items = items.filter((i) => done.has(i.id));
    else if (state.tab !== "top") items = items.filter((i) => i.source === state.tab);

    items = items.filter((it) => {
      if (state.tab !== "done" && done.has(it.id)) return false;
      if (state.win && (hoursAgo(it.started_at) ?? 999) > state.win) return false;
      if (state.geo && it.source === "google_trends" && it.geo !== state.geo) return false;
      if (state.geo && state.tab === "google_trends" && it.geo !== state.geo) return false;
      if (state.cat && it.category !== state.cat) return false;
      if (state.nicheOnly && it.relevance < 30) return false;
      if (state.activeOnly && !it.active) return false;
      if (state.hideCovered && it.covered && state.tab !== "done") return false;
      if (state.newOnly && it.source === "google_suggest" && !it.is_new) return false;
      if (state.newOnly && state.tab === "google_suggest" && !it.is_new) return false;
      if (q && !(it.keyword.toLowerCase().includes(q) || (it.ideas || []).some((x) => x.toLowerCase().includes(q)))) return false;
      return true;
    });

    const sorters = {
      score: (a, b) => b.score - a.score || (hoursAgo(a.started_at) - hoursAgo(b.started_at)),
      fresh: (a, b) => (hoursAgo(a.started_at) ?? 999) - (hoursAgo(b.started_at) ?? 999),
      long: (a, b) => liveDuration(b) - liveDuration(a),
      traffic: (a, b) => (b.traffic || b.upvotes || 0) - (a.traffic || a.upvotes || 0) || b.score - a.score,
    };
    items = [...items].sort(sorters[state.sort] || sorters.score);

    // Top picks: keep the mix diverse so autocomplete doesn't drown the rest.
    // Round-robin through sources (each already sorted by score), max 25 per source.
    if (state.tab === "top" && state.sort === "score") {
      const order = ["google_trends", "google_suggest", "google_news", "reddit"];
      const buckets = Object.fromEntries(order.map((s) => [s, items.filter((i) => i.source === s).slice(0, 25)]));
      const mixed = [];
      while (order.some((s) => buckets[s].length)) {
        const round = order.map((s) => buckets[s].shift()).filter(Boolean).sort((a, b) => b.score - a.score);
        mixed.push(...round);
      }
      items = mixed;
    }
    return items;
  }

  // ---------- rendering ----------
  function metaHTML(it) {
    const b = [];
    b.push(`<span class="badge src-${it.source}">${SRC_LABEL[it.source]}</span>`);
    const h = liveDuration(it);
    if (it.source === "google_trends") {
      if (it.geo) b.push(`<span>${GEO_LABEL[it.geo] || it.geo}</span>`);
      if (it.active) {
        b.push(`<span class="badge ${h <= 4 ? "hot" : ""}">🔥 Trending for ${dur(h)}</span>`);
      } else {
        b.push(`<span class="badge ended">Trended ${dur(h)}</span><span>ended ${dur(hoursAgo(it.last_seen))} ago</span>`);
      }
      if (it.traffic_label) b.push(`<span>${esc(it.traffic_label)} searches</span>`);
    } else if (it.source === "google_suggest") {
      if (it.is_new) b.push(`<span class="badge new">New · ${dur(h)} ago</span>`);
      else b.push(`<span>In Google suggestions for ${dur(h)}</span>`);
      b.push(`<span>#${it.rank} for “${esc(it.seed)}”</span>`);
    } else if (it.source === "google_news") {
      b.push(`<span class="${h <= 4 ? "badge hot" : ""}">${dur(h)} ago</span>`);
      if (it.publisher) b.push(`<span>${esc(it.publisher)}</span>`);
    } else if (it.source === "reddit") {
      b.push(`<span>r/${esc(it.subreddit)}</span>`);
      b.push(`<span class="${h <= 4 ? "badge hot" : ""}">${dur(h)} ago</span>`);
      if (it.upvotes != null) b.push(`<span>▲ ${it.upvotes} · 💬 ${it.comments}</span>`);
      if (it.is_question) b.push(`<span class="badge new">Question</span>`);
    }
    if (it.category && it.category !== "general") b.push(`<span class="badge">${CAT_LABEL[it.category] || it.category}</span>`);
    if (it.covered) b.push(`<span class="badge covered">Covered</span>`);
    return b.join("");
  }

  function bodyHTML(it) {
    const q = encodeURIComponent(it.keyword);
    const parts = [];
    if (it.ideas?.length) {
      parts.push(`<div><h4>Article ideas</h4><ul class="ideas">${it.ideas.map((x) =>
        `<li><span>${esc(x)}</span><button class="copy" data-copy="${esc(x)}">Copy</button></li>`).join("")}</ul></div>`);
    }
    if (it.news?.length) {
      parts.push(`<div><h4>Why it's trending</h4><ul class="news">${it.news.map((n) =>
        `<li><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a> <span class="kv">· ${esc(n.source)}</span></li>`).join("")}</ul></div>`);
    }
    if (it.covered) {
      parts.push(`<div class="kv">Already on your site: <a href="${esc(it.covered.url)}" target="_blank" rel="noopener">${esc(it.covered.url.replace(/^https?:\/\//, ""))}</a>. Refresh that post with the new angle.</div>`);
    }
    if (it.niche_hits?.length) parts.push(`<div class="kv">Niche match: ${it.niche_hits.map(esc).join(", ")} · relevance ${it.relevance}/100</div>`);

    const acts = [];
    if (it.source === "google_news" || it.source === "reddit") acts.push(`<a class="btn primary" href="${esc(it.url)}" target="_blank" rel="noopener">Open ${it.source === "reddit" ? "post" : "article"}</a>`);
    acts.push(`<a class="btn ${acts.length ? "" : "primary"}" href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">Google results</a>`);
    acts.push(`<a class="btn" href="${esc(it.trends_url || `https://trends.google.com/trends/explore?date=now%207-d&q=${q}`)}" target="_blank" rel="noopener">Google Trends</a>`);
    acts.push(`<a class="btn" href="https://www.google.com/search?q=site%3Adesignerslab.io+${q}" target="_blank" rel="noopener">Check my site</a>`);
    acts.push(`<button class="btn" data-brief="1">Copy brief</button>`);
    acts.push(`<button class="btn" data-done="1">${done.has(it.id) ? "Undo written" : "✓ Mark written"}</button>`);
    parts.push(`<div class="actions">${acts.join("")}</div>`);
    return parts.join("");
  }

  function brief(it) {
    const lines = [`Keyword: ${it.keyword}`, `Source: ${SRC_LABEL[it.source]}${it.geo ? " (" + it.geo + ")" : ""}`,
      `Opportunity score: ${it.score}/100 · relevance ${it.relevance}/100`];
    const h = liveDuration(it);
    if (h != null) lines.push(`${it.source === "google_trends" ? "Trending for" : "Age"}: ${dur(h)}`);
    if (it.traffic_label) lines.push(`Search volume: ${it.traffic_label}`);
    if (it.ideas?.length) lines.push("", "Title ideas:", ...it.ideas.map((x) => "- " + x));
    if (it.news?.length) lines.push("", "Context:", ...it.news.map((n) => `- ${n.title} (${n.url})`));
    if (it.url) lines.push("", `Link: ${it.url}`);
    return lines.join("\n");
  }

  function render() {
    const items = filtered();
    const list = $("#list");
    list.innerHTML = "";
    const tpl = $("#rowTpl");
    items.slice(0, shown).forEach((it) => {
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.dataset.id = it.id;
      if (done.has(it.id)) node.classList.add("done");
      const sc = $(".score", node);
      sc.textContent = it.score;
      sc.classList.add(it.score >= 65 ? "s-high" : it.score >= 45 ? "s-mid" : "s-low");
      sc.title = "Opportunity score (0-100)";
      $(".kw", node).textContent = it.keyword;
      $(".meta", node).innerHTML = metaHTML(it);
      list.append(node);
    });
    if (!items.length) {
      list.innerHTML = `<div class="empty">${data ? "Nothing matches these filters. Try a wider time window or turn off “Design niche only”." : "Loading trends…"}</div>`;
    }
    $("#count").textContent = data ? `${items.length} ${items.length === 1 ? "result" : "results"}${state.win ? ` that started in the last ${state.win}h` : ""}` : "";
    $("#more").hidden = items.length <= shown;
    renderTabs();
  }

  function renderTabs() {
    if (!data) return;
    $$("#tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === state.tab);
      const t = b.dataset.tab;
      let n = t === "top" ? null : t === "done" ? done.size : data.counts?.[t];
      b.innerHTML = b.textContent.replace(/\s*\d+$/, "") + (n != null ? `<span class="cnt">${n}</span>` : "");
    });
  }

  function renderStats() {
    const it = data.items;
    const fresh2 = it.filter((i) => i.source === "google_trends" && i.active && liveDuration(i) <= 2).length;
    const fresh4 = it.filter((i) => i.source === "google_trends" && i.active && liveDuration(i) <= 4).length;
    const newS = it.filter((i) => i.is_new).length;
    const good = it.filter((i) => i.score >= 75 && !i.covered && !done.has(i.id)).length;
    const S = [
      { n: good, l: "Strong opportunities (75+)", act: { tab: "top", win: 0 } },
      { n: fresh2, l: "Google trends < 2h old", hot: true, act: { tab: "google_trends", win: 2, nicheOnly: false, activeOnly: true } },
      { n: fresh4, l: "Google trends < 4h old", act: { tab: "google_trends", win: 4, nicheOnly: false, activeOnly: true } },
      { n: newS, l: "New Google suggestions", act: { tab: "google_suggest", win: 0, newOnly: true } },
    ];
    $("#stats").innerHTML = S.map((s, i) => `<button class="stat ${s.hot ? "hot" : ""}" data-i="${i}"><div class="n">${s.n}</div><div class="l">${s.l}</div></button>`).join("");
    $$("#stats .stat").forEach((el) => el.addEventListener("click", () => { Object.assign(state, S[+el.dataset.i].act); syncControls(); persist(); shown = PAGE; render(); }));
  }

  function renderHeader() {
    const h = hoursAgo(data.generated_at);
    $("#updatedText").textContent = `Updated ${dur(h)} ago`;
    $("#updatedText").title = new Date(data.generated_at).toLocaleString();
    $("#liveDot").className = "dot " + (h < 1.5 ? "live" : "stale");
    const st = data.status || {};
    const bad = Object.entries(st).filter(([k, v]) => k !== "site" && v && v.ok === false).map(([k]) => SRC_LABEL[k] || k);
    if (bad.length) $("#updatedText").textContent += ` · ${bad.join(", ")} unavailable`;
  }

  function fillSelects() {
    const geos = [...new Set(data.items.filter((i) => i.geo).map((i) => i.geo))].sort();
    $("#geo").innerHTML = `<option value="">All countries</option>` + geos.map((g) => `<option value="${g}">${GEO_LABEL[g] || g}</option>`).join("");
    const cats = [...new Set(data.items.map((i) => i.category))].sort();
    $("#cat").innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option value="${c}">${CAT_LABEL[c] || c}</option>`).join("");
    syncControls();
  }

  function syncControls() {
    $$("#windowSeg button").forEach((b) => b.classList.toggle("active", +b.dataset.win === state.win));
    $("#geo").value = state.geo; $("#cat").value = state.cat; $("#sort").value = state.sort; $("#q").value = state.q;
    ["nicheOnly", "activeOnly", "hideCovered", "newOnly"].forEach((k) => { $("#" + k).checked = !!state[k]; });
  }
  function persist() { const { q, ...rest } = state; store.set("filters", rest); }

  // ---------- events ----------
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    state.tab = b.dataset.tab; shown = PAGE; persist(); render();
  });
  $("#windowSeg").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-win]"); if (!b) return;
    state.win = +b.dataset.win; shown = PAGE; syncControls(); persist(); render();
  });
  ["geo", "cat", "sort"].forEach((id) => $("#" + id).addEventListener("change", (e) => { state[id] = e.target.value; shown = PAGE; persist(); render(); }));
  ["nicheOnly", "activeOnly", "hideCovered", "newOnly"].forEach((id) => $("#" + id).addEventListener("change", (e) => { state[id] = e.target.checked; shown = PAGE; persist(); render(); }));
  let qt; $("#q").addEventListener("input", (e) => { clearTimeout(qt); qt = setTimeout(() => { state.q = e.target.value; shown = PAGE; render(); }, 150); });
  $("#more").addEventListener("click", () => { shown += PAGE; render(); });
  $("#refreshBtn").addEventListener("click", () => load(true));

  $("#list").addEventListener("click", (e) => {
    const card = e.target.closest(".item"); if (!card) return;
    const it = data.items.find((x) => x.id === card.dataset.id); if (!it) return;
    const c = e.target.closest("[data-copy]"); if (c) { copy(c.dataset.copy); return; }
    if (e.target.closest("[data-brief]")) { copy(brief(it)); return; }
    if (e.target.closest("[data-done]")) {
      done.has(it.id) ? done.delete(it.id) : done.add(it.id);
      store.set("done", [...done]); toast(done.has(it.id) ? "Marked as written" : "Moved back"); renderStats(); render(); return;
    }
    const head = e.target.closest(".item-head");
    if (head) {
      const body = $(".item-body", card);
      const open = head.getAttribute("aria-expanded") === "true";
      head.setAttribute("aria-expanded", String(!open));
      if (!open && !body.innerHTML) body.innerHTML = bodyHTML(it);
      body.hidden = open;
    }
  });

  // ---------- load ----------
  async function load(manual) {
    const btn = $("#refreshBtn"); btn.classList.add("spin");
    try {
      const r = await fetch(`${DATA_URL}?t=${Math.floor(now() / 60000)}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const fresh = await r.json();
      if (!manual && data && fresh.generated_at === data.generated_at) { renderHeader(); return; }
      data = fresh;
      renderHeader(); renderStats(); fillSelects(); render();
      if (manual) toast("Data reloaded");
    } catch (err) {
      $("#updatedText").textContent = "Could not load data";
      if (!data) $("#list").innerHTML = `<div class="empty">No data yet. The first GitHub Actions run creates it within a few minutes.</div>`;
    } finally { btn.classList.remove("spin"); }
  }
  syncControls();
  load();
  setInterval(() => load(false), 5 * 60 * 1000);
  setInterval(() => { if (data) { renderHeader(); } }, 60 * 1000);
})();
