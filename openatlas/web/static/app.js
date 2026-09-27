// OpenAtlas UI. Vanilla JS, no build step. All DOM is built with textContent (never
// innerHTML with data), so nothing fetched from the web can inject markup.
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const TYPE_LABEL = { email: "Email", username: "Username", name: "Person", phone: "Phone",
  domain: "Domain", url: "URL", ip: "IP", image: "Image", text: "Text", file: "File" };
const PURPOSES = ["Self-audit (my own footprint)", "Security research", "Due diligence", "Journalism", "CTF / training"];

const state = {
  catalog: { filters: [], actions: [] }, filter: "", selected: [], detected: null,
  forcedType: "", purpose: "", showTools: false, view: "investigate", activeCase: null, token: sessionStorage.getItem("oa-token") || "",
};

// ------------------------------------------------------------------ helpers
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false)
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), 2200); }
const safeUrl = (u) => { try { const x = new URL(u, location.href); return ["http:", "https:"].includes(x.protocol) ? x.href : null; } catch { return null; } };
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; } };
const fmtBytes = (b) => b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.round(b / 1e3) + " KB";
const shq = (s) => /^[\w@.+:/-]+$/.test(s) ? s : "'" + String(s).replace(/'/g, "'\\''") + "'";

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(state.token ? { "X-OpenAtlas-Token": state.token } : {}) };
  const r = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  if (r.status === 401) {
    const t = prompt("This OpenAtlas server needs its access token:");
    if (t) { state.token = t; sessionStorage.setItem("oa-token", t); return api(path, opts); }
  }
  if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch {} throw new Error(typeof d === "string" ? d : JSON.stringify(d)); }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

// Server-Sent Events over fetch (EventSource can't send the token header).
async function streamEvents(caseId, onEvent) {
  const r = await fetch(`/api/cases/${caseId}/events`, { headers: state.token ? { "X-OpenAtlas-Token": state.token } : {} });
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

// ------------------------------------------------------------------ navigation
function show(view) {
  state.view = view;
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  document.querySelectorAll("main > section").forEach((s) => s.classList.toggle("hidden", s.id !== "v-" + view));
  $("#view-title").textContent = { investigate: "Investigate", cases: "Cases", brain: "Brain", skills: "Skills", system: "System" }[view];
  if (view === "cases") loadCases();
  if (view === "brain") loadBrain();
  if (view === "skills") loadSkills();
  if (view === "system") loadSystem();
}
document.querySelectorAll(".nav").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
$("#theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next; try { localStorage.setItem("oa-theme", next); } catch {}
});

// ------------------------------------------------------------------ investigate: target + purpose
const qEl = $("#q");
let detectTimer;
qEl.addEventListener("input", () => { clearTimeout(detectTimer); detectTimer = setTimeout(detectType, 250); });
qEl.addEventListener("keydown", (e) => { if (e.key === "Enter") runSelected(); });
document.addEventListener("keydown", (e) => { if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); show("investigate"); qEl.focus(); } });

async function detectType() {
  const v = qEl.value.trim();
  if (!v) { state.detected = null; renderAll(); return; }
  try { state.detected = (await api(`/api/detect?q=${encodeURIComponent(v)}`)).target; } catch { state.detected = null; }
  if (!state.filter && !state.selected.length) state.filter = { email: "email", username: "username", name: "people",
    phone: "phone", domain: "web", url: "web", ip: "network", image: "images" }[currentType()] || "";
  renderAll();
}
const currentType = () => state.forcedType || (state.detected && state.detected.type) || "";

$("#type-btn").addEventListener("click", () => $("#types").classList.toggle("open"));
function renderTypes() {
  const box = $("#types"); box.replaceChildren();
  box.append(h("span", { class: "label", style: "align-self:center;margin-right:6px" }, "Treat as"));
  for (const t of ["", "name", "username", "email", "phone", "domain", "url", "ip", "image"])
    box.append(h("button", { class: "chip" + (state.forcedType === t ? " on" : ""),
      onclick: () => { state.forcedType = t; $("#types").classList.remove("open"); renderAll(); } }, t ? TYPE_LABEL[t] : "Auto-detect"));
  const t = currentType();
  $("#type-btn").textContent = t ? TYPE_LABEL[t] + (state.forcedType ? " *" : "") : "auto";
}

function renderPurposes() {
  const box = $("#purposes"); box.replaceChildren();
  for (const p of PURPOSES) box.append(h("button", { class: "chip" + (state.purpose === p ? " on" : ""),
    onclick: () => { state.purpose = state.purpose === p ? "" : p; $("#purpose").value = ""; renderAll(); } }, p.split(" (")[0]));
}
$("#purpose").addEventListener("input", (e) => { state.purpose = e.target.value; renderPurposes(); renderCommand(); });

// ------------------------------------------------------------------ filters + tiles
function applies(a, t) { return !t || a.inputs.includes(t) || (a.kind === "tool" && a.inputs.includes("text")); }
function visibleActions() { return state.catalog.actions.filter((a) => !state.filter || a.filters.includes(state.filter)); }

function renderFilters() {
  const box = $("#filters"); box.replaceChildren();
  const t = currentType();
  const all = [{ id: "", label: "All" }, ...state.catalog.filters];
  for (const f of all) {
    const n = state.catalog.actions.filter((a) => (!f.id || a.filters.includes(f.id)) && applies(a, t)).length;
    if (t && !n && f.id !== state.filter) continue; // nothing here for this kind of target
    box.append(h("button", { class: state.filter === f.id ? "on" : "", role: "tab",
      onclick: () => { state.filter = f.id; state.selected = []; renderAll(); } }, f.label, h("span", { class: "n" }, n)));
  }
}

function renderTiles() {
  const box = $("#tiles"); box.replaceChildren();
  const t = currentType();
  // Only what fits the target (a selected tile always stays visible).
  const list = visibleActions().filter((a) => applies(a, t) || state.selected.includes(a.slug));
  const tile = (a) => h("button", { class: "tile" + (state.selected.includes(a.slug) ? " on" : ""), title: a.description,
    onclick: () => toggle(a) },
    h("div", { class: "t" }, a.title), h("div", { class: "d" }, a.description),
    h("div", { class: "meta" }, h("span", {}, a.kind === "source" ? "evidence" : "tool"),
      ...a.inputs.slice(0, 2).map((i) => h("span", {}, TYPE_LABEL[i] || i)),
      a.inputs.length > 2 ? h("span", { title: a.inputs.slice(2).map((i) => TYPE_LABEL[i] || i).join(", ") }, "+" + (a.inputs.length - 2)) : null));
  const sources = list.filter((a) => a.kind === "source"), tools = list.filter((a) => a.kind === "tool");
  sources.forEach((a) => box.append(tile(a)));
  if (tools.length) { // the single-purpose tools stay one click away, folded by default
    const open = state.showTools || tools.some((a) => state.selected.includes(a.slug));
    box.append(h("button", { class: "tile more", onclick: () => { state.showTools = !open; renderTiles(); } },
      h("div", { class: "t" }, open ? "Fewer tools ▴" : `More tools (${tools.length}) ▾`),
      h("div", { class: "d" }, "Single-purpose tools from the original toolkit")));
    if (open) tools.forEach((a) => box.append(tile(a)));
  }
  if (!list.length) box.append(h("div", { class: "empty" }, "No actions in this filter."));
}

function toggle(a) {
  const sel = state.selected;
  if (sel.includes(a.slug)) state.selected = sel.filter((s) => s !== a.slug);
  else if (a.kind === "tool") state.selected = [a.slug];                          // tools run alone
  else state.selected = [...sel.filter((s) => byslug(s).kind === "source"), a.slug]; // sources combine
  renderAll();
}
const byslug = (s) => state.catalog.actions.find((a) => a.slug === s);

// ------------------------------------------------------------------ command preview (autofill)
function plan() {
  const v = qEl.value.trim() || "<target>";
  const purpose = state.purpose.trim();
  const sel = state.selected.map(byslug).filter(Boolean);
  if (sel.length === 1 && sel[0].kind === "tool")
    return { kind: "tool", action: sel[0], cli: `openatlas run ${sel[0].slug} ${shq(v)}` };
  const parts = ["openatlas investigate", shq(v)];
  if (sel.length) parts.push("--sources " + sel.map((a) => a.slug).join(","));
  else if (state.filter) parts.push("--filter " + state.filter);
  if (state.forcedType) parts.push("--type " + state.forcedType);
  parts.push("--purpose " + shq(purpose || "<purpose>"));
  return { kind: "investigate", sources: sel.map((a) => a.slug), cli: parts.join(" ") };
}
function renderCommand() {
  const p = plan(); $("#cmd").textContent = p.cli;
  const box = $("#params"); box.replaceChildren();
  const params = p.kind === "tool" ? Object.entries(p.action.params || {}) : [];
  box.classList.toggle("hidden", !params.length);
  for (const [name, spec] of params)
    box.append(h("label", {}, h("span", { class: "label" }, name.replace(/_/g, " ") + (spec.required ? " *" : "")),
      h("input", { "data-param": name, placeholder: spec.description || "", "data-type": spec.type || "string" })));
  // Say what Run will do: nothing selected = every recommended evidence source that fits.
  const t = currentType();
  const auto = state.catalog.actions.filter((a) => a.kind === "source" && a.default && applies(a, t) &&
    (!state.filter || a.filters.includes(state.filter))).length;
  $("#run").textContent = p.kind === "tool" ? "Run ▸" : p.sources.length ? `Run ${p.sources.length} ▸` : `Run all ${auto} ▸`;
  $("#run").disabled = !qEl.value.trim() || (p.kind === "investigate" && state.purpose.trim().length < 3);
  $("#run").title = $("#run").disabled ? (qEl.value.trim() ? "Pick or type a purpose first" : "Type a target first") : "";
}
$("#copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("#cmd").textContent); toast("Command copied"); } catch { toast("Copy failed"); } });
$("#run").addEventListener("click", runSelected);

function renderAll() { renderTypes(); renderPurposes(); renderFilters(); renderTiles(); renderCommand(); }

// ------------------------------------------------------------------ running
async function runSelected() {
  if ($("#run").disabled) return;
  const p = plan(); const value = qEl.value.trim();
  if (p.kind === "tool") {
    const args = {};
    document.querySelectorAll("#params input").forEach((i) => {
      if (!i.value.trim()) return;
      const t = i.dataset.type; args[i.dataset.param] = t === "integer" ? parseInt(i.value, 10) :
        t === "number" ? parseFloat(i.value) : t === "boolean" ? /^(1|true|yes)$/i.test(i.value) :
        t === "array" ? i.value.split(",").map((s) => s.trim()).filter(Boolean) : i.value;
    });
    const box = $("#results"); box.replaceChildren(h("div", { class: "panel" }, h("div", { class: "case-head" },
      h("span", { class: "spin" }), h("span", { class: "mono" }, "Running " + p.action.title + "…"))));
    try { renderToolResult(p.action, (await api(`/api/run/${p.action.slug}`, { method: "POST", body: JSON.stringify({ value, args }) })).result); }
    catch (e) { box.replaceChildren(h("div", { class: "empty" }, "Failed: " + e.message)); }
    return;
  }
  try {
    const body = { target: value, purpose: state.purpose.trim(), filter: p.sources.length ? "" : state.filter,
      sources: p.sources.length ? p.sources : null, type: state.forcedType || null };
    const { case_id } = await api("/api/investigate", { method: "POST", body: JSON.stringify(body) });
    liveCase(case_id);
  } catch (e) { toast(e.message); }
}

function renderToolResult(action, res) {
  const ok = res.success;
  const kv = h("div", { class: "kv" });
  const content = res.content && typeof res.content === "object" ? res.content : { result: res.content };
  for (const [k, v] of Object.entries(content))
    kv.append(h("div", {}, k.replace(/_/g, " ")), h("div", {}, typeof v === "object" ? JSON.stringify(v) : String(v)));
  const raw = h("pre", { class: "json hidden" }, JSON.stringify(res, null, 2));
  $("#results").replaceChildren(h("div", { class: "panel" },
    h("div", { class: "case-head" }, h("span", { class: "badge " + (ok ? "confirmed" : "unverified") }, ok ? "ok" : "degraded"),
      h("strong", {}, action.title), h("span", { class: "muted" }, res.error || ""), h("div", { style: "flex:1" }),
      h("button", { class: "btn ghost", onclick: () => raw.classList.toggle("hidden") }, "Raw JSON")),
    kv, raw));
}

// ------------------------------------------------------------------ live case view
function caseView(caseId, target) {
  const root = h("div", { class: "panel" });
  const head = h("div", { class: "case-head" });
  const counts = h("div", { class: "counts" });
  const srcs = h("div", { class: "srcs" });
  const stage = h("div", { class: "stage" });
  const filt = h("div", { class: "filters-mini" });
  const cards = h("div", { class: "cards" });
  root.append(head, srcs, stage, filt, cards);
  const view = { root, head, counts, srcs, stage, filt, cards, evidence: [], sources: {}, show: "all", caseId, target };
  return view;
}

function paintHead(v, status) {
  const c = { confirmed: 0, unverified: 0, refuted: 0 };
  v.evidence.forEach((e) => c[e.status]++);
  v.counts.replaceChildren(
    h("div", { class: "count ok" }, h("b", {}, c.confirmed), h("span", { class: "label" }, "Confirmed")),
    h("div", { class: "count un" }, h("b", {}, c.unverified), h("span", { class: "label" }, "Unverified")),
    h("div", { class: "count bad" }, h("b", {}, c.refuted), h("span", { class: "label" }, "Refuted")));
  const done = status === "done";
  v.head.replaceChildren(...[
    h("div", {}, h("div", { class: "label" }, "Case " + v.caseId + " · " + (done ? "complete" : status)),
      h("div", { style: "font-size:18px;font-weight:600;margin-top:6px" }, v.target || "")),
    h("div", { style: "flex:1" }), v.counts,
    done ? h("a", { class: "btn ghost", href: `/viz/${v.caseId}`, target: "_blank", rel: "noopener" }, "Graph ↗") : null,
    done ? h("a", { class: "btn ghost", href: `/api/cases/${v.caseId}/markdown`, target: "_blank", rel: "noopener" }, "Report .md") : null,
    !done && status !== "failed" ? h("button", { class: "btn ghost", onclick: () => api(`/api/cases/${v.caseId}/cancel`, { method: "POST" }) }, "Stop") : null,
  ].filter(Boolean)); // native replaceChildren would print null as text
  v.filt.replaceChildren(...["all", "confirmed", "unverified", "refuted"].map((s) =>
    h("button", { class: "chip" + (v.show === s ? " on" : ""), onclick: () => { v.show = s; paintHead(v, status); paintCards(v); } },
      s === "all" ? `All ${v.evidence.length}` : s)));
}

function paintSources(v) {
  v.srcs.replaceChildren(...Object.values(v.sources).map((s) =>
    h("span", { class: "src " + s.state, title: s.detail || "" }, s.state === "run" ? "● " : s.state === "fail" ? "✗ " : "✓ ",
      s.title, s.found != null ? ` · ${s.found}` : "")));
}

function card(e) {
  const url = safeUrl(e.url);
  const why = (e.verification && (e.verification.result || e.verification.reason)) || "";
  const pct = Math.round((e.confidence || 0) * 100);
  return h("div", { class: "card" },
    h("span", { class: "badge " + e.status }, e.status),
    h("div", {},
      h("div", { class: "title" }, url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, e.title, " ↗") : e.title),
      h("div", { class: "sub" }, [e.source, url ? host(url) : null, e.corroborated_by && e.corroborated_by.length ? "also: " + e.corroborated_by.join(", ") : null].filter(Boolean).join(" · ")),
      e.snippet ? h("div", { class: "snip" }, e.snippet) : null,
      why ? h("div", { class: "why" }, h("b", {}, (e.verification.method || "check") + ": "), why) : null),
    h("div", { class: "conf" }, h("span", {}, pct + "%"), h("div", { class: "bar" }, h("i", { style: `width:${pct}%` }))));
}
function paintCards(v) {
  const order = { confirmed: 0, unverified: 1, refuted: 2 };
  const list = v.evidence.filter((e) => v.show === "all" || e.status === v.show)
    .sort((a, b) => order[a.status] - order[b.status] || b.confidence - a.confidence);
  v.cards.replaceChildren(...list.map(card));
  if (!list.length) v.cards.append(h("div", { class: "empty", style: "margin:16px" }, "Nothing here yet."));
}

async function liveCase(caseId) {
  const v = caseView(caseId, qEl.value.trim());
  $("#results").replaceChildren(v.root);
  paintHead(v, "running"); paintCards(v);
  let pending = false; const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; paintHead(v, "running"); paintCards(v); }); } };
  try {
    await streamEvents(caseId, (ev) => {
      if (ev.type === "start") { ev.sources.forEach((s) => v.sources[s.id] = { title: s.title, state: "run" }); v.target = ev.target.value; paintSources(v); }
      else if (ev.type === "source_done") { const r = ev.result; v.sources[r.source] = { ...(v.sources[r.source] || { title: r.source }), state: r.ok ? "ok" : "fail", found: r.found, detail: r.error || r.searched }; paintSources(v); }
      else if (ev.type === "evidence") { v.evidence.push(ev.evidence); schedule(); }
      else if (ev.type === "stage") v.stage.textContent = "› " + ev.message;
      else if (ev.type === "error") { v.stage.textContent = "✗ " + ev.message; paintHead(v, "failed"); }
    });
  } catch (e) { v.stage.textContent = "Connection lost: " + e.message; }
  // Replace streamed evidence with the final, verified report.
  try { const c = await api(`/api/cases/${caseId}`); if (c.report && c.report.evidence) { v.evidence = c.report.evidence; v.stage.textContent = c.report.ai_summary ? "Local AI: " + c.report.ai_summary : ""; } } catch {}
  paintHead(v, "done"); paintCards(v); loadPills();
}

// ------------------------------------------------------------------ cases
async function loadCases() {
  const rows = await api("/api/cases");
  const body = $("#cases-body"); body.replaceChildren();
  if (!rows.length) body.append(h("tr", {}, h("td", { colspan: 5, class: "muted" }, "No cases yet — run an investigation.")));
  for (const c of rows) {
    const s = c.summary || {};
    body.append(h("tr", { class: "click", onclick: () => openCase(c.case_id) },
      h("td", {}, h("strong", {}, c.target)), h("td", { class: "mono" }, c.target_type), h("td", { class: "muted" }, c.purpose),
      h("td", { class: "mono muted" }, (c.created_at || "").replace("T", " ").slice(0, 16)),
      h("td", { class: "mono" }, c.status === "done" ? `${s.confirmed || 0} ✓ · ${s.unverified || 0} ○ · ${s.refuted || 0} ✗` : c.status)));
  }
}
async function openCase(id) {
  const c = await api(`/api/cases/${id}`); const rep = c.report || {};
  const v = caseView(id, c.target); v.evidence = rep.evidence || [];
  (rep.searched || []).forEach((r) => v.sources[r.source] = { title: r.source, state: r.ok ? "ok" : "fail", found: r.found, detail: r.error || r.searched });
  paintSources(v); paintHead(v, c.status === "done" ? "done" : c.status); paintCards(v);
  if (rep.ai_summary) v.stage.textContent = "Local AI: " + rep.ai_summary;
  $("#case-detail").replaceChildren(v.root);
  v.root.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------------ brain
async function loadBrain() {
  const b = await api("/api/brain");
  $("#brain-bar").style.width = b.percent + "%";
  const tier = b.current_tier ? `${b.current_tier.name}` : (b.queued ? "all tiers done" : "not started");
  $("#brain-line").textContent = `${b.articles.toLocaleString()} articles · ${fmtBytes(b.bytes)} · ${b.percent}% · ${tier}` + (b.remaining ? ` · ~${b.eta_hours} h left` : "");
  $("#brain-state").textContent = (b.paused ? "paused" : (b.worker && b.worker.state) || "idle") + (b.worker && b.worker.task ? ` — ${b.worker.task}` : "");
  $("#brain-path").textContent = b.path;
  $("#brain-pause").textContent = b.paused ? "Resume" : "Pause";
  $("#brain-stats").replaceChildren(...[["Articles", b.articles.toLocaleString()], ["Your cases", b.cases], ["Passages", b.chunks.toLocaleString()],
    ["Vectors", b.vectors.toLocaleString()], ["Queued", b.remaining.toLocaleString()]].map(([k, v]) => h("div", { class: "stat" }, h("span", { class: "label" }, k), h("b", {}, v))));
  $("#brain-tiers").replaceChildren(...(b.tiers.length ? b.tiers : []).map((t) => h("div", { class: "tier" },
    h("span", {}, t.name), h("div", { class: "progress" }, h("i", { style: `width:${t.total ? 100 * t.done / t.total : 0}%` })),
    h("span", { class: "mono muted" }, `${t.done.toLocaleString()} / ${t.total.toLocaleString()}`))));
  if (!b.tiers.length) $("#brain-tiers").append(h("div", { class: "muted" }, "Press “Grow the brain” to start with your ~1,800 fields of study. It keeps going in the background, gently."));
}
$("#brain-start").addEventListener("click", async () => { await api("/api/brain/start", { method: "POST" }); toast("Brain is growing"); loadBrain(); });
$("#brain-pause").addEventListener("click", async (e) => { await api(`/api/brain/${e.target.textContent === "Resume" ? "resume" : "pause"}`, { method: "POST" }); loadBrain(); });
async function askBrain() {
  const q = $("#ask-q").value.trim(); if (!q) return;
  const out = $("#ask-out"); out.replaceChildren(h("div", { class: "answer muted" }, h("span", { class: "spin" }), " thinking…"));
  try {
    const a = await api("/api/ask", { method: "POST", body: JSON.stringify({ q }) });
    out.replaceChildren(h("div", { class: "answer" }, a.answer),
      h("div", { class: "cites" }, ...a.citations.map((c) => h("div", {}, `[${c.n}] `,
        safeUrl(c.url) ? h("a", { href: safeUrl(c.url), target: "_blank", rel: "noopener noreferrer" }, c.title) : c.title,
        h("span", { class: "dim" }, "  " + (c.license || ""))))),
      h("div", { class: "cites dim mono" }, a.mode === "llm" ? "answered by your local model from the passages above" : a.mode === "extractive" ? "local AI offline — showing the most relevant passages" : ""));
  } catch (e) { out.replaceChildren(h("div", { class: "answer" }, "Failed: " + e.message)); }
}
$("#ask-go").addEventListener("click", askBrain);
$("#ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter") askBrain(); });

// ------------------------------------------------------------------ skills
async function loadSkills() {
  const skills = await api("/api/skills");
  $("#skills").replaceChildren(...skills.map((s) => h("div", { class: "panel skill" },
    h("h3", {}, s.name), h("div", { class: "muted" }, s.summary),
    h("div", { class: "label", style: "margin-top:14px" }, "Triggers on"),
    h("ul", {}, ...(s.triggers || []).slice(0, 4).map((t) => h("li", {}, t))),
    h("div", { class: "row", style: "margin-top:12px" }, h("span", { class: "pill" },
      h("span", { class: "dot " + (s.lint_ok ? "ok" : "bad") }), s.lint_ok ? "SKILL.md valid" : "SKILL.md has problems")))));
}
$("#skills-check").addEventListener("click", async () => {
  const box = $("#doctor"); box.replaceChildren(h("div", { class: "answer muted" }, h("span", { class: "spin" }), " checking every tool…"));
  const r = await api("/api/skills/check", { method: "POST" });
  box.replaceChildren(h("table", { class: "t" }, h("thead", {}, h("tr", {}, h("th", {}, "Tool"), h("th", {}, "Result"), h("th", {}, "Detail"))),
    h("tbody", {}, ...r.checks.map((c) => h("tr", {}, h("td", {}, c.tool),
      h("td", { class: c.status === "pass" ? "ok-t mono" : c.status === "warn" ? "warn-t mono" : "bad-t mono" }, c.status.toUpperCase()),
      h("td", { class: "muted" }, c.detail))))));
  toast(r.ok ? "All checks passed" : "Some checks need attention");
});

// ------------------------------------------------------------------ system
async function loadSystem() {
  const s = await api("/api/health");
  const hw = s.hardware, p = s.profile, llm = s.llm;
  const rows = [["Profile", p.name], ["Chat model", p.text_model], ["Vision model", p.vision_model || "off"], ["Embedding model", p.embed_model],
    ["Local AI", llm.reachable ? "online at " + llm.host : "offline — run `ollama serve`"],
    ["GPU", hw.gpus.length ? hw.gpus.map((g) => `${g.name} (${g.vram_gb} GB)`).join(", ") : "none detected"],
    ["Models on GPU", s.gpu.models.length ? s.gpu.models.map((m) => `${m.model}: ${m.on_gpu ? "GPU" : m.partly_cpu ? "partly CPU" : "CPU"}`).join(", ") : "no model loaded right now"],
    ["RAM", `${hw.available_ram_gb} GB free of ${hw.total_ram_gb} GB`], ["CPU cores", hw.cpu_count],
    ["Web search", s.search_backend], ["OpenAtlas memory", s.rss_mb + " MB"], ["Version", s.version]];
  $("#system").replaceChildren(h("div", { class: "panel kv" }, ...rows.flatMap(([k, v]) => [h("div", {}, k), h("div", {}, String(v))])));
}

// ------------------------------------------------------------------ status pills
async function loadPills() {
  try {
    const [s, b] = await Promise.all([api("/api/health"), api("/api/brain")]);
    const set = (id, cls, text) => { const el = $(id); el.querySelector(".dot").className = "dot " + cls; el.lastElementChild.textContent = text; };
    set("#pill-profile", "ok", s.profile.name + " profile");
    set("#pill-llm", s.llm.reachable ? "ok" : "warn", s.llm.reachable ? "local AI on" : "local AI off");
    set("#pill-brain", b.worker && b.worker.state === "working" ? "ok" : b.articles ? "warn" : "", `brain ${b.articles.toLocaleString()}`);
  } catch {}
}

// ------------------------------------------------------------------ boot
(async function boot() {
  state.catalog = await api("/api/catalog");
  renderAll(); loadPills();
  setInterval(() => { if (!document.hidden) { loadPills(); if (state.view === "brain") loadBrain(); } }, 15000);
  qEl.focus();
})();
