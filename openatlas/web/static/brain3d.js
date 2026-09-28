// The brain as a 3D space of neurons: inspect, search, isolate, trace paths, replay growth,
// and customize the look. three.js + 3d-force-graph (vendored, MIT). Text from the brain is
// only ever set with textContent.
"use strict";
(function () {
  const $ = (s) => document.querySelector(s);
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v; else if (k.startsWith("on")) el.addEventListener(k.slice(2), v); else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  };
  const token = sessionStorage.getItem("oa-token") || "";
  const api = (p) => fetch(p, { headers: token ? { "X-OpenAtlas-Token": token } : {} }).then((r) => { if (!r.ok) throw new Error(r.statusText); return r.json(); });
  const safeUrl = (u) => { try { const x = new URL(u); return ["http:", "https:"].includes(x.protocol) ? x.href : null; } catch { return null; } };

  // ------------------------------------------------------------ settings
  const PRESETS = {
    Synapse: { palette: ["#22d3ee", "#2dd4bf", "#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#f87171", "#38bdf8", "#c084fc", "#fb923c", "#4ade80", "#e879f9", "#facc15"],
               bg: "#05070a", bloom: true, bloomStrength: 1.2, linkOpacity: 0.16, curvature: 0.12, core: "#e0fbff" },
    Nebula: { palette: ["#f0abfc", "#c084fc", "#818cf8", "#f472b6", "#fb7185", "#a78bfa", "#e879f9", "#67e8f9", "#fda4af", "#d8b4fe", "#93c5fd", "#f9a8d4", "#c4b5fd", "#fbcfe8"],
              bg: "#0b0716", bloom: true, bloomStrength: 1.8, linkOpacity: 0.12, curvature: 0.3, core: "#fff1fb" },
    Blueprint: { palette: ["#93c5fd", "#bfdbfe", "#60a5fa", "#dbeafe", "#7dd3fc", "#a5b4fc", "#e0f2fe", "#93c5fd", "#bae6fd", "#c7d2fe", "#60a5fa", "#dbeafe", "#7dd3fc", "#bfdbfe"],
                 bg: "#0a1a33", bloom: false, bloomStrength: 0.6, linkOpacity: 0.35, curvature: 0, core: "#ffffff" },
    Mono: { palette: ["#f4f4f5", "#d4d4d8", "#a1a1aa", "#e4e4e7", "#71717a", "#fafafa", "#d4d4d8", "#a1a1aa", "#e4e4e7", "#f4f4f5", "#71717a", "#d4d4d8", "#a1a1aa", "#e4e4e7"],
            bg: "#0b0b0c", bloom: false, bloomStrength: 0.8, linkOpacity: 0.22, curvature: 0.05, core: "#ffffff" },
  };
  const DEFAULTS = { preset: "Synapse", colorBy: "division", nodeSize: 1, sizeByDegree: 0.5, nodeOpacity: 0.92, linkOpacity: 0.16,
    linkWidth: 0, curvature: 0.12, firing: true, firingSpeed: 0.01, bloom: true, bloomStrength: 1.2, bg: "#05070a", labels: "hubs",
    rotate: false, charge: -45, distance: 32, freeze: false, limit: "3000", quality: "auto" };
  let C = { ...DEFAULTS };
  try { C = { ...DEFAULTS, ...JSON.parse(localStorage.getItem("oa-brain3d") || "{}") }; } catch {}
  const save = () => { try { localStorage.setItem("oa-brain3d", JSON.stringify(C)); } catch {} };

  // ------------------------------------------------------------ state
  let G, data, byId = new Map(), nbrs = new Map(), groups = [], groupColor = new Map();
  let selected = null, hover = null, highlight = new Set(), hlLinks = new Set(), isolate = 0, pathFrom = null, similar = new Set();
  const hiddenGroups = new Set(); let cutoff = Infinity, times = [];
  let bloomPass = null, fitted = false;
  const TIER = ["your field (seed)", "vital article", "depth 1", "depth 2"];

  // ------------------------------------------------------------ colour helpers
  const hex = (c) => new window.THREE.Color(c);
  function mix(a, b, t) { const x = hex(a), y = hex(b); return "#" + x.lerp(y, t).getHexString(); }
  const ramp = (t) => (t < 0.5 ? mix("#312e81", "#22d3ee", t * 2) : mix("#22d3ee", "#fde68a", (t - 0.5) * 2));
  let maxDeg = 1, tMin = 0, tMax = 1;
  function baseColor(n) {
    const P = PRESETS[C.preset] || PRESETS.Synapse;
    if (n.kind === "core") return P.core;
    if (C.colorBy === "tier" && n.kind === "neuron") return ["#fbbf24", "#22d3ee", "#a78bfa", "#f472b6"][n.tier] || "#94a3b8";
    if (C.colorBy === "degree") return ramp(Math.log2(1 + n.degree) / Math.log2(1 + maxDeg));
    if (C.colorBy === "age" && n.kind === "neuron" && n._t) return ramp((n._t - tMin) / Math.max(1, tMax - tMin));
    return groupColor.get(n.group) || "#94a3b8";
  }
  function nodeColor(n) {
    const c = baseColor(n);
    const focus = highlight.size || similar.size;
    if (!focus) return c;
    if (highlight.has(n.id) || similar.has(n.id)) return n.id === (selected && selected.id) ? "#ffffff" : c;
    return mix(c, C.bg, 0.9);
  }
  function nodeVal(n) {
    const base = n.kind === "core" ? 9 : n.kind === "hub" ? 2.5 + Math.log2(2 + (n.count || 0)) * 0.9 : 1;
    return base * C.nodeSize * (1 + C.sizeByDegree * Math.log2(1 + n.degree) * (n.kind === "neuron" ? 1 : 0.2));
  }
  function visible(n) {
    if (n.kind === "neuron") {
      if (hiddenGroups.has(n.group)) return false;
      if (n._t && n._t > cutoff) return false;
    }
    if (isolate && selected) return highlight.has(n.id);
    return true;
  }

  // ------------------------------------------------------------ build
  async function load() {
    $("#loading").classList.remove("hidden");
    data = await api(`/api/brain/graph3d?limit=${encodeURIComponent(C.limit)}`);
    byId = new Map(data.nodes.map((n) => [n.id, n])); nbrs = new Map(data.nodes.map((n) => [n.id, new Set()]));
    for (const l of data.links) { nbrs.get(l.source)?.add(l.target); nbrs.get(l.target)?.add(l.source); }
    maxDeg = Math.max(1, ...data.nodes.map((n) => n.degree || 0));
    times = data.nodes.filter((n) => n.learned).map((n) => (n._t = Date.parse(n.learned))).sort((a, b) => a - b);
    tMin = times[0] || 0; tMax = times[times.length - 1] || 1;
    groups = [...new Set(data.nodes.filter((n) => n.kind === "hub").map((n) => n.group))];
    paintPalette();
    $("#stat").textContent = `${data.meta.shown.toLocaleString()} of ${data.meta.articles.toLocaleString()} articles · ${data.meta.hubs} hubs`;
    if (!G) init(); else G.graphData(data);
    $("#loading").classList.toggle("hidden", data.nodes.length > 1);
    if (data.nodes.length <= data.meta.hubs + 1) $("#loading").replaceChildren(h("div", { class: "glass", style: "padding:14px 18px;color:#c3ccd5" },
      "The brain has no articles yet - press “Grow the brain” in Atlas, or download a Kiwix book."));
    fitted = false;
    // keep the whole brain in view while the layout unfolds, until you take the controls
    let fits = 0; const auto = setInterval(() => { if (fitted || ++fits > 12) return clearInterval(auto); G.zoomToFit(500, 50); }, 800);
  }
  function paintPalette() {
    const P = PRESETS[C.preset] || PRESETS.Synapse;
    groups.forEach((g, i) => groupColor.set(g, P.palette[i % P.palette.length]));
    $("#legend").replaceChildren(...data.nodes.filter((n) => n.kind === "hub").map((n) =>
      h("span", { class: hiddenGroups.has(n.group) ? "off" : "", title: `${n.count} article(s)`, onclick: (e) => {
        hiddenGroups.has(n.group) ? hiddenGroups.delete(n.group) : hiddenGroups.add(n.group); e.currentTarget.classList.toggle("off"); refresh(); } },
        h("span", { class: "sw", style: `background:${groupColor.get(n.group)}` }), n.label)));
  }

  function hubLabel(n) {
    if (C.labels !== "hubs" || n.kind === "neuron") return null;
    const s = new window.SpriteText(n.kind === "core" ? `Brain · ${data.meta.articles.toLocaleString()}` : `${n.label} ${n.count ? "· " + n.count : ""}`);
    s.color = "#e8edf2"; s.textHeight = n.kind === "core" ? 7 : 4.2; s.fontFace = "Chakra Petch, system-ui"; s.fontWeight = "600";
    s.backgroundColor = "rgba(8,12,18,.55)"; s.padding = 1.6; s.borderRadius = 3; s.position.y = Math.cbrt(nodeVal(n)) * 4 + 4;
    return s;
  }

  function init() {
    const el = $("#graph");
    G = window.ForceGraph3D({ controlType: "orbit", rendererConfig: { antialias: true, powerPreference: "high-performance" } })(el)
      .graphData(data)
      .backgroundColor(C.bg)
      .showNavInfo(false)
      .nodeRelSize(3.2)
      .nodeVal(nodeVal)
      .nodeColor(nodeColor)
      .nodeOpacity(C.nodeOpacity)
      .nodeResolution(C.quality === "low" ? 6 : 12)
      .nodeLabel(() => "")
      .nodeVisibility(visible)
      .nodeThreeObject(hubLabel).nodeThreeObjectExtend(true)
      .linkVisibility(linkVis)
      .linkColor(linkCol)
      .linkOpacity(C.linkOpacity)
      .linkWidth(linkW)
      .linkCurvature(C.curvature)
      .linkDirectionalParticleWidth(1.6)
      .linkDirectionalParticleColor(() => "#ecfeff")
      .linkDirectionalParticleSpeed(() => C.firingSpeed)
      .warmupTicks(data.nodes.length > 2000 ? 40 : 80)
      .cooldownTime(9000)
      .d3AlphaDecay(0.028).d3VelocityDecay(0.35)
      .onEngineStop(() => { if (!fitted) { fitted = true; G.zoomToFit(900, 50); } })
      .onNodeClick((n) => select(n, true))
      .onNodeRightClick((n) => togglePin(n))
      .onBackgroundClick(() => select(null))
      .onNodeHover((n) => { hover = n; el.style.cursor = n ? "pointer" : ""; showTip(n); });
    G.d3Force("charge").strength(C.charge);
    G.d3Force("link").distance((l) => (l.kind === "core" ? C.distance * 3.2 : l.kind === "hub" ? C.distance * 1.3 : C.distance));
    bloomPass = new window.UnrealBloomPass(new window.THREE.Vector2(innerWidth, innerHeight), C.bloomStrength, 0.55, 0.12);
    G.postProcessingComposer().addPass(bloomPass);
    applyLook();
    addEventListener("resize", () => G.width(innerWidth).height(innerHeight));
    for (const ev of ["pointerdown", "wheel"]) el.addEventListener(ev, () => { fitted = true; }, { passive: true });
    document.addEventListener("visibilitychange", () => (document.hidden ? G.pauseAnimation() : G.resumeAnimation()));
    firingLoop(); fpsLoop();
  }

  // ------------------------------------------------------------ look & physics
  function applyLook() {
    if (!G) return;
    G.backgroundColor(C.bg).nodeOpacity(C.nodeOpacity).linkOpacity(C.linkOpacity).linkCurvature(C.curvature)
      .nodeVal(nodeVal).nodeThreeObject(hubLabel);
    bloomPass.enabled = !!C.bloom; bloomPass.strength = C.bloomStrength;
    const ctl = G.controls(); ctl.autoRotate = !!C.rotate; ctl.autoRotateSpeed = 0.6; ctl.enableDamping = true; ctl.dampingFactor = 0.08;
    G.d3Force("charge").strength(C.charge);
    G.d3Force("link").distance((l) => (l.kind === "core" ? C.distance * 3.2 : l.kind === "hub" ? C.distance * 1.3 : C.distance));
    if (C.freeze) data.nodes.forEach((n) => { n.fx = n.x; n.fy = n.y; n.fz = n.z; });
    else data.nodes.forEach((n) => { if (!n._pinned) { n.fx = n.fy = n.fz = undefined; } });
    refresh();
  }
  const linkVis = (l) => visible(l.source.id ? l.source : byId.get(l.source)) && visible(l.target.id ? l.target : byId.get(l.target));
  const linkCol = (l) => (hlLinks.has(l) ? "#e0fbff" : l.kind === "bridge" ? "#fbbf24" : l.kind === "core" ? "#64748b" : "#7dd3fc");
  const linkW = (l) => (hlLinks.has(l) ? Math.max(0.6, C.linkWidth * 2) : C.linkWidth);
  function refresh() {  // fresh wrappers so the renderer re-applies them
    if (G) G.nodeColor((n) => nodeColor(n)).nodeVisibility((n) => visible(n)).linkVisibility((l) => linkVis(l))
      .linkWidth((l) => linkW(l)).linkColor((l) => linkCol(l));
  }

  // ------------------------------------------------------------ synapse firing (emits pulses, no per-frame cost when off)
  function firingLoop() {
    setInterval(() => {
      if (!C.firing || document.hidden || !G) return;
      const links = G.graphData().links; if (!links.length) return;
      const pool = hlLinks.size ? [...hlLinks] : links;
      const n = hlLinks.size ? Math.min(6, pool.length) : Math.min(10, Math.ceil(links.length / 300));
      for (let i = 0; i < n; i++) { const l = pool[(Math.random() * pool.length) | 0]; if (l && linkVis(l)) G.emitParticle(l); }
    }, 160);
  }

  // ------------------------------------------------------------ fps + adaptive quality
  function fpsLoop() {
    let frames = 0, t0 = performance.now(), slow = 0, fast = 0, ratio = Math.min(devicePixelRatio || 1, 2);
    const tick = () => {
      frames++; const now = performance.now();
      if (now - t0 >= 1000) {
        const fps = Math.round((frames * 1000) / (now - t0)); frames = 0; t0 = now;
        $("#fps").textContent = `${fps} fps`;
        if (C.quality === "auto" && !document.hidden) {
          slow = fps < 45 ? slow + 1 : 0; fast = fps > 58 ? fast + 1 : 0;
          if (slow >= 2 && ratio > 0.75) { ratio = Math.max(0.75, ratio - 0.25); G.renderer().setPixelRatio(ratio); slow = 0; }
          if (slow >= 2 && bloomPass.enabled && ratio <= 0.75) { bloomPass.enabled = false; slow = 0; }
          if (fast >= 4 && ratio < Math.min(devicePixelRatio || 1, 2)) { ratio += 0.25; G.renderer().setPixelRatio(ratio); fast = 0; }
        }
      }
      requestAnimationFrame(tick);
    };
    if (C.quality === "high") G.renderer().setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    if (C.quality === "low") G.renderer().setPixelRatio(0.75);
    requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------ selection + inspector
  function neighbours(id, hops) {
    const seen = new Set([id]); let frontier = [id];
    for (let d = 0; d < hops; d++) { const next = []; for (const x of frontier) for (const y of nbrs.get(x) || []) if (!seen.has(y)) { seen.add(y); next.push(y); } frontier = next; }
    return seen;
  }
  function select(n, fly) {
    if (pathFrom && n && n !== pathFrom) { tracePath(pathFrom, n); pathFrom = null; return; }
    selected = n; similar.clear();
    highlight = n ? neighbours(n.id, isolate || 1) : new Set();
    hlLinks = new Set(n ? G.graphData().links.filter((l) => highlight.has(l.source.id) && highlight.has(l.target.id) && (l.source.id === n.id || l.target.id === n.id || isolate > 1)) : []);
    refresh(); inspector(n);
    if (n && fly) {  // keep the current viewing direction, stop a comfortable distance away
      const cam = G.camera().position, dist = 150 + Math.cbrt(nodeVal(n)) * 20;
      let dx = cam.x - (n.x || 0), dy = cam.y - (n.y || 0), dz = cam.z - (n.z || 0);
      const len = Math.hypot(dx, dy, dz) || 1; dx /= len; dy /= len; dz /= len;
      G.cameraPosition({ x: (n.x || 0) + dx * dist, y: (n.y || 0) + dy * dist, z: (n.z || 0) + dz * dist }, n, 1100);
    }
  }
  function kindLabel(n) { return n.kind === "core" ? "the whole brain" : n.kind === "hub" ? "division hub" : "neuron · article"; }
  function inspector(n) {
    $("#insp-empty").classList.toggle("hidden", !!n); $("#insp").classList.toggle("hidden", !n);
    if (!n) return;
    $("#inspector").classList.remove("collapsed");
    $("#insp-sw").style.background = baseColor(n); $("#insp-kind").textContent = kindLabel(n);
    $("#insp-title").textContent = n.label;
    const rows = n.kind === "neuron" ? [["Division", n.division], ["Tier", TIER[n.tier] || "tier " + n.tier], ["Learned", (n.learned || "").replace("T", " ").slice(0, 16)],
      ["Source", n.source], ["Licence", n.license || "—"], ["Size", `${(n.chars || 0).toLocaleString()} chars`], ["Links", n.degree]]
      : n.kind === "hub" ? [["Articles", (n.count || 0).toLocaleString()], ["Links", n.degree]] : [["Articles", data.meta.articles.toLocaleString()], ["Shown", data.meta.shown.toLocaleString()]];
    $("#insp-meta").replaceChildren(...rows.flatMap(([k, v]) => [h("div", {}, k), h("div", {}, String(v))]));
    $("#insp-snip").textContent = n.snippet || "";
    const acts = [];
    if (n.kind === "neuron") {
      acts.push(h("button", { class: "btn", onclick: () => window.open("/#ask=" + encodeURIComponent(`Tell me about ${n.label}`), "_blank") }, "Ask E.V about this"));
      acts.push(h("button", { class: "btn", onclick: readFull }, "Read full text"));
      const u = safeUrl(n.url); if (u) acts.push(h("a", { class: "btn", href: u, target: "_blank", rel: "noopener" }, "Open source ↗"));
      acts.push(h("button", { class: "btn", onclick: findSimilar }, "Find similar"));
    }
    acts.push(h("button", { class: "btn" + (isolate ? " on" : ""), onclick: () => { isolate = isolate === 0 ? 1 : isolate === 1 ? 2 : 0; select(selected); } },
      isolate ? `Isolated (${isolate} hop${isolate > 1 ? "s" : ""})` : "Isolate"));
    acts.push(h("button", { class: "btn", onclick: () => { pathFrom = n; $("#path-h").classList.remove("hidden"); $("#path-out").classList.remove("hidden");
      $("#path-out").textContent = "Now click another neuron to trace the shortest path…"; } }, "Path to…"));
    acts.push(h("button", { class: "btn" + (n._pinned ? " on" : ""), onclick: () => { togglePin(n); inspector(n); } }, n._pinned ? "Unpin" : "Pin"));
    $("#insp-acts").replaceChildren(...acts);
    const list = [...(nbrs.get(n.id) || [])].map((id) => byId.get(id)).filter(Boolean)
      .sort((a, b) => (a.kind === "neuron") - (b.kind === "neuron") || b.degree - a.degree).slice(0, 60);
    $("#insp-nbr-h").textContent = `Connected (${(nbrs.get(n.id) || new Set()).size})`;
    $("#insp-nbrs").replaceChildren(...list.map((m) => h("button", { onclick: () => select(m, true) },
      h("span", { class: "sw", style: `background:${baseColor(m)}` }), m.label, h("span", { class: "grow" }), h("small", { style: "color:#6b7785" }, m.kind === "hub" ? "hub" : ""))));
  }
  async function readFull() {
    if (!selected) return; const box = $("#insp-snip"); box.textContent = "loading…";
    try { const a = await api("/api/brain/article?key=" + encodeURIComponent(selected.key));
      box.textContent = (a.aliases.length ? `Also known as: ${a.aliases.join(", ")}\n\n` : "") + a.text + `\n\n— ${a.license || ""}`; }
    catch (e) { box.textContent = "Couldn't load it: " + e.message; }
  }
  async function findSimilar() {
    if (!selected) return;
    const hits = await api("/api/kb/search?k=15&q=" + encodeURIComponent(selected.label)).catch(() => []);
    const keys = new Set(hits.map((x) => x.key));
    similar = new Set(data.nodes.filter((n) => keys.has(n.key) && n.id !== selected.id).map((n) => n.id));
    highlight = new Set([selected.id, ...similar]); refresh();
    $("#insp-nbr-h").textContent = `Similar (${hits.length - 1 > 0 ? hits.length - 1 : 0} found, ${similar.size} on screen)`;
    $("#insp-nbrs").replaceChildren(...hits.filter((x) => x.key !== selected.key).map((x) => {
      const n = data.nodes.find((m) => m.key === x.key);
      return h("button", { onclick: () => n && select(n, true), title: x.why || "" }, h("span", { class: "sw", style: `background:${n ? baseColor(n) : "#475569"}` }),
        x.title, h("span", { class: "grow" }), h("small", { style: "color:#6b7785" }, n ? "" : "not shown"));
    }));
  }
  function tracePath(a, b) {
    const prev = new Map([[a.id, null]]), q = [a.id];
    while (q.length) { const x = q.shift(); if (x === b.id) break; for (const y of nbrs.get(x) || []) if (!prev.has(y)) { prev.set(y, x); q.push(y); } }
    if (!prev.has(b.id)) { $("#path-out").textContent = "No path between them."; return; }
    const path = []; for (let x = b.id; x; x = prev.get(x)) path.unshift(x);
    const set = new Set(path);
    highlight = set; hlLinks = new Set(G.graphData().links.filter((l) => set.has(l.source.id) && set.has(l.target.id) &&
      Math.abs(path.indexOf(l.source.id) - path.indexOf(l.target.id)) === 1));
    selected = b; refresh(); inspector(b);
    $("#path-h").classList.remove("hidden"); $("#path-out").classList.remove("hidden");
    $("#path-out").textContent = `${path.length - 1} step(s): ` + path.map((id) => byId.get(id).label).join(" → ");
  }
  function togglePin(n) {
    n._pinned = !n._pinned;
    if (n._pinned) { n.fx = n.x; n.fy = n.y; n.fz = n.z; } else { n.fx = n.fy = n.fz = undefined; }
  }

  // ------------------------------------------------------------ tooltip, search, timeline
  let mx = 0, my = 0; addEventListener("mousemove", (e) => { mx = e.clientX; my = e.clientY; const t = $("#tip"); if (!t.classList.contains("hidden")) { t.style.left = mx + 14 + "px"; t.style.top = my + 12 + "px"; } });
  function showTip(n) {
    const t = $("#tip");
    if (!n) { t.classList.add("hidden"); return; }
    t.replaceChildren(h("b", {}, n.label), n.kind === "neuron" ? h("div", { style: "color:#8b97a4;font-size:11.5px" }, `${n.division} · ${TIER[n.tier] || ""}`) : null);
    t.style.left = mx + 14 + "px"; t.style.top = my + 12 + "px"; t.classList.remove("hidden");
  }
  const find = $("#find"), results = $("#results");
  find.addEventListener("input", () => {
    const q = find.value.trim().toLowerCase();
    if (!q) { results.classList.add("hidden"); return; }
    const hits = data.nodes.filter((n) => n.label.toLowerCase().includes(q)).sort((a, b) => a.label.length - b.label.length).slice(0, 12);
    results.replaceChildren(...(hits.length ? hits.map((n) => h("button", { onclick: () => { results.classList.add("hidden"); find.value = n.label; select(n, true); } },
      n.label, " ", h("small", {}, n.kind === "neuron" ? n.division : n.kind))) : [h("div", { class: "hint3d", style: "padding:8px" }, "No neuron by that name on screen.")]));
    results.classList.remove("hidden");
  });
  find.addEventListener("keydown", (e) => { if (e.key === "Enter") { const b = results.querySelector("button"); if (b) b.click(); } });
  addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") { if (e.key === "Escape") e.target.blur(); return; }
    if (e.key === "/") { e.preventDefault(); find.focus(); }
    if (e.key === "Escape") { isolate = 0; select(null); }
    if (e.key === "f" || e.key === "F") G.zoomToFit(800, 60);
  });
  function setCutoff(v) {
    if (!times.length) return;
    if (v >= 1000) { cutoff = Infinity; $("#tl-when").textContent = "now"; }
    else { cutoff = times[Math.min(times.length - 1, Math.floor((v / 1000) * times.length))]; $("#tl-when").textContent = new Date(cutoff).toLocaleString(); }
    refresh();
  }
  $("#tl").addEventListener("input", (e) => setCutoff(+e.target.value));
  $("#tl-play").addEventListener("click", () => {
    let v = 0; const tl = $("#tl"); const step = () => { v += 12; tl.value = Math.min(1000, v); setCutoff(+tl.value); if (v < 1000) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  });

  // ------------------------------------------------------------ customize panel
  function bindControls() {
    $("#presets").replaceChildren(...Object.keys(PRESETS).map((p) => h("button", { class: p === C.preset ? "on" : "", onclick: () => {
      const P = PRESETS[p]; Object.assign(C, { preset: p, bg: P.bg, bloom: P.bloom, bloomStrength: P.bloomStrength, linkOpacity: P.linkOpacity, curvature: P.curvature });
      save(); syncControls(); paintPalette(); applyLook(); bindControls(); } }, p)));
    syncControls();
  }
  function syncControls() {
    for (const [k, v] of Object.entries(C)) {
      const el = $("#c-" + k); if (!el) continue;
      if (el.type === "checkbox") el.checked = !!v; else el.value = v;
      const out = el.parentElement && el.parentElement.querySelector(".v"); if (out) out.textContent = (+v).toFixed(Math.abs(+v) >= 10 ? 0 : 2);
    }
  }
  document.querySelectorAll("[id^='c-']").forEach((el) => {
    const key = el.id.slice(2);
    el.addEventListener(el.type === "checkbox" || el.tagName === "SELECT" || el.type === "color" ? "change" : "input", () => {
      C[key] = el.type === "checkbox" ? el.checked : el.type === "range" ? +el.value : el.value;
      const out = el.parentElement.querySelector(".v"); if (out) out.textContent = (+el.value).toFixed(Math.abs(+el.value) >= 10 ? 0 : 2);
      save();
      if (key === "limit") { load(); return; }
      if (key === "quality") { location.reload(); return; }
      if (key === "charge" || key === "distance") { applyLook(); G.d3ReheatSimulation(); return; }
      applyLook();
    });
  });
  $("#reset").addEventListener("click", () => { C = { ...DEFAULTS }; save(); location.reload(); });
  $("#fit").addEventListener("click", () => G.zoomToFit(800, 60));
  $("#toggle-custom").addEventListener("click", () => $("#custom").classList.toggle("collapsed"));
  $("#toggle-inspector").addEventListener("click", () => $("#inspector").classList.toggle("collapsed"));

  bindControls();
  load().catch((e) => $("#loading").replaceChildren(h("div", {}, "Couldn't load the brain: " + e.message)));
  window.BRAIN3D = { get graph() { return G; }, get data() { return data; }, select: (id) => select(byId.get(id), true), settings: () => ({ ...C }) };
})();
