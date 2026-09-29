const { chromium } = require("playwright");
const out = process.argv[2];
const ok = (c, m) => { if (!c) { console.log("FAIL", m); process.exitCode = 1; } else console.log("PASS", m); };
(async () => {
  const b = await chromium.launch({ executablePath: process.env.CHROME || undefined,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"] });
  const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on("pageerror", (e) => errs.push(e.message)); p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  await p.goto("http://127.0.0.1:8611/"); await p.waitForSelector("#welcome");
  await p.screenshot({ path: out + "/0-chat-home.png" });

  // E.V chat is home: skills run, cards are interactive, answers are checked
  ok(await p.isVisible("#welcome") && (await p.$$("#suggest button")).length === 4, "E.V welcome with suggestions");
  await p.fill("#chat-input", "help me plan my week"); await p.keyboard.press("Enter");
  await p.waitForSelector(".plan-step", { timeout: 15000 });
  ok((await p.$$(".plan-step")).length === 5, "Interactive Planning card with 5 steps");
  await p.click(".plan-step input[type=checkbox] >> nth=0"); await p.waitForSelector("text=1/5 done");
  ok(true, "ticking a step saves it (1/5 done)");
  ok((await p.textContent("#conv-list")).includes("help me plan my week"), "conversation listed in the sidebar");
  await p.fill("#chat-input", "What is World War II?"); await p.keyboard.press("Enter");
  await p.waitForFunction(() => { const m = document.querySelectorAll(".msg.ev"); return m.length >= 2 && m[m.length - 1].querySelectorAll(".xray span").length >= 1; }, null, { timeout: 15000 });
  ok((await p.textContent("#messages")).includes("Research Synthesis"), "brain search used for a question");
  ok((await p.textContent("#messages")).includes("World War II"), "answer comes from the brain");
  await p.screenshot({ path: out + "/0b-chat.png" });
  await p.click("[data-view='settings']"); await p.waitForSelector(".dial");
  ok((await p.$$(".dial")).length === 9, "nine personality dials in Settings");
  await p.click("[data-view='investigate']"); await p.waitForSelector("#filters button");
  await p.screenshot({ path: out + "/1-empty.png" });

  await p.fill("#q", "jdoe_42"); await p.waitForFunction(() => document.querySelector("#type-btn").textContent !== "auto");
  ok((await p.textContent("#type-btn")).toLowerCase().includes("user"), "type auto-detected as username: " + await p.textContent("#type-btn"));
  ok((await p.textContent("#filters button.on")).startsWith("Username"), "Username filter auto-selected");
  ok((await p.textContent("#cmd")).includes("openatlas investigate jdoe_42 --filter username"), "command autofilled from filter: " + await p.textContent("#cmd"));
  ok(await p.isDisabled("#run"), "Run disabled until a purpose is chosen");
  ok(/^Run all \d+ ▸$/.test(await p.textContent("#run")), "Run says how many sources it will use: " + await p.textContent("#run"));
  ok((await p.$$(".tile.more")).length === 1 && !(await p.$$(".tile:has(.meta span:text-is('tool'))")).length,
    "single-purpose tools folded under one 'More tools' tile");
  ok(!(await p.textContent("#filters")).includes("Breach"), "filters with nothing for a username are hidden");
  await p.screenshot({ path: out + "/1b-typed.png" });

  await p.click("#purposes button >> nth=0");
  await p.click(".tile:has-text('Keybase proofs')");
  await p.click(".tile:has-text('GitHub profiles')");
  const cmd = await p.textContent("#cmd");
  ok(/--sources keybase,github/.test(cmd) && cmd.includes("--purpose"), "tiles autofill --sources and --purpose: " + cmd);
  ok((await p.textContent("#run")) === "Run 2 ▸", "Run counts the selected sources");
  const titles = await p.$$eval(".tile .t", (els) => els.map((e) => e.textContent));
  ok(titles.every((t) => !t.includes("_")), `no snake_case in ${titles.length} tile titles`);
  ok(new Set(titles).size === titles.length, "tile titles are unique");
  await p.screenshot({ path: out + "/2-selected.png" });

  await p.click("#run");
  await p.waitForSelector("text=complete", { timeout: 30000 });
  ok(!/\bnull\b|undefined/.test(await p.textContent("#results")), "no 'null'/'undefined' text in results");
  const cards = await p.$$(".card"); ok(cards.length >= 3, `evidence cards rendered: ${cards.length}`);
  const links = await p.$$eval(".card a[href^='http']", (as) => as.map((a) => a.href)); ok(links.length >= 3, "cards carry source links");
  ok((await p.textContent("#results")).match(/confirmed/i), "verification badges shown");
  await p.waitForSelector(".check", { timeout: 10000 });
  ok((await p.textContent(".check")).includes("confirmed"), "ATLAS check row appears after the case: " + (await p.textContent(".check")).slice(0, 90));
  await p.screenshot({ path: out + "/3-results.png", fullPage: true });

  // a tool tile autofills `openatlas run`
  await p.click("#filters button:has-text('Domain')");
  await p.fill("#q", "example.com"); await p.waitForTimeout(400);
  await p.click(".tile.more");
  const tool = await p.$(".tile:has(.meta span:text-is('tool'))"); await tool.click();
  ok((await p.textContent("#cmd")).startsWith("openatlas run "), "tool tile autofills `openatlas run`: " + await p.textContent("#cmd"));

  // Auto-plan (ATLAS loop step 1): proposes sources, a human still presses Run
  await p.click("#autoplan"); await p.waitForSelector("#plan-note:not(.hidden)");
  const planned = await p.textContent("#cmd");
  ok(/--sources [a-z-]+(,[a-z-]+)+/.test(planned) && planned.includes("rdap"), "Auto-plan selects domain sources: " + planned);
  ok(/Auto-plan \((heuristic|local AI)\)/.test(await p.textContent("#plan-note")), "plan explains itself: " + await p.textContent("#plan-note"));
  ok(/^Run \d+ ▸$/.test(await p.textContent("#run")), "Run shows the planned count: " + await p.textContent("#run"));
  await p.screenshot({ path: out + "/7-autoplan.png" });

  for (const v of ["brain", "skills", "system", "cases"]) {
    await p.click(`[data-view='${v}']`).catch(() => p.click(`text=${v[0].toUpperCase() + v.slice(1)}`));
    await p.waitForTimeout(700); await p.screenshot({ path: `${out}/4-${v}.png` });
  }
  ok((await p.textContent("#cases-body")).includes("jdoe_42"), "case listed in Cases view");
  await p.click("[data-view='brain']").catch(() => p.click("text=Brain")); await p.waitForTimeout(300);
  const [viz] = await Promise.all([p.context().waitForEvent("page"), p.click("#brain-graph")]);
  await viz.waitForLoadState(); await viz.waitForTimeout(1500);
  const g = await viz.evaluate(() => window.ATLAS_GRAPH && { n: window.ATLAS_GRAPH.nodes.length, src: window.ATLAS_GRAPH.meta.source });
  ok(g && g.src === "OpenAtlas brain" && g.n >= 15, "Brain graph opens the visualizer with the brain: " + JSON.stringify(g));
  await viz.screenshot({ path: out + "/6-brain-graph.png" }); await viz.close();
  // Brain graph (2D): the Customize panel applies and remembers settings; a slow GPU eases off
  const [bg] = await Promise.all([p.context().waitForEvent("page"), p.click("#brain-graph")]);
  await bg.waitForFunction(() => window.ATLAS_VIZ && window.ATLAS_VIZ.stats().fps > 0, null, { timeout: 30000 });
  await bg.click("#custom-btn"); await bg.selectOption("#c-labels", "hubs"); await bg.selectOption("#c-fps", "60");
  await bg.reload(); await bg.waitForFunction(() => window.ATLAS_VIZ, null, { timeout: 30000 });
  const vs = await bg.evaluate(() => window.ATLAS_VIZ.settings());
  ok(vs.labels === "hubs" && vs.fps === "60", "brain graph settings persist: " + JSON.stringify(vs));
  await bg.evaluate(() => window.ATLAS_VIZ.simulateFps(6));
  await bg.waitForFunction(() => window.ATLAS_VIZ.stats().level === 3, null, { timeout: 30000 });
  ok(true, "brain graph eases off (glow, photons, labels) when frames drop");
  await bg.evaluate(() => { window.ATLAS_VIZ.simulateFps(0); });
  await bg.click("#custom-btn"); await bg.click("#custom-reset");
  ok((await bg.evaluate(() => window.ATLAS_VIZ.settings().labels)) === "all", "brain graph settings reset to defaults");
  await bg.screenshot({ path: out + "/6b-brain-graph-custom.png" }); await bg.close();
  ok((await p.$("#brain-3d")) === null, "no 3D brain button any more");
  await p.emulateMedia({ colorScheme: "light" }); await p.click("#theme"); await p.waitForTimeout(200);
  await p.screenshot({ path: out + "/5-light.png" });
  const idle = await p.evaluate(async () => { let frames = 0; const t0 = performance.now();
    await new Promise((r) => { const tick = () => { frames++; performance.now() - t0 < 2000 ? requestAnimationFrame(tick) : r(); }; requestAnimationFrame(tick); });
    return { anims: document.getAnimations().length, frames }; });
  ok(idle.anims === 0, "no running CSS animations when idle: " + JSON.stringify(idle));
  // Subtitles: what E.V says aloud is printed on screen (muted monitor); the test plays the
  // voice server's part through a stand-in socket and a fake microphone
  const vctx = await b.newContext({ viewport: { width: 1360, height: 900 }, permissions: ["microphone"] });
  const vp = await vctx.newPage(); vp.on("pageerror", (e) => errs.push(e.message));
  await vp.addInitScript(() => {
    const Real = window.WebSocket;
    window.WebSocket = function (url) {
      if (!String(url).includes("/ws/ev/voice")) return new Real(url);
      const fake = { readyState: 1, binaryType: "arraybuffer", send() {}, close() {} };
      window.__voiceWS = fake; return fake;
    };
    window.__srv = (ev) => window.__voiceWS.onmessage({ data: JSON.stringify(ev) });
    window.__pcm = (sec) => window.__voiceWS.onmessage({ data: new Int16Array(Math.round(24000 * sec)).buffer });
  });
  await vp.goto("http://127.0.0.1:8611/"); await vp.waitForSelector("#welcome");
  await vp.click("#mic"); await vp.waitForFunction(() => window.__voiceWS && window.__voiceWS.onmessage, null, { timeout: 15000 });
  await vp.evaluate(() => { __srv({ type: "ready", stt: true, tts: "server" }); __srv({ type: "audio_start", text: "The capital of Australia is Canberra.", rate: 24000 }); __pcm(1.2); __srv({ type: "audio_end" }); });
  await vp.waitForFunction(() => !document.querySelector("#subtitles").classList.contains("hidden"), null, { timeout: 5000 });
  ok((await vp.textContent("#subtitles")) === "The capital of Australia is Canberra.", "subtitles show what E.V says aloud");
  await vp.screenshot({ path: out + "/0c-subtitles.png" });
  await vp.evaluate(() => { __srv({ type: "audio_start", text: "It was a compromise between Sydney and Melbourne.", rate: 24000 }); __pcm(3); __srv({ type: "audio_end" }); });
  await vp.waitForFunction(() => document.querySelector("#subtitles").textContent.startsWith("It was"), null, { timeout: 5000 });
  await vp.evaluate(() => __srv({ type: "audio_stop" }));
  ok((await vp.textContent("#subtitles")).endsWith("(stopped)"), "talking over her marks where she stopped");
  await vctx.close();
  // Brain: answers cite only on-topic articles and say why they matched
  await p.click("[data-view='brain']"); await p.waitForTimeout(300);
  await p.fill("#ask-q", "WWII"); await p.click("#ask-go");
  await p.waitForSelector(".cites a", { timeout: 10000 });
  const cites = await p.$$eval(".cites a", (as) => as.map((a) => a.textContent));
  ok(cites.length === 1 && cites[0] === "World War II", "ask 'WWII' cites only World War II: " + JSON.stringify(cites));
  ok((await p.textContent("#ask-out")).includes("matched: exact alias"), "citation says why it matched");
  await p.screenshot({ path: out + "/8-ask.png" });

  // Library (Kiwix): catalog -> download -> verified; the same book can't be downloaded twice
  await p.click("[data-view='library']"); await p.waitForTimeout(300);
  await p.click("#lib-go"); await p.waitForSelector("#lib-catalog .lib-row");
  await p.click("#lib-catalog button:has-text('Download')");
  await p.waitForFunction(() => /ingested/.test(document.querySelector("#lib-books").textContent), null, { timeout: 20000 });
  ok((await p.textContent("#lib-books")).includes("verified"), "download finished, was checksum-verified and fed the brain");
  await p.click("#lib-go"); await p.waitForSelector("#lib-catalog button:has-text('In library')");
  ok(await p.isDisabled("#lib-catalog button:has-text('In library')"), "the same book can't be downloaded twice");
  await p.screenshot({ path: out + "/9-library.png", fullPage: true });
  ok(errs.length === 0, "no JS errors " + JSON.stringify(errs));
  await b.close();
})().catch((e) => { console.log("CRASH", e.message); process.exitCode = 1; });
