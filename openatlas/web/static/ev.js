// E.V - chat, cards, settings and hands-free voice. Vanilla JS; every bit of text from the
// model or the web goes in through textContent (the tiny markdown renderer builds nodes).
"use strict";
(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const h = window.h || function (tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  };
  const token = () => sessionStorage.getItem("oa-token") || "";
  const hdrs = (json = true) => ({ ...(json ? { "Content-Type": "application/json" } : {}), ...(token() ? { "X-OpenAtlas-Token": token() } : {}) });
  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { ...hdrs(opts.json !== false), ...(opts.headers || {}) } });
    if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch {} throw new Error(d); }
    return r.json();
  }
  const toast = window.toast || ((m) => console.log(m));
  const safeUrl = (u) => { try { const x = new URL(u, location.href); return ["http:", "https:"].includes(x.protocol) ? x.href : null; } catch { return null; } };

  const S = { conv: null, streaming: null, sources: [], state: null, voice: null, lastTimings: null };
  const SKILL_INFO = {
    "Document Intelligence": "Reads your PDFs, Word files and notes; answers with page numbers.",
    "Project Setup": "Drafts a project layout and creates it (never overwrites) once you approve.",
    "Research Synthesis": "Searches the brain (and the web, with approval) and answers with citations.",
    "Workflow Automation": "Named routines on a schedule - ingest, downloads, checks, digests.",
    "Context Continuity": "Remembers what you tell her to, across chats. You can see and delete it all.",
    "Interactive Planning": "Editable checklists in the chat that she keeps track of.",
    "Quality Assurance": "Checks every factual answer claim-by-claim against its sources.",
    "Decision Support": "Weighted option matrices with a risk read-out and a sensitivity check.",
  };
  const SUGGEST = [
    ["Research", "What do you know about black holes?"],
    ["Documents", "Which documents can you read?"],
    ["Planning", "Help me plan a weekend trip to the Blue Mountains"],
    ["Decisions", "Should I buy a laptop or a desktop?"],
  ];

  // ------------------------------------------------------------ markdown (safe, tiny)
  function inline(text, sources) {
    const out = []; const re = /(\*\*[^*]+\*\*|`[^`]+`|\[\d{1,2}\]|\[[^\]]+\]\((https?:\/\/[^)\s]+)\)|_\([^)]*\)_)/g;
    let last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("**")) out.push(h("b", {}, t.slice(2, -2)));
      else if (t.startsWith("`")) out.push(h("code", {}, t.slice(1, -1)));
      else if (/^\[\d{1,2}\]$/.test(t)) {
        const n = +t.slice(1, -1), src = sources[n - 1];
        const u = src && safeUrl(src.url || "");
        out.push(u ? h("a", { class: "cite", href: u, target: "_blank", rel: "noopener", title: src.title }, t)
                   : h("span", { class: "cite", title: src ? src.title : "" }, t));
      } else if (t.startsWith("_(")) out.push(h("span", { class: "dim small" }, t.slice(2, -2)));
      else { const u = safeUrl(m[2]); const label = t.slice(1, t.indexOf("]("));
        out.push(u ? h("a", { href: u, target: "_blank", rel: "noopener" }, label) : label); }
      last = m.index + t.length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }
  function markdown(text, sources = []) {
    const root = h("div", { class: "md" }); const lines = String(text || "").split("\n");
    let list = null, code = null;
    for (const raw of lines) {
      if (raw.trim().startsWith("```")) { if (code) { root.append(h("pre", {}, code.join("\n"))); code = null; } else code = []; continue; }
      if (code) { code.push(raw); continue; }
      const li = raw.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
      if (li) { if (!list) { list = h(/^\s*\d/.test(raw) ? "ol" : "ul"); root.append(list); } list.append(h("li", {}, inline(li[1], sources))); continue; }
      list = null;
      const hd = raw.match(/^#{1,4}\s+(.*)$/);
      if (hd) { root.append(h("h3", {}, inline(hd[1], sources))); continue; }
      if (raw.trim()) root.append(h("p", {}, inline(raw, sources)));
    }
    if (code) root.append(h("pre", {}, code.join("\n")));
    return root;
  }

  // ------------------------------------------------------------ message rendering
  const msgs = () => $("#messages");
  function scrollDown(force) {
    const sc = $("#chat-scroll"); if (force || sc.scrollHeight - sc.scrollTop - sc.clientHeight < 160) sc.scrollTop = sc.scrollHeight;
  }
  function welcome(show) { $("#welcome").classList.toggle("hidden", !show); }
  function userMsg(text) {
    welcome(false);
    const el = h("div", { class: "msg user" }, h("div", { class: "bubble" }, text)); msgs().append(el); scrollDown(true); return el;
  }
  function evMsg() {
    welcome(false);
    const body = h("div", { class: "body" }), extra = h("div", { class: "extra" }), foot = h("div", { class: "xray" });
    const who = h("div", { class: "who" }, "E.V", h("span", { class: "mood-tag" }));
    const el = h("div", { class: "msg ev" }, h("span", { class: "orb md thinking" }), h("div", { class: "bubble" }, who, extra, body, foot));
    msgs().append(el); scrollDown(true);
    return { el, body, extra, foot, who, text: "", sources: [], orb: el.firstChild };
  }
  function paintText(m, streaming) {
    m.body.replaceChildren(markdown(m.text, m.sources));
    if (streaming) { const p = m.body.querySelector(".md > :last-child") || m.body.firstChild; (p || m.body).append(h("span", { class: "caret" })); }
    scrollDown();
  }
  const KIND = { read: "auto", network: "web", write: "writes", command: "command" };

  function toolChip(ev) {
    return h("div", { class: "tcard" }, h("div", { class: "th" },
      h("span", { class: "tag " + (ev.kind || "read") }, KIND[ev.kind] || "tool"), h("b", {}, ev.skill || "Skill"), "·", ev.name.replace(/_/g, " "),
      h("span", { class: "grow" }), ev.ok ? h("span", { class: "ok-t" }, "✓") : h("span", { class: "bad-t", title: ev.error || "" }, "✗ " + (ev.error || "").slice(0, 80))));
  }
  function approvalCard(a, m) {
    const box = h("div", { class: "tcard approval", "data-approval": a.id });
    const argsText = JSON.stringify(a.args || {}, null, 2);
    const risk = a.risk || {};
    const btns = h("div", { class: "row" });
    const status = h("span", { class: "mono small dim" });
    const paint = (x) => {
      btns.replaceChildren(); status.textContent = "";
      if (x.status === "pending") {
        btns.append(h("button", { class: "btn primary sm", onclick: () => decide(true) }, "Approve"),
                    h("button", { class: "btn sm", onclick: () => decide(false) }, "Deny"));
      } else status.textContent = { done: "✓ approved and done", running: "running…", denied: "denied", failed: "✗ failed" }[x.status] || x.status;
    };
    async function decide(yes) {
      btns.querySelectorAll("button").forEach((b) => (b.disabled = true)); status.textContent = yes ? "running…" : "";
      try {
        const r = await api(`/api/ev/approvals/${a.id}`, { method: "POST", body: JSON.stringify({ approve: yes }) });
        paint(r);
        if (r.message) { const f = evMsg(); f.orb.classList.remove("thinking"); f.text = r.message; paintText(f); }
        EV.refresh();
      } catch (e) { toast(e.message); paint(a); }
    }
    box.append(h("div", { class: "th" }, h("span", { class: "tag " + a.kind }, KIND[a.kind] || a.kind), h("b", {}, a.skill || "Action"), "·",
      (a.tool || "").replace(/_/g, " "), h("span", { class: "grow" }), "needs your OK"),
    h("div", { class: "tb" },
      h("div", { class: "risk" }, h("span", { class: "risk-lvl " + (risk.level || "low") }, (risk.level || "low") + " risk"),
        h("div", {}, h("div", {}, risk.feeling || ""), h("div", { class: "muted small" },
          "Worst case: " + (risk.worst_case || "—") + (risk.reversible === false ? " · not easily undone" : " · reversible")),
          ...(risk.concerns || []).map((c) => h("div", { class: "muted small" }, "• " + c)))),
      h("div", { class: "args" }, argsText),
      h("div", { class: "row", style: "margin-top:10px" }, btns, status)));
    paint(a);
    return box;
  }
  function planCard(plan) {
    const box = h("div", { class: "tcard" });
    const render = (p) => {
      const list = h("div", {});
      p.steps.forEach((st, i) => {
        const txt = h("span", { class: "st", contenteditable: "true", spellcheck: "false" }, st.text);
        txt.addEventListener("blur", () => { if (txt.textContent.trim() !== st.text) edit({ text: { index: i, text: txt.textContent.trim() } }); });
        txt.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); txt.blur(); } });
        list.append(h("div", { class: "plan-step" + (st.done ? " done" : "") },
          h("input", { type: "checkbox", checked: st.done, onchange: () => edit({ toggle: i }) }), txt,
          i > 0 ? h("button", { class: "icon-btn", title: "Move up", onclick: () => edit({ move: { from: i, to: i - 1 } }) }, "↑") : null,
          h("button", { class: "icon-btn", title: "Remove", onclick: () => edit({ remove: i }) }, "×")));
      });
      const add = h("input", { placeholder: "Add a step…" });
      add.addEventListener("keydown", (e) => { if (e.key === "Enter" && add.value.trim()) edit({ add: add.value.trim() }); });
      box.replaceChildren(h("div", { class: "th" }, h("span", { class: "tag read" }, "plan"), h("b", {}, p.goal),
        h("span", { class: "grow" }), `${p.done}/${p.steps.length} done`),
        h("div", { class: "tb" }, h("div", { class: "mbar" }, h("i", { style: `width:${p.steps.length ? (100 * p.done / p.steps.length) : 0}%` })),
          list, h("div", { class: "plan-add" }, add)));
    };
    async function edit(body) { try { render(await api(`/api/ev/plans/${plan.id}`, { method: "PATCH", body: JSON.stringify(body) })); EV.refresh(); } catch (e) { toast(e.message); } }
    render(plan); return box;
  }
  function decisionCard(d) {
    const max = Math.max(10, ...Object.values(d.totals || {}));
    const rows = (d.ranking || []).map((o) => h("div", { class: "dm-row" + (o === d.winner ? " win" : "") },
      h("b", {}, o), h("div", { class: "mbar" }, h("i", { style: `width:${100 * (d.totals[o] || 0) / max}%` })), h("span", { class: "mono small" }, (d.totals[o] || 0).toFixed(1))));
    return h("div", { class: "tcard" }, h("div", { class: "th" }, h("span", { class: "tag read" }, "decision"), h("b", {}, d.question || "Comparison"),
      h("span", { class: "grow" }), d.needs_scores ? "needs scores" : `confidence: ${d.confidence}`),
      h("div", { class: "tb" }, ...rows,
        d.needs_scores ? h("div", { class: "muted small" }, "Give each option a 0-10 score per criterion (" + d.criteria.map((c) => c.name + (c.lower_is_better ? " ↓" : "")).join(", ") + ") and I'll work it out.") : null,
        d.risk_note ? h("div", { class: "notice" }, d.risk_note) : null,
        (d.sensitivity || []).length ? h("div", { class: "muted small", style: "margin-top:6px" }, "Sensitivity: " + d.sensitivity.join("; ")) : null,
        h("div", { class: "dim small mono", style: "margin-top:6px" }, "weights: " + Object.entries(d.weights_normalised || {}).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(" · "))));
  }
  function projectCard(p) {
    const btn = h("button", { class: "btn primary sm", onclick: async () => {
      btn.disabled = true;
      try { const r = await api("/api/ev/propose", { method: "POST", body: JSON.stringify({ tool: "create_project", conv_id: S.conv, args: { name: p.name, kind: p.kind } }) });
        if (r.approval) btn.replaceWith(approvalCard(r.approval)); } catch (e) { toast(e.message); btn.disabled = false; } } }, "Create it…");
    return h("div", { class: "tcard" }, h("div", { class: "th" }, h("span", { class: "tag read" }, "project"), h("b", {}, p.name), "·", p.kind),
      h("div", { class: "tb" }, h("div", { class: "mono small muted" }, p.folder), h("div", { class: "args", style: "margin:8px 0" }, p.files.join("\n")), btn));
  }
  function qaCard(q) {
    const c = q.counts || {};
    const detail = h("div", { class: "tb qa hidden" }, ...(q.claims || []).map((r) => h("div", { class: "qa-row" },
      h("span", { class: "verdict " + r.verdict }, r.verdict), h("div", {}, r.claim, h("div", { class: "dim small" }, r.why + (r.source ? ` — ${r.source}` : ""))))));
    const head = h("div", { class: "th qa-sum", onclick: () => detail.classList.toggle("hidden") },
      h("span", { class: "tag " + (c.unsupported ? "write" : "read") }, "checked"), h("b", {}, "Quality check"),
      `${c.supported || 0} supported · ${c.unsupported || 0} unsupported · ${c.unverified || 0} unverified`, h("span", { class: "grow" }), "details ▾");
    return h("div", { class: "tcard" }, head, detail);
  }
  function cardFor(ev) {
    if (ev.card === "plan") return planCard(ev.plan);
    if (ev.card === "decision") return decisionCard(ev);
    if (ev.card === "project") return projectCard(ev);
    return null;
  }

  // ------------------------------------------------------------ one event stream (chat SSE and voice WS share it)
  function handler(m) {
    return function (ev) {
      switch (ev.type) {
        case "start": if (ev.conv_id !== S.conv) { S.conv = ev.conv_id; loadConversations(); } break;
        case "mood": paintMood(ev); break;
        case "token": m.orb.classList.remove("thinking"); m.text += ev.text; paintText(m, true); break;
        case "tool": m.extra.append(toolChip(ev)); scrollDown(); break;
        case "approval": m.extra.append(approvalCard(ev, m)); scrollDown(); break;
        case "card": { const c = cardFor(ev); if (c) m.extra.append(c); scrollDown(); break; }
        case "qa": m.foot.before(qaCard(ev)); break;
        case "notice": m.extra.append(h("div", { class: "notice" + (ev.level === "error" ? " error" : "") }, ev.text)); break;
        case "done": {
          m.orb.classList.remove("thinking");
          m.sources = (ev.meta && ev.meta.sources) || [];
          if (ev.text) m.text = ev.text;
          paintText(m, false);
          const meta = ev.meta || {};
          const bits = [meta.model, meta.ms_first_token != null ? `first word ${meta.ms_first_token} ms` : null,
            meta.ms_total != null ? `${(meta.ms_total / 1000).toFixed(1)} s` : null, meta.offline ? "offline mode" : null,
            meta.interrupted ? "interrupted" : null, (meta.sources || []).length ? `${meta.sources.length} source(s)` : null].filter(Boolean);
          m.foot.replaceChildren(...bits.map((b) => h("span", {}, b)));
          if (meta.mood) m.who.lastChild.textContent = meta.mood;
          EV.refresh(); break;
        }
      }
    };
  }

  async function send(text) {
    text = (text || "").trim(); if (!text || S.streaming) return;
    const input = $("#chat-input"); input.value = ""; autoGrow();
    if (S.voice && S.voice.ws && S.voice.ws.readyState === 1) { S.voice.ws.send(JSON.stringify({ type: "text", text })); userMsg(text); S.voice.current = null; return; }
    userMsg(text);
    const m = evMsg(); const on = handler(m);
    const ctrl = new AbortController(); S.streaming = ctrl; setSend(true);
    try {
      const r = await fetch("/api/ev/chat", { method: "POST", headers: hdrs(), body: JSON.stringify({ text, conv_id: S.conv }), signal: ctrl.signal });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
      const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "";
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (line) on(JSON.parse(line.slice(6)));
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") m.extra.append(h("div", { class: "notice error" }, e.message));
      m.orb.classList.remove("thinking"); paintText(m, false);
    } finally { S.streaming = null; setSend(false); }
  }
  function setSend(busy) {
    const b = $("#send"); b.classList.toggle("stop", busy); b.title = busy ? "Stop" : "Send";
    b.replaceChildren(busy ? h("span", { style: "width:11px;height:11px;background:currentColor;border-radius:2px" }) :
      (() => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("viewBox", "0 0 24 24");
        const p = document.createElementNS("http://www.w3.org/2000/svg", "path"); p.setAttribute("d", "M5 12h14M13 6l6 6-6 6"); s.append(p); return s; })());
  }
  function autoGrow() { const t = $("#chat-input"); t.style.height = "auto"; t.style.height = Math.min(200, t.scrollHeight) + "px"; }

  // ------------------------------------------------------------ conversations
  async function loadConversations() {
    const q = $("#chat-search").value.trim();
    let list = []; try { list = await api("/api/ev/conversations?q=" + encodeURIComponent(q)); } catch {}
    const box = $("#conv-list"); box.replaceChildren();
    if (!list.length) box.append(h("div", { class: "conv-empty" }, q ? "No chats match." : "No conversations yet."));
    for (const c of list) {
      const when = (c.updated || "").replace("T", " ").slice(0, 16);
      box.append(h("div", { class: "conv" + (c.id === S.conv ? " on" : ""), role: "button", tabindex: "0", onclick: () => openConversation(c.id) },
        h("span", { class: "t" }, c.title || "New chat"), h("span", { class: "w" }, when),
        h("button", { class: "x", title: "Delete chat", onclick: async (e) => { e.stopPropagation();
          if (!confirm("Delete this conversation?")) return; await api(`/api/ev/conversations/${c.id}`, { method: "DELETE" });
          if (S.conv === c.id) newChat(); loadConversations(); } }, "×")));
    }
  }
  async function openConversation(id) {
    window.show && window.show("chat");
    const c = await api(`/api/ev/conversations/${id}`); S.conv = id;
    msgs().replaceChildren(); welcome(!c.messages.length);
    for (const mm of c.messages) {
      if (mm.role === "user") { userMsg(mm.content); continue; }
      const m = evMsg(); m.orb.classList.remove("thinking"); m.sources = mm.meta.sources || []; m.text = mm.content; paintText(m, false);
      for (const card of mm.meta.cards || []) { const el = cardFor(card); if (el) m.extra.append(el); }
      for (const a of mm.meta.approvals || []) if (a) m.extra.append(approvalCard(a, m));
      if (mm.meta.qa) m.foot.before(qaCard(mm.meta.qa));
      if (mm.meta.mood) m.who.lastChild.textContent = mm.meta.mood;
    }
    loadConversations(); scrollDown(true);
  }
  function newChat() {
    S.conv = null; msgs().replaceChildren(); welcome(true); loadConversations();
    window.show && window.show("chat"); $("#chat-input").focus();
  }

  // ------------------------------------------------------------ state / system panel
  function paintMood(m) {
    const cls = { cheerful: "warm", content: "", focused: "", steady: "", concerned: "concern", uneasy: "cool" }[m.label] || "";
    for (const id of ["#mood-orb", "#welcome-orb"]) { const o = $(id); if (o) o.className = "orb " + (id === "#mood-orb" ? "md " : "xl ") + cls; }
    $("#mood-label").textContent = m.label;
    $("#rapport-bar").style.width = Math.round((m.rapport || 0) * 100) + "%";
    $("#rapport-text").textContent = `rapport ${Math.round((m.rapport || 0) * 100)}% · ${m.turns || 0} chats`;
  }
  async function refresh() {
    let st; try { st = await api("/api/ev/state"); } catch { return; } S.state = st;
    paintMood(st.mood);
    $("#sys-pending").textContent = st.pending; $("#sys-plans").textContent = st.plans.length;
    const llm = st.llm;
    $("#model-name").textContent = llm.ok ? llm.model : "local model offline";
    $("#model-dot").className = "dot " + (llm.ok ? "ok" : "warn");
    $("#sys-model").replaceChildren(h("div", { class: "v small" }, llm.message));
    const v = st.voice;
    $("#sys-voice").replaceChildren(
      h("div", {}, v.stt.available ? "✓ Hearing (faster-whisper)" : "Hearing: not installed"),
      h("div", {}, v.tts.available ? `✓ Voice: MeloTTS ${v.tts.voice}` : `Voice: ${v.tts.fallback || "off"} for now`),
      !(v.stt.available && v.tts.available) ? h("div", { class: "dim small mono", style: "margin-top:4px" },
        [!v.stt.available ? "pip install -e '.[voice]'" : null, !v.tts.available ? "openatlas ev voice-setup" : null].filter(Boolean).join("  ·  ")) : null);
    $("#mic-hint").textContent = v.stt.available ? "mic for hands-free" : "mic needs: pip install -e '.[voice]'";
    const name = st.persona.user_name;
    $("#welcome-hi").textContent = name ? `G'day ${name}, E.V here` : "G'day, I'm E.V";
  }
  async function loadSystemPanel() {
    try {
      const [hs, b, lib] = await Promise.all([api("/api/health"), api("/api/brain"), api("/api/library")]);
      const hw = hs.hardware;
      $("#sys-gpu").textContent = hw.gpus.length ? hw.gpus.map((g) => `${g.name} · ${g.vram_gb} GB`).join(", ") : "none (CPU)";
      $("#sys-ram").textContent = `${hw.available_ram_gb} GB`;
      $("#sys-brain").textContent = (b.articles || 0).toLocaleString();
      const active = lib.books.filter((x) => ["downloading", "queued", "ingesting"].includes(x.status));
      $("#sys-lib").textContent = active.length ? active.map((x) => `${x.filename.slice(0, 22)}… ${x.status === "ingesting" ? x.ingest_percent : x.percent}%`).join(", ")
        : `${lib.books.length} book(s)`;
    } catch {}
  }

  // ------------------------------------------------------------ skills + settings views
  function loadSkills() {
    const st = S.state; if (!st) return refresh().then(loadSkills);
    $("#ev-skills").replaceChildren(...Object.entries(st.skills).map(([skill, tools]) => h("div", { class: "panel evskill" },
      h("h4", {}, h("span", { class: "orb sm" }), skill), h("div", { class: "muted small" }, SKILL_INFO[skill] || ""),
      h("div", { class: "tools" }, ...tools.map((t) => h("code", {}, t))))));
  }
  let saveT;
  function saveSettings(patch) { clearTimeout(saveT); saveT = setTimeout(async () => { try { await api("/api/ev/settings", { method: "POST", body: JSON.stringify(patch) }); refresh(); } catch (e) { toast(e.message); } }, 350); }
  async function loadSettings() {
    await refresh(); const st = S.state, p = st.persona;
    $("#set-name").value = p.user_name; $("#set-mission").value = p.mission;
    $("#set-speed").value = p.voice_speed; $("#set-speed-v").textContent = p.voice_speed.toFixed(2) + "×";
    $("#voice-status").replaceChildren(...[...$("#sys-voice").childNodes].map((n) => n.cloneNode(true)));
    $("#dials").replaceChildren(...st.traits.map((t) => {
      const val = h("span", { class: "v" }, p.dials[t.key].toFixed(2));
      const r = h("input", { type: "range", min: "0", max: "1", step: "0.05", value: p.dials[t.key], "aria-label": t.label });
      r.addEventListener("input", () => { val.textContent = (+r.value).toFixed(2); saveSettings({ dials: { [t.key]: +r.value } }); });
      return h("div", { class: "dial" }, h("span", {}, t.label), r, val);
    }));
    $("#facts").replaceChildren(...(st.facts.length ? st.facts.map((f) => h("div", { class: "fact" }, h("span", {}, f.text),
      h("button", { class: "btn ghost sm danger", onclick: async () => { await api(`/api/ev/memory/${f.id}`, { method: "DELETE" }); loadSettings(); } }, "Forget")))
      : [h("div", { class: "muted small" }, "Nothing yet. Tell her “remember that …” in the chat, or add it here.")]));
    $("#routines").replaceChildren(...(st.routines.length ? st.routines.map((r) => h("div", { class: "fact" },
      h("span", {}, h("b", {}, r.name), ` · ${r.schedule} · `, r.steps.map((s) => s.action + (s.arg ? ":" + s.arg : "")).join(" → "),
        h("span", { class: "dim small" }, r.last_run ? `  (last run ${r.last_run.replace("T", " ")})` : "")),
      h("button", { class: "btn ghost sm danger", onclick: async () => { await api(`/api/ev/routines/${encodeURIComponent(r.name)}`, { method: "DELETE" }); loadSettings(); } }, "Remove")))
      : [h("div", { class: "muted small" }, "No routines. Ask E.V: “every morning at 7, grow the brain and check search quality”.")]));
  }
  ["#set-name", "#set-mission"].forEach((id) => $(id).addEventListener("input", (e) => saveSettings({ [id === "#set-name" ? "user_name" : "mission"]: e.target.value })));
  $("#set-speed").addEventListener("input", (e) => { $("#set-speed-v").textContent = (+e.target.value).toFixed(2) + "×"; saveSettings({ voice_speed: +e.target.value }); });
  $("#fact-form").addEventListener("submit", async (e) => { e.preventDefault(); const v = $("#fact-new").value.trim(); if (!v) return;
    await api("/api/ev/memory", { method: "POST", body: JSON.stringify({ text: v }) }); $("#fact-new").value = ""; loadSettings(); });

  // ------------------------------------------------------------ voice: hands-free, barge-in
  const WORKLET = `class Mic extends AudioWorkletProcessor {
    constructor() { super(); this.buf = []; this.ratio = sampleRate / 16000; this.acc = 0; }
    process(inputs) { const ch = inputs[0][0]; if (!ch) return true;
      for (let i = 0; i < ch.length; i++) { this.acc += 1; if (this.acc >= this.ratio) { this.acc -= this.ratio; this.buf.push(ch[i]); } }
      while (this.buf.length >= 320) { const f = this.buf.splice(0, 320); const pcm = new Int16Array(320); let e = 0;
        for (let i = 0; i < 320; i++) { const s = Math.max(-1, Math.min(1, f[i])); pcm[i] = s * 32767; e += s * s; }
        this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(e / 320) }, [pcm.buffer]); }
      return true; } }
  registerProcessor("ev-mic", Mic);`;

  function voiceUI(on, text) {
    $("#voicebar").classList.toggle("hidden", !on); $("#mic").classList.toggle("on", on);
    if (text) $("#voice-state").textContent = text;
  }
  function stopPlayback(v) {
    for (const s of v.playing) { try { s.stop(); } catch {} } v.playing = []; v.next = 0;
    if (window.speechSynthesis) speechSynthesis.cancel();
    $("#voice-orb").classList.remove("speaking");
  }
  function pickVoice() {
    const vs = (window.speechSynthesis && speechSynthesis.getVoices()) || [];
    return vs.find((x) => /en[-_]AU/i.test(x.lang) && /female|karen|catherine|natasha|olivia|matilda/i.test(x.name))
        || vs.find((x) => /en[-_]AU/i.test(x.lang)) || vs.find((x) => /en[-_]GB/i.test(x.lang) && /female/i.test(x.name)) || null;
  }
  async function startVoice() {
    if (!navigator.mediaDevices) { toast("This browser can't use the microphone here."); return; }
    const v = { playing: [], next: 0, rate: 24000, current: null, speakingUntil: 0 };
    try {
      v.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    } catch (e) { toast("Microphone blocked: " + e.message); return; }
    v.ctx = new AudioContext({ latencyHint: "interactive" });
    await v.ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })));
    v.src = v.ctx.createMediaStreamSource(v.stream); v.node = new AudioWorkletNode(v.ctx, "ev-mic"); v.src.connect(v.node);
    const proto = location.protocol === "https:" ? "wss" : "ws";
    v.ws = new WebSocket(`${proto}://${location.host}/ws/ev/voice?conv=${S.conv || ""}${token() ? "&token=" + encodeURIComponent(token()) : ""}`);
    v.ws.binaryType = "arraybuffer"; S.voice = v;
    let loud = 0;
    v.node.port.onmessage = (e) => {
      if (v.ws.readyState !== 1) return;
      v.ws.send(e.data.pcm);
      // barge-in: you start talking while she's speaking -> stop her at once
      const playing = v.playing.length || (window.speechSynthesis && speechSynthesis.speaking);
      loud = e.data.rms > 0.04 ? loud + 1 : 0;
      if (playing && loud >= 6) { stopPlayback(v); v.ws.send(JSON.stringify({ type: "interrupt" })); voiceUI(true, "listening…"); }
    };
    v.ws.onmessage = (e) => {
      if (typeof e.data !== "string") { playPcm(v, e.data); return; }
      const ev = JSON.parse(e.data);
      if (ev.type === "ready") {
        voiceUI(true, ev.stt ? "listening… just talk" : "can't hear yet: " + (ev.hint || "install faster-whisper"));
        v.ws.send(JSON.stringify({ type: "config", speak: true, conv_id: S.conv }));
        v.serverTts = ev.tts === "server"; return;
      }
      if (ev.type === "vad") { voiceUI(true, ev.speech ? "hearing you…" : "thinking…"); return; }
      if (ev.type === "transcript") { if (ev.text) { userMsg(ev.text); v.current = null; } else voiceUI(true, "listening…"); return; }
      if (ev.type === "audio_start") { v.rate = ev.rate; $("#voice-orb").classList.add("speaking"); voiceUI(true, "speaking…"); return; }
      if (ev.type === "audio_end") return;
      if (ev.type === "audio_stop") { stopPlayback(v); voiceUI(true, "listening…"); return; }
      if (ev.type === "say") { speakBrowser(v, ev.text); return; }
      if (ev.type === "timings") {
        const t = [ev.stt_ms != null ? `hear ${ev.stt_ms}` : null, ev.first_token_ms != null ? `think ${ev.first_token_ms}` : null,
          ev.first_audio_ms != null ? `speak ${ev.first_audio_ms}` : null].filter(Boolean).join(" · ");
        if (t) { $("#voice-timing").textContent = t + " ms"; $("#sys-latency").textContent = "last turn: " + t + " ms"; } return;
      }
      if (!v.current && ["start", "token", "tool", "approval", "card", "mood"].includes(ev.type)) v.current = handler(evMsg());
      if (v.current) v.current(ev);
      if (ev.type === "done") { v.current = null; voiceUI(true, "listening…"); }
    };
    v.ws.onclose = () => { if (S.voice === v) stopVoice(); };
  }
  function playPcm(v, buf) {
    const i16 = new Int16Array(buf); const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    const ab = v.ctx.createBuffer(1, f32.length, v.rate); ab.copyToChannel(f32, 0);
    const s = v.ctx.createBufferSource(); s.buffer = ab; s.connect(v.ctx.destination);
    const at = Math.max(v.ctx.currentTime + 0.02, v.next); s.start(at); v.next = at + ab.duration;
    v.playing.push(s); s.onended = () => { v.playing = v.playing.filter((x) => x !== s); if (!v.playing.length) { $("#voice-orb").classList.remove("speaking"); voiceUI(true, "listening…"); } };
  }
  function speakBrowser(v, text) {
    if (!window.speechSynthesis) return;
    const u = new SpeechSynthesisUtterance(text); const voice = pickVoice(); if (voice) u.voice = voice; u.lang = voice ? voice.lang : "en-AU";
    u.rate = (S.state && S.state.persona.voice_speed) || 1; u.pitch = 1.05;
    u.onstart = () => { $("#voice-orb").classList.add("speaking"); voiceUI(true, "speaking…"); };
    u.onend = () => { if (!speechSynthesis.speaking) { $("#voice-orb").classList.remove("speaking"); voiceUI(true, "listening…"); } };
    speechSynthesis.speak(u);
  }
  function stopVoice() {
    const v = S.voice; if (!v) return; S.voice = null; stopPlayback(v);
    try { v.ws.close(); } catch {} try { v.stream.getTracks().forEach((t) => t.stop()); } catch {} try { v.ctx.close(); } catch {}
    voiceUI(false);
  }

  // ------------------------------------------------------------ wiring
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); if (S.streaming) { S.streaming.abort(); return; } send($("#chat-input").value); });
  $("#chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); } });
  $("#chat-input").addEventListener("input", autoGrow);
  $("#new-chat").addEventListener("click", newChat);
  let searchT; $("#chat-search").addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(loadConversations, 200); });
  $("#model-chip").addEventListener("click", () => window.show && window.show("system"));
  $("#mic").addEventListener("click", () => (S.voice ? stopVoice() : startVoice()));
  $("#attach").addEventListener("click", () => $("#file").click());
  $("#file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return; e.target.value = "";
    try {
      const r = await fetch("/api/ev/documents?name=" + encodeURIComponent(f.name), { method: "POST", headers: { ...(token() ? { "X-OpenAtlas-Token": token() } : {}) }, body: f });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast(`E.V can read ${f.name} now`); const inp = $("#chat-input"); inp.value = `Summarise ${f.name} for me`; autoGrow(); inp.focus();
    } catch (err) { toast(err.message); }
  });
  $("#suggest").replaceChildren(...SUGGEST.map(([k, q]) => h("button", { onclick: () => send(q) }, h("b", {}, k), h("span", {}, q))));

  const EV = window.EV = {
    refresh, send, newChat, openConversation,
    onShow(view) { if (view === "skills") loadSkills(); if (view === "settings") loadSettings(); if (view === "chat") setTimeout(() => $("#chat-input").focus(), 0); },
  };
  window.addEventListener("load", () => {
    refresh(); loadConversations(); loadSystemPanel(); $("#chat-input").focus();
    if (location.hash.startsWith("#ask=")) {  // "Ask E.V about this" from the 3D brain
      const q = decodeURIComponent(location.hash.slice(5)); history.replaceState(null, "", "/"); send(q);
    }
    setInterval(() => { if (!document.hidden) { refresh(); loadSystemPanel(); } }, 15000);
  });
})();
