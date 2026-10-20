"use strict";
// Ghostship agent viewer. Everything from the server is untrusted display
// data: it only ever reaches the page through textContent / attributes.

const HDR = { "X-Ghostship-Viewer": "1" };
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

const S = {
  runs: [], browsers: {}, clockSkew: 0,
  current: null, detail: null, target: null,
  ws: null, wsTimer: null, wsBackoff: 500,
  meta: null, frameW: 0, frameH: 0,
  view: { z: 1, tx: 0, ty: 0 }, img: { x: 0, y: 0, w: 0, h: 0 },
  dialog: null,
  modePref: { portrait: null, landscape: null }, layoutMode: null,
  manualAt: 0, knownTabs: null, lastStateAt: 0,
  apps: [], closing: new Set(), launching: null,
};

// ---------------------------------------------------------------- helpers
function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.round(Date.now() / 1000 - S.clockSkew - ts));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function runTitle(run) {
  const o = run.owner || {};
  return run.label || run.app_name || o.t3_thread_title || `Run ${run.run_id.slice(0, 8)}`;
}
function isApp(run) { return run && run.kind === "app"; }
function ownerLine(run) {
  const o = run.owner || {};
  return [o.harness, o.model].filter(Boolean).join(" · ");
}
function stateLine(run) {
  const st = run.state;
  if (!st && isApp(run)) return (run.tabs[0] && run.tabs[0].title) || run.app_name || "App";
  if (!st) return run.registered ? "No activity recorded yet" : "Untracked window";
  const what = [st.tool, st.action].filter(Boolean).join(": ");
  const mark = st.ok === false ? "✗ " : "";
  return `${mark}${what} · ${ago(st.at)}`;
}
function isHuman(run) { return (run.owner || {}).harness === "human"; }
// T3 thread: a t3-thread:// deep link (opens the T3 app) when the id is known.
function threadNode(o, prefix) {
  if (!o || !(o.t3_thread_id || o.t3_thread_title)) return null;
  const text = (prefix || "") + (o.t3_thread_title || o.t3_thread_id);
  if (!o.t3_thread_id) return el("span", null, text);
  const a = el("a", "thread", text);
  a.href = `t3-thread://v1/${encodeURIComponent(o.t3_thread_id)}`;
  a.title = "Open the thread in T3";
  a.addEventListener("click", (e) => e.stopPropagation());
  return a;
}
function tabLabel(tab) {
  if (tab.is_anchor) return "⚓ home";
  return tab.title || tab.origin || "tab";
}
async function api(path, opts = {}) {
  const res = await fetch(path, { cache: "no-store", ...opts, headers: { ...(opts.headers || {}), ...HDR } });
  let body = null;
  try { body = await res.json(); } catch (_) { /* empty */ }
  if (!res.ok) {
    const err = new Error((body && body.error) || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}
function toast(msg) {
  const b = $("banner");
  b.textContent = msg; b.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { b.hidden = true; renderBanner(); }, 4000);
}

// ---------------------------------------------------------------- grid
const cards = new Map();
let visible = new Set();
const observer = "IntersectionObserver" in window ? new IntersectionObserver((entries) => {
  for (const e of entries) {
    const id = e.target.dataset.run;
    if (e.isIntersecting) { visible.add(id); refreshThumb(id); } else visible.delete(id);
  }
}) : null;

async function loadRuns() {
  try {
    const data = await api("api/runs");
    S.runs = (data.runs || []).filter((r) => !S.closing.has(r.run_id));
    S.browsers = data.browsers || {};
    renderAppButtons(data.apps || []);
    S.clockSkew = Date.now() / 1000 - (data.now || Date.now() / 1000);
    renderGrid();
    if (S.current) renderHeader();
  } catch (err) {
    $("browsers").textContent = "viewer offline";
  }
}

function renderBanner() {
  const stopped = Object.entries(S.browsers).filter(([, v]) => v !== "up").map(([k]) => k);
  const b = $("banner");
  if (!b.hidden && toast.t) return;
  b.hidden = stopped.length === 0;
  b.textContent = stopped.length ? `Browser stopped: ${stopped.join(", ")} (it starts when an agent or + opens a window)` : "";
}

function renderGrid() {
  const ordered = [...S.runs.filter(isApp), ...S.runs.filter((r) => !isApp(r))];
  $("browsers").textContent = `${S.runs.length} open`;
  renderBanner();
  renderLauncher();
  $("empty").hidden = S.runs.length > 0;
  const keep = new Set();
  for (const [grid, runs] of [[$("grid"), ordered]]) {
    runs.forEach((run, i) => {
      keep.add(run.run_id);
      let card = cards.get(run.run_id);
      if (!card) {
        card = buildCard(run.run_id);
        cards.set(run.run_id, card);
        if (observer) observer.observe(card.root); else visible.add(run.run_id);
      }
      fillCard(card, run);
      if (grid.children[i] !== card.root) grid.insertBefore(card.root, grid.children[i] || null);
    });
  }
  for (const [id, card] of cards) {
    if (!keep.has(id)) { if (observer) observer.unobserve(card.root); card.root.remove(); cards.delete(id); visible.delete(id); }
  }
}

function buildCard(id) {
  const root = el("article", "card");
  root.dataset.run = id;
  root.tabIndex = 0;
  const thumb = el("div", "thumb");
  const img = el("img"); img.alt = "";
  const badges = el("div", "badges");
  thumb.append(img, badges);
  const body = el("div", "card-body");
  const title = el("div", "card-title");
  const owner = el("div", "card-line muted");
  const thread = el("div", "card-line muted");
  const state = el("div", "card-line");
  const foot = el("div", "card-foot");
  const age = el("span", "muted card-line");
  const grow = el("span", "grow");
  const pause = el("button", "btn pause");
  pause.type = "button";
  const close = el("button", "btn", "Close");
  close.type = "button";
  foot.append(age, grow, close, pause);
  body.append(title, owner, thread, state, foot);
  root.append(thumb, body);
  root.addEventListener("click", (e) => { if (e.target !== pause && e.target !== close) openRun(id); });
  close.addEventListener("click", (e) => { e.stopPropagation(); closeRun(id); });
  root.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === root) openRun(id); });
  pause.addEventListener("click", (e) => { e.stopPropagation(); togglePause(id); });
  return { root, img, badges, title, owner, thread, state, age, pause };
}

function fillCard(card, run) {
  card.root.classList.toggle("paused", run.paused);
  card.title.textContent = runTitle(run);
  card.owner.textContent = ownerLine(run) || (run.registered ? "" : "no registry entry");
  const thread = threadNode(run.owner, "Thread: ");
  card.thread.replaceChildren(...(thread ? [thread] : []));
  card.thread.hidden = !thread;
  card.state.textContent = stateLine(run);
  card.state.classList.toggle("fail", !!(run.state && run.state.ok === false));
  const tabs = run.tabs.filter((t) => !t.is_anchor);
  const first = tabs.length ? tabs[tabs.length - 1].origin : "";
  card.age.textContent = [ago(run.opened_at || run.seen_at), `${run.tabs.length} tab${run.tabs.length === 1 ? "" : "s"}`, first].filter(Boolean).join(" · ");
  card.pause.textContent = run.paused ? "Resume" : "Pause";
  card.pause.classList.toggle("paused", run.paused);
  card.badges.replaceChildren(el("span", `badge ${run.identity}`, isApp(run) ? run.app_name || "app" : run.identity));
  if (run.paused) card.badges.append(el("span", "badge paused", "paused"));
  if (isHuman(run)) card.badges.append(el("span", "badge human", "human"));
  card.run = run;
}

function refreshThumb(id) {
  const card = cards.get(id);
  if (!card || !card.run || card.loading || S.current) return;
  card.loading = true;
  const target = card.run.primary_target || "";
  const probe = new Image();
  const done = () => { card.loading = false; };
  probe.onload = () => { card.img.src = probe.src; done(); };
  probe.onerror = done;
  probe.src = `api/runs/${encodeURIComponent(id)}/thumb?target=${encodeURIComponent(target)}&_=${Date.now()}`;
}
setInterval(() => { if (!document.hidden && !S.current) for (const id of visible) refreshThumb(id); }, 2000);

async function togglePause(id) {
  const run = S.runs.find((r) => r.run_id === id) || (S.detail && S.detail.run_id === id ? S.detail : null);
  if (!run) return;
  try {
    await api(`api/runs/${encodeURIComponent(id)}/${run.paused ? "resume" : "pause"}`, { method: "POST" });
    run.paused = !run.paused;
    if (S.detail && S.detail.run_id === id) S.detail.paused = run.paused;
    renderGrid(); if (S.current) renderHeader();
  } catch (err) { toast(`Could not ${run.paused ? "resume" : "pause"}: ${err.message}`); }
}

// The + menu in a session view: one entry per launcher tile.
function renderAppButtons(apps) {
  S.apps = apps;
  const key = JSON.stringify(apps);
  if (key === renderAppButtons.key) return;
  renderAppButtons.key = key;
  $("new-menu-apps").replaceChildren(...apps.map((app) => {
    const b = el("button", "btn", `+ ${app.name}`);
    b.type = "button";
    b.addEventListener("click", () => { $("new-menu").hidden = true; launch(app); });
    return b;
  }));
}

// Launcher: one tile per catalog entry (Chrome identities and desktop apps).
// A browser tile opens a new window; an app tile shows its running session or starts it.
function renderLauncher() {
  const tiles = (S.apps || []).map((app) => {
    const browser = app.kind === "browser";
    const running = !browser && S.runs.find((r) => isApp(r) && r.app === app.app);
    const busy = S.launching === app.app;
    const tile = el("button", "tile" + (running ? " running" : ""));
    tile.type = "button";
    tile.title = running ? `Show ${app.name}` : `Open ${app.name}`;
    const icon = app.icon ? el("img", "tile-icon") : el("span", "tile-icon letter", app.name.slice(0, 1));
    if (app.icon) { icon.src = app.icon; icon.alt = ""; }
    tile.append(icon, el("span", "tile-name", app.name),
      el("span", "tile-state", busy ? "Opening…" : running ? (running.paused ? "Running · paused" : "Running")
        : browser ? "New window" : "Tap to open"));
    tile.addEventListener("click", () => launch(app));
    return tile;
  });
  $("launcher").replaceChildren(...tiles);
  if (!tiles.length) $("launcher").append(el("p", "muted empty", "No desktop apps are configured."));
}

function launch(app) {
  if (app.kind === "browser") return newRun(app.identity, app);
  const running = S.runs.find((r) => isApp(r) && r.app === app.app);
  if (running) openRun(running.run_id); else newApp(app);
}

async function newApp(app) {
  if (S.launching) return;
  S.launching = app.app;
  renderLauncher();
  try {
    const r = await api(`api/runs/new?app=${encodeURIComponent(app.app)}`, { method: "POST" });
    await loadRuns();
    if (r.run_id) openRun(r.run_id);
  } catch (err) { toast(`Could not open ${app.name}: ${err.message}`); }
  finally { S.launching = null; renderLauncher(); }
}

async function newRun(identity, tile) {
  if (S.launching) return;
  S.launching = tile ? tile.app : identity;
  renderLauncher();
  try {
    const r = await api(`api/runs/new?identity=${identity}`, { method: "POST" });
    await loadRuns();
    openRun(r.run_id);
  } catch (err) { toast(`Could not open a ${identity} window: ${err.message}`); }
  finally { S.launching = null; renderLauncher(); }
}

// ---------------------------------------------------------------- routing
function route() {
  const m = /^#run=([A-Za-z0-9_-]{1,64})$/.exec(location.hash);
  if (location.hash !== "#desktop") hideDesktop();
  if (m) showRun(m[1]); else if (location.hash === "#desktop") showDesktop(); else showGrid();
}
// Desktop mode embeds Selkies from the site root. nginx serves Selkies there
// to frames and sends top-level visits here, so this page is the one entry.
// Leaving the mode unloads the frame, which ends the Selkies stream.
const DESKTOP_URL = "desktop/";
function showDesktop() {
  S.current = null; S.detail = null;
  closeStream();
  setKeyboard(false);
  $("grid-view").hidden = true; $("agent-view").hidden = true; $("desktop-view").hidden = false;
  const frame = $("desktop-frame");
  if (!frame.getAttribute("src")) frame.src = DESKTOP_URL;
  frame.focus();
}
function hideDesktop() {
  if ($("desktop-view").hidden) return;
  $("desktop-view").hidden = true;
  $("desktop-frame").removeAttribute("src");
}
function openRun(id) { location.hash = `run=${id}`; }
function showGrid() {
  S.current = null; S.detail = null;
  closeStream();
  $("agent-view").hidden = true; $("grid-view").hidden = false;
  setKeyboard(false);
  loadRuns();
}
function showRun(id) {
  if (S.current === id && S.ws) return;
  closeStream();
  S.current = id; S.target = null; S.meta = null; S.detail = S.runs.find((r) => r.run_id === id) || null;
  S.view = { z: 1, tx: 0, ty: 0 }; S.layoutMode = null;
  S.manualAt = 0; S.knownTabs = null; S.lastStateAt = 0; S.readOnly = false;
  notice("");
  $("agent-view").classList.remove("url-open");
  $("grid-view").hidden = true; $("agent-view").hidden = false;
  $("screen").removeAttribute("src");
  stageMsg("Connecting…");
  renderHeader();
  openStream();
}
function step(dir) {
  if (!S.runs.length) return;
  const i = S.runs.findIndex((r) => r.run_id === S.current);
  const next = S.runs[(i + dir + S.runs.length) % S.runs.length];
  if (next && next.run_id !== S.current) location.replace(`#run=${next.run_id}`);
}

// ---------------------------------------------------------------- agent view
// One tab per open session (all identities); x closes it.
function renderSessions() {
  const nav = $("sessions");
  const runs = [...S.runs.filter(isApp), ...S.runs.filter((r) => !isApp(r))];
  if (S.current && !runs.some((r) => r.run_id === S.current) && S.detail) runs.push(S.detail);
  nav.replaceChildren(...runs.map((run) => {
    const chip = el("div", `session ${run.identity}` + (run.run_id === S.current ? " active" : "") + (run.paused ? " paused" : ""));
    const open = el("button", "session-open");
    open.type = "button";
    open.title = [runTitle(run), run.identity, ownerLine(run)].filter(Boolean).join(" · ");
    open.append(el("span", `dot ${run.identity}`), el("span", "session-label", runTitle(run)));
    open.addEventListener("click", () => { if (run.run_id !== S.current) location.replace(`#run=${run.run_id}`); });
    const x = el("button", "session-x", "×");
    x.type = "button";
    x.setAttribute("aria-label", `Close ${runTitle(run)}`);
    x.addEventListener("click", (e) => { e.stopPropagation(); closeRun(run.run_id); });
    chip.append(open, x);
    return chip;
  }));
  // Scroll only when the active session changes, so a manual scroll of the strip sticks across refreshes.
  const active = nav.querySelector(".session.active");
  if (active && S.current !== renderSessions.lastId) active.scrollIntoView({ block: "nearest", inline: "nearest" });
  renderSessions.lastId = S.current;
}

// x closes at once: the tab disappears now and the desktop finishes in the
// background (an app is asked to quit, then stopped after a few seconds).
async function closeRun(id) {
  const run = S.runs.find((r) => r.run_id === id) || (S.detail && S.detail.run_id === id ? S.detail : null);
  if (!run) return;
  S.closing.add(id);
  const i = S.runs.findIndex((r) => r.run_id === id);
  S.runs = S.runs.filter((r) => r.run_id !== id);
  if (S.current === id) {
    const next = S.runs[Math.min(Math.max(i, 0), S.runs.length - 1)];
    if (next) location.replace(`#run=${next.run_id}`); else location.hash = "";
  }
  renderGrid(); if (S.current) renderHeader();
  try {
    await api(`api/runs/${encodeURIComponent(id)}/close${isApp(run) ? "?force=1" : ""}`, { method: "POST" });
  } catch (err) { toast(`Could not close ${runTitle(run)}: ${err.message}`); }
  finally { S.closing.delete(id); loadRuns(); }
}

function renderHeader() {
  renderSessions();
  const run = S.detail || S.runs.find((r) => r.run_id === S.current);
  const line = $("run-state");
  if (!run) { line.textContent = "Window closed"; return; }
  $("agent-view").classList.toggle("app-mode", isApp(run));
  const thread = threadNode(run.owner);
  line.replaceChildren(el("span", null, [isApp(run) ? run.app_name || "app" : run.identity, ownerLine(run)].filter(Boolean).join(" · ")));
  if (thread) line.append(" · ", thread);
  line.append(` · ${stateLine(run)}`);
  const btn = $("pause-btn");
  btn.textContent = run.paused ? "Resume agent" : "Pause";
  btn.classList.toggle("paused", run.paused);
  btn.hidden = isHuman(run);
  const tabs = $("tabs");
  const buttons = run.tabs.map((tab) => {
    const b = el("button", "btn tab" + (tab.target_id === S.target ? " active" : ""), tabLabel(tab));
    b.type = "button";
    b.title = tab.url || tab.origin || "";
    b.addEventListener("click", () => { S.manualAt = Date.now(); send({ t: "select-tab", target: tab.target_id }); });
    return b;
  });
  tabs.replaceChildren(...buttons);
  const tab = run.tabs.find((t) => t.target_id === S.target);
  S.readOnly = !!(tab && tab.is_anchor);
  for (const id of ["nav-back", "nav-forward", "nav-reload", "nav-back-compact", "url", "url-toggle", "kbd-btn"]) $(id).disabled = S.readOnly;
  for (const b of document.querySelectorAll("#urlbar button[type=submit]")) b.disabled = S.readOnly;
  if (S.readOnly) { setKeyboard(false); notice("Home tab — read-only. Pick another tab above.", "info", 0); }
  else if (S.noticeKind === "anchor") notice("");
  if (S.readOnly) S.noticeKind = "anchor";
  const url = $("url");
  if (tab && document.activeElement !== url) url.value = tab.is_anchor ? "" : (tab.url || tab.origin || "");
}

function notice(text, kind, ms) {
  const n = $("notice");
  clearTimeout(notice.t);
  n.textContent = text || ""; n.hidden = !text;
  n.className = `notice ${kind || ""}`;
  S.noticeKind = null;
  if (text && ms) notice.t = setTimeout(() => { n.hidden = true; }, ms);
}
function stageMsg(text) {
  const m = $("stage-msg");
  m.textContent = text || ""; m.hidden = !text;
}

function wsUrl() {
  const stage = $("stage");
  const dpr = window.devicePixelRatio || 1;
  const w = Math.min(1920, Math.round(stage.clientWidth * dpr * 1.5));
  const h = Math.min(1920, Math.round(stage.clientHeight * dpr * 1.5));
  const u = new URL(`api/runs/${encodeURIComponent(S.current)}/stream`, location.href);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.searchParams.set("w", w); u.searchParams.set("h", h);
  if (S.target) u.searchParams.set("target", S.target);
  return u.toString();
}

function openStream() {
  if (!S.current) return;
  const id = S.current;
  let ws;
  try { ws = new WebSocket(wsUrl(), "ghostship-viewer"); } catch (_) { return retryStream(); }
  S.ws = ws;
  $("conn").textContent = "connecting";
  ws.onopen = () => { S.wsBackoff = 500; $("conn").textContent = "live"; };
  ws.onmessage = (ev) => { if (S.ws === ws) onMessage(JSON.parse(ev.data)); };
  ws.onclose = () => {
    if (S.ws !== ws) return;
    S.ws = null;
    $("conn").textContent = "offline";
    if (S.current === id) { stageMsg(S.browsers[(S.detail || {}).identity] === "stopped" ? "Browser stopped" : "Reconnecting…"); retryStream(); }
  };
}
function retryStream() {
  clearTimeout(S.wsTimer);
  S.wsTimer = setTimeout(() => { loadRuns(); openStream(); }, S.wsBackoff);
  S.wsBackoff = Math.min(S.wsBackoff * 2, 8000);
}
function closeStream() {
  clearTimeout(S.wsTimer);
  if (S.ws) { const ws = S.ws; S.ws = null; ws.close(); }
}
const INPUT_TYPES = new Set(["tap", "pointer", "wheel", "key", "text", "navigate", "reload", "back", "forward", "dialog"]);
function send(msg) {
  if (S.readOnly && INPUT_TYPES.has(msg.t)) return false; // the home (anchor) tab is read-only
  if (S.ws && S.ws.readyState === 1) { S.ws.send(JSON.stringify(msg)); return true; }
  return false;
}

function onMessage(msg) {
  switch (msg.t) {
    case "frame": {
      if (msg.target !== S.target) return;
      const m = msg.meta || {};
      S.meta = m;
      const img = $("screen");
      img.src = `data:image/jpeg;base64,${msg.data}`;
      if (m.deviceWidth !== S.frameW || m.deviceHeight !== S.frameH) { S.frameW = m.deviceWidth; S.frameH = m.deviceHeight; layout(); }
      stageMsg("");
      break;
    }
    case "run":
      autoFollow(msg.run);
      S.detail = msg.run;
      renderHeader();
      break;
    case "tab":
      S.target = msg.target; S.meta = null;
      renderHeader();
      break;
    case "dialog": showDialog(msg); break;
    case "dialog-closed": if (S.dialog && S.dialog.target === msg.target) closeDialog(); break;
    case "status":
    case "gone":
      stageMsg(msg.browser === "stopped" ? "Browser stopped" : "This window was closed");
      break;
    case "busy":
      notice(msg.stuck ? "Agent is still busy — try again" : "Agent is finishing its current action…", "", msg.stuck ? 6000 : 0);
      S.noticeKind = "busy";
      break;
    case "ready":
      notice("Agent paused — you have control", "info", 2500);
      S.noticeKind = "ready";
      break;
    case "error": toast(msg.error); break;
    default: break;
  }
}

// ---------------------------------------------------------------- geometry
// Fit shows the whole page; Fill scales the page to the stage height (pan
// sideways with two fingers). Portrait defaults to Fill, landscape to Fit.
function orientation() { return window.matchMedia("(orientation: portrait)").matches ? "portrait" : "landscape"; }
function currentMode() {
  const o = orientation();
  return S.modePref[o] || (o === "portrait" ? "fill" : "fit");
}
function layout() {
  const stage = $("stage");
  const sw = stage.clientWidth, sh = stage.clientHeight;
  const mode = currentMode();
  $("mode-btn").textContent = mode === "fill" ? "Fit page" : "Fill height";
  if (!S.frameW || !S.frameH || !sw || !sh) return;
  const scale = mode === "fill" ? sh / S.frameH : Math.min(sw / S.frameW, sh / S.frameH);
  const w = S.frameW * scale, h = S.frameH * scale;
  S.img = { x: w > sw ? 0 : (sw - w) / 2, y: h > sh ? 0 : (sh - h) / 2, w, h };
  const img = $("screen");
  img.style.left = `${S.img.x}px`; img.style.top = `${S.img.y}px`;
  img.style.width = `${w}px`; img.style.height = `${h}px`;
  if (mode !== S.layoutMode) { S.layoutMode = mode; resetView(); } else applyView();
}
function resetView() {
  const stage = $("stage");
  // Start centred: most sites centre their content in the wide viewport.
  S.view = { z: 1, tx: (stage.clientWidth - S.img.w) / 2 - S.img.x, ty: 0 };
  applyView();
}
// Keep the content covering the stage where it can; centre it where it can't.
function clampAxis(t, start, len, z, size) {
  const c = len * z;
  if (c <= size) return (size - c) / 2 - start * z;
  return Math.min(-start * z, Math.max(size - (start + len) * z, t));
}
function clampView() {
  const stage = $("stage");
  const v = S.view;
  v.z = Math.min(Math.max(v.z, 1), 6);
  if (!S.img.w) return;
  v.tx = clampAxis(v.tx, S.img.x, S.img.w, v.z, stage.clientWidth);
  v.ty = clampAxis(v.ty, S.img.y, S.img.h, v.z, stage.clientHeight);
}
function applyView() {
  clampView();
  const v = S.view;
  $("layer").style.transform = `translate(${v.tx}px, ${v.ty}px) scale(${v.z})`;
  $("zoom-reset").hidden = v.z <= 1.01;
}
function toggleMode() {
  const o = orientation();
  S.modePref[o] = currentMode() === "fill" ? "fit" : "fill";
  layout();
}

// Follow the tab the agent is driving (newest activity, or a tab/popup it just
// opened) unless the operator picked a tab in the last 30 s.
function autoFollow(run) {
  if (!run || run.run_id !== S.current) return;
  const ids = run.tabs.map((t) => t.target_id);
  const st = run.state;
  let pick = null;
  if (S.knownTabs) {
    const fresh = run.tabs.filter((t) => !t.is_anchor && !S.knownTabs.has(t.target_id));
    if (fresh.length) pick = fresh[fresh.length - 1].target_id;
    if (st && (st.at || 0) > S.lastStateAt && ids.includes(st.target_id)) pick = st.target_id;
  }
  S.knownTabs = new Set(ids);
  if (st && st.at) S.lastStateAt = Math.max(S.lastStateAt, st.at);
  if (pick && pick !== S.target && Date.now() - S.manualAt > 30000) send({ t: "select-tab", target: pick });
}
// Client point -> frame coordinates normalized to 0..1 (inverse of the view transform).
function toFrame(clientX, clientY) {
  const r = $("stage").getBoundingClientRect();
  const lx = (clientX - r.left - S.view.tx) / S.view.z;
  const ly = (clientY - r.top - S.view.ty) / S.view.z;
  return { x: (lx - S.img.x) / S.img.w, y: (ly - S.img.y) / S.img.h };
}
function inside(p) { return p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1; }
// Screen pixels per page CSS pixel, for drag-to-scroll deltas.
function cssScale() {
  if (!S.meta || !S.meta.deviceWidth) return 1;
  return (S.img.w * S.view.z * (S.meta.pageScaleFactor || 1)) / S.meta.deviceWidth;
}
function mods(e) { return (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0); }

// ---------------------------------------------------------------- pointer input
const touches = new Map();
let gesture = null;
let wheelAcc = null;
let moveQueued = null;
const BUTTONS = ["left", "middle", "right"];

function flushWheel() {
  if (!wheelAcc) return;
  const w = wheelAcc; wheelAcc = null;
  if (Math.abs(w.dx) + Math.abs(w.dy) > 0.5) send({ t: "wheel", x: w.x, y: w.y, dx: w.dx, dy: w.dy });
}
function queueWheel(p, dx, dy) {
  if (!wheelAcc) { wheelAcc = { x: p.x, y: p.y, dx: 0, dy: 0 }; requestAnimationFrame(flushWheel); }
  wheelAcc.dx += dx; wheelAcc.dy += dy;
}

function setupStage() {
  const stage = $("stage");
  stage.addEventListener("contextmenu", (e) => e.preventDefault());
  stage.addEventListener("pointerdown", (e) => {
    if (!S.meta) return;
    stage.setPointerCapture(e.pointerId);
    if (e.pointerType === "mouse") {
      stage.focus({ preventScroll: true });
      const p = toFrame(e.clientX, e.clientY);
      if (!inside(p)) return;
      e.preventDefault();
      send({ t: "pointer", kind: "down", x: p.x, y: p.y, button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1, mods: mods(e) });
      return;
    }
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (touches.size === 1) {
      gesture = { kind: "pending", start: { x: e.clientX, y: e.clientY }, last: { x: e.clientX, y: e.clientY }, t: performance.now() };
    } else if (touches.size === 2) {
      const [a, b] = [...touches.values()];
      const r = stage.getBoundingClientRect();
      gesture = { kind: "pinch", d0: Math.hypot(a.x - b.x, a.y - b.y) || 1,
        c0: { x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top }, v0: { ...S.view } };
    }
  });
  stage.addEventListener("pointermove", (e) => {
    if (e.pointerType === "mouse") {
      if (!S.meta) return;
      const p = toFrame(e.clientX, e.clientY);
      if (!inside(p) && !e.buttons) return;
      if (!moveQueued) requestAnimationFrame(() => { const m = moveQueued; moveQueued = null; if (m) send(m); });
      moveQueued = { t: "pointer", kind: "move", x: Math.min(Math.max(p.x, 0), 1), y: Math.min(Math.max(p.y, 0), 1), button: e.buttons & 1 ? "left" : (e.buttons & 2 ? "right" : "none"), buttons: e.buttons, mods: mods(e) };
      return;
    }
    if (!touches.has(e.pointerId) || !gesture) return;
    touches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (gesture.kind === "pinch" && touches.size >= 2) {
      const [a, b] = [...touches.values()];
      const r = stage.getBoundingClientRect();
      const c = { x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top };
      const v0 = gesture.v0;
      const z = Math.min(Math.max(v0.z * Math.hypot(a.x - b.x, a.y - b.y) / gesture.d0, 1), 6);
      const px = (gesture.c0.x - v0.tx) / v0.z, py = (gesture.c0.y - v0.ty) / v0.z;
      S.view = { z, tx: c.x - px * z, ty: c.y - py * z };
      applyView();
      return;
    }
    const dx = e.clientX - gesture.last.x, dy = e.clientY - gesture.last.y;
    if (gesture.kind === "pending" && Math.hypot(e.clientX - gesture.start.x, e.clientY - gesture.start.y) > 10) {
      gesture.kind = S.view.z > 1.01 ? "pan" : "scroll";
    }
    if (gesture.kind === "pan") {
      S.view.tx += dx; S.view.ty += dy; applyView();
    } else if (gesture.kind === "scroll") {
      const p = toFrame(gesture.start.x, gesture.start.y);
      const k = cssScale();
      queueWheel({ x: Math.min(Math.max(p.x, 0), 1), y: Math.min(Math.max(p.y, 0), 1) }, -dx / k, -dy / k);
    }
    gesture.last = { x: e.clientX, y: e.clientY };
  });
  const end = (e) => {
    if (e.pointerType === "mouse") {
      if (!S.meta || e.type === "pointercancel") return;
      const p = toFrame(e.clientX, e.clientY);
      send({ t: "pointer", kind: "up", x: Math.min(Math.max(p.x, 0), 1), y: Math.min(Math.max(p.y, 0), 1), button: BUTTONS[e.button] || "left", buttons: e.buttons, clickCount: e.detail || 1, mods: mods(e) });
      return;
    }
    if (!touches.has(e.pointerId)) return;
    touches.delete(e.pointerId);
    if (gesture && gesture.kind === "pending" && e.type === "pointerup" && performance.now() - gesture.t < 800) {
      const p = toFrame(gesture.start.x, gesture.start.y);
      if (inside(p)) send({ t: "tap", x: p.x, y: p.y });
    }
    if (touches.size === 0) gesture = null;
    else if (gesture && gesture.kind === "pinch") gesture = { kind: "done" };
  };
  stage.addEventListener("pointerup", end);
  stage.addEventListener("pointercancel", end);
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (!S.meta) return;
    if (e.ctrlKey) { // trackpad pinch zooms the view only
      const r = stage.getBoundingClientRect();
      const c = { x: e.clientX - r.left, y: e.clientY - r.top };
      const v0 = S.view;
      const z = Math.min(Math.max(v0.z * Math.exp(-e.deltaY / 200), 1), 6);
      const px = (c.x - v0.tx) / v0.z, py = (c.y - v0.ty) / v0.z;
      S.view = { z, tx: c.x - px * z, ty: c.y - py * z };
      applyView();
      return;
    }
    const unit = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? S.frameH : 1;
    const p = toFrame(e.clientX, e.clientY);
    if (!inside(p)) return;
    queueWheel(p, e.deltaX * unit, e.deltaY * unit);
  }, { passive: false });

  // Physical keyboard (desktop): forward while the stage has focus.
  stage.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === "v" || e.key === "V")) return; // let the paste event carry text
    e.preventDefault();
    send({ t: "key", kind: "down", key: e.key, code: e.code, keyCode: e.keyCode, mods: mods(e) });
  });
  stage.addEventListener("keyup", (e) => {
    if (e.isComposing) return;
    if ((e.ctrlKey || e.metaKey) && (e.key === "v" || e.key === "V")) return;
    e.preventDefault();
    send({ t: "key", kind: "up", key: e.key, code: e.code, keyCode: e.keyCode, mods: mods(e) });
  });
  stage.addEventListener("paste", (e) => {
    const text = e.clipboardData && e.clipboardData.getData("text/plain");
    if (text) { e.preventDefault(); send({ t: "text", text: text.slice(0, 2000) }); }
  });

  // Swipe on the header switches agents.
  const head = $("agent-head");
  let sx = null, sy = null;
  head.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse") { sx = e.clientX; sy = e.clientY; } });
  head.addEventListener("pointerup", (e) => {
    if (sx == null) return;
    const dx = e.clientX - sx, dy = e.clientY - sy;
    sx = null;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  });

  new ResizeObserver(() => {
    layout();
    if (S.ws && S.ws.readyState === 1) {
      const dpr = window.devicePixelRatio || 1;
      send({ t: "viewport", w: Math.min(1920, Math.round(stage.clientWidth * dpr * 1.5)), h: Math.min(1920, Math.round(stage.clientHeight * dpr * 1.5)) });
    }
  }).observe(stage);
}

// ---------------------------------------------------------------- on-screen keyboard
const SENTINEL = "​​";
let composing = false;
function setKeyboard(on) {
  $("kbd-bar").hidden = !on;
  $("kbd-btn").classList.toggle("primary", on);
  const t = $("kbd-input");
  if (on) { resetKbd(); t.focus(); } else t.blur();
}
function resetKbd() {
  const t = $("kbd-input");
  t.value = SENTINEL;
  t.setSelectionRange(SENTINEL.length, SENTINEL.length);
}
function sendKey(key) { send({ t: "key", kind: "press", key }); }
function sendText(text) { if (text) send({ t: "text", text: text.slice(0, 2000) }); }
function setupKeyboard() {
  const t = $("kbd-input");
  $("kbd-btn").addEventListener("click", () => setKeyboard($("kbd-bar").hidden));
  for (const b of document.querySelectorAll("#kbd-bar .key")) {
    b.addEventListener("pointerdown", (e) => e.preventDefault()); // keep the soft keyboard open
    b.addEventListener("click", () => sendKey(b.dataset.key));
  }
  t.addEventListener("compositionstart", () => { composing = true; });
  t.addEventListener("compositionend", (e) => {
    composing = false;
    sendText(e.data);
    setTimeout(resetKbd, 0);
  });
  t.addEventListener("beforeinput", (e) => {
    if (composing || e.isComposing || !e.cancelable) return;
    const type = e.inputType;
    if (type === "insertText" || type === "insertReplacementText") { e.preventDefault(); sendText(e.data || (e.dataTransfer && e.dataTransfer.getData("text/plain"))); }
    else if (type === "insertLineBreak" || type === "insertParagraph") { e.preventDefault(); sendKey("Enter"); }
    else if (type === "deleteContentBackward" || type === "deleteWordBackward") { e.preventDefault(); sendKey("Backspace"); }
    else if (type === "deleteContentForward") { e.preventDefault(); sendKey("Delete"); }
    else if (type === "insertFromPaste" || type === "insertFromDrop") {
      e.preventDefault(); sendText(e.dataTransfer ? e.dataTransfer.getData("text/plain") : e.data);
    }
  });
  // Fallback when beforeinput was not cancelable: diff against the sentinel.
  t.addEventListener("input", () => {
    if (composing) return;
    const v = t.value;
    if (v === SENTINEL) return;
    if (v.length < SENTINEL.length && SENTINEL.startsWith(v)) sendKey("Backspace");
    else {
      const added = v.replace(/​/g, "");
      if (added.includes("\n")) { sendText(added.replace(/\n/g, "")); sendKey("Enter"); } else sendText(added);
    }
    resetKbd();
  });
  t.addEventListener("keydown", (e) => {
    if (composing || e.isComposing) return;
    if (["Escape", "Tab", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); sendKey(e.key); }
  });
}

// ---------------------------------------------------------------- page dialogs
function showDialog(msg) {
  S.dialog = msg;
  const d = $("page-dialog");
  $("dialog-origin").textContent = `${msg.origin || "The page"} says (${msg.kind || "alert"}):`;
  $("dialog-message").textContent = msg.message || "";
  const input = $("dialog-input");
  input.hidden = msg.kind !== "prompt";
  input.value = msg.default || "";
  $("dialog-cancel").hidden = msg.kind === "alert";
  if (!d.open) d.showModal();
}
function closeDialog() { S.dialog = null; const d = $("page-dialog"); if (d.open) d.close(); }
function answerDialog(accept) {
  if (!S.dialog) return closeDialog();
  const msg = { t: "dialog", accept };
  if (S.dialog.kind === "prompt" && accept) msg.text = $("dialog-input").value;
  send(msg);
  closeDialog();
}

// ---------------------------------------------------------------- wiring
function init() {
  $("to-grid").addEventListener("click", () => { location.hash = ""; });
  $("new-session").addEventListener("click", () => {
    const menu = $("new-menu");
    menu.hidden = !menu.hidden;
    $("new-session").setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("click", (e) => {
    if (!$("new-menu").hidden && !e.target.closest("#new-menu, #new-session")) $("new-menu").hidden = true;
  });
  $("pause-btn").addEventListener("click", () => S.current && togglePause(S.current));
  $("nav-back").addEventListener("click", () => send({ t: "back" }));
  $("nav-forward").addEventListener("click", () => send({ t: "forward" }));
  $("nav-reload").addEventListener("click", () => send({ t: "reload" }));
  $("urlbar").addEventListener("submit", (e) => {
    e.preventDefault();
    const url = $("url").value.trim();
    if (url) { send({ t: "navigate", url }); $("url").blur(); }
  });
  $("zoom-reset").addEventListener("click", resetView);
  $("mode-btn").addEventListener("click", toggleMode);
  $("nav-back-compact").addEventListener("click", () => send({ t: "back" }));
  $("url-toggle").addEventListener("click", () => {
    const view = $("agent-view");
    view.classList.toggle("url-open");
    if (view.classList.contains("url-open")) $("url").focus();
  });
  $("url").addEventListener("blur", () => setTimeout(() => {
    if (!$("urlbar").contains(document.activeElement)) $("agent-view").classList.remove("url-open");
  }, 200));
  $("dialog-ok").addEventListener("click", () => answerDialog(true));
  $("dialog-cancel").addEventListener("click", () => answerDialog(false));
  $("page-dialog").addEventListener("cancel", (e) => { e.preventDefault(); answerDialog(false); });
  setupStage();
  setupKeyboard();
  window.addEventListener("hashchange", route);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) loadRuns(); });
  setInterval(() => { if (!document.hidden) loadRuns(); }, 2000);
  route();
}
init();
