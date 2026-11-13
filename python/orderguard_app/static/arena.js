"use strict";
/* arena.js: the Swarm arena page. Run controls, headline tiles, the tape (animated playback), envelopes over time, who got through,
   latency and the envelope lab. Data comes from /api/arena/run and /api/arena/frontier; everything is simulated.
   Same rules as the rest of the dashboard: nodes only (no HTML strings), SVG through createElementNS, sizes through the CSSOM. */
(function () {
const { h, svg, $, show, usd, pct, pill, table, empty, errorBox } = OG;
const MINUS = "−", MAX_EVENTS = 400, TAPE_MAX = 200, MAX_STEPS = 2000;      // MAX_EVENTS mirrors orderguard_arena.api (the API keeps every bad proposal first)
const num = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (v, f) => (v < 0 ? MINUS : v > 0 ? "+" : "") + f(Math.abs(v));
const kfmt = (v) => (v >= 1e6 ? "$" + +(v / 1e6).toFixed(2) + "M" : v >= 1e3 ? "$" + +(v / 1e3).toFixed(0) + "k" : "$" + Math.round(v));
const nice = (v) => { const p = Math.pow(10, Math.floor(Math.log10(v || 1))), f = v / p; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p; };
const axis = (max) => { const st = nice(max / 4 || 1), top = Math.max(st, Math.ceil(max / st) * st), t = []; for (let v = 0; v <= top + 1e-9; v += st) t.push(v); return { t, top }; };
const preset = (label, run) => OG.presets.push({ group: "Arena", label, page: "arena", run });
const S = { run: null, front: null, rows: [], shown: 0, playing: false, speed: 1, reveal: false, timer: null, say: null, acc: 0, tally: { allow: 0, hold: 0, refuse: 0 }, spd: 100 };

/* ---------- 1. words ---------- */
const DEC = { allow: ["Allowed", "allow", "✓"], hold: ["Held", "hold", "‖"], refuse: ["Refused", "refuse", "✕"] };
const REASON = {
  money: "Moving money is not an order.", revoked: "The envelope was revoked.", expired: "The envelope has expired.", idempotency: "The key was reused for a different order.",
  ticker: "Ticker is not on the allow-list, or uses look-alike letters.", side: "That side is not allowed.", quantity: "Quantity must be a whole positive number.",
  limit: "The limit price is not valid.", no_price: "There is no trusted price for this ticker.", per_order: "Over the per-order cap at the trusted price.",
  daily: "The envelope's daily budget is used up.", band: "Limit price is outside the price band around the trusted price.", fair_share: "This agent has used its fair share of the daily budget.",
  l7: "A standing rule fired, but two independent sources do not confirm it.", stepup: "Large order: a human must approve it.", no_envelope: "No envelope allows this order.",
};
const ARCH = { legit: "honest", collusion: "colluding", runaway_loop: "runaway loop", runaway_dup: "runaway, repeated key", off_list: "off-list ticker", homoglyph: "look-alike ticker" };
const arch = (l) => ARCH[l] || l.replace(/_/g, " ");
const reasonOf = (e) => (e.replay ? "Repeated key: the first decision stands and nothing moved." : e.d === "allow" ? "Inside the envelope" + (e.env ? " (" + e.env + ")" : "") + ": listed ticker, under the caps, price in band." : REASON[e.code] || "Decided by the order gate.");
const chip = (d) => pill(DEC[d][0], DEC[d][1], DEC[d][2]);

/* ---------- 2. run controls and the CLI line ---------- */
const radio = (name) => (document.querySelector('input[name="' + name + '"]:checked') || {}).value;
function params() {
  return { seed: Number($("ar-seed").value), agents: Number(radio("ar-agents")), steps: Number($("ar-steps").value), routing: radio("ar-routing"),
    share: $("ar-share-on").checked ? Number($("ar-share").value) / 100 : null, feed: $("ar-feed").value || null };
}
function cli(p) {
  if (p.feed) {
    const path = "data/arena/feeds/" + p.feed;
    const quoted = /^[\w./-]+$/.test(path) ? path : "'" + path.replace(/'/g, "'\\''") + "'";
    return ["og-arena replay --feed " + quoted, "--agents " + p.agents, "--seed " + p.seed].join(" ");
  }
  return ["og-arena run --seed " + p.seed, "--agents " + p.agents, "--steps " + p.steps, "--steps-per-day " + Math.max(Math.floor(p.steps / 4), 1)]
    .concat(p.routing === "tightest_fit" ? ["--routing tightest_fit"] : [], p.share ? ["--agent-share " + +p.share.toFixed(4)] : []).join(" ");
}
function syncCli() { $("ar-cli").textContent = cli(params()); $("ar-share").disabled = !$("ar-share-on").checked; }
function valid() {
  const p = params(), ok = [
    OG.setErr("ar-seed", Number.isInteger(p.seed) && p.seed >= 0 && p.seed < 2147483648 ? "" : "Use a whole number from 0 to 2,147,483,647."),
    OG.setErr("ar-steps", Number.isInteger(p.steps) && p.steps >= 50 && p.steps <= MAX_STEPS ? "" : "Use a whole number of steps from 50 to " + MAX_STEPS + "."),
    OG.setErr("ar-share", p.share === null || (p.share > 0 && p.share <= 1) ? "" : "Use a share above 0 and up to 100 percent."),
  ];
  return ok.every(Boolean) ? p : (OG.firstInvalid(["ar-seed", "ar-steps", "ar-share"]), null);
}
$("ar-form").addEventListener("input", syncCli);
$("ar-form").addEventListener("change", syncCli);
$("ar-copy").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  try { await navigator.clipboard.writeText($("ar-cli").textContent); b.textContent = "Copied"; } catch (x) { b.textContent = "Copy failed"; }
  setTimeout(() => { b.textContent = "Copy"; }, 1500);
});
$("ar-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const p = valid();
  if (!p) return;
  stop();
  OG.run(OG.submitter(e), "ar-out", "Running the arena", async () => {
    const q = "seed=" + p.seed + "&agents=" + p.agents + "&steps=" + p.steps + (p.feed ? "&feed=" + encodeURIComponent(p.feed) : "");
    const [run, front] = await Promise.all([
      OG.api("/api/arena/run?" + q + "&routing=" + p.routing + (p.share ? "&agent_share=" + p.share : "")),
      OG.api("/api/arena/frontier?" + q).catch((x) => ({ error: x })),
    ]);
    S.run = run; S.front = front.error ? null : front;
    render(p, front.error);
  });
});
preset("Arena: run 1,000 agents", () => { document.querySelector('input[name="ar-agents"][value="1000"]').checked = true; syncCli(); OG.submitForm("ar-form"); });
preset("Arena: envelope lab", () => { const go = () => $("ar-lab") && $("ar-lab").scrollIntoView({ block: "start" }); if (S.run) go(); else { OG.submitForm("ar-form"); const w = setInterval(() => { if (S.run) { clearInterval(w); go(); } }, 300); setTimeout(() => clearInterval(w), 20000); } });

/* ---------- 3. page ---------- */
const card = (id, title, hint, ...kids) => h("section", { class: "card sect", id, "aria-labelledby": id + "-h" }, h("h3", { id: id + "-h" }, title), hint ? h("p", { class: "hint" }, hint) : null, kids);
const numbers = (t) => h("details", { class: "mt8" }, h("summary", {}, "Show the numbers"), t);
function render(p, frontErr) {
  const sm = S.run.summary, cfg = sm.config;
  S.rows = S.run.events; S.spd = cfg.steps_per_day || 100;
  const notes = [];
  const ran = S.run.ran || { agents: cfg.agents, steps: cfg.steps };
  if (ran.agents < p.agents || ran.steps < p.steps) notes.push(h("div", { class: "msg", role: "status" }, h("b", {}, "This server ran " + num(ran.agents) + " agents for " + num(ran.steps) + " steps."),
    h("p", {}, p.feed ? "A recorded feed sets the number of steps: one per recorded tick." : "Dashboard runs bound agents times steps to keep each run to a few seconds. The command above runs the full size.")));
  show("ar-out", notes, tiles(sm), tapeCard(), envCard(sm), whoCard(sm), riskCard(S.run.risk), latCard(sm), labCard(frontErr));
  startTape();
}
function tiles(sm) {
  const b = sm.bad, l = sm.legit, t = sm.timing, peak = Object.entries(sm.utilisation_peak || {}).sort((a, c) => c[1] - a[1]), top = peak[0] || ["", 0];
  const share = b.attack_notional_usd ? 100 * b.blocked_usd / b.attack_notional_usd : 100;
  const tile = (label, n, sub, cls) => h("div", { class: "tile " + (cls || "") }, h("span", { class: "tl" }, label), h("span", { class: "tn" }, n), h("span", { class: "ti" }, sub));
  return h("section", { "aria-label": "Headline numbers" }, h("div", { class: "tiles t5" },
    tile("Proposals", num(sm.proposals), num(sm.replays_absorbed || 0) + " duplicates absorbed"),
    tile("Throughput", num(t.authority_decisions_per_s) + " decisions/s", "p99 " + num(t.latency_us.p99, 1) + " µs"),
    tile("Bad notional blocked", b.attack_notional_usd ? usd(b.blocked_usd) + " of " + usd(b.attack_notional_usd) + " (" + num(share, 1) + "%)" : "No bad orders", b.attack_notional_usd ? usd(b.leaked_usd) + " authorized at the trusted price" : "in this run", share < 100 ? "hot" : "good"),
    tile("Honest false refusals", num(l.notional_usd ? 100 * l.refused_usd / l.notional_usd : 0, 1) + "% of legitimate notional", usd(l.refused_usd) + " of " + usd(l.notional_usd) + "; " + num(100 * l.false_refusal_rate, 1) + "% of orders", l.refused_usd ? "hot" : "good"),
    tile("Envelope use", "peak " + num(100 * top[1], 1) + "% of daily budget", top[0] ? "on " + top[0] + "; " + peak.slice(1).map((x) => x[0] + " " + num(100 * x[1], 1) + "%").join(", ") : "")));
}

/* ---------- 4. the tape ---------- */
let tapeBody = null, tapeWrap = null, playBtn = null, prog = null;
function tapeRow(e, reveal) {
  return h("tr", {}, h("td", { class: "mono" }, "d" + (Math.floor(e.step / S.spd) + 1) + " s" + e.step), h("td", { class: "mono" }, "a" + e.agent), h("td", { class: "mono" }, e.order.ticker),
    h("td", {}, e.order.side), h("td", { class: "n num" }, num(e.order.quantity)), h("td", { class: "n num" }, usd(e.risk)), h("td", {}, chip(e.d)), h("td", {}, reasonOf(e)),
    reveal ? h("td", {}, pill(arch(e.label), e.label === "legit" ? "off" : "quarantine")) : null);
}
function buildTape() {
  const heads = ["Time", "Agent", "Ticker", "Side", "Qty", "Notional at trusted price", "Decision", "Why"].concat(S.reveal ? ["Ground truth"] : []);
  tapeBody = h("tbody", {});
  tapeWrap.replaceChildren(h("table", { class: "tape" }, h("caption", { class: "sr" }, "Proposals in time order"), h("thead", {}, h("tr", {}, heads.map((x, i) => h("th", { scope: "col", class: i === 4 || i === 5 ? "n" : null }, x)))), tapeBody));
  for (const e of S.rows.slice(Math.max(0, S.shown - TAPE_MAX), S.shown)) tapeBody.append(tapeRow(e, S.reveal));
  tapeWrap.scrollTop = tapeWrap.scrollHeight;
}
function progress() {
  prog.textContent = num(S.shown) + " of " + num(S.rows.length) + " shown" + (S.run.events_total > S.rows.length ? " (sampled from " + num(S.run.events_total) + " proposals; every bad one first)" : "");
  playBtn.textContent = S.playing ? "Pause" : S.shown >= S.rows.length ? "Replay" : "Play";
}
function advance(n) {
  const to = Math.min(S.rows.length, S.shown + n);
  for (; S.shown < to; S.shown++) { const e = S.rows[S.shown]; tapeBody.append(tapeRow(e, S.reveal)); S.tally[e.d]++; }
  while (tapeBody.childNodes.length > TAPE_MAX) tapeBody.firstChild.remove();
  tapeWrap.scrollTop = tapeWrap.scrollHeight;
  if (S.shown >= S.rows.length) pause();
  progress();
}
function stop() { clearInterval(S.timer); clearInterval(S.say); S.timer = S.say = null; S.playing = false; }
function pause() { clearInterval(S.timer); S.timer = null; S.playing = false; if (playBtn) progress(); }
function play() {
  if (S.shown >= S.rows.length) { S.shown = 0; buildTape(); }
  S.playing = true; S.acc = 0; clearInterval(S.timer);
  S.timer = setInterval(() => { S.acc += S.speed; const n = Math.floor(S.acc); S.acc -= n; if (n) advance(n); }, 100);
  progress();
}
function startTape() {
  S.shown = 0; S.tally = { allow: 0, hold: 0, refuse: 0 };
  buildTape();
  clearInterval(S.say);
  S.say = setInterval(() => {        // one polite summary every few seconds instead of a row-by-row announcement
    if (!S.playing) return;
    const t = S.tally; S.tally = { allow: 0, hold: 0, refuse: 0 };
    $("ar-say").textContent = num(S.shown) + " of " + num(S.rows.length) + " proposals shown. Latest: " + t.allow + " allowed, " + t.hold + " held, " + t.refuse + " refused.";
  }, 4000);
  if (OG.reduceMotion()) { advance(S.rows.length); $("ar-say").textContent = "All " + num(S.rows.length) + " proposals shown."; } else play();
  progress();
}
window.addEventListener("hashchange", () => { if ($("arena").hidden) pause(); });
function tapeCard() {
  playBtn = h("button", { type: "button", class: "ghost sm", on: { click: () => (S.playing ? pause() : play()) } }, "Play");
  prog = h("span", { class: "cap num" });
  tapeWrap = h("div", { class: "tapewrap", tabindex: "0", role: "region", "aria-label": "The tape: proposals and decisions", "aria-live": "off" });
  const speeds = h("div", { class: "segc", role: "group", "aria-label": "Playback speed" }, [1, 4, 16].map((s) => h("label", {}, h("input", { type: "radio", name: "ar-speed", value: s, checked: s === S.speed, on: { change: () => { S.speed = s; } } }), h("span", {}, s + "×"))));
  const rev = h("input", { type: "checkbox", id: "ar-reveal", checked: S.reveal, on: { change: (e) => { S.reveal = e.target.checked; buildTape(); } } });
  return card("ar-tape", "The tape", "As the guard sees it: each proposal with the decision and the reason. The agent's type stays hidden unless you reveal it.",
    h("div", { class: "tape-bar" }, playBtn, speeds, h("label", { class: "check", for: "ar-reveal" }, rev, "Reveal ground truth"), prog),
    tapeWrap, h("p", { class: "sr", id: "ar-say", role: "status", "aria-live": "polite" }));
}

/* ---------- 5. envelopes over time ---------- */
/* The first moment the colluding group's cumulative spend on an envelope reached half its daily cap, from the events themselves.
   Only when no bad event was dropped by the API's sampling (it keeps every bad event up to MAX_EVENTS); otherwise no marker rather than a wrong one. */
function crossings(sm) {
  if (Array.isArray(S.run.collusion_markers)) {        // computed on the server over every event, not the downsampled tape
    const out = {};
    for (const m of S.run.collusion_markers) if (out[m.envelope] == null) out[m.envelope] = m.step;
    return out;
  }
  const ev = S.rows, out = {}, bad = ev.filter((e) => e.label !== "legit").length;
  if (bad >= MAX_EVENTS) return out;
  const cap = Object.fromEntries(sm.envelopes.map((x) => [x.name, x.daily])), spent = {};
  for (const e of ev) {
    if (e.label !== "collusion" || e.d !== "allow" || e.replay || !cap[e.env]) continue;
    const k = e.env + ":" + Math.floor(e.step / S.spd);
    spent[k] = (spent[k] || 0) + e.risk;
    if (!out[e.env] && spent[k] >= cap[e.env] / 2) out[e.env] = e.step;
  }
  return out;
}
function envChart(env, series, maxStep, mark, peak) {
  const W = 320, H = 170, L = 38, R = 8, T = 12, B = 24, X = (s) => L + (W - L - R) * s / maxStep, Y = (f) => T + (H - T - B) * (1 - f);
  const pts = series.map((r) => [X(r.step), Y(Math.min(1, r[env.name] || 0))]);
  const s = svg("svg", { class: "chart envc", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": env.name + ": daily budget used over time, peak " + num(100 * peak, 1) + "% of the " + usd(env.daily) + " cap" + (mark != null ? "; the colluding group reached half of the cap at step " + mark : "") });
  for (const f of [0, 0.5, 1]) { s.append(svg("line", { x1: L, x2: W - R, y1: Y(f), y2: Y(f), class: f === 1 ? "cap-line" : "gl" })); s.append(svg("text", { x: L - 5, y: Y(f) + 4, "text-anchor": "end" }, f === 0 ? "0" : f * 100 + "%")); }
  const spd = S.spd;
  for (let d = 1; d * spd < maxStep; d++) { s.append(svg("line", { x1: X(d * spd), x2: X(d * spd), y1: T, y2: H - B, class: "dayt" })); s.append(svg("text", { x: X(d * spd) + 3, y: H - 8 }, "d" + (d + 1))); }
  s.append(svg("text", { x: L + 3, y: H - 8 }, "d1"));
  if (pts.length) {
    s.append(svg("path", { class: "area", d: "M" + pts[0][0] + " " + Y(0) + pts.map((p) => " L" + p[0].toFixed(1) + " " + p[1].toFixed(1)).join("") + " L" + pts[pts.length - 1][0] + " " + Y(0) + " Z" }));
    s.append(svg("path", { class: "ln", d: "M" + pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L") }));
  }
  if (mark != null) {
    const r = series.find((x) => x.step >= mark) || series[series.length - 1], x = X(mark), y = Y(Math.min(1, r[env.name] || 0));
    s.append(svg("path", { class: "mk", d: "M" + x + " " + (y - 7) + " l6 7 l-6 7 l-6 -7 Z" }, svg("title", {}, "The colluding group's spend on this envelope reached 50% of the daily cap at step " + mark)));
  }
  return s;
}
function envCard(sm) {
  const series = S.run.utilisation || [], maxStep = Math.max(1, ...series.map((r) => r.step)), cross = crossings(sm), peak = sm.utilisation_peak || {};
  const figs = sm.envelopes.map((e) => h("figure", { class: "envfig" }, envChart(e, series, maxStep, cross[e.name], peak[e.name] || 0),
    h("figcaption", {}, h("b", {}, e.name), " cap " + usd(e.daily) + "/day, peak " + num(100 * (peak[e.name] || 0), 1) + "%")));
  const any = Object.keys(cross).length;
  return card("ar-env", "Envelopes over time", "Each envelope has one daily budget shared by every agent that draws on it. Solid: used so far. Dashed: the cap. Faint ticks: day boundaries.",
    h("div", { class: "ar-multi" }, figs), any ? h("p", { class: "cap" }, "◆ marks where the colluding group's own spend on that envelope passed half of its daily cap.") : null,
    numbers(table(["Step", "Day"].concat(sm.envelopes.map((e) => e.name + " used")), series.map((r) => [r.step, r.day + 1].concat(sm.envelopes.map((e) => num(100 * (r[e.name] || 0), 1) + "%"))), { caption: "Daily budget used", num: [0, 1, 2, 3, 4] })));
}

/* ---------- 6. who got through ---------- */
/* Order-risk layer (python/orderguard_risk): tighten-only, replayed over this run's decisions by the API. */
function riskCard(r) {
  if (!r) return card("ar-risk", "Order-risk layer", "No model file on this server (data/models/order_risk.json), so the learned layer did not run.");
  const before = r.leak_before_usd || 0, after = r.leak_after_usd || 0, cut = before ? Math.round(100 * (before - after) / before) : 0;
  const tile = (cls, tl, tn, ti) => h("div", { class: "tile " + cls }, h("span", { class: "tl" }, tl), h("span", { class: "tn" }, tn), h("span", { class: "ti" }, ti));
  const rows = Object.entries(r.by_label || {}).sort((a, b) => b[1].allowed_usd - a[1].allowed_usd)
    .map(([k, v]) => [arch(k), usd(v.allowed_usd), usd(v.stopped_usd), v.allowed_usd ? Math.round(100 * v.stopped_usd / v.allowed_usd) + "%" : "—"]);
  return card("ar-risk", "Order-risk layer", "A model trained on simulated swarms scores each order the gate allowed from behaviour across agents and time. It can only tighten: allow becomes hold (a human decides) or refuse.",
    h("div", { class: "tiles" },
      tile(after > 0 ? "hot" : "good", "Bad notional past the gate", usd(before) + " → " + usd(after), before ? cut + "% held or refused" : "nothing bad got past the gate"),
      tile("", "Honest orders tightened", num(100 * (r.honest_tightened_rate || 0), 2) + "%", num((r.honest_held || 0) + (r.honest_refused || 0)) + " of " + num(r.honest_allowed || 0) + ", mostly sent to a human"),
      tile("", "Scoring time", r.latency_us ? num(r.latency_us.p50, 0) + " µs" : "n/a", r.latency_us ? "median; p99 " + num(r.latency_us.p99, 0) + " µs" : "")),
    h("p", { class: "caption" }, "Replayed over this run's decisions; budget a refused colluder would have freed is not re-simulated. Colluders here come from the generator the model trained on; see docs/RISK.md for agents it never saw."),
    numbers(table(["Group", "Allowed by the gate", "Stopped by the risk layer", "Share"], rows, { caption: "Bad notional by group", num: [1, 2, 3] })));
}
function whoCard(sm) {
  const rows = Object.entries(sm.by_label).map(([k, v]) => ({ k, v, tot: v.allow_usd + v.hold_usd + v.refuse_usd + (v.replay_usd || 0) }))
    .sort((a, b) => (a.k === "legit" ? -1 : b.k === "legit" ? 1 : b.v.allow_usd - a.v.allow_usd || b.tot - a.tot));
  const W = 640, L = 160, R = 190, BW = W - L - R, RH = 30, H = rows.length * RH + 8;
  const SEG = [["allow_usd", "sg-allow", "✓", "allowed"], ["hold_usd", "sg-hold", "‖", "held"], ["refuse_usd", "sg-refuse", "✕", "refused"], ["replay_usd", "sg-dup", "", "repeated key, nothing moved"]];
  const s = svg("svg", { class: "chart who", viewBox: "0 0 " + W + " " + H, role: "img",
    "aria-label": "Share of each archetype's notional that was allowed, held or refused. " + rows.map((r) => arch(r.k) + ": " + usd(r.v.allow_usd) + " allowed of " + usd(r.tot)).join("; ") });
  rows.forEach(({ k, v, tot }, i) => {
    const y = 4 + i * RH, bad = k !== "legit" && v.allow_usd > 0;
    s.append(svg("text", { x: L - 8, y: y + 17, "text-anchor": "end", class: "lab" }, arch(k)));
    let x = L;
    for (const [f, cls, ic, w] of SEG) {
      const n = v[f] || 0, bw = tot ? BW * n / tot : 0;
      if (!n) continue;
      s.append(svg("rect", { x, y: y + 3, width: Math.max(1.5, bw), height: 18, class: cls }, svg("title", {}, arch(k) + ", " + w + ": " + usd(n))));
      if (bw > 22 && ic) s.append(svg("text", { x: x + bw / 2, y: y + 16, "text-anchor": "middle", class: "ic" }, ic));
      x += bw;
    }
    s.append(svg("text", { x: L + BW + 8, y: y + 17, class: bad ? "lk" : "" }, usd(v.allow_usd) + " allowed of " + usd(tot)));
  });
  const legend = h("p", { class: "legend" }, SEG.map(([, cls, ic, w]) => h("span", {}, svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, svg("rect", { width: 14, height: 14, rx: 2, class: cls })), (ic ? ic + " " : "") + w)));
  return card("ar-who", "Who got through", "Each bar is that group's own notional at the trusted price, split by what the guard decided. Honest agents are first; the rest are sorted by the dollars that were allowed.",
    legend, s, h("p", { class: "caption" }, "Each colluding order is inside the envelope, so no single-order rule can identify intent. A per-agent share limits how much one agent can consume; the order-risk layer below scores behaviour across agents."),
    numbers(table(["Group", "Proposals", "Allowed", "Held", "Refused", "Repeated key"], rows.map(({ k, v }) => [arch(k), num(v.n), usd(v.allow_usd), usd(v.hold_usd), usd(v.refuse_usd), usd(v.replay_usd || 0)]), { caption: "Notional by group and decision", num: [1, 2, 3, 4, 5] })));
}

/* ---------- 7. latency ---------- */
function latCard(sm) {
  const l = sm.timing.latency_us, W = 640, H = 96, L = 12, R = 24, mx = nice(l.p99 * 1.1), X = (v) => L + (W - L - R) * v / mx;
  const s = svg("svg", { class: "chart lat", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Authorization latency per decision: median " + num(l.p50, 1) + " microseconds, p95 " + num(l.p95, 1) + ", p99 " + num(l.p99, 1) });
  const ax = axis(mx);
  for (const t of ax.t) { s.append(svg("line", { x1: X(t), x2: X(t), y1: 38, y2: 62, class: "gl" })); s.append(svg("text", { x: X(t), y: 80, "text-anchor": "middle" }, num(t, t < 10 ? 1 : 0))); }
  s.append(svg("text", { x: W - R, y: 94, "text-anchor": "end" }, "microseconds (µs) per authorization"));
  const smp = (S.run.latency_us_samples || []).filter((v) => v <= mx);
  if (smp.length > 20) {                                // histogram of sampled decisions, drawn behind the percentile markers
    const nb = 40, bins = new Array(nb).fill(0);
    for (const v of smp) bins[Math.min(nb - 1, Math.floor(v / mx * nb))]++;
    const top = Math.max(...bins), bw = (W - L - R) / nb;
    bins.forEach((c, i) => { if (c) s.append(svg("rect", { x: L + i * bw + 0.5, y: 62 - 24 * c / top, width: Math.max(1, bw - 1), height: 24 * c / top, class: "hist" })); });
  } else {
    s.append(svg("rect", { x: X(l.p50), y: 42, width: Math.max(2, X(l.p99) - X(l.p50)), height: 16, class: "box", rx: 3 }));
  }
  [["p50", l.p50, 0], ["p95", l.p95, 1], ["p99", l.p99, 0]].forEach(([n, v, up]) => {
    s.append(svg("line", { x1: X(v), x2: X(v), y1: 36, y2: 64, class: "pm" }));
    s.append(svg("text", { x: X(v), y: up ? 14 : 28, "text-anchor": "middle", class: "vl" }, n + " " + num(v, 1) + " µs"));
  });
  return card("ar-lat", "Latency", "Time inside the authorization call per decision, in one process: a histogram of sampled decisions with the median, p95 and p99 marked. Not network or broker time.",
    s, numbers(table(["Percentile", "Latency"], [["p50", num(l.p50, 2) + " µs"], ["p95", num(l.p95, 2) + " µs"], ["p99", num(l.p99, 2) + " µs"], ["mean", num(l.mean, 2) + " µs"]], { caption: "Latency percentiles", num: [1] })));
}

/* ---------- 8. envelope lab ---------- */
const sym = (r, n) => r.breadth + " of " + n + " symbols";
function describe(r, n) {
  return "Per-order cap " + usd(r.per_order) + ", daily cap " + usd(r.daily) + ", band " + r.band_pct + "%, " + sym(r, n) + ", step-up " + (r.step_up == null ? "none" : usd(r.step_up)) +
    ", agent share " + (r.agent_share ? num(100 * r.agent_share, 1) + "%" : "none") + ". Leaks " + usd(r.leaked_per_day_usd) + "/day, allows " + usd(r.utility_per_day_usd) + "/day of legitimate orders, " + num(r.approvals_per_day, 1) + " approvals/day.";
}
/* Same rule as frontier.recommend: the most legitimate dollars allowed inside the three limits; ties go to fewer approvals. */
function pick(c, lim) {
  const ok = c.filter((r) => r.leaked_per_day_usd <= lim.leak && r.approvals_per_day <= lim.appr && r.false_refusal_rate * 100 <= lim.fr);
  if (ok.length) return { r: ok.reduce((a, b) => (b.utility_usd > a.utility_usd || (b.utility_usd === a.utility_usd && b.approvals_per_day < a.approvals_per_day) ? b : a)), feasible: true };
  const over = (r) => Math.max(r.leaked_per_day_usd - lim.leak, 0) / Math.max(lim.leak, 1) + Math.max(r.approvals_per_day - lim.appr, 0) / Math.max(lim.appr, 1) + Math.max(r.false_refusal_rate * 100 - lim.fr, 0) / Math.max(lim.fr, 1);
  return { r: c.reduce((a, b) => (over(b) < over(a) || (over(b) === over(a) && b.utility_usd > a.utility_usd) ? b : a)), feasible: false };
}
function labCard(err) {
  const f = S.front;
  if (!f) return card("ar-lab", "Envelope lab", null, errorBox("The envelope lab could not be computed.", (err && (err.title || err.message)) || "Run the arena again."));
  const rec = f.recommendation, base = f.baseline, nsym = (f.profile.symbols || []).length;
  const seen = new Set(), cands = [];
  for (const r of [].concat(Array.isArray(f.candidates) ? f.candidates : [], f.frontier, rec.candidate)) if (!seen.has(r.label)) { seen.add(r.label); cands.push(r); }   // the API returns a count of candidates, so fall back to the frontier
  const rb = rec.risk_budget, maxLeak = Math.max(rb.max_leak_per_day_usd, ...cands.map((r) => r.leaked_per_day_usd)), maxAppr = Math.max(rb.max_approvals_per_day, ...cands.map((r) => r.approvals_per_day));
  const init = { leak: rb.max_leak_per_day_usd, appr: rb.max_approvals_per_day, fr: +(100 * rb.max_false_refusal_rate).toFixed(1) };
  const front = f.frontier.slice().sort((a, b) => a.leaked_per_day_usd - b.leaked_per_day_usd);
  const W = 680, H = 380, L = 70, R = 24, T = 16, B = 52, ax = axis(Math.max(maxLeak, base.leaked_per_day_usd, 1)), ay = axis(Math.max(...cands.map((r) => r.utility_per_day_usd), base.utility_per_day_usd));
  const X = (v) => L + (W - L - R) * v / ax.top, Y = (v) => T + (H - T - B) * (1 - v / ay.top), ap = Math.max(1, ...cands.map((r) => r.approvals_per_day)), R0 = (r) => 4 + 9 * Math.sqrt(r.approvals_per_day / ap);
  const s = svg("svg", { class: "chart scat", viewBox: "0 0 " + W + " " + H, role: "img",
    "aria-label": "Scatter of " + cands.length + " candidate envelopes: bad dollars leaked per day across, legitimate dollars allowed per day up. The frontier runs from " + usd(front[0].utility_per_day_usd) + " allowed at " + usd(front[0].leaked_per_day_usd) + " leaked to " + usd(front[front.length - 1].utility_per_day_usd) + " allowed at " + usd(front[front.length - 1].leaked_per_day_usd) + " leaked per day. Today leaks " + usd(base.leaked_per_day_usd) + " per day." });
  for (const t of ax.t) { s.append(svg("line", { x1: X(t), x2: X(t), y1: T, y2: H - B, class: "gl" })); s.append(svg("text", { x: X(t), y: H - B + 16, "text-anchor": "middle" }, kfmt(t))); }
  for (const t of ay.t) { s.append(svg("line", { x1: L, x2: W - R, y1: Y(t), y2: Y(t), class: "gl" })); s.append(svg("text", { x: L - 6, y: Y(t) + 4, "text-anchor": "end" }, kfmt(t))); }
  s.append(svg("text", { x: (L + W - R) / 2, y: H - 8, "text-anchor": "middle" }, "Bad dollars leaked per day (less is safer)"));
  s.append(svg("text", { x: 14, y: (T + H - B) / 2, "text-anchor": "middle", transform: "rotate(-90 14 " + (T + H - B) / 2 + ")" }, "Legitimate dollars allowed per day"));
  s.append(svg("path", { class: "pareto", d: "M" + front.map((r) => X(r.leaked_per_day_usd).toFixed(1) + " " + Y(r.utility_per_day_usd).toFixed(1)).join(" L") }));
  const tip = h("div", { class: "ar-tip", role: "tooltip", id: "ar-tip", hidden: true }), onFront = new Set(front.map((r) => r.label));
  const place = (r, cx, cy) => { tip.textContent = describe(r, nsym); tip.hidden = false; tip.style.setProperty("left", (100 * cx / W) + "%"); tip.style.setProperty("top", (100 * cy / H) + "%"); };
  const dot = (r, cls, label) => {
    const cx = X(r.leaked_per_day_usd), cy = Y(r.utility_per_day_usd), foc = cls !== "c0";
    const g = svg(cls === "today" ? "rect" : "circle", cls === "today" ? { x: cx - 7, y: cy - 7, width: 14, height: 14, class: "pt today" } : { cx, cy, r: R0(r), class: "pt " + cls },
      svg("title", {}, (label ? label + ": " : "") + describe(r, nsym)));
    if (foc) { g.setAttribute("tabindex", "0"); g.setAttribute("role", "img"); g.setAttribute("aria-label", (label ? label + ". " : "") + describe(r, nsym)); }
    g.addEventListener("mouseenter", () => place(r, cx, cy)); g.addEventListener("focus", () => place(r, cx, cy));
    g.addEventListener("mouseleave", () => { tip.hidden = true; }); g.addEventListener("blur", () => { tip.hidden = true; });
    return g;
  };
  cands.forEach((r) => s.append(dot(r, onFront.has(r.label) ? "c1" : "c0")));
  s.append(dot(base, "today", "Today"));
  s.append(svg("text", { x: X(base.leaked_per_day_usd) + 11, y: Y(base.utility_per_day_usd) - 9, class: "lab" }, "Today"));
  const ring = svg("g", {});
  s.append(ring);

  const sl = (id, label, min, max, step, v, fmt) => {
    const out = h("output", { class: "num", for: id }, fmt(v)), inp = h("input", { type: "range", id, min, max, step, value: v });
    inp.addEventListener("input", () => { out.textContent = fmt(Number(inp.value)); update(); });
    return [h("div", { class: "field" }, h("label", { for: id }, label, " ", out), inp), inp];
  };
  const [fl, il] = sl("ar-s-leak", "Max leak per day", 0, maxLeak, Math.max(1, Math.round(maxLeak / 200)), Math.min(init.leak, maxLeak), (v) => usd(v));
  const [fa, ia] = sl("ar-s-appr", "Max human approvals per day", 0, Math.ceil(maxAppr), 0.5, Math.min(init.appr, Math.ceil(maxAppr)), (v) => num(v, 1));
  const [fr, ir] = sl("ar-s-fr", "Max false refusals", 0, 30, 0.5, Math.min(init.fr, 30), (v) => num(v, 1) + "% of legitimate orders");
  const reset = h("button", { type: "button", class: "ghost sm", on: { click: () => { il.value = Math.min(init.leak, maxLeak); ia.value = Math.min(init.appr, Math.ceil(maxAppr)); ir.value = Math.min(init.fr, 30); for (const i of [il, ia, ir]) i.dispatchEvent(new Event("input")); } } }, "Reset to the lab's budget");
  const recBox = h("div", { id: "ar-rec", "aria-live": "polite" });
  function update() {
    const lim = { leak: Number(il.value), appr: Number(ia.value), fr: Number(ir.value) };
    const same = lim.leak === Math.min(init.leak, maxLeak) && lim.appr === Math.min(init.appr, Math.ceil(maxAppr)) && lim.fr === Math.min(init.fr, 30);
    const p = same ? { r: rec.candidate, feasible: rec.feasible } : pick(cands, lim), r = p.r, cx = X(r.leaked_per_day_usd), cy = Y(r.utility_per_day_usd);
    ring.replaceChildren(svg("circle", { cx, cy, r: R0(r) + 6, class: "ring" }), svg("text", { x: cx + R0(r) + 10, y: cy - R0(r) - 6, class: "lab rl" }, "Recommended"));
    recBox.replaceChildren(recCard(r, p.feasible, same ? rec : null, base, nsym));
  }
  update();
  const plotted = cands.slice().sort((a, b) => a.leaked_per_day_usd - b.leaked_per_day_usd);
  return card("ar-lab", "Envelope lab", "Which envelope should the owner sign? Each point replays the same recorded proposals through one candidate envelope. Point size is human approvals per day; the line is the frontier where no candidate has both less leak and more legitimate flow.",
    h("div", { class: "scatwrap" }, s, tip),
    h("p", { class: "legend" }, h("span", {}, svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, svg("circle", { cx: 7, cy: 7, r: 5, class: "pt c1" })), "Frontier"), h("span", {}, svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, svg("circle", { cx: 7, cy: 7, r: 5, class: "pt c0" })), "Other candidate"),
      h("span", {}, svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, svg("rect", { x: 2, y: 2, width: 10, height: 10, class: "pt today" })), "Today: the envelopes this swarm ran under"), h("span", {}, svg("svg", { viewBox: "0 0 14 14", "aria-hidden": "true" }, svg("circle", { cx: 7, cy: 7, r: 5, class: "ring" })), "Recommended")),
    numbers(table(["Envelope", "Leak per day", "Legitimate allowed per day", "False refusals", "Approvals per day"], [["Today", usd(base.leaked_per_day_usd), usd(base.utility_per_day_usd), num(100 * base.false_refusal_rate, 1) + "%", num(base.approvals_per_day, 1)]]
      .concat(plotted.map((r) => [describe(r, nsym).split(". ")[0], usd(r.leaked_per_day_usd), usd(r.utility_per_day_usd), num(100 * r.false_refusal_rate, 1) + "%", num(r.approvals_per_day, 1)])), { caption: "Candidate envelopes", num: [1, 2, 3, 4] })),
    h("h4", { class: "mt16" }, "Risk budget"), h("p", { class: "hint" }, "Set what you can live with. The lab picks the candidate that allows the most legitimate dollars inside all three limits (fewer approvals on a tie)."),
    h("div", { class: "ar-sliders" }, fl, fa, fr), h("p", {}, reset), recBox,
    h("div", { class: "msg", role: "note" }, h("b", {}, "This is advice to the account owner."), h("p", {}, "Agents can never choose or widen their own envelope; the owner signs it.")));
}
function recCard(r, feasible, server, base, nsym) {
  const dl = (v, better, f) => (Math.abs(v) < 1e-9 ? h("span", { class: "cap" }, "no change") : h("span", { class: "delta " + (better ? "ok" : "bad") }, sgn(v, f) + (better ? " better" : " worse")));
  const fm = (v) => usd(v), fp = (v) => num(v, 1) + " pts";
  const row = (k, v, d) => [k, v, d || ""];
  const rows = [
    row("Per-order cap", usd(r.per_order)), row("Daily cap", usd(r.daily)), row("Price band", "±" + r.band_pct + "% of the trusted price"),
    row("Symbols", server ? server.proposed_mandate.symbols.join(", ") : sym(r, nsym)), row("Step-up threshold", r.step_up == null ? "none" : usd(r.step_up)), row("Per-agent share", r.agent_share ? num(100 * r.agent_share, 1) + "% of the daily cap" : "none"),
    row("Legitimate allowed", usd(r.utility_per_day_usd) + "/day (" + num(100 * r.utility_share, 1) + "%)", dl(r.utility_per_day_usd - base.utility_per_day_usd, r.utility_per_day_usd >= base.utility_per_day_usd, fm)),
    row("False refusals", num(100 * r.false_refusal_rate, 1) + "%", dl(100 * (r.false_refusal_rate - base.false_refusal_rate), r.false_refusal_rate <= base.false_refusal_rate, fp)),
    row("Leak", usd(r.leaked_per_day_usd) + "/day", dl(r.leaked_per_day_usd - base.leaked_per_day_usd, r.leaked_per_day_usd <= base.leaked_per_day_usd, fm)),
    row("Human approvals", num(r.approvals_per_day, 1) + "/day", dl(r.approvals_per_day - base.approvals_per_day, r.approvals_per_day <= base.approvals_per_day, (v) => num(v, 1))),
  ];
  return h("div", { class: "reccard" }, h("h4", {}, "Recommended envelope ", feasible ? pill("inside your limits", "allow", "✓") : pill("no candidate fits; closest shown", "hold", "‖")),
    table(["", "Recommended", "Compared with today"], rows, { caption: "Recommended envelope and what it would have done" }),
    h("p", { class: "cap" }, "Parameters are unsigned advice. The last four rows replay this run's proposals through the envelope."), server ? h("details", {}, h("summary", {}, "Why this one"), h("p", {}, server.explanation)) : null);
}

OG.pages.arena = { empty: () => show("ar-out", empty("Run the arena to see many agents decided at the trusted price, the tape of decisions, who got through and which envelope to sign.", "Run arena", () => OG.submitForm("ar-form"))) };

/* Recorded market-data feeds offered by this server. */
const feedPicker = $("ar-feed"), feedHelp = $("ar-feed-help"), synthetic = feedPicker.options[0];
let feedRequest = 0;
async function loadFeeds() {
  const request = ++feedRequest;
  feedHelp.textContent = "Loading recorded feeds…";
  let options = [];
  let help;
  try {
    const { feeds } = await OG.api("/api/arena/feeds");
    options = feeds.map((f) => h("option", { value: f.name }, f.name.replace(/\.jsonl$/, "") + " (" + num(f.ticks) + " ticks, " + f.source + ")"));
    help = options.length ? "A recorded feed replays one step per tick. Synthetic feeds are seeded and reproducible." : "No recorded feeds on this server. Record one with og-arena record.";
  } catch (e) {
    help = "Recorded feeds could not be loaded. You can still select the synthetic feed.";
  }
  if (request !== feedRequest) return;
  const selected = feedPicker.value;
  feedPicker.replaceChildren(synthetic, ...options);
  if (options.some((option) => option.value === selected)) feedPicker.value = selected;
  feedHelp.textContent = help;
  syncCli();
}
feedHelp.setAttribute("role", "status");
window.addEventListener("submit", (e) => { if (e.target.id === "auth-form" && OG.token) loadFeeds(); });
syncCli();
loadFeeds();
})();
