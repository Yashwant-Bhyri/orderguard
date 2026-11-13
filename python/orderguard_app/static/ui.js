"use strict";
/* ui.js: DOM helpers, number formats and the signature components (rail, verdict card, meters, states).
   No HTML strings anywhere: every server or user string reaches the page through textContent or a text node.
   Inline style attributes are blocked by the CSP, so dynamic sizes are set through the CSSOM (el.style). */
const OG = (window.OG = { presets: [] });

/* ---------- 1. DOM helpers ---------- */
OG.$ = (id) => document.getElementById(id);
OG.h = function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  decorate(e, props);
  for (const c of kids.flat(Infinity)) if (c !== null && c !== undefined && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
};
function decorate(e, props) {
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.setAttribute("class", v);
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "css") for (const [p, val] of Object.entries(v)) e.style.setProperty(p, val);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
}
const NS = "http://www.w3.org/2000/svg";
OG.svg = function svg(tag, attrs, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined && v !== false) e.setAttribute(k, String(v));
  for (const c of kids.flat(Infinity)) if (c !== null && c !== undefined && c !== false) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
};
const { h, svg } = OG;
let uidN = 0;
OG.uid = (p) => p + "-" + ++uidN;
OG.show = (id, ...nodes) => OG.$(id).replaceChildren(...nodes.flat(Infinity).filter(Boolean));
OG.reduceMotion = () => { try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };

/* ---------- 2. number formats: tabular, signed with a real minus, money as $12,345 ---------- */
const MINUS = "−";
OG.usd = (n, cents) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "n/a";
  const v = Number(n), c = cents === undefined ? Math.abs(v) < 1000 && v % 1 !== 0 : cents;
  return (v < 0 ? MINUS : "") + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: c ? 2 : 0, maximumFractionDigits: c ? 2 : 0 });
};
OG.pct = (n, d = 1, signed = true) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "n/a";
  const v = Number(n), s = Math.abs(v).toFixed(d);
  return (v < 0 ? MINUS : signed && v > 0 ? "+" : "") + s + "%";
};
OG.ms = (n) => (n === null || n === undefined ? null : n < 10 ? n.toFixed(1) + " ms" : Math.round(n) + " ms");

/* ---------- 3. small pieces ---------- */
OG.pill = (text, cls, icon) => h("span", { class: "pill " + (cls || "") }, icon ? h("span", { "aria-hidden": "true" }, icon) : null, text);
OG.list = (items, cls) => h("ul", { class: cls || "plain" }, items.map((t) => h("li", {}, t)));
OG.kv = (rows) => h("dl", { class: "kv" }, rows.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
OG.table = (headers, rows, o = {}) => h("div", { class: "tablewrap", tabindex: "0", role: "region", "aria-label": o.caption || "Table" },
  h("table", {}, o.caption ? h("caption", {}, o.caption) : null,
    h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { scope: "col", class: (o.num || []).includes(i) ? "n" : null }, x)))),
    h("tbody", {}, rows.map((r) => h("tr", { class: r.cls || null }, (r.cells || r).map((x, i) => h("td", { class: (o.num || []).includes(i) ? "n num" : null }, x)))))));
OG.lcodes = (ids) => h("span", { class: "lps" }, ids.map((i) => h("span", { class: "lcode" }, i)));

/* ---------- 4. layers and the rail (DESIGN.md section 4) ---------- */
OG.LAYERS = {
  L1: ["Normalise", "Strips hidden characters and flags look-alike letters, in code, before any model reads the text."],
  L2: ["Model screen", "A model reads each chunk and says whether it is safe to show an agent."],
  L3: ["Risk bucket", "Quarantines repeats of a claim that was already quarantined."],
  L4: ["Data marking", "Wraps tool output in data tags so it reads as data, not as instructions."],
  L5: ["Order gate", "Checks the order against the signed mandate at the trusted price: caps, price band, step-up."],
  L6: ["Figure check", "Checks the figures an order cites against SEC filings."],
  L7: ["Trigger graph", "Standing rules fire only when two independent sources agree."],
  L8: ["Receiver", "Final authority and the ledger."],
};
const STATE_WORD = { idle: "not used here", passed: "passed", acted: "acted", off: "off", not_reached: "not reached" };
OG.VERDICT_WORD = { allow: "allowed", hold: "held", refuse: "refused", quarantine: "quarantined" };

/* rail(path, {mini, animate, label}) where path = [{id, state: idle|passed|acted|off|not_reached, verdict?, note?}] for L1..L8.
   The connector after the first station that acted is dashed. Stations light one by one at 60 ms each unless motion is reduced. */
OG.rail = function rail(path, o = {}) {
  const firstActed = path.findIndex((s) => s.state === "acted");
  const ol = h("ol", { class: "rail" + (o.mini ? " mini" : ""), "aria-label": o.label || "Path through layers L1 to L8" });
  path.forEach((s, i) => {
    const [name, what] = OG.LAYERS[s.id] || [s.id, ""];
    const word = s.word ? s.word : s.state === "acted" && s.verdict ? "acted: " + (OG.VERDICT_WORD[s.verdict] || s.verdict) : STATE_WORD[s.state] || s.state;
    const tip = OG.uid("tip");
    const cls = [s.state, s.state === "acted" && s.verdict ? "v-" + s.verdict : "", firstActed >= 0 && i >= firstActed ? "dashed" : ""].join(" ").trim();
    ol.append(h("li", { class: cls, css: { "--i": String(i) } },
      h("button", { type: "button", class: "nd", "aria-describedby": tip, "aria-label": s.id + " " + name + ": " + word }, s.id),
      o.mini ? null : h("span", { class: "nm" }, name),
      o.mini || !(s.state === "acted" || s.state === "off") ? null : h("span", { class: "st" }, word),   // only the decisive station is labelled; the rest speak through style + tooltip
      h("span", { class: "tip", id: tip, role: "tooltip" }, h("b", {}, s.id + " " + name + ": " + word), what, s.note ? h("span", { class: "st" }, s.note) : null)));
  });
  if (o.animate !== false && !OG.reduceMotion()) {
    ol.classList.add("pre");
    const go = () => ol.classList.remove("pre");
    if (window.requestAnimationFrame) requestAnimationFrame(() => requestAnimationFrame(go)); else setTimeout(go, 30);
  }
  return ol;
};
OG.railLegend = () => h("p", { class: "rail-legend" }, h("span", {}, "Filled grey: passed"), h("span", {}, "Coloured ring: acted"), h("span", {}, "Dashed outline: off"), h("span", {}, "Dashed line: the run stopped"));

/* ---------- 5. verdict card (DESIGN.md section 4) ---------- */
OG.VERDICTS = { allow: ["✓", "Allow"], clean: ["✓", "Clean"], hold: ["‖", "Hold"], unknown: ["‖", "Unknown"], refuse: ["✕", "Refuse"], quarantine: ["◆", "Quarantine"] };
OG.rawJson = function rawJson(data) {
  const pre = h("pre", {}, JSON.stringify(data, null, 2));
  const btn = h("button", { type: "button", class: "ghost sm", "aria-label": "Copy raw JSON" }, "Copy");
  btn.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(pre.textContent); btn.textContent = "Copied"; } catch (e) { btn.textContent = "Copy failed"; }
    setTimeout(() => { btn.textContent = "Copy"; }, 1500);
  });
  return h("details", {}, h("summary", {}, "Show raw JSON"), h("div", { class: "rawbar" }, btn), pre);
};
/* verdictCard({verdict, by: "L5 order gate", lead: sentence, reasons: [sentences], raw}) */
OG.verdictCard = function verdictCard(o) {
  const [icon, word] = OG.VERDICTS[o.verdict] || ["?", String(o.verdict)];
  return h("section", { class: "verdict " + o.verdict, "aria-label": "Verdict: " + word },
    h("div", { class: "vh" }, h("span", { class: "vw" }, h("span", { "aria-hidden": "true" }, icon), word),
      o.by ? h("span", { class: "chip by" }, "Decided by " + o.by) : h("span", { class: "chip by" }, "No layer decided")),
    o.lead ? h("p", { class: "lead" }, o.lead) : null,
    o.reasons && o.reasons.length ? h("ol", {}, o.reasons.map((r) => h("li", {}, r))) : null,
    o.raw ? OG.rawJson(o.raw) : null);
};

/* ---------- 6. states: empty, loading, error (DESIGN.md section 5) ---------- */
OG.empty = (text, label, fn) => h("div", { class: "empty" }, h("p", {}, text), label ? h("button", { type: "button", class: "ghost", on: { click: fn } }, label) : null);
OG.skeleton = (label) => h("div", { class: "skel", role: "status" }, h("span", { class: "sr" }, label || "Working"), h("i", { class: "big", "aria-hidden": "true" }), h("i", { "aria-hidden": "true" }), h("i", { "aria-hidden": "true" }), h("i", { "aria-hidden": "true" }));
OG.errorBox = (title, next, cls) => h("div", { class: "msg " + (cls || "bad"), role: "alert" }, h("b", {}, title), next ? h("p", {}, next) : null);

/* ---------- 7. meters ---------- */
const seg = (cls, from, to, scale) => h("div", { class: "mseg " + cls, css: { left: (100 * from / scale) + "%", width: (100 * (to - from) / scale) + "%" } });
const tick = (at, scale, label) => h("div", { class: "mtick", css: { left: (100 * at / scale) + "%" } }, h("span", {}, label));
/* A cap meter: `before` already used (grey), then this order in green up to the cap and hatched red beyond it; the cap is the tick. */
OG.capMeter = function capMeter(title, amount, cap, before = 0) {
  const total = before + amount, scale = Math.max(cap, total, 1) * 1.08;
  const over = total > cap, within = Math.max(0, Math.min(total, cap) - before);
  const track = h("div", { class: "mtrack", role: "img", "aria-label": title + ": " + OG.usd(total) + " against a cap of " + OG.usd(cap) + (over ? ", over the cap" : ", within the cap") });
  const parts = [];                                   // [class, from, to]; the outer two get rounded ends
  if (before > 0) parts.push(["prior", 0, Math.min(before, scale)]);
  if (within > 0) parts.push(["ok", Math.min(before, cap), Math.min(before, cap) + within]);
  if (over) parts.push(["over", Math.max(cap, before), total]);
  parts.forEach(([c, a, b], i) => track.append(seg(c + (i === 0 ? " first" : "") + (i === parts.length - 1 ? " last" : ""), a, b, scale)));
  track.append(tick(cap, scale, "cap " + OG.usd(cap)));
  return h("div", { class: "meter" },
    h("div", { class: "mh" }, h("span", {}, title), h("span", {}, OG.usd(total) + " of " + OG.usd(cap) + (over ? ": over by " + OG.usd(total - cap) : ": within the cap"))), track);
};
/* The price band: the trusted price is the centre tick, the allowed band is the shaded zone, the limit is the marker. */
OG.bandMeter = function bandMeter(limitPct, bandPct, trusted) {
  const R = bandPct * 3, clamp = Math.max(-R, Math.min(R, limitPct)), out = Math.abs(limitPct) > bandPct + 1e-9;
  const track = h("div", { class: "mtrack band", role: "img", "aria-label": "Limit price is " + OG.pct(limitPct, 1) + " from the trusted price; the allowed band is plus or minus " + bandPct + " percent" + (out ? ", outside the band" : ", inside the band") },
    h("div", { class: "zone", css: { left: (50 - 50 * bandPct / R) + "%", width: (100 * bandPct / R) + "%" } }),
    tick(R, 2 * R, "trusted " + OG.usd(trusted, true)),
    h("div", { class: "mk" + (out ? " bad" : ""), css: { left: (50 + 50 * clamp / R) + "%" } }));
  return h("div", { class: "meter" },
    h("div", { class: "mh" }, h("span", {}, "Limit price against the price band"), h("span", {}, "limit " + OG.pct(limitPct, 1) + " from trusted; band ±" + bandPct + "%" + (out ? ": outside the band" : ": inside the band"))), track);
};
