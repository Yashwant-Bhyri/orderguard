"use strict";
/* theater.js: the Swarm Theater. A guided replay of one recorded arena run, read from /api/theater/timeline.
   Nothing is generated here: dots, counters, gauges and the feed are all drawn from the timeline (docs/APP.md, "Swarm Theater").
   Same rules as the dashboard: no HTML strings, every string through textContent, sizes through the CSSOM, no inline script. */
(function () {
const { h } = OG;
const $ = (id) => document.getElementById(id);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
};
const reduce = OG.reduceMotion() || /[?&]motion=reduce\b/.test(location.search);     // ?motion=reduce forces the static step-through
let D = null;                 // the timeline
let C = null;                 // decoded arrays, clusters, beat clock
const NOW = () => (window.performance && performance.now ? performance.now() : Date.now());

/* ---------- 1. formats and facts ---------- */
const FMT = {
  usd: (v) => OG.usd(v, false),
  usdm: (v) => (Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : OG.usd(v, false)),
  pct: (v) => v.toFixed(1) + "%",
  int: (v) => Math.round(v).toLocaleString("en-US"),
  num: (v) => String(v),
  us: (v) => v.toFixed(2) + " µs",
  text: (v) => String(v),
};
const fact = (id) => { const f = D.facts[id]; return f ? FMT[f.fmt](f.value) : id; };
const fill = (tpl) => tpl.replace(/\{(\w+)\}/g, (m, id) => (D.facts[id] ? fact(id) : m));
const money = (cents) => OG.usd(cents / 100, false);
const srcPath = (id) => (D.sources.find((s) => s.id === id) || { path: id }).path;
function srcLink(id, label) {
  const a = h("a", { class: "th-src", href: "/api/theater/source?id=" + id, target: "_blank", rel: "noopener" }, label || srcPath(id).split("/").pop());
  if (OG.token) a.addEventListener("click", async (e) => {      // with an access token set a plain link cannot send it: fetch, then open the text
    e.preventDefault();
    try {
      const r = await fetch(a.getAttribute("href"), { headers: { Authorization: "Bearer " + OG.token } });
      window.open(URL.createObjectURL(await r.blob()), "_blank", "noopener");
    } catch (x) { status("The file could not be opened."); }
  });
  return a;
}
const src = (id) => srcLink(id);
function status(t) { $("th-status").textContent = t; }

/* ---------- 2. decode the timeline ---------- */
function decode() {
  const steps = D.run.steps, bin = atob(D.events), n = bin.length >> 1;
  const agent = new Uint16Array(n), state = new Uint8Array(n);
  for (let i = 0; i < n; i++) { const v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8); agent[i] = v & 1023; state[i] = v >> 10; }
  const start = new Int32Array(steps + 1);
  for (let s = 0; s < steps; s++) start[s + 1] = start[s] + D.per_step[s];
  const cum = {};
  for (const k of Object.keys(D.series)) { const a = new Float64Array(steps + 1); for (let s = 0; s < steps; s++) a[s + 1] = a[s] + D.series[k][s]; cum[k] = a; }
  const day = {};                        // budget committed through each step, within its own day, in cents
  for (const e of D.envelopes) {
    const a = new Float64Array(steps); let run = 0;
    for (let s = 0; s < steps; s++) { if (s % D.run.steps_per_day === 0) run = 0; run += D.reserve_cents[e.name][s]; a[s] = run; }
    day[e.name] = a;
  }
  const sleeve = D.swarm.sleeve, fam = D.swarm.family;
  const clusters = D.envelopes.map((e, i) => ({ env: e, i, agents: [] }));
  clusters.push({ env: null, i: 3, agents: [] });
  for (let a = 0; a < sleeve.length; a++) clusters[Number(sleeve[a])].agents.push(a);
  const famOf = new Int8Array(sleeve.length).fill(-1);
  for (let a = 0; a < fam.length; a++) if (fam[a] !== "-") famOf[a] = fam.charCodeAt(a) - 97;
  const where = new Array(sleeve.length);
  clusters.forEach((c) => c.agents.forEach((a, k) => { where[a] = [c, k]; }));
  // the beat clock: each beat is a run of [from step, to step, seconds] segments, or a dwell
  let t = 0;
  const beats = D.beats.map((b) => {
    const dur = b.segments.length ? b.segments.reduce((s, g) => s + g[2], 0) : b.dwell;
    const o = Object.assign({}, b, { t0: t, dur });
    t += dur; return o;
  });
  const windowsEnd = beats[2].segments[beats[2].segments.length - 1][1];
  return { steps, n, agent, state, start, cum, day, clusters, famOf, where, beats, total: t, windowsEnd };
}

/* ---------- 3. the swarm on canvas ---------- */
const NEUTRAL = 0, VIS = {
  guard: { 0: ["c", "n", 0], 1: ["s", "hold", 1], 2: ["d", "refuse", 1], 3: ["d", "stop", 1], 4: ["c", "leak", 1], 5: ["s", "hold", 1], 6: ["d", "refuse", 1], 7: ["r", "dup", 1], 8: ["s", "hold", 1] },
  calm: { 0: ["c", "n", 0], 1: ["s", "hold", 1], 2: ["d", "refuse", 1], 3: ["c", "n", 0], 4: ["c", "n", 0], 5: ["s", "hold", 1], 6: ["d", "refuse", 1], 7: ["c", "n", 0], 8: ["c", "n", 0] },
  naive: { 0: ["c", "n", 0], 1: ["c", "n", 0], 2: ["c", "n", 0], 3: ["c", "attack", 1], 4: ["c", "attack", 1], 5: ["c", "attack", 1], 6: ["c", "attack", 1], 7: ["c", "attack", 1], 8: ["c", "n", 0] },
};
let pal = {}, dot = null, view = "calm", reveal = false, ringFam = -1, animUntil = 0, dirty = true;
function readPalette() {
  const cs = getComputedStyle(document.documentElement), v = (n) => cs.getPropertyValue(n).trim();
  pal = { base: v("--line-strong"), n: v("--allow"), hold: v("--hold"), refuse: v("--refuse"), stop: v("--quarantine"), leak: v("--refuse"), attack: v("--refuse"), dup: v("--text-3"),
          ring: v("--text"), focus: v("--accent"), bg: v("--surface") };
  dirty = true;
}
function resetDots() { dot = { last: new Uint8Array(1000).fill(255), at: new Float64Array(1000), applied: -1, idx: 0, fam: new Int32Array(D.families.length) }; dirty = true; }
function applyTo(step, instant) {
  if (step < dot.applied) resetDots();
  const stop = C.start[Math.min(step, C.steps - 1) + 1], t = instant ? -1e9 : NOW();
  for (let i = dot.idx; i < stop; i++) {
    const a = C.agent[i], s = C.state[i];
    dot.last[a] = s; dot.at[a] = t;
    if (s >= 3 && s <= 7 && C.famOf[a] >= 0) dot.fam[C.famOf[a]]++;
  }
  dot.idx = Math.max(dot.idx, stop); dot.applied = Math.max(dot.applied, step);
  if (!instant && !reduce) animUntil = t + 1600;
  dirty = true;
}
function layout(c) {
  const cv = c.canvas, w = cv.clientWidth, hgt = cv.clientHeight, r = window.devicePixelRatio || 1, n = c.agents.length || 1;
  if (!w || !hgt) return;
  cv.width = Math.round(w * r); cv.height = Math.round(hgt * r);
  c.ctx = cv.getContext("2d"); c.ctx.setTransform(r, 0, 0, r, 0, 0);
  const cols = Math.max(1, Math.ceil(Math.sqrt(n * w / hgt))), rows = Math.ceil(n / cols), cell = Math.min(w / cols, hgt / rows);
  c.cols = cols; c.cell = cell; c.ox = (w - cols * cell) / 2; c.oy = (hgt - rows * cell) / 2; c.w = w; c.h = hgt;
  dirty = true;
}
function shape(ctx, kind, x, y, r) {
  if (kind === "c" || kind === "r") { ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); return; }
  ctx.beginPath();
  if (kind === "s") ctx.rect(x - r * 0.9, y - r * 0.9, r * 1.8, r * 1.8);
  else { ctx.moveTo(x, y - r * 1.2); ctx.lineTo(x + r * 1.2, y); ctx.lineTo(x, y + r * 1.2); ctx.lineTo(x - r * 1.2, y); ctx.closePath(); }
}
function draw(now) {
  const vis = VIS[view === "human" || view === "proof" ? "guard" : view], fading = now < animUntil;
  for (const c of C.clusters) {
    if (!c.ctx) continue;
    const ctx = c.ctx; ctx.clearRect(0, 0, c.w, c.h);
    const r = Math.max(1.2, c.cell * 0.34);
    for (let k = 0; k < c.agents.length; k++) {
      const a = c.agents[k], s = dot.last[a], x = c.ox + (k % c.cols + 0.5) * c.cell, y = c.oy + (Math.floor(k / c.cols) + 0.5) * c.cell;
      let kind = "c", color = pal.base, rr = r, alpha = 1;
      if (s !== 255) {
        const v = vis[s], age = reduce ? 1e9 : now - dot.at[a];
        if (v[2]) { kind = v[0]; color = pal[v[1]]; alpha = age < 1400 ? 1 : 0.8; if (age < 500) rr = r * (1 + 0.9 * (1 - age / 500)); }
        else if (age < 700) { color = pal.n; rr = r * (1 + 0.8 * (1 - age / 700)); }
      }
      ctx.globalAlpha = alpha; ctx.fillStyle = color; shape(ctx, kind, x, y, rr); ctx.fill();
      if (s !== 255 && vis[s][1] === "leak") { ctx.strokeStyle = pal.ring; ctx.lineWidth = 1.5; ctx.stroke(); }
      if (kind === "r") { ctx.fillStyle = pal.bg; ctx.beginPath(); ctx.arc(x, y, rr * 0.5, 0, 6.2832); ctx.fill(); }
      ctx.globalAlpha = 1;
      const f = C.famOf[a];
      if (f >= 0 && reveal) { ctx.strokeStyle = f === ringFam ? pal.focus : pal.ring; ctx.lineWidth = f === ringFam ? 2.5 : 1; ctx.globalAlpha = f === ringFam ? 1 : 0.55; ctx.beginPath(); ctx.arc(x, y, r + 2.4, 0, 6.2832); ctx.stroke(); ctx.globalAlpha = 1; }
    }
  }
  dirty = fading;
}

/* ---------- 4. build the stage ---------- */
function buildStage() {
  const envs = $("th-envs");
  envs.replaceChildren(...D.envelopes.map((e, i) => {
    const c = C.clusters[i];
    c.canvas = h("canvas", { role: "img", "aria-label": e.name + " envelope: " + c.agents.length + " agents. The counters beside the beat carry the same information as text." });
    c.fill = h("i", {}); c.meter = h("div", { class: "th-meter", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0", "aria-label": e.name + " daily budget used" }, c.fill);
    c.used = h("b", {}, "$0"); c.flag = h("span", {}, "0%"); c.lab = h("span", {}, "Daily budget used");
    return h("div", { class: "th-env" },
      h("h3", {}, e.name, h("span", { class: "cap" }, c.agents.length + " agents")),
      h("p", { class: "why" }, e.purpose),
      c.canvas,
      h("div", { class: "th-gauge" }, h("div", { class: "row" }, c.lab, c.flag), c.meter, h("div", { class: "row" }, c.used, h("span", {}, "of " + OG.usd(e.daily, false)))),
      h("p", { class: "caps" }, "Per order " + OG.usd(e.per_order, false) + " · step-up " + OG.usd(e.step_up, false) + " · price band ±" + e.band_pct + "%"));
  }));
  const sc = C.clusters[3];
  sc.canvas = h("canvas", { role: "img", "aria-label": sc.agents.length + " agents sent no orders in this run" });
  $("th-silent").replaceChildren(sc.canvas, h("span", {}, D.swarm.silent + " agents sent no orders in this run."));
  const sw = (kind, color) => { const s = OG.svg("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }); const el = kind === "c" ? OG.svg("circle", { cx: 6, cy: 6, r: 4.5 }) : kind === "s" ? OG.svg("rect", { x: 2, y: 2, width: 8, height: 8 }) : OG.svg("path", { d: "M6 .5 11.5 6 6 11.5.5 6z" });
    el.setAttribute("fill", color); s.append(el); return s; };
  const items = [["c", "var(--text-3)", "allowed"], ["s", "var(--hold)", "held for a human"], ["d", "var(--refuse)", "refused"], ["d", "var(--quarantine)", "stopped by the order-risk layer"], ["c", "var(--refuse)", "bad order that reached the exchange (naive view)"]];
  $("th-legend").replaceChildren(...items.map(([k, col, t]) => h("li", {}, sw(k, col), t)), h("li", { id: "lg-ring" }, "A ring marks an agent the arena labelled an attacker. The guard never sees that label."));
}
function layoutAll() { C.clusters.forEach(layout); }

/* ---------- 5. counters, gauges, side panels ---------- */
const P = {};
function cumAt(k, step) { return C.cum[k][Math.min(step, C.steps - 1) + 1]; }
function tile(cls, v, k) { const v1 = h("span", { class: "v" }, v), t = h("div", { class: "th-stat " + (cls || "") }, v1, h("span", { class: "k" }, k)); t.val = v1; return t; }
function buildPanels() {
  // 1 Calm
  P.calm = { orders: tile("", "0", "orders so far"), allow: tile("allow", "0", "allowed"), hold: tile("hold", "0", "held for a human"), refuse: tile("refuse", "0", "refused") };
  $("p-calm").replaceChildren(h("h2", {}, "Honest agents, signed limits"),
    h("p", {}, "Five strategy styles propose orders off market data. Each order is checked at the trusted price against the envelope its agent draws on. Agents never choose, create or widen an envelope."),
    h("div", { class: "th-stats" }, P.calm.orders, P.calm.allow, P.calm.hold, P.calm.refuse),
    h("p", { class: "th-note" }, "Counted from the first rows of the recording, up to the first attack at step " + D.families.reduce((m, f) => (f.first_step === null ? m : Math.min(m, f.first_step)), 1e9) + ". Over the whole run: " + fact("legit_allowed") + " of " + fact("legit_orders") + " honest orders were allowed."),
    h("p", { class: "th-note" }, "Source: ", src("stream"), src("summary")));
  // 2 Naive
  P.naive = { usd: h("div", { class: "th-big bad" }, "$0"), n: h("span", {}, "0"), fam: h("ul", { class: "th-fam" }) };
  $("p-naive").replaceChildren(h("h2", {}, "What reaches the exchange with no guard"),
    P.naive.usd, h("p", {}, "of bad orders have reached the gate so far (", P.naive.n, " orders)."),
    h("p", { class: "th-note" }, "This is the dollars of bad orders the agents proposed, counted from the stream. It is not a modelled loss: the run has no no-guard counterfactual. The whole run: " + fact("attack_usd") + " in " + fact("attack_orders") + " orders, of which " + fact("dup_usd") + " were duplicate deliveries."),
    h("h3", {}, "Who is attacking, so far"), P.naive.fam, h("p", { class: "th-note" }, "Labels come from the arena, which knows which agents it made fail. ", src("stream")));
  // 3 Guard
  P.guard = { gate: tile("refuse", "$0", "stopped by the mandate gate"), risk: tile("quarantine", "$0", "stopped by the order-risk layer"), leak: tile("hold", "$0", "got through both"), honest: tile("hold", "0", "honest orders held or refused"),
              feed: h("ul", { class: "th-feed", "aria-label": "Recent refusals and holds, newest first" }), focus: h("div", { id: "th-focus" }) };
  $("p-guard").replaceChildren(h("h2", {}, "Every decision, with its reason"),
    h("div", { class: "th-stats" }, P.guard.gate, P.guard.risk, P.guard.leak, P.guard.honest),
    h("p", { class: "th-note" }, "The mandate gate is the recorded run. The order-risk layer is replayed over the gate's decisions: it can only tighten, and the budget a stopped order would have freed is not re-simulated. ", src("risk")),
    h("h3", {}, "Latest decisions"), P.guard.feed, h("h3", {}, "Follow one attack end to end"), P.guard.focus);
  // 4 Human
  P.human = { body: h("div") };
  $("p-human").replaceChildren(P.human.body);
  // 5 Proof
  P.proof = { body: h("div") };
  $("p-proof").replaceChildren(P.proof.body);
  buildQueue(); buildFocus(); buildProof();
}
function pillFor(s) {
  if (s === 1 || s === 5 || s === 8) return OG.pill("Held", "hold", "‖");
  if (s === 2 || s === 6) return OG.pill("Refused", "refuse", "✕");
  if (s === 3) return OG.pill("Stopped", "quarantine", "◆");
  if (s === 4) return OG.pill("Leaked", "bad", "!");
  return OG.pill("Allowed", "allow", "✓");
}
let feedPos = -1;
function renderFeed(step) {
  const f = D.feed; let hi = f.length - 1;
  while (hi >= 0 && f[hi][1] > step) hi--;
  if (hi === feedPos) return;
  feedPos = hi;
  const groups = [];                                   // consecutive decisions with the same verdict and reason collapse into one line with a count
  for (let k = hi; k >= 0 && k > hi - 600 && groups.length < 5; k--) {
    const e = f[k], g = groups[groups.length - 1];
    if (g && g.state === e[3] && g.text === e[4]) { g.n++; g.from = e[1]; } else groups.push({ state: e[3], text: e[4], n: 1, to: e[1], from: e[1], agent: e[2] });
  }
  const out = groups.map((g) => h("li", {}, pillFor(g.state), h("span", {}, D.feed_texts[g.text],
    h("span", { class: "m" }, g.n > 1 ? g.n + " orders \u00b7 steps " + g.from.toLocaleString("en-US") + " to " + g.to.toLocaleString("en-US") : "Step " + g.to.toLocaleString("en-US") + " \u00b7 agent " + g.agent))));
  P.guard.feed.replaceChildren(...(out.length ? out : [h("li", {}, h("span", {}), h("span", {}, "Nothing held or refused yet in this stretch."))]));
}
function renderNaiveFamilies(step) {
  const rows = D.families.map((f, i) => ({ f, i, n: dot.fam[i] })).filter((r) => r.f.first_step !== null && r.f.first_step <= step);
  P.naive.fam.replaceChildren(...(rows.length ? rows.map((r) => h("li", {}, h("span", {}, r.f.text), h("span", { class: "num" }, r.n.toLocaleString("en-US") + " bad orders"))) : [h("li", { class: "off" }, "None yet.")]));
}
function updateUI(step) {
  const last = Math.min(step, C.steps - 1);
  for (const c of C.clusters.slice(0, 3)) {
    const used = C.day[c.env.name][last], frac = Math.min(1, used / 100 / c.env.daily), p = Math.round(frac * 1000) / 10;
    c.fill.style.setProperty("width", p + "%");
    c.meter.className = "th-meter" + (p >= 99.95 ? " full" : p >= 85 ? " hot" : "");
    c.meter.setAttribute("aria-valuenow", String(p));
    c.used.textContent = money(used);
    c.flag.textContent = p.toFixed(1) + "%" + (p >= 99.95 ? " · exhausted" : "");
  }
  const day = Math.floor(last / D.run.steps_per_day);
  $("t-step").textContent = "Step " + (last + 1).toLocaleString("en-US") + " of " + D.run.steps.toLocaleString("en-US") + " · day " + (day + 1) + " of " + D.run.days;
  const b = C.beats[cur], v = b.view;
  if (v === "calm") {
    const L = cumAt("legit", last);
    P.calm.orders.val.textContent = L.toLocaleString("en-US"); P.calm.allow.val.textContent = cumAt("legit_allow", last).toLocaleString("en-US");
    P.calm.hold.val.textContent = cumAt("legit_hold", last).toLocaleString("en-US"); P.calm.refuse.val.textContent = cumAt("legit_refuse", last).toLocaleString("en-US");
  } else if (v === "naive") {
    P.naive.usd.textContent = money(cumAt("bad_usd", last)); P.naive.n.textContent = cumAt("bad_n", last).toLocaleString("en-US");
    if (updateUI.nf !== dot.idx) { updateUI.nf = dot.idx; renderNaiveFamilies(last); }
  } else if (v === "guard") {
    P.guard.gate.val.textContent = money(cumAt("bad_gate_usd", last)); P.guard.risk.val.textContent = money(cumAt("bad_risk_usd", last));
    P.guard.leak.val.textContent = money(cumAt("bad_leak_usd", last));
    P.guard.honest.val.textContent = (cumAt("legit_hold", last) + cumAt("legit_refuse", last) + cumAt("legit_tight", last)).toLocaleString("en-US");
    renderFeed(last); autoFocus(last);
  }
}

/* ---------- 6. the focus attack, end to end ---------- */
let focusIx = 2, pinned = false, focusEls = [];
const ORDER = (o) => (o.type === "transfer" ? "transfer " + OG.usd(o.amount_usd, false) + " to " + o.destination_account : o.side + " " + o.quantity + " " + o.ticker + " at limit " + OG.usd(o.limit_price, true));
function buildFocus() {
  const tabs = h("div", { class: "th-tabs", role: "group", "aria-label": "Choose an attack to follow" }, D.focus.map((f, i) => {
    const b = h("button", { type: "button", class: "ghost", "aria-pressed": "false", on: { click: () => { pinned = true; setFocus(i); } } }, f.title);
    focusEls.push(b); return b;
  }));
  P.guard.focus.replaceChildren(tabs, h("p", { class: "th-note", id: "th-focus-note" }), h("ol", { class: "th-flow", id: "th-flow" }));
  setFocus(2);
}
function autoFocus(step) {
  if (pinned) return;
  const ordered = D.focus.map((f, i) => [f.step, i]).sort((a, b) => a[0] - b[0]);
  let k = ordered[0][1]; for (const [s, i] of ordered) if (s <= step) k = i;
  if (k !== focusIx) setFocus(k);
}
function setFocus(i) {
  focusIx = i; const f = D.focus[i]; ringFam = f.family; dirty = true;
  focusEls.forEach((b, k) => b.setAttribute("aria-pressed", String(k === i)));
  $("th-focus-note").textContent = f.blurb + " Agent " + f.agent + " at step " + f.step.toLocaleString("en-US") + ", row " + f.row.toLocaleString("en-US") + " of the recording.";
  const ct = f.claimed ? h("table", { class: "th-ct" }, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "The agent says"), h("th", {}, "OrderGuard trusts"))),
    h("tbody", {}, h("tr", {}, h("td", {}, "Price"), h("td", {}, OG.usd(f.claimed.limit, true)), h("td", {}, OG.usd(f.claimed.trusted, true))),
      h("tr", {}, h("td", {}, "Notional"), h("td", {}, OG.usd(f.claimed.notional_at_limit, false)), h("td", {}, OG.usd(f.claimed.notional_at_trusted, false))))) : null;
  const rule = f.rule;
  const ruleBody = f.gate_checks
    ? [h("p", {}, "The gate checks all pass, so it allows the order:"), h("ul", {}, f.gate_checks.map((t) => h("li", {}, "✓ " + t))),
       h("p", {}, OG.pill("Order-risk unit", "quarantine", "◆"), " ", h("span", { class: "mono" }, rule.code), " fired at risk " + rule.risk.toFixed(2) + "."),
       ...(rule.units || []).map((u) => h("div", { class: "th-act" }, h("span", { class: "mono" }, u.name), h("span", { class: "t" }, h("i", { css: { width: Math.round(u.activation * 100) + "%" } })), h("span", {}, Math.round(u.activation * 100) + "%"))),
       h("details", {}, h("summary", {}, "The model's own words"), h("p", {}, rule.text))]
    : [h("p", {}, OG.pill(rule.layer + " " + (OG.LAYERS[rule.layer] ? OG.LAYERS[rule.layer][0] : ""), "refuse"), " ", rule.text)];
  const dec = f.then ? [OG.pill("Gate: allow", "allow", "✓"), " then ", OG.pill("Order-risk layer: " + (f.then === "hold" ? "hold" : "refuse"), f.then === "hold" ? "hold" : "refuse", f.then === "hold" ? "‖" : "✕")]
    : [OG.pill(f.decision === "hold" ? "Held" : "Refused", f.decision === "hold" ? "hold" : "refuse", f.decision === "hold" ? "‖" : "✕")];
  const L = f.ledger, ch = L.chain;
  const verify = h("p", { class: "th-note", id: "th-verify" }, "Not yet checked.");
  const rows = h("ul", { class: "th-chain" }, ch.hashes.map((hx, k) => h("li", { class: k === ch.at ? "at" : null }, h("span", { class: "num" }, "row " + (ch.first_row + k).toLocaleString("en-US")), h("span", { class: "mono" }, hx.slice(0, 16) + "…"))));
  const ledger = [
    h("p", {}, L.envelope ? "Envelope " + L.envelope + ", day " + (L.day + 1) + ": " + OG.usd(L.budget_before_usd, false) + " committed before, " + OG.usd(L.budget_after_usd, false) + " after, of " + OG.usd(L.cap_usd, false) + "." : "No envelope applies, so no budget moves."),
    h("p", {}, L.effect), h("h4", {}, "Recording chain (an index of the stream file, not the receiver's ledger)"), rows,
    h("button", { type: "button", class: "ghost sm", on: { click: () => verifyFocus(f, verify) } }, "Verify these links in this browser"), verify];
  $("th-flow").replaceChildren(
    h("li", {}, h("h4", {}, "The order"), h("p", {}, ORDER(f.order)), ct, f.note ? h("p", { class: "cap" }, "Arena note on this agent: " + f.note + ".") : null),
    h("li", {}, h("h4", {}, "What fired"), ruleBody),
    h("li", {}, h("h4", {}, "The decision"), h("p", {}, dec)),
    h("li", {}, h("h4", {}, "The ledger"), ledger));
}
async function sha256hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function verifyChain(ch) {
  let prev = ch.prev;
  for (let k = 0; k < ch.rows.length; k++) { const hx = await sha256hex(prev + ch.rows[k]); if (hx !== ch.hashes[k]) return k; prev = hx; }
  return -1;
}
async function verifyFocus(f, el) {
  if (!(window.crypto && crypto.subtle)) { el.textContent = "This browser only offers SHA-256 on https or localhost. The same chain was recomputed when the file was built."; return; }
  const bad = await verifyChain(f.ledger.chain);
  el.textContent = bad < 0 ? "Verified: all " + f.ledger.chain.rows.length + " links recomputed here from the rows' text." : "Link " + (bad + 1) + " does not match.";
}

/* ---------- 7. the human: held-order queue and revocation ---------- */
const PATTERN = { collusion_split: "collusion split", runaway: "runaway loop", size_jump: "size jump", stale_price: "stale price", fat_finger: "fat finger", looks_honest: "looks honest" };
let revealTruth = false, truthEls = [];
function buildQueue() {
  const q = D.queue, tb = h("button", { type: "button", class: "ghost sm", "aria-pressed": "false", on: { click: () => { revealTruth = !revealTruth; tb.setAttribute("aria-pressed", String(revealTruth)); tb.textContent = revealTruth ? "Hide what they really were" : "Reveal what they really were"; truthEls.forEach((e) => { e.hidden = !revealTruth; }); } } }, "Reveal what they really were");
  truthEls = [];
  const items = q.items.map((it) => {
    const adv = it.advice, tr = h("p", { class: "truth", hidden: true }, "Arena label (hidden from the guard): " + (D.families.find((f) => f.id === it.truth) || { text: it.truth }).text + ".");
    truthEls.push(tr);
    return h("li", {}, h("span", { class: "rk", "aria-label": "Queue position " + it.rank }, String(it.rank)),
      h("div", {}, h("b", {}, ORDER(it.order)), " ", h("span", { class: "num" }, OG.usd(it.notional_usd, false)),
        h("p", { class: "cap" }, "Step " + it.step.toLocaleString("en-US") + " · agent " + it.agent + " · first-in-first-out position " + it.fifo_rank + " of " + q.orders),
        h("p", {}, it.why_held), it.model_reason ? h("details", { class: "cap" }, h("summary", {}, "Order-risk model reason"), it.model_reason) : null,
        h("div", { class: "pl" }, OG.pill("Risk model " + it.p_model.toFixed(2), "quarantine", "◆"), OG.pill("Rank key " + OG.usd(it.rank_key_usd, false), "")),
        adv.available ? h("div", { class: "adv" }, h("b", {}, "Advice only. "), "Jev: " + Math.round(adv.p_jev * 100) + "% chance of a compromised, colluding or runaway agent; most likely pattern: " + (PATTERN[adv.pattern] || adv.pattern) + " (" + Math.round(adv.confidence * 100) + "% confident); urgency " + adv.urgency + ". Suggests: " + adv.suggested + ". It cannot approve or release this order.")
                      : h("div", { class: "adv" }, h("b", {}, "No advice. "), "The recording for this order is missing, so the queue is ordered by the risk model alone."), tr));
  });
  P.human.body.replaceChildren(h("h2", {}, "A person decides what the code held"),
    h("p", {}, "Hour " + (q.hour + 1) + " of the run (day " + (q.of_day + 1) + "): " + q.orders + " orders are waiting, " + q.bad + " of them bad. A reviewer opens about " + q.opens + " an hour, so the order matters. This is the queue defined in docs/REVIEW.md: the gate's holds plus every order the risk model flagged, held for a human instead of refused."),
    h("p", { class: "th-note" }, "Ordered by " + q.ordering + ". Position in a plain first-in-first-out queue is shown for comparison."),
    tb, h("ol", { class: "th-queue" }, items),
    h("p", {}, "Against first-in-first-out, opening orders in this advised order takes " + fact("jev_90") + " reviews to reach 90% of the bad dollars instead of " + fact("fifo_90") + ". The risk model's own ordering needs " + fact("model_90") + ": the advice does not beat it, and merging it in makes the order slightly worse. A call costs about US$" + fact("jev_cost_1000") + " per 1,000."),
    h("p", { class: "th-note" }, "Jev is a typed decision model; its output can raise an order in the queue, add a warning or a hold, and nothing more. Code is the only thing that can say yes. ", src("review_doc"), src("triage")),
    h("div", { class: "th-card" }, h("h3", {}, "Revoke and the kill switch"),
      h("p", {}, "This recorded run set no revocation, so there is no revoke moment in it. The behaviour below comes from a separate recorded-action replay of the receiver, not from this run."),
      h("p", {}, h("b", {}, "Receiver evidence, Q5: "), fact("revoke_text") + "."),
      h("p", { class: "th-note" }, "Recorded actions replayed, not a fresh model trial and not a production result. ", src("receiver"))));
}

/* ---------- 8. the proof ---------- */
function buildProof() {
  const split = (parts) => h("div", { class: "th-split", role: "img", "aria-label": "Share of the bad dollars that reached the gate" }, parts.map(([cls, v]) => h("i", { class: cls, css: { width: (100 * v / D.facts.attack_usd.value) + "%" } })));
  const tile1 = h("div", { class: "th-tile" }, h("h3", {}, "Bad dollars stopped"),
    h("div", { class: "big" }, fact("stopped_total_usd") + " of " + fact("attack_usd")), h("p", {}, "stopped by the two layers together. The mandate gate alone stopped " + fact("gate_blocked_usd") + " (" + fact("gate_blocked_share") + "). ", src("summary")),
    split([["a", D.facts.gate_blocked_usd.value], ["b", D.facts.risk_stopped_usd.value], ["c", D.facts.dup_usd.value]]),
    h("p", {}, "Each of the " + fact("gate_leaked_orders") + " orders the gate let through fit the envelope: " + fact("gate_leaked_usd") + ". The order-risk layer then held or refused " + fact("risk_stopped_usd") + " of it (" + fact("risk_stopped_share") + "), leaving " + fact("risk_after_usd") + ". ", src("risk")),
    h("p", { class: "cav" }, "Green: stopped by the gate. Violet: stopped by the order-risk layer. Grey: " + fact("dup_usd") + " of duplicate deliveries, absorbed by idempotency with no effect. The risk layer is a replay over the recorded decisions on a seed it never trained on; budget a stopped colluder would have freed for honest agents is not re-simulated."));
  const starved = D.facts.legit_refused.value;
  const tile2 = h("div", { class: "th-tile" }, h("h3", {}, "Honest orders held"),
    h("div", { class: "big" }, fact("legit_held") + " held, " + fact("legit_refused") + " refused"),
    h("p", {}, "of " + fact("legit_orders") + " honest orders: " + fact("false_refusal") + " refused. ", src("summary")),
    h("p", {}, "The order-risk layer adds " + fact("risk_honest_tightened") + " of " + fact("risk_honest_allowed") + " allowed honest orders (" + fact("risk_honest_tightened_usd") + "). ", src("risk")),
    h("p", { class: "cav" }, "This is a cost, stated plainly. Once an envelope's shared daily budget is spent, honest agents drawing on it are refused: " + fact("legit_daily_refusals") + " of the " + fact("legit_refused") + " honest refusals were that cap, and core reached " + fact("peak_core") + " of its daily cap."));
  const bench = D.bench || { present: false, path: "results/bench/summary.json" };
  const tile3 = h("div", { class: "th-tile" }, h("h3", {}, "Decisions per second"),
    h("div", { class: "big" }, fact("decisions_per_s") + " / s"), h("p", {}, "authority decisions in one process: median " + fact("lat_p50_us") + ", 99th percentile " + fact("lat_p99_us") + ". ", src("summary")),
    h("p", {}, "The order-risk layer scores in " + fact("risk_p50_us") + " median, " + fact("risk_p99_us") + " at the 99th percentile. ", src("latency")),
    h("p", { class: "cav" }, "One CPython thread on a laptop, local authorization only. Machine-dependent."));
  const tile4 = bench.present
    ? h("div", { class: "th-tile" }, h("h3", {}, "Benchmark headline"), h("dl", { class: "kv" }, ...bench.rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, typeof v === "number" ? v.toLocaleString("en-US") : v)])), h("p", { class: "th-note" }, "Read from ", h("a", { class: "th-src", href: "/api/theater/source?id=bench", target: "_blank", rel: "noopener" }, bench.path), "."))
    : h("div", { class: "th-tile slot" }, h("h3", {}, "Benchmark headline"), h("p", {}, "Not written yet. This slot reads ", h("code", {}, bench.path), " as soon as it exists and shows its headline here."), h("p", { class: "cav" }, "Nothing is shown in its place."));
  P.proof.verified = h("p", {}, "Checking the recording's hash chain in this browser…");
  const checks = h("ul", { class: "th-checks" }, D.checks.map((c) => h("li", {}, (c.ok ? "✓ " : "✕ ") + c.name + ": " + c.detail + ".")));
  const tile5 = h("div", { class: "th-tile" }, h("h3", {}, "Ledger chain verified"),
    h("div", { class: "big" }, fact("l8_agree") + " of " + fact("l8_sampled")), h("p", {}, "decisions agreed by the TypeScript receiver, which keeps the real ledger (separate run, seed 23). ", src("l8")),
    h("p", {}, "The recording itself is a hash chain of " + fact("chain_rows") + " rows. Head " + fact("chain_head").slice(0, 16) + "…"), P.proof.verified,
    h("details", { class: "cap" }, h("summary", {}, "Reconciliation: " + fact("checks_ok") + " checks passed when this file was built"), checks));
  P.proof.body.replaceChildren(h("h2", {}, "The scoreboard"), h("div", { class: "th-tiles" }, tile1, tile2, tile3, tile4, tile5));
}
async function verifyAll() {
  if (!(window.crypto && crypto.subtle)) { P.proof.verified.textContent = "This browser only offers SHA-256 on https or localhost; the chain was recomputed when the file was built."; return; }
  let ok = 0, total = 0;
  for (const f of D.focus) { const bad = await verifyChain(f.ledger.chain); total += f.ledger.chain.rows.length; ok += bad < 0 ? f.ledger.chain.rows.length : bad; }
  P.proof.verified.textContent = "Verified in this browser: " + ok + " of " + total + " links on the three followed attacks recomputed from their rows' text.";
}

/* ---------- 9. the clock ---------- */
let cur = -1, showT = 0, playing = false, lastFrame = 0, speed = 1, lastUI = 0, dragging = false;
const BEAT_VIEW = { calm: "p-calm", naive: "p-naive", guard: "p-guard", human: "p-human", proof: "p-proof" };
function stepAtLocal(b, local) {
  if (!b.segments.length) return C.windowsEnd;
  let t = local;
  for (const [a, z, secs] of b.segments) { if (t <= secs) return a + (z - a) * Math.max(0, Math.min(1, t / secs)); t -= secs; }
  return b.segments[b.segments.length - 1][1];
}
function localAtStep(b, step) {
  let t = 0;
  for (const [a, z, secs] of b.segments) { if (step >= a && step <= z) return t + secs * (z === a ? 0 : (step - a) / (z - a)); t += secs; }
  return null;
}
function beatAt(t) { let k = 0; C.beats.forEach((b, i) => { if (t >= b.t0) k = i; }); return k; }
function enterBeat(k, instantStep) {
  cur = k; const b = C.beats[k]; view = b.view; reveal = view !== "calm"; document.body.setAttribute("data-view", view);
  for (const id of Object.values(BEAT_VIEW)) $(id).hidden = id !== BEAT_VIEW[view];
  $("th-kicker").textContent = "Beat " + b.kicker;
  $("th-title").textContent = b.title;
  $("th-caption").textContent = fill(b.caption);
  [...$("th-beatnav").querySelectorAll("button")].forEach((x, i) => { if (i === k) x.setAttribute("aria-current", "step"); else x.removeAttribute("aria-current"); });
  $("b-sback").disabled = $("b-sfwd").disabled = !b.segments.length;
  $("lg-ring").hidden = !reveal; ringFam = view === "guard" ? D.focus[focusIx].family : -1;
  resetDots(); updateUI.nf = -1; feedPos = -1;
  if (view === "guard") { pinned = false; }
  if (view === "proof") verifyAll();
  const s = instantStep === undefined ? (b.segments.length ? b.segments[0][0] : C.windowsEnd) : instantStep;
  applyTo(s, true);
  return s;
}
function setClock(t, fromUser) {
  showT = Math.max(0, Math.min(C.total, t));
  const k = Math.min(C.beats.length - 1, beatAt(showT)), b = C.beats[k], local = showT - b.t0;
  let step = Math.floor(stepAtLocal(b, local));
  if (k !== cur) enterBeat(k, Math.floor(stepAtLocal(b, 0)));
  if (step < dot.applied) { resetDots(); applyTo(step, true); } else applyTo(step, !playing || fromUser === "instant");
  const now = NOW();
  if (now - lastUI > 70 || !playing) { updateUI(step); lastUI = now; }
  $("t-clock").textContent = clock(showT) + " / " + clock(C.total);
  if (!dragging) $("b-scrub").value = String(Math.round(1000 * showT / C.total));
  $("b-scrub").setAttribute("aria-valuetext", "Beat " + (k + 1) + ", " + b.title + ", " + clock(showT));
  C.beats.forEach((bb, i) => { const bar = $("th-beatnav").children[i].firstChild.querySelector(".bar"); bar.style.setProperty("width", (i < k ? 100 : i > k ? 0 : 100 * local / Math.max(bb.dur, 0.001)) + "%"); });
  curStep = step; dirty = true;
}
let curStep = 0;
const clock = (t) => Math.floor(t / 60) + ":" + String(Math.floor(t % 60)).padStart(2, "0");
function frame(ts) {
  if (!lastFrame) lastFrame = ts;
  const dt = Math.min(0.1, (ts - lastFrame) / 1000); lastFrame = ts;
  if (playing) { if (showT >= C.total) pause(); else setClock(showT + dt * speed); }
  if (dirty) draw(NOW());
  requestAnimationFrame(frame);
}
function play() {
  if (reduce) return;
  if (showT >= C.total - 0.01) setClock(0, "instant");
  playing = true; lastFrame = 0; const b = $("b-play"); b.textContent = "❚❚ Pause"; b.setAttribute("aria-label", "Pause");
}
function pause() { playing = false; const b = $("b-play"); b.textContent = "▶ Play"; b.setAttribute("aria-label", "Play"); saveHash(); }
function gotoBeat(k, atEnd) {
  k = Math.max(0, Math.min(C.beats.length - 1, k)); const b = C.beats[k];
  setClock(b.t0 + (atEnd || reduce ? Math.max(0, b.dur - 0.001) : 0.0001), "instant");
  saveHash();
}
function stepBy(n) {
  pause(); const b = C.beats[cur]; if (!b.segments.length) return;
  const want = Math.max(0, Math.min(C.steps - 1, curStep + n));
  const lo = b.segments[0][0], hi = b.segments[b.segments.length - 1][1];
  let tgt = Math.max(lo, Math.min(hi, want)), at = localAtStep(b, tgt);
  if (at === null) { for (const [a, z] of b.segments) if (tgt < a) { tgt = a; break; } at = localAtStep(b, tgt); }
  if (at !== null) { setClock(b.t0 + at, "instant"); saveHash(); }
}
function saveHash() { try { history.replaceState(null, "", "#beat=" + (cur + 1) + "&step=" + (curStep + 1)); } catch (e) { /* no history */ } }
function readHash() {
  const m = /beat=(\d)/.exec(location.hash), s = /step=(\d+)/.exec(location.hash);
  if (!m) return false;
  const k = Math.max(0, Math.min(C.beats.length - 1, Number(m[1]) - 1)), b = C.beats[k];
  let t = b.t0 + 0.0001;
  if (s && b.segments.length) { const at = localAtStep(b, Number(s[1]) - 1); if (at !== null) t = b.t0 + at; }
  setClock(t, "instant"); return true;
}

/* ---------- 10. wire up ---------- */
function applyTheme() {
  const mode = store.get("og_theme"), m = mode === "light" || mode === "dark" ? mode : "system";
  if (m === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", m);
  $("th-theme").textContent = "Theme: " + m; $("th-theme").setAttribute("aria-label", "Theme: " + (m === "system" ? "follow system" : m) + ". Activate to change.");
  if (D) readPalette();
}
$("th-theme").addEventListener("click", () => { const m = store.get("og_theme"); const nx = m === "light" ? "dark" : m === "dark" ? null : "light"; store.set("og_theme", nx); applyTheme(); });
applyTheme();
try { window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => D && readPalette()); } catch (e) { /* old browser */ }

function wire() {
  $("th-beatnav").replaceChildren(...C.beats.map((b, i) => h("li", {}, h("button", { type: "button", class: "ghost", on: { click: () => { pause(); gotoBeat(i); } } }, h("span", { class: "n" }, "Beat " + b.kicker), h("span", { class: "t" }, b.title), h("span", { class: "bar" })))));
  $("th-marks").replaceChildren(...C.beats.slice(1).map((b) => h("li", { css: { left: (100 * b.t0 / C.total) + "%" } })));
  $("b-play").addEventListener("click", () => (playing ? pause() : play()));
  $("b-next").addEventListener("click", () => { pause(); gotoBeat(cur + 1); });
  $("b-prev").addEventListener("click", () => { pause(); gotoBeat(showT - C.beats[cur].t0 > 2 && !reduce ? cur : cur - 1); });
  $("b-sback").addEventListener("click", () => stepBy(-1)); $("b-sfwd").addEventListener("click", () => stepBy(1));
  $("b-speed").addEventListener("change", (e) => { speed = Number(e.target.value) || 1; });
  const sc = $("b-scrub");
  sc.addEventListener("pointerdown", () => { dragging = true; }); sc.addEventListener("pointerup", () => { dragging = false; saveHash(); });
  sc.addEventListener("input", () => setClock(C.total * Number(sc.value) / 1000, "instant"));
  sc.addEventListener("change", saveHash);
  $("b-link").addEventListener("click", async () => {
    saveHash(); const u = location.href;
    try { await navigator.clipboard.writeText(u); status("Link copied: it opens at beat " + (cur + 1) + ", step " + (curStep + 1) + "."); } catch (e) { status("Copy this link: " + u); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (e.key === " " && tag !== "BUTTON" && tag !== "A" && tag !== "SUMMARY") { e.preventDefault(); playing ? pause() : play(); }
    else if (e.key === "ArrowRight" && tag !== "BUTTON") { pause(); gotoBeat(cur + 1); }
    else if (e.key === "ArrowLeft" && tag !== "BUTTON") { pause(); gotoBeat(cur - 1); }
    else if (e.key === "." || e.key === ",") stepBy((e.key === "." ? 1 : -1) * (e.shiftKey ? 10 : 1));
    else if (e.key === "Home") { pause(); gotoBeat(0); }
  });
  window.addEventListener("hashchange", () => { if (!playing) readHash(); });
  $("th-sources").replaceChildren(...D.sources.map((s) => h("li", {}, h("a", { href: "/api/theater/source?id=" + s.id, target: "_blank", rel: "noopener", class: "mono" }, s.path), h("span", { class: "what" }, s.what + " (" + Math.round(s.bytes / 1024).toLocaleString("en-US") + " KB, sha256 " + s.sha256.slice(0, 12) + ")"))));
  $("th-limits").replaceChildren(...D.limits.map((t) => h("li", {}, t)));
  if (reduce) { $("th-motion").hidden = false; $("b-play").disabled = true; $("b-speed").disabled = true; }
  let to = 0;
  window.addEventListener("resize", () => { clearTimeout(to); to = setTimeout(layoutAll, 120); });
  if (window.ResizeObserver) new ResizeObserver(() => { clearTimeout(to); to = setTimeout(layoutAll, 60); }).observe($("th-envs"));
  new MutationObserver(readPalette).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
}

async function boot() {
  try { OG.token = sessionStorage.getItem("og_token") || undefined; } catch (e) { /* storage blocked */ }
  let r;
  try { r = await fetch("/api/theater/timeline", { headers: Object.assign({ Accept: "application/json" }, OG.token ? { Authorization: "Bearer " + OG.token } : {}) }); }
  catch (e) { return fail("The server could not be reached.", "Check that orderguard serve is still running, then reload."); }
  if (r.status === 401) return fail("An access token is needed.", "Open the dashboard, enter the token there, then come back to this page.");
  if (!r.ok) { let m = ""; try { m = (await r.json()).error; } catch (e) { /* not JSON */ } return fail("The recorded run is not available.", m || "Reload to try again."); }
  D = await r.json();
  try { const b = await fetch("/api/theater/bench", { headers: OG.token ? { Authorization: "Bearer " + OG.token } : {} }); D.bench = b.ok ? await b.json() : null; } catch (e) { D.bench = null; }
  C = decode();
  buildStage(); buildPanels(); wire(); readPalette(); layoutAll();
  resetDots();
  if (!readHash()) { setClock(0, "instant"); if (reduce) gotoBeat(0); }
  requestAnimationFrame(frame);
  if (!reduce && !/beat=/.test(location.hash)) play();
}
function fail(title, next) {
  $("th-kicker").textContent = "Not available"; $("th-title").textContent = title; $("th-caption").textContent = next;
  for (const id of ["b-prev", "b-play", "b-next", "b-sback", "b-sfwd", "b-link"]) $(id).disabled = true;
}
boot();
})();
