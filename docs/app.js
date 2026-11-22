(() => {
  "use strict";

  const COUNTRY = { US: "🇺🇸 US", GB: "🇬🇧 UK", CA: "🇨🇦 Canada", AU: "🇦🇺 Australia", IN: "🇮🇳 India", PK: "🇵🇰 Pakistan",
    NZ: "🇳🇿 New Zealand", IE: "🇮🇪 Ireland", ZA: "🇿🇦 South Africa", PH: "🇵🇭 Philippines", AE: "🇦🇪 UAE", SG: "🇸🇬 Singapore" };
  const WIN_LABEL = { 2: "in the past 2 hours", 4: "in the past 4 hours", 24: "in the past 24 hours", 48: "in the past 48 hours", 168: "in the past 7 days" };

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const store = {
    get(k, d) { try { const v = localStorage.getItem("dltf2:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("dltf2:" + k, JSON.stringify(v)); } catch { /* optional */ } },
  };
  const state = Object.assign({ win: 4, minSearches: 1000, country: "", activeOnly: false, showOther: false, sort: "searches" },
    store.get("state", {}));
  const cache = {};       // hours -> payload
  const open = new Set(); // expanded row ids

  // ---------- formatting ----------
  const now = () => Date.now();
  const hoursAgo = (iso) => (iso ? (now() - Date.parse(iso)) / 36e5 : null);
  function dur(h) {
    if (h == null) return "";
    if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
    if (h < 48) { const H = Math.floor(h), M = Math.round((h - H) * 60); return M && H < 10 ? `${H}h ${M}m` : `${H}h`; }
    return `${Math.round(h / 24)}d`;
  }
  function vol(n) {
    if (!n) return "–";
    if (n >= 1e6) return `${n / 1e6}M+`;
    if (n >= 1e3) return `${n / 1e3}K+`;
    return `${n}+`;
  }
  const pct = (p) => (p == null ? "–" : `+${Number(p).toLocaleString()}%`);
  const exact = (iso) => (iso ? new Date(iso).toLocaleString() : "");
  const fetchHours = () => (state.win === 2 ? 4 : state.win);
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
  function highlight(text, term) {
    const i = text.toLowerCase().indexOf(String(term).toLowerCase());
    if (i < 0) return esc(text);
    return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + term.length)) + "</mark>" + esc(text.slice(i + term.length));
  }

  // ---------- filtering ----------
  function inWindow(iso) {
    if (state.win !== 2) return true; // Google already limited the list to its own window
    return (hoursAgo(iso) ?? 999) <= 2;
  }
  function trendFilter(t, ignoreMin) {
    if (!ignoreMin && t.searches < state.minSearches) return false;
    if (state.country && t.country !== state.country) return false;
    if (state.activeOnly && !t.active) return false;
    return inWindow(t.started_at);
  }
  const sorters = {
    searches: (a, b) => b.searches - a.searches || (b.increase_pct || 0) - (a.increase_pct || 0),
    increase: (a, b) => (b.increase_pct || 0) - (a.increase_pct || 0) || b.searches - a.searches,
    started: (a, b) => Date.parse(b.started_at) - Date.parse(a.started_at),
  };

  // ---------- rendering ----------
  function trendRows(list, withMatch) {
    const head = `<thead><tr>
      <th>Trend</th>
      <th class="num sortable ${state.sort === "searches" ? "sorted" : ""}" data-sort="searches">Searches ${state.sort === "searches" ? "↓" : ""}</th>
      <th class="num sortable ${state.sort === "increase" ? "sorted" : ""}" data-sort="increase">Increase ${state.sort === "increase" ? "↓" : ""}</th>
      <th class="sortable ${state.sort === "started" ? "sorted" : ""}" data-sort="started">Started ${state.sort === "started" ? "↓" : ""}</th>
      <th>Status</th><th>Country</th>
      ${withMatch ? "<th>Why it matched</th><th>On your site</th>" : "<th>Google category</th>"}
    </tr></thead>`;
    const cols = withMatch ? 8 : 7;
    const body = list.map((t) => {
      const age = hoursAgo(t.started_at);
      const status = t.active
        ? `<span class="pill active">● Active</span>`
        : `<span class="pill">Ended</span><div class="muted">lasted ${dur((Date.parse(t.ended_at) - Date.parse(t.started_at)) / 36e5)}</div>`;
      const m = t.design;
      const why = m ? `<span class="pill match">${esc(m.group)}</span>
          <div class="muted">${m.in === "title" ? "in the trend" : "Google related query"}: “${highlight(m.query, m.term)}”${m.match_count > 1 ? ` · ${m.match_count} matching queries` : ""}</div>` : "";
      const site = t.covered ? `<a class="pill covered" href="${esc(t.covered)}" target="_blank" rel="noopener">Covered ↗</a>` : `<span class="muted">Not yet</span>`;
      const row = `<tr class="main-row" data-id="${esc(t.id)}">
        <td><div class="kw">${esc(t.keyword)}</div><div class="muted">${t.related_count} related queries · click for details</div></td>
        <td class="num"><b>${vol(t.searches)}</b></td>
        <td class="num up">${pct(t.increase_pct)}</td>
        <td class="nowrap" title="${esc(exact(t.started_at))}"><span class="pill ${age <= 2 ? "hot" : ""}">${dur(age)} ago</span></td>
        <td>${status}</td>
        <td class="nowrap">${COUNTRY[t.country] || t.country}</td>
        ${withMatch ? `<td>${why}</td><td>${site}</td>` : `<td class="muted">${esc(t.google_categories.join(", ") || "–")}</td>`}
      </tr>`;
      return row + (open.has(t.id) ? detailRow(t, cols) : "");
    }).join("");
    return head + `<tbody>${body}</tbody>`;
  }

  function detailRow(t, cols) {
    const hits = new Set((t.design?.matching_queries || []).map((q) => q.toLowerCase()));
    const q = encodeURIComponent(t.keyword);
    const date = state.win <= 4 ? "now%204-H" : state.win <= 24 ? "now%201-d" : "now%207-d";
    const chips = t.related_queries.map((r) => `<span class="chip ${hits.has(r.toLowerCase()) ? "hit" : ""}" data-copy="${esc(r)}" title="Click to copy">${esc(r)}</span>`).join("");
    return `<tr class="detail"><td colspan="${cols}"><div class="detail-inner">
      <div><h4>What people searched (Google's related queries)</h4><div class="chips">${chips || '<span class="muted">Google listed no related queries.</span>'}</div>
        ${t.related_count > t.related_queries.length ? `<div class="muted">+ ${t.related_count - t.related_queries.length} more on Google Trends</div>` : ""}</div>
      <div class="muted">Google category: ${esc(t.google_categories.join(", ") || "–")} · Started ${esc(exact(t.started_at))}${t.ended_at ? ` · Ended ${esc(exact(t.ended_at))}` : ""}</div>
      <div class="actions">
        <a class="btn" href="https://trends.google.com/trends/explore?date=${date}&geo=${t.country}&q=${q}" target="_blank" rel="noopener">Google Trends chart</a>
        <a class="btn" href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">Google results</a>
        <a class="btn" href="https://news.google.com/search?q=${q}%20when%3A1d&hl=en-US&gl=US&ceid=US%3Aen" target="_blank" rel="noopener">Google News</a>
        <a class="btn" href="https://www.google.com/search?q=site%3Adesignerslab.io+${q}" target="_blank" rel="noopener">Search my site</a>
        <button class="btn" data-copy="${esc(t.keyword)}">Copy keyword</button>
      </div></div></td></tr>`;
  }

  function newsRows(list) {
    if (!list.length) return "";
    return `<thead><tr><th>Headline</th><th>Publisher</th><th>Published</th><th>Matched term</th><th>On your site</th></tr></thead><tbody>` +
      list.map((n) => {
        const age = hoursAgo(n.published_at);
        return `<tr>
          <td><a class="kw" href="${esc(n.url)}" target="_blank" rel="noopener">${highlight(n.headline, n.design.term)}</a></td>
          <td class="muted">${esc(n.publisher)}</td>
          <td class="nowrap" title="${esc(exact(n.published_at))}"><span class="pill ${age <= 2 ? "hot" : ""}">${dur(age)} ago</span></td>
          <td><span class="pill match">${esc(n.design.group)}</span></td>
          <td>${n.covered ? `<a class="pill covered" href="${esc(n.covered)}" target="_blank" rel="noopener">Covered ↗</a>` : '<span class="muted">Not yet</span>'}</td>
        </tr>`;
      }).join("") + "</tbody>";
  }

  function redditRows(list) {
    if (!list.length) return "";
    return `<thead><tr><th>Post</th><th>Subreddit</th><th class="num">Upvotes</th><th class="num">Comments</th><th class="num">Upvotes / hour</th><th>Posted</th></tr></thead><tbody>` +
      list.map((p) => `<tr>
        <td><a class="kw" href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></td>
        <td class="muted nowrap">r/${esc(p.subreddit)}</td>
        <td class="num">${p.upvotes ?? "–"}</td><td class="num">${p.comments ?? "–"}</td><td class="num">${p.upvotes_per_hour ?? "–"}</td>
        <td class="nowrap" title="${esc(exact(p.posted_at))}">${dur(hoursAgo(p.posted_at))} ago</td>
      </tr>`).join("") + "</tbody>";
  }

  function render() {
    const data = cache[fetchHours()];
    syncControls();
    if (!data) return;
    const wl = WIN_LABEL[state.win];
    const nCountries = Object.keys(data.scanned.by_country).length;

    const allDesign = data.google_trends.filter((t) => trendFilter(t, true));
    const design = allDesign.filter((t) => t.searches >= state.minSearches).sort(sorters[state.sort]);
    const news = data.google_news.filter((n) => inWindow(n.published_at));
    const rd = data.reddit.filter((p) => inWindow(p.posted_at));
    const rdStatus = data.status.reddit || {};

    // summary
    const scannedCount = state.country ? (data.scanned.by_country[state.country] || 0) : data.scanned.total;
    $("#summary").innerHTML = [
      { n: scannedCount.toLocaleString(), l: `Google trends checked ${wl} (${state.country ? COUNTRY[state.country] : nCountries + " countries"})` },
      { n: design.length, l: `Design-related with ${state.minSearches ? vol(state.minSearches) : "any"} searches`, cls: design.length ? "good" : "zero" },
      { n: news.length, l: `Design news stories ${wl}`, cls: news.length ? "good" : "zero" },
      { n: rdStatus.needs_keys && !rd.length ? "—" : rd.length, l: rdStatus.needs_keys && !rd.length ? "Reddit posts (needs API keys)" : `Reddit posts ${wl}`, cls: rd.length ? "good" : "zero" },
    ].map((s) => `<div class="stat ${s.cls || ""}"><div class="n">${s.n}</div><div class="l">${s.l}</div></div>`).join("");

    // google trends (design)
    $("#gtTable").innerHTML = design.length ? trendRows(design, true) : "";
    const lower = allDesign.length - design.length;
    $("#gtEmpty").innerHTML = design.length ? "" : `<div class="empty">
      <b>No design-related search is trending on Google with ${vol(state.minSearches)} searches ${wl}.</b><br>
      Google listed ${scannedCount.toLocaleString()} trending searches in this window. None of them, or their related queries, mention fonts, logos, mockups, templates, Canva, Photoshop, AI images or other design terms at this volume.
      Design keywords rarely reach Google's trending list, so an empty table is a real result, not an error.
      ${lower > 0 ? `<br><br>There ${lower === 1 ? "is" : "are"} <b>${lower}</b> design-related trend${lower === 1 ? "" : "s"} with fewer searches.` : ""}
      <div class="actions">
        ${lower > 0 ? '<button class="btn" data-set=\'{"minSearches":0}\'>Show lower-volume design trends</button>' : ""}
        ${state.win < 168 ? '<button class="btn" data-set=\'{"win":168}\'>Check past 7 days</button>' : ""}
      </div></div>`;

    // other trends
    $("#otherBlock").hidden = !state.showOther;
    if (state.showOther) {
      const other = data.google_trends_other.filter((t) => trendFilter(t)).sort(sorters[state.sort]).slice(0, 100);
      $("#otherTable").innerHTML = other.length ? trendRows(other, false) : "";
    }

    // news
    $("#newsTable").innerHTML = newsRows(news);
    $("#newsEmpty").innerHTML = news.length ? "" : `<div class="empty">No design news published ${wl} in the Google News searches this tool runs.</div>`;

    // reddit
    $("#redditTable").innerHTML = redditRows(rd);
    $("#redditEmpty").innerHTML = rd.length ? "" : rdStatus.needs_keys
      ? `<div class="empty"><b>Reddit blocks anonymous requests from servers, so this needs free Reddit API keys.</b>
          <ol><li>Sign in to Reddit, open <a href="https://www.reddit.com/prefs/apps" target="_blank" rel="noopener">reddit.com/prefs/apps</a>, click “create another app”, choose <b>script</b> and use <code>http://localhost</code> as the redirect URL.</li>
          <li>In Vercel → designerslab-trends → Settings → Environment Variables, add <code>REDDIT_CLIENT_ID</code> (the code under the app name) and <code>REDDIT_CLIENT_SECRET</code>.</li>
          <li>Redeploy. Real posts, upvotes and comments will show here.</li></ol></div>`
      : `<div class="empty">No new posts ${wl} in the tracked design subreddits.</div>`;

    // header
    const age = hoursAgo(data.generated_at);
    $("#updatedText").textContent = `Data from ${dur(age)} ago`;
    $("#updatedText").title = exact(data.generated_at);
    $("#liveDot").className = "dot " + (age < 0.5 ? "live" : "stale");
  }

  function syncControls() {
    $$("#windowSeg button").forEach((b) => b.classList.toggle("active", +b.dataset.win === state.win));
    $("#minSearches").value = String(state.minSearches);
    $("#country").value = state.country;
    $("#activeOnly").checked = state.activeOnly;
    $("#showOther").checked = state.showOther;
  }
  function fillCountries(data) {
    const sel = $("#country");
    if (sel.options.length > 1) return;
    sel.innerHTML = `<option value="">All countries</option>` + data.countries.map((c) => `<option value="${c}">${COUNTRY[c] || c}</option>`).join("");
  }
  function setState(patch) { Object.assign(state, patch); store.set("state", state); ensureData(); }

  // ---------- loading ----------
  async function load(hours, force) {
    const btn = $("#refreshBtn"); btn.classList.add("spin");
    if (!cache[hours]) {
      $("#gtTable").innerHTML = ""; $("#gtEmpty").innerHTML = `<div class="empty">Fetching live data from Google Trends (${hours === 4 ? "past 4 hours" : WIN_LABEL[hours].replace("in the ", "")})… this can take up to 30 seconds the first time.</div>`;
      $("#updatedText").textContent = "Loading…";
    }
    try {
      let data = null;
      if (!location.hostname.endsWith("github.io")) {
        try {
          const r = await fetch(`/api/trends?hours=${hours}`);
          if (r.ok) data = await r.json();
        } catch { /* fall back */ }
      }
      if (!data || !data.scanned) {
        const r = await fetch(`data/trends-${hours}h.json?t=${Math.floor(now() / 60000)}`, { cache: "no-store" });
        if (!r.ok) throw new Error(r.status);
        data = await r.json();
      }
      cache[hours] = data;
      fillCountries(data);
      if (force) toast("Data reloaded");
    } catch {
      if (!cache[hours]) $("#gtEmpty").innerHTML = `<div class="empty">Couldn't load data right now. Press the reload button to try again.</div>`;
    } finally {
      btn.classList.remove("spin");
      if (fetchHours() === hours) render();
    }
  }
  function ensureData() { const h = fetchHours(); if (cache[h]) render(); else load(h); }

  // ---------- events ----------
  $("#windowSeg").addEventListener("click", (e) => { const b = e.target.closest("button[data-win]"); if (b) setState({ win: +b.dataset.win }); });
  $("#minSearches").addEventListener("change", (e) => setState({ minSearches: +e.target.value }));
  $("#country").addEventListener("change", (e) => setState({ country: e.target.value }));
  $("#activeOnly").addEventListener("change", (e) => setState({ activeOnly: e.target.checked }));
  $("#showOther").addEventListener("change", (e) => setState({ showOther: e.target.checked }));
  $("#refreshBtn").addEventListener("click", () => { delete cache[fetchHours()]; load(fetchHours(), true); });

  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-copy]"); if (c) { copy(c.dataset.copy); return; }
    const s = e.target.closest("[data-set]"); if (s) { setState(JSON.parse(s.dataset.set)); return; }
    const th = e.target.closest("th[data-sort]"); if (th) { setState({ sort: th.dataset.sort }); return; }
    if (e.target.closest("a, button")) return;
    const tr = e.target.closest("tr.main-row");
    if (tr) { const id = tr.dataset.id; open.has(id) ? open.delete(id) : open.add(id); render(); }
  });

  syncControls();
  ensureData();
  setInterval(() => load(fetchHours()), 10 * 60 * 1000);
})();
