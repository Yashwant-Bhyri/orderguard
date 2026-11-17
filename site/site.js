/* OrderGuard launch site. Every figure shown here is a string or a series from data.json (built by scripts/build_site_data.py from
   the committed results). This file positions marks and places those strings; it formats nothing it was not given, except the
   running counters under the hero replay, which add up data.json's own per-bin series. */
"use strict";

const NS = "http://www.w3.org/2000/svg";
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
let D = null;

/* ---------------------------------------------------------------- tiny DOM helpers (no innerHTML anywhere) */
function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "text") n.textContent = v; else if (k === "cls") n.className = v; else n.setAttribute(k, v);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c);
  return n;
}
function S(tag, attrs, kids) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null) continue;
    if (k === "text") n.textContent = v; else if (k === "cls") n.setAttribute("class", v); else n.setAttribute(k, v);
  }
  for (const c of [].concat(kids || [])) if (c != null) n.append(c);
  return n;
}
const get = (path) => path.split(".").reduce((o, k) => (o == null ? o : o[k]), D);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* ---------------------------------------------------------------- links to the repository */
function repoBase() {
  const m = $('meta[name="og-repo"]');
  let v = m && m.content ? m.content.trim() : "";
  if (!v && /\.github\.io$/.test(location.hostname)) {
    const seg = location.pathname.split("/").filter(Boolean)[0];
    if (seg) v = location.hostname.split(".")[0] + "/" + seg;
  }
  return v ? "https://github.com/" + v + "/" : null;
}
const REPO = repoBase();
function fileHref(path) {
  if (/^[a-z]+:/.test(path) || path.startsWith("#")) return path;
  if (REPO) return REPO + (/\.(md|json|jsonl|txt|html|gz|py|js|ts|mjs)(#.*)?$/.test(path) || path.includes(".") ? "blob/main/" : "tree/main/") + path;
  return "../" + path;
}
function srcLink(path, label) {
  return el("a", { cls: "src", href: fileHref(path), text: label || path, title: "Open the source file" });
}

/* ---------------------------------------------------------------- binding text from data.json */
function segs(list) {
  const f = document.createDocumentFragment();
  for (const s of list || []) {
    if ("t" in s) f.append(s.t);
    else if ("b" in s) f.append(el("b", { text: s.b }));
    else if ("code" in s) f.append(el("code", { text: s.code }));
    else if ("a" in s) f.append(el("a", { href: fileHref(s.href), text: s.a }));
  }
  return f;
}
function bind() {
  for (const n of $$("[data-t]")) n.textContent = get(n.dataset.t) ?? "";
  for (const n of $$("[data-f]")) { const f = get(n.dataset.f); n.textContent = f ? f.text : ""; if (f && f.src) n.title = "From " + f.src; }
  for (const n of $$("[data-seg]")) { n.textContent = ""; n.append(segs(get(n.dataset.seg))); }
  for (const n of $$("[data-src]")) {
    const v = get(n.dataset.src); const path = typeof v === "string" ? v : Array.isArray(v) ? v[0] : v && v.src;
    if (path) { n.href = fileHref(path); n.textContent = path; }
  }
  for (const n of $$("[data-doc]")) n.href = fileHref(n.dataset.doc);
  for (const n of $$("[data-repo-link]")) { if (REPO) n.href = REPO; else n.href = "../README.md"; }
}

/* ---------------------------------------------------------------- lists built from data.json */
function lists() {
  const ln = $("#learn");
  if (ln) for (const l of D.readme.learn) ln.append(el("li", {}, segs(l)));
}

/* ---------------------------------------------------------------- tooltip */
const tip = () => $("#tip");
function tipOn(node, text) {
  node.setAttribute("data-tip", text);
  node.style.cursor = "default";
}
document.addEventListener("pointermove", (e) => {
  const t = e.target.closest && e.target.closest("[data-tip]");
  const box = tip();
  if (!box) return;
  if (!t) { box.hidden = true; return; }
  box.textContent = t.getAttribute("data-tip");
  box.hidden = false;
  const w = box.offsetWidth, h = box.offsetHeight;
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > innerHeight - 8) y = e.clientY - h - 14;
  box.style.left = x + "px"; box.style.top = y + "px";
});
document.addEventListener("pointerleave", () => { const b = tip(); if (b) b.hidden = true; });

/* ---------------------------------------------------------------- chart frame */
function frame(id, o) {
  const fig = $("#" + id);
  fig.textContent = "";
  const tid = id + "-t", did = id + "-d";
  fig.append(el("h4", { id: tid, text: o.title }));
  if (o.desc) fig.append(el("p", { cls: "cdesc", id: did, text: o.desc }));
  const w = Math.max(260, fig.clientWidth - (parseFloat(getComputedStyle(fig).paddingLeft) * 2 || 40));
  const h = typeof o.height === "function" ? o.height(w) : (o.height || 0);
  const svg = S("svg", { viewBox: [0, 0, w, h].join(" "), width: w, height: h, role: "img", "aria-labelledby": tid + (o.desc ? " " + did : "") });
  svg.append(S("title", { text: o.title }));
  if (o.alt) svg.append(S("desc", { text: o.alt }));
  if (o.html) fig.append(o.html);
  else fig.append(svg);
  if (o.html) svg.remove();
  const foot = el("div", { cls: "cfoot" });
  const leg = el("ul", { cls: "legend" });
  for (const l of o.legend || []) leg.append(el("li", {}, [el("span", { cls: "sw", style: "background:" + l.color + (l.border ? ";border:1px solid " + l.border : "") }), l.name]));
  foot.append(leg);
  const srcs = el("span", { cls: "src-line" });
  for (const s of [].concat(o.src || [])) srcs.append(srcLink(s, s.split("/").pop()));
  foot.append(srcs);
  fig.append(foot);
  return { svg, w, h, fig };
}
const fmtTick = (t) => t.label;
function xscale(d0, d1, r0, r1) { return (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0); }
function lscale(d0, d1, r0, r1) { const a = Math.log10(d0), b = Math.log10(d1); return (v) => r0 + ((Math.log10(Math.max(v, d0)) - a) / (b - a)) * (r1 - r0); }
function hbar(x, y, w, h, color, r) {
  const rr = Math.min(r == null ? 4 : r, w / 2, h / 2);
  if (w <= 0) return S("rect", { x, y, width: 0, height: h, fill: color });
  return S("path", { d: ["M", x, y, "H", x + w - rr, "Q", x + w, y, x + w, y + rr, "V", y + h - rr, "Q", x + w, y + h, x + w - rr, y + h, "H", x, "Z"].join(" "), fill: color });
}
function vbar(x, y, w, h, color) {
  const rr = Math.min(4, w / 2, h / 2);
  return S("path", { d: ["M", x, y + h, "V", y + rr, "Q", x, y, x + rr, y, "H", x + w - rr, "Q", x + w, y, x + w, y + rr, "V", y + h, "Z"].join(" "), fill: color });
}
function vgrid(svg, ticks, sx, top, bottom, opts) {
  for (const t of ticks) {
    const x = sx(t.v);
    svg.append(S("line", { x1: x, x2: x, y1: top, y2: bottom, cls: "gridl" }));
    if (!opts || !opts.nolabel) svg.append(S("text", { x, y: bottom + 16, "text-anchor": "middle", cls: "muted", text: fmtTick(t) }));
  }
}
const textW = (s, size) => s.length * (size || 12) * 0.56;

/* ---------------------------------------------------------------- the charts */
/* ---------------------------------------------------------------- shared formatting */
const NF = new Intl.NumberFormat("en-US"), MF = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdShort = (v) => (v >= 1e6 ? "$" + MF.format(v / 1e6) + "M" : "$" + NF.format(Math.round(v)));
const pad2 = (n) => String(n).padStart(2, "0");

/* ---------------------------------------------------------------- hero console: a recorded episode, replayed */

/* ---------------------------------------------------------------- full scope against OrderGuard */
function compareSetup() {
  const box = $("#cmp"), bars = [];
  if (!box) return;
  for (const r of D.compare.rows) {
    const scale = Math.max(r.without, r.with) || 1;
    const bo = el("i"), bg = el("i");
    bars.push([bo, (r.without / scale) * 100], [bg, (r.with / scale) * 100]);
    box.append(el("div", { cls: "cmp-row" }, [
      el("div", { cls: "cmp-what" }, [r.what, el("a", { cls: "src", href: fileHref(r.src), text: r.src })]),
      el("div", { cls: "cmp-v o" }, [el("b", { text: r.without_t }), el("span", { cls: "bar" }, bo)]),
      el("div", { cls: "cmp-v g" }, [el("b", { text: r.with_t }), el("span", { cls: "bar" }, bg)]),
      el("span", { cls: "cmp-d", text: r.delta })]));
  }
  const grow = () => bars.forEach(([i, w]) => { i.style.width = Math.max(w, w > 0 ? 1.5 : 0) + "%"; });
  if (reduce.matches) { grow(); return; }
  const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { grow(); io.disconnect(); } }, { threshold: 0.25 });
  io.observe(box);
}

/* ---------------------------------------------------------------- shared demo helpers */
const pad4 = (n) => String(n).padStart(4, "0");
const money = (s) => Number(String(s).replace(/[^0-9.]/g, ""));
const usdN = (v) => "$" + NF.format(Math.round(v));
function onView(node, fn, threshold) {
  const io = new IntersectionObserver((es) => fn(es[0].isIntersecting), { threshold: threshold == null ? 0.35 : threshold });
  io.observe(node);
}

/* ---------------------------------------------------------------- hero: five agents, one position */

/* ---------------------------------------------------------------- signed mandate: the real document, annotated */

/* ---------------------------------------------------------------- trusted data: what an order relies on, checked */

/* ---------------------------------------------------------------- film segments pinned to each layer */

/* ---------------------------------------------------------------- results, each with its context */

/* ---------------------------------------------------------------- risk: one order through the five stops */

/* ---------------------------------------------------------------- record: decisions sealed into a chain */

function timeline() {
  // a cancellable chain of timed steps, so a demo can be restarted cleanly
  let ids = [];
  return {
    at(ms, fn) { ids.push(setTimeout(fn, ms)); },
    clear() { ids.forEach(clearTimeout); ids = []; },
  };
}
/* ---------------------------------------------------------------- vision: scenes acted out from data.json (illustrative inputs) */
function replayOnView(node, run) {
  run();
  if (reduce.matches) return;
  let vis = false;
  onView(node, (v) => { const was = vis; vis = v; if (v && !was) run(); });
}
function revealList(list, cls, gap) {
  const items = $$("li", list), T = timeline();
  replayOnView(list, () => {
    T.clear();
    items.forEach((li) => li.classList.remove(cls));
    items.forEach((li, i) => T.at(reduce.matches ? 0 : 300 + i * gap, () => li.classList.add(cls)));
  });
}


function sign3Scene() {
  const box = $("#sign3");
  if (!box) return;
  const V = D.vision, T = timeline();
  $("#s3-intent").textContent = "“" + V.intent + "”";
  const json = (o) => JSON.stringify(o, null, 2);
  $("#s3-prop").textContent = json(V.contract);
  const [grp, key] = V.edit.path;
  function run() {
    T.clear();
    const signed = $("#s3-signed"), st = $("#s3-state"), diff = $("#s3-diff");
    signed.textContent = ""; diff.textContent = ""; st.className = "pill"; st.textContent = "unsigned";
    box.classList.remove("done");
    T.at(reduce.matches ? 0 : 1600, () => {
      const c = JSON.parse(JSON.stringify(V.contract)); c[grp][key] = V.edit.signed;
      const lines = json(c).split("\n");
      lines.forEach((ln) => signed.append(ln.includes('"' + key + '"') ? el("mark", { text: ln }) : ln, "\n"));
      diff.textContent = "You changed " + key + " from " + V.edit.proposed + " to " + V.edit.signed + " before signing. The change is recorded with the contract.";
    });
    T.at(reduce.matches ? 0 : 3600, () => { st.className = "pill allowed"; st.textContent = "signed by the owner"; box.classList.add("done"); });
  }
  replayOnView(box, run);
}

function concScene() {
  const box = $("#conc");
  if (!box) return;
  const C = D.vision.concurrency, T = timeline(), naive = $("#conc-naive"), proj = $("#conc-proj");
  function run() {
    T.clear(); naive.textContent = ""; proj.textContent = ""; $("#conc-naive-f").textContent = ""; $("#conc-proj-f").textContent = "";
    const g = reduce.matches ? 0 : 900;
    C.naive.forEach((v, i) => T.at(300 + i * g, () => {
      naive.append(el("li", { cls: "in" }, [el("span", { text: "Agent " + (i + 1) + " adds " + C.add }), el("b", { text: "sees " + v }), el("span", { cls: "pill allowed", text: "fits" })]));
      proj.append(el("li", { cls: "in" }, [el("span", { text: "Agent " + (i + 1) + " adds " + C.add }), el("b", { text: "projected " + C.projected[i] }),
        el("span", { cls: "pill " + (C.verdicts[i] === "allow" ? "allowed" : "held"), text: C.verdicts[i] === "allow" ? "reserved" : "held" })]));
    }));
    T.at(300 + 3 * g, () => {
      $("#conc-naive-f").textContent = "All three fill. The account now holds " + C.actual + ", over the " + C.issuer_cap + " cap nobody's check saw.";
      $("#conc-proj-f").textContent = "The third order would take the position past the " + C.issuer_cap + " cap, so it waits for a person.";
    });
  }
  const p = el("p", { cls: "conc-start", text: "The account already holds " + C.holding + " of the stock. The per-stock cap is " + C.issuer_cap + "." });
  box.before(p);
  replayOnView(box, run);
}

function cfScene() {
  const box = $("#cf");
  if (!box) return;
  const F = D.vision.counterfactual;
  $("#cf-note").textContent = F.note + " Signed volatility budget: " + F.budget + ".";
  const title = { diversified: "A diversified book", concentrated: "A book already heavy in technology" };
  for (const b of F.books) {
    const bars = el("div", { cls: "cf-mix" }, b.weights.map((w) => el("span", { style: "flex:" + w.pct, title: w.name + " " + w.usd, text: w.pct > 0.12 ? w.name : "" })));
    box.append(el("div", { cls: "cf-book " + b.verdict }, [
      el("p", { cls: "cf-h" }, [el("b", { text: title[b.book] || b.book }), el("span", { cls: "pill " + (b.verdict === "allow" ? "allowed" : "held"), text: b.verdict === "allow" ? "Allowed" : "Held" })]),
      bars,
      el("p", { cls: "cf-o", text: "Add " + F.order }),
      el("dl", { cls: "cf-kv" }, [el("div", {}, [el("dt", { text: "Risk before" }), el("dd", { text: b.before })]), el("div", {}, [el("dt", { text: "Risk after" }), el("dd", { text: b.after })]),
        el("div", {}, [el("dt", { text: "Added by this order" }), el("dd", { text: b.delta })])])]));
  }
}

function loopScene() {
  const box = $("#loop");
  if (!box) return;
  const ring = $$("#loop-ring li"), log = $("#loop-log"), T = timeline(), L = D.vision.lease_s;
  const events = [
    ["ok", "Three agents renew their leases against the current portfolio"],
    ["warn", "Three supposedly independent agents start buying on the same unverified rumour"],
    ["bad", "New risk paused for all three. Cancels and risk-reducing orders still allowed"],
    ["ok", "A person reviews the rumour; one agent's lease is renewed with a smaller budget"],
  ];
  function run() {
    T.clear(); log.textContent = "";
    let k = 0;
    const tick = () => { ring.forEach((li, i) => li.classList.toggle("on", i === k % ring.length)); k += 1; };
    for (let i = 0; i < 16; i++) T.at(i * 700, tick);
    events.forEach(([c, t], i) => T.at(600 + i * 2600, () => log.append(el("li", { cls: "in " + c, text: t }))));
    const fill = $("#lease-fill"), lt = $("#lease-t");
    for (let i = 0; i <= 20; i++) T.at(i * 550, () => { const left = Math.round(L * (1 - i / 20)); fill.style.width = (100 * (1 - i / 20)) + "%"; lt.textContent = Math.floor(left / 60) + " min left"; });
    T.at(11600, () => { fill.style.width = 100 + "%"; lt.textContent = "renewed"; });
  }
  replayOnView(box, run);
}

function certScene() {
  const box = $("#cert");
  if (!box) return;
  const ledger = D.flows.ledger[0], T = timeline();
  const lines = [
    ["order", D.layers.price.order], ["agent", D.layers.price.agent], ["contract", "growth-portfolio-v1, policy version signed by the owner"],
    ["portfolio snapshot", "the state it was checked against"], ["reservation", "capacity held for this order"], ["evidence", "two sources, by content hash and time"],
  ];
  function run() {
    T.clear(); const ol = $("#cert-lines"); ol.textContent = ""; $("#cert-seal").hidden = true;
    lines.forEach(([k, v], i) => T.at(reduce.matches ? 0 : 300 + i * 700, () => ol.append(el("li", { cls: "in" }, [el("span", { text: k }), el("b", { text: v }), el("i", { text: "✓" })]))));
    T.at(reduce.matches ? 0 : 300 + lines.length * 700 + 400, () => { const s = $("#cert-seal"); s.hidden = false; s.textContent = "Receipt sealed into the ledger · " + ledger.seal_short; });
  }
  replayOnView(box, run);
}

function visionScenes() {
  sign3Scene(); concScene(); cfScene(); loopScene(); certScene();
  for (const id of ["#gap", "#parts", "#j-time"]) { const l = $(id); if (l) revealList(l, "on", id === "#j-time" ? 1100 : 450); }
}

/* ---------------------------------------------------------------- measured results, each drawn to its scale */
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
function runner() {
  // one run at a time per scene; a new run (or a resize) cancels the old one
  let id = 0;
  return {
    start(instant) {
      const me = ++id;
      const alive = () => me === id;
      const fast = instant || reduce.matches;
      return {
        alive,
        fast,
        wait: (ms) => new Promise((r) => setTimeout(r, fast ? 0 : ms)),
        tween: (ms, fn) => new Promise((res) => {
          if (fast || ms <= 0) { fn(1); res(); return; }
          const t0 = performance.now();
          const f = (now) => {
            if (!alive()) { res(); return; }
            const t = Math.max(0, Math.min(1, (now - t0) / ms));   // a frame can be stamped just before t0
            fn(easeOut(t));
            if (t < 1) requestAnimationFrame(f); else res();
          };
          requestAnimationFrame(f);
        }),
      };
    },
    stop() { id += 1; },
  };
}
const lerp = (a, b, t) => a + (b - a) * t;
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const word = (n, cap) => { const w = WORDS[n] || String(n); return cap ? w.charAt(0).toUpperCase() + w.slice(1) : w; };
function playOnView(node, fn, threshold) {
  // play once the first time the node is properly in view
  let done = false;
  const io = new IntersectionObserver((es) => { if (!done && es[0].isIntersecting) { done = true; io.disconnect(); fn(); } }, { threshold: threshold || 0.4 });
  io.observe(node);
}
function onWidth(node, fn) {
  // call fn when the node's width changes (layout depends on it)
  let w = node.clientWidth, tm = 0;
  addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => { if (node.clientWidth !== w) { w = node.clientWidth; fn(); } }, 120); });
}

/* ---------------------------------------------------------------- the scene: five agents, one position, with or without OrderGuard */


/* ---------------------------------------------------------------- results: honest tasks, done or not */

/* ---------------------------------------------------------------- results: the thousand-agent run */

/* ---------------------------------------------------------------- film segments pinned where they explain something */

/* ---------------------------------------------------------------- depth: panels lean toward the pointer, sections ease in */
function depth() {
  document.documentElement.classList.add("js");
  const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  if (fine && !reduce.matches) {
    for (const p of $$(".depth")) {
      p.addEventListener("pointermove", (e) => {
        const r = p.getBoundingClientRect();
        const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
        p.style.setProperty("--ry", ((x - 0.5) * 4).toFixed(2) + "deg");
        p.style.setProperty("--rx", ((0.5 - y) * 3).toFixed(2) + "deg");
        p.style.setProperty("--mx", (x * 100).toFixed(1) + "%");
        p.style.setProperty("--my", (y * 100).toFixed(1) + "%");
      });
      p.addEventListener("pointerleave", () => { p.style.removeProperty("--rx"); p.style.removeProperty("--ry"); });
    }
  }
  const items = $$(".l-head, .l-body, .res, .sec-head, .scope, .cmp-row, .part, .sys-head, .sc-card, .story-intro");
  items.forEach((n) => n.classList.add("rv"));
  if (reduce.matches) { items.forEach((n) => n.classList.add("in")); return; }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
  items.forEach((n) => io.observe(n));
}

/* ---------------------------------------------------------------- open a pinned film segment large, with sound and controls */

/* ================================================================ launch page v7: what it is, the cascade, the parts, at scale */
const L = () => D.launch;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const T = (s) => document.createTextNode(s);
function pill(kind, text) { return el("span", { cls: "pl pl-" + kind, text }); }
function clsOn(n, c, on) { if (n) n.classList.toggle(c, !!on); }
const nf = (f) => (f && f.text) || "";

/* a looping script that runs while its figure is on screen; reduced motion shows the informative end state instead */
function loopOnView(node, s) {
  if (!node) return;
  let timers = [], gen = 0, live = false;
  const run = () => {
    const g = ++gen; s.reset();
    for (const [ms, fn] of s.steps) timers.push(setTimeout(() => { if (g === gen) fn(); }, ms));
    timers.push(setTimeout(() => { if (g === gen) { timers = []; run(); } }, s.end));
  };
  const stop = () => { gen++; timers.forEach(clearTimeout); timers = []; };
  if (reduce.matches) { s.reset(); (s.still || (() => {}))(); return; }
  new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting && !live) { live = true; run(); } else if (!e.isIntersecting && live) { live = false; stop(); }
  }), { threshold: 0.3 }).observe(node);
}



/* ---------------------------------------------------------------- the story stage: pinned, scroll-driven */
const CH = [
  { fall: "A remembered figure", fix: "Fact check", harm: "Sized a trade on a figure from memory" },
  { fall: "A note with no author", fix: "Provenance", harm: "Followed a note nobody signed" },
  { fall: "A plan that aged", fix: "Final check", harm: "Sent an order priced for an hour ago" },
  { fall: "One position, five agents", fix: "Swarm risk model", harm: "Built one position from many small orders" },
  { fall: "A loop that feeds itself", fix: "Supervision", harm: "Chased a price its own buying moved" },
  { fall: "A step outside the task", fix: "Signed mandate", harm: "Moved cash, which no one signed for" },
];

function memoCard(checked) {
  const F = L().figure;
  const row = (k, a, b, cls) => el("li", { cls: "mm-r " + (cls || "") }, [el("span", { cls: "mm-day", text: k }), el("b", { text: a }), el("small", { text: b })]);
  return el("div", { cls: "mo mo-memo" + (checked ? " checked" : "") }, [
    el("p", { cls: "mo-k", text: "The agent's notes, week two" }),
    el("ol", { cls: "mm-rows" }, [
      row("Mon", "Apple revenue " + F.truth, "from the SEC filing", "ok"),
      row("Wed", "The owner prefers large positions", "added by a plugin, author unknown", "odd"),
      row("Thu", "So: size up on conviction", "the agent's own reasoning, built on the line above", "dep"),
    ]),
    el("p", { cls: "mo-foot" }, checked ? [pill("hold", "Not used"), T(" It isn't in what you signed, and nobody can say who wrote it")] : [T("A preference nobody stated now steers every order")]),
  ]);
}
function noteCard(checked) {
  const F = L().figure, claim = F.claim.split(": ").pop();
  return el("div", { cls: "mo mo-note" + (checked ? " checked" : "") }, [
    el("p", { cls: "mo-k", text: "From the agent's own notes, week one" }),
    el("p", { cls: "nt-row" }, [el("span", { text: "Apple revenue, fiscal year" }), el("b", { cls: "nt-claim", text: claim })]),
    checked ? el("p", { cls: "nt-row nt-truth" }, [el("span", { text: "Apple's SEC filing says" }), el("b", { text: F.truth })]) : el("p", { cls: "nt-row nt-src" }, [el("span", { text: "Source" }), el("b", { text: "its summary of an earlier summary" })]),
    el("p", { cls: "nt-act" }, [T("Plan: "), el("b", { text: "buy, sized on that figure" })]),
    el("p", { cls: "mo-foot" }, checked ? [pill("refuse", "Not used"), T(" The figure doesn't match the filing, so the order built on it doesn't go")] : [T("Models misremember numbers. Nothing compares it with the filing")]),
  ]);
}
function priceCard(checked) {
  const P = L().price, old = P.claim.split(" at ").pop().split(",")[0], now = P.truth.split(" ")[0];
  const svg = S("svg", { viewBox: "0 0 320 120", cls: "ag-svg", preserveAspectRatio: "none", "aria-hidden": "true" });
  svg.append(
    S("rect", { cls: "ag-band", x: 0, y: 17, width: 320, height: 16 }),
    S("path", { cls: "ag-line", d: "M0 92 C40 90 70 94 100 84 S160 62 200 46 S262 28 320 25" }),
    S("line", { cls: "ag-plan", x1: 0, x2: 320, y1: 92, y2: 92 }),
    S("circle", { cls: "ag-dot", cx: 306, cy: 92, r: 6 }),
  );
  return el("div", { cls: "mo mo-price" + (checked ? " checked" : "") }, [
    el("p", { cls: "mo-k", text: "Planned in the morning, sent in the afternoon" }),
    el("div", { cls: "ag-wrap" }, [svg, el("span", { cls: "ag-lbl ag-l-plan", text: "The plan's price " + old }), el("span", { cls: "ag-lbl ag-l-now", text: "The market at send time " + now })]),
    el("p", { cls: "mo-foot" }, checked ? [pill("refuse", "Sent back to re-plan"), T(" At send time it's " + P.result.split(";")[0].replace("The agent's price is ", "") + ". The band you signed is narrower")] : [T("The order goes out at a price the market left behind")]),
  ]);
}
function herdCard(seen) {
  const H = L().herd, n = H.agents.value, max = H.combined.value * 1.08;
  const bars = el("div", { cls: "hd-bars" });
  for (let i = 0; i < n; i++) bars.append(el("div", { cls: "hd-row" }, [el("span", { text: "Agent " + word(i + 1) }), el("i", { style: "width:" + (H.slice.value / H.per_order.value * 100).toFixed(1) + "%" }), el("b", { text: H.slice.text })]));
  const lim = el("div", { cls: "hd-lim" }, [el("span", { text: "Largest single order " + H.per_order.text })]);
  const sum = el("div", { cls: "hd-sum" }, [
    el("i", { style: "width:" + (H.combined.value / max * 100).toFixed(1) + "%" }),
    el("em", { style: "left:" + (H.step_up.value / max * 100).toFixed(1) + "%" }, [el("span", { text: "A person approves above " + H.step_up.text })]),
    el("b", { text: "Together " + H.combined.text + ", " + H.times.text + " the approval line" }),
  ]);
  return el("div", { cls: "mo mo-herd" + (seen ? " seen" : "") }, [
    el("p", { cls: "mo-k", text: word(n, true) + " research agents read the same story, within the same minute" }),
    el("div", { cls: "hd-wrap" }, [bars, lim]), sum,
    el("p", { cls: "mo-foot" }, seen ? [pill("hold", "Held for a person"), T(" The swarm risk model sees one position, not " + word(n) + " orders")] : [T("Every order passes every per-order limit")]),
  ]);
}
function spiralCard(sup) {
  const S_ = L().spiral;
  const svg = S("svg", { viewBox: "0 0 320 120", cls: "sp-svg", preserveAspectRatio: "none" });
  svg.append(S("path", { cls: "sp-up", d: "M0 100 C40 98 60 92 90 84 S140 60 170 44 S215 14 240 10 S262 40 276 70 S300 112 320 116" }));
  if (sup) svg.append(S("path", { cls: "sp-flat", d: "M0 100 C40 98 70 94 100 90 S160 84 200 82 S260 80 320 78" }));
  return el("div", { cls: "mo mo-spiral" + (sup ? " sup" : "") }, [
    el("p", { cls: "mo-k", text: "Their buying moves the price. The rising price looks like proof." }), svg,
    el("dl", { cls: "sp-kv" }, [
      el("div", {}, [el("dt", { text: "Worst drawdown" }), el("dd", {}, [el("s", { text: S_.dd_open.split(".")[0] }), sup ? el("b", { text: S_.dd_full }) : null])]),
      el("div", {}, [el("dt", { text: "Slippage" }), el("dd", {}, [el("s", { text: S_.slip_open }), sup ? el("b", { text: S_.slip_full }) : null])]),
    ]),
    el("p", { cls: "mo-foot" }, [T("A crowded-market stress test with " + S_.agents.text + " agents, the mean of " + word(S_.seeds.value) + " runs" + (sup ? ": with OrderGuard" : ": without OrderGuard"))]),
  ]);
}
function moneyCard(sealed) {
  return el("div", { cls: "mo mo-money" + (sealed ? " sealed" : "") }, [
    el("p", { cls: "mo-k", text: "To free up cash for the trade, it moves money between accounts" }),
    el("div", { cls: "mn-flow" }, [
      el("div", { cls: "mn-acct" }, [el("small", { text: "Your account" }), el("b", { text: "Brokerage" })]),
      el("div", { cls: "mn-arrow" }, [el("span", { text: "transfer_funds " + L().page.amount.text }), el("i", { cls: "mn-seal" })]),
      el("div", { cls: "mn-acct out" }, [el("small", { text: "Another account" }), el("b", { text: "Not on your list" })]),
    ]),
    el("p", { cls: "mo-foot" }, sealed ? [pill("refuse", "Refused at the receiver"), T(" Moving money isn't in what you signed, and the agent never held the key")] : [T("A sensible-looking step that nobody asked for")]),
  ]);
}
function recordCard(sealed) {
  const rows = el("ol", { cls: "rc-rows" });
  const ds = [["refuse", "Not used"], ["hold", "Not used"], ["refuse", "Sent back"], ["hold", "Held"], ["hold", "Slowed"], ["refuse", "Refused"]];
  CH.forEach((c, i) => rows.append(el("li", {}, [el("span", { text: c.harm }), sealed ? pill(ds[i][0], ds[i][1] + " · " + c.fix) : el("em", { text: "no record" })])));
  return el("div", { cls: "mo mo-record" + (sealed ? " sealed" : "") }, [
    el("p", { cls: "mo-k", text: sealed ? "Every decision, sealed with its reason" : "A month later: why does the book look like this?" }), rows,
    sealed ? el("p", { cls: "mo-foot" }, [T("The held position is first in line for a person, ranked by money at stake")]) : el("p", { cls: "mo-foot", text: "Each step looked reasonable. Nothing wrote down why" }),
  ]);
}
function assistantCard() {
  const tools = [["search_web", "Apple 10-K analysis"], ["get_filing", "AAPL"], ["get_quote", "AAPL"], ["place_order", "ready"], ["transfer_funds", "ready"]];
  const team = el("div", { cls: "as-team" });
  for (let i = 0; i < L().herd.agents.value; i++) team.append(el("i", { text: "R" + (i + 1) }));
  return el("div", { cls: "mo mo-assist" }, [
    el("div", { cls: "as-top" }, [el("i", { cls: "as-av" }), el("span", {}, [el("b", { text: "Assistant" }), el("small", { text: "Connected to a broker's MCP server" })]), el("span", { cls: "as-live", text: "Live" })]),
    el("div", { cls: "as-chat" }, [el("p", { cls: "as-me", text: "Grow my portfolio. Keep it safe." }), el("p", { cls: "as-ai" }, [el("span", { cls: "as-dots" }, [el("i"), el("i"), el("i")]), el("span", { cls: "as-txt", text: "On it. I'll research first, then trade." })])]),
    el("p", { cls: "mo-k", text: "Tool calls" }),
    el("div", { cls: "as-calls" }, tools.map((t, i) => el("p", { cls: "as-call", style: "--i:" + i }, [el("code", { text: t[0] }), el("span", { text: t[1] })]))),
    el("div", { cls: "as-foot" }, [el("p", { cls: "mo-k", text: "Research agents" }), team]),
  ]);
}

function storyStage() {
  const stage = $("#stage");
  if (!stage) return;
  const card = $("#st-card"), phase = $("#st-phase"), say = $("#st-say"), chain = $("#chain"), tally = $("#st-tally");
  const video = $("#st-video"), fcap = $("#st-film-cap");
  const sc = D.story.scene, run = D.story.run, A = L().attacks;
  fcap.textContent = "From the film";
  const nodes = CH.map((c, i) => {
    const li = el("li", { cls: "dom" }, [el("span", { cls: "dom-n", text: String(i + 1) }), el("b", { cls: "dom-fall", text: c.fall }), el("b", { cls: "dom-fix", text: c.fix })]);
    chain.append(li); return li;
  });
  chain.prepend(el("li", { cls: "dom-end" }, [el("i", { cls: "ic ic-chat" }), el("span", { text: "Chat assistant" })]));
  chain.append(el("li", { cls: "dom-end" }, [el("i", { cls: "ic ic-mkt" }), el("span", { text: "Market" })]));
  const harms = CH.map((c) => { const li = el("li", {}, [el("span", { text: c.harm }), el("b", { text: c.fix })]); tally.append(li); return li; });
  const W = "Without OrderGuard", G = "With OrderGuard";
  const rc = D.story.clips.receiver;
  const steps = [
    { ph: "swarm", head: "A recorded run", say: sc.total_agents.text + " AI agents trading one book for " + word(run.days.value) + " days: " + sc.run_orders.text + " orders.", zoom: 0, ms: 3600 },
    { ph: "swarm", head: "Follow one of them", say: "A chat assistant, given a broker's trading tools and a research team.", zoom: 1, card: assistantCard, ms: 5200 },
    { ph: "without", head: "The problem", say: "You ask it to watch robotics stocks. Only to watch.", card: () => contagionCard(0), ms: 5000 },
    { ph: "without", head: "The problem", say: "A loosely related name jumps. The agent reads the jump as a signal and buys, though nobody asked it to.", card: () => contagionCard(1), ms: 7000 },
    { ph: "without", head: "The problem", say: "Its order trips a risk rule elsewhere in the book. That rule sells, which trips the next. One small order spreads.", card: () => contagionCard(2), ms: 8600 },
    { ph: "without", head: W, say: "Week one. Its notes carry a revenue figure it remembered, not one it read in the filing.", fall: 1, card: () => noteCard(false), ms: 5200 },
    { ph: "without", head: W, say: "Week two. A plugin adds a line to its notes: the owner prefers large positions.", fall: 2, card: () => memoCard(false), ms: 5000 },
    { ph: "without", head: W, say: "It plans an order in the morning and sends it in the afternoon. The market has moved, but the order still carries the morning price.", fall: 3, card: () => priceCard(false), ms: 7000 },
    { ph: "without", head: W, say: "Its research agents read the same story and pile in. Each order is under the limit.", fall: 4, card: () => herdCard(false), ms: 5200 },
    { ph: "without", head: W, say: "Their buying lifts the price, and the rise looks like proof. They buy more.", fall: 5, card: () => spiralCard(false), ms: 5000 },
    { ph: "without", head: W, say: "To free up cash, it moves money to another account. Nobody asked for that.", fall: 6, card: () => moneyCard(false), ms: 4800 },
    { ph: "without", head: W, say: "Each step looked reasonable. A month later the book holds positions nobody chose.", fall: 6, card: () => recordCard(false), ms: 5000 },
    { ph: "with", head: G, say: "The same month, with OrderGuard between the agents and the broker.", fix: 0, card: assistantCard, ms: 3800 },
    { ph: "with", head: G, say: "The figure is traced to the SEC filing. It doesn't match, so it isn't used.", fix: 1, card: () => noteCard(true), ms: 4800 },
    { ph: "with", head: G, say: "The note has no known author and isn't in what you signed. It isn't used.", fix: 2, card: () => memoCard(true), ms: 4800 },
    { ph: "with", head: G, say: "Right before it's sent, the order is checked at the live price. It is too far from the market, so it goes back to be re-planned.", fix: 3, card: () => priceCard(true), ms: 6600 },
    { ph: "with", head: G, say: "The swarm risk model sees " + word(sc.agents.value) + " agents building one position, and holds it for a person.", fix: 4, card: () => herdCard(true), ms: 5000 },
    { ph: "with", head: G, say: "Supervision sees the crowd forming and slows new buying.", fix: 5, card: () => spiralCard(true), ms: 4800 },
    { ph: "with", head: G, say: "Moving money was never in the mandate you signed. The receiver refuses it.", fix: 6, card: () => moneyCard(true), ms: 4600 },
    { ph: "with", head: "From the film", say: "One order, stopped at the receiver.", fix: 6, film: rc, card: () => moneyCard(true), ms: Math.round(Math.min(12, rc[2] - rc[1]) * 1000) },
    { ph: "with", head: G, say: A.n.text + " attacks on a live AI agent: " + A.without.text + " got a falsehood in without OrderGuard, " + A.with.text + " with it.", fix: 6, card: () => recordCard(true), ms: 6000 },
  ];
  steps.forEach((s) => { s.label = s.say; });

  /* the swarm field */
  const cv = $("#st-swarm"), cx = cv.getContext("2d");
  const N = sc.total_agents.value, dots = [];
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < N; i++) dots.push({ x: rnd(), y: rnd(), vx: (rnd() - 0.5) * 0.0006, vy: (rnd() - 0.5) * 0.0006, r: 1.2 + rnd() * 1.4, hot: rnd() < 0.04 });
  const focus = dots[N >> 1]; focus.x = 0.5; focus.y = 0.48; focus.vx = focus.vy = 0; focus.hot = false;
  let zoom = 0, zoomTo = 0, live = false;
  function paint() {
    const w = cv.clientWidth, h = cv.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, h);
    zoom += (zoomTo - zoom) * 0.08;
    const s = 1 + zoom * zoom * 26, fx = focus.x * w, fy = focus.y * h;
    const grey = css("--dot"), red = css("--refuse"), blue = css("--accent");
    for (const d of dots) {
      if (!reduce.matches) { d.x += d.vx; d.y += d.vy; if (d.x < 0 || d.x > 1) d.vx *= -1; if (d.y < 0 || d.y > 1) d.vy *= -1; }
      const x = (d.x * w - fx) * s + w / 2, y = (d.y * h - fy) * s + h / 2;
      if (x < -20 || y < -20 || x > w + 20 || y > h + 20) continue;
      cx.globalAlpha = d === focus ? 1 : 1 - zoom * 0.85;
      cx.fillStyle = d === focus ? blue : d.hot ? red : grey;
      cx.beginPath(); cx.arc(x, y, d === focus ? d.r + 2 + zoom * 10 : d.r * (1 + zoom), 0, 6.283); cx.fill();
    }
    cx.globalAlpha = 1;
    if (live) requestAnimationFrame(paint);
  }
  new IntersectionObserver((es) => es.forEach((e) => { const was = live; live = e.isIntersecting; if (live && !was) requestAnimationFrame(paint); }), { threshold: 0 }).observe(stage);

  const pnl = $("#st-pnl");
  const level = [0, 0, 0, 0, 0, 6, 14, 22, 34, 50, 64, 70];
  const pnlPath = (drop) => { const pts = []; for (let i = 0; i <= 24; i++) { const t = i / 24; pts.push((t * 240).toFixed(1) + "," + (30 + Math.sin(i * 1.3) * 2 + drop * Math.pow(t, 1.6) * 0.8).toFixed(1)); } return "M" + pts.join(" L"); };
  const ghost = S("path", { cls: "pnl-ghost", d: pnlPath(level[9]) }), line = S("path", { cls: "pnl-line", d: pnlPath(0) });
  pnl.append(S("line", { x1: 0, x2: 240, y1: 30, y2: 30, cls: "pnl-base" }), ghost, line);

  let cardFor = null, cur = 0;
  function show(i) {
    cur = i;
    const s = steps[i];
    stage.dataset.phase = s.ph;
    stage.dataset.step = String(i);
    phase.textContent = s.head;
    say.textContent = s.say;
    say.classList.remove("in"); void say.offsetWidth; say.classList.add("in");
    zoomTo = s.zoom === 0 ? 0 : 1;
    stage.classList.toggle("zoomed", s.ph !== "swarm" || s.zoom === 1);
    if (s.card !== cardFor) { cardFor = s.card; card.replaceChildren(s.card ? s.card() : ""); card.classList.remove("in"); void card.offsetWidth; card.classList.add("in"); }
    const falls = s.ph === "without" ? (s.fall || 0) : s.ph === "with" ? 6 : 0;
    const fixes = s.ph === "with" ? (s.fix || 0) : 0;
    nodes.forEach((n, j) => {
      n.classList.toggle("fallen", j < falls && s.ph !== "with");
      n.classList.toggle("ghost", s.ph === "with" && j >= fixes);
      n.classList.toggle("fixed", s.ph === "with" && j < fixes);
      n.classList.toggle("now", (s.ph === "without" && j === falls - 1 && i <= 10) || (s.ph === "with" && j === fixes - 1 && i <= 18));
    });
    harms.forEach((h, j) => { h.classList.toggle("in", j < falls); h.classList.toggle("undone", j < fixes); });
    line.setAttribute("d", pnlPath(s.ph === "without" ? level[Math.min(11, i)] : 0));
    stage.classList.toggle("ghosted", s.ph === "with");
    stage.classList.toggle("film-lead", !!s.film);
    if (s.film) {
      const src = "media/og-" + s.film[0] + ".mp4#t=" + s.film[1] + "," + s.film[2];
      if (video.dataset.src !== src) { video.dataset.src = src; video.poster = "media/og-" + s.film[0] + ".jpg"; video.src = src; }
      const seek = () => { if (Math.abs(video.currentTime - s.film[1]) > 0.5) video.currentTime = s.film[1]; };
      if (video.readyState >= 1) seek(); else video.addEventListener("loadedmetadata", seek, { once: true });
      if (!reduce.matches && !stage.classList.contains("paused")) video.play().catch(() => {});
    } else video.pause();
  }
  $("#st-film-x").addEventListener("click", () => {
    const f = steps[cur].film || rc;
    video.pause();
    const dlg = $("#film-dlg"), v = $("#film-v");
    v.poster = "media/og-" + f[0] + ".jpg"; v.src = "media/og-" + f[0] + ".mp4#t=" + f[1];
    dlg.showModal(); v.play().catch(() => {});
  });
  sequencer({ root: stage, segs: $("#st-segs"), play: $("#st-play"), steps, show,
    onPlay: (on) => { if (steps[cur].film) { if (on) video.play().catch(() => {}); else video.pause(); } } });
}





/* ---------------------------------------------------------------- part: the swarm risk model */
function spec(dl, rows) {
  for (const [k, v, sub] of rows) dl.append(el("div", {}, [el("dt", { text: k }), el("dd", {}, [el("b", { text: v }), sub ? el("small", { text: sub }) : null])]));
}

/* ---------------------------------------------------------------- attention: one thing lit at a time, the rest recedes; numbers count up the first time they are lit */
function countUp(node) {
  if (!node || node.dataset.counted || reduce.matches) return;
  node.dataset.counted = "1";
  const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  const jobs = [];
  for (let t = walk.nextNode(); t; t = walk.nextNode()) {
    const m = /(\d[\d,]*\.?\d*)/.exec(t.nodeValue);
    if (!m) continue;
    const raw = m[1], dec = (raw.split(".")[1] || "").length, val = parseFloat(raw.replace(/,/g, "")), comma = raw.includes(",");
    if (!isFinite(val) || val === 0) continue;
    jobs.push({ t, pre: t.nodeValue.slice(0, m.index), post: t.nodeValue.slice(m.index + raw.length), val, dec, comma, orig: t.nodeValue });
  }
  if (!jobs.length) return;
  const t0 = performance.now(), D_ = 900;
  const fmt = (v, j) => { let s = v.toFixed(j.dec); if (j.comma) { const [a, b] = s.split("."); s = a.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (b ? "." + b : ""); } return s; };
  const step = (now) => {
    const k = Math.min(1, (now - t0) / D_), e = 1 - Math.pow(1 - k, 3);
    for (const j of jobs) j.t.nodeValue = k >= 1 ? j.orig : j.pre + fmt(j.val * e, j) + j.post;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function highlighter(part) {
  const words = $$("[data-hl]", part);
  let cur = "";
  const set = (k) => {
    cur = k;
    const keys = (k || "").split(" ").filter(Boolean);
    words.forEach((w) => w.classList.toggle("on", keys.includes(w.dataset.hl)));
    let any = false;
    $$("[data-hk]", part).forEach((n) => {
      const on = n.dataset.hk.split(" ").some((x) => keys.includes(x));
      n.classList.toggle("lit", on);
      if (on) { any = true; if (n.matches(".spec > div")) countUp($("dd b", n)); }
    });
    part.classList.toggle("focus", any);
  };
  words.forEach((w) => {
    w.tabIndex = 0;
    w.addEventListener("pointerenter", () => { part.classList.add("hover"); set(w.dataset.hl); });
    w.addEventListener("focus", () => set(w.dataset.hl));
    w.addEventListener("pointerleave", () => part.classList.remove("hover"));
  });
  return (k) => { if (!part.classList.contains("hover")) set(k); };
}

/* ---------------------------------------------------------------- a planned timeline: segments of drawing and film, played in order; the film and the drawing trade places on schedule */
function director(root, cfg) {
  const viz = cfg.viz, film = cfg.film;
  const segs = cfg.segs.map((s) => Object.assign({}, s, { dur: s.kind === "film" ? s.t1 - s.t0 : s.ms / 1000 }));
  let acc = 0; segs.forEach((s) => { s.start = acc; acc += s.dur; });
  const total = acc;
  const stage = el("div", { cls: "duo-stage" + (film ? "" : " solo") });
  root.prepend(stage);
  viz.classList.add("duo-viz");
  stage.append(viz);
  let v = null, fwrap = null;
  const chip = el("span", { cls: "duo-chip" }), nowEl = el("div", { cls: "duo-now" });
  if (film) {
    v = el("video", { playsinline: "", preload: "none", poster: "media/og-" + film + ".jpg", "aria-hidden": "true" });
    v.muted = true; v.defaultMuted = true;
    fwrap = el("div", { cls: "duo-film" }, [v, el("span", { cls: "duo-film-k", text: "From the film" })]);
    stage.append(fwrap, chip, nowEl);
  }
  const btn = el("button", { type: "button", cls: "dr-play", "aria-label": "Pause" }, [el("i")]);
  const bar = el("div", { cls: "dr-bar", role: "slider", tabindex: "0", "aria-label": "Position in this part", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" });
  const segEls = [];
  const fills = segs.map((s) => { const f = el("i"); bar.append(el("span", { cls: "dr-seg dr-" + s.kind, style: "flex:" + s.dur.toFixed(2) + " 1 0" }, [el("b", { cls: "dr-track" }, [f]), el("small", {}, [s.kind === "film" ? el("em", { text: "Film" }) : null, T(s.label)])])); segEls.push(bar.lastChild); return f; });
  const sound = film ? el("button", { type: "button", cls: "dr-sound", text: "Watch with sound" }) : null;
  root.append(el("div", { cls: "dr-ctl" }, [btn, bar, sound]));
  let g = 0, cur = 0, fired = 0, user = false, seen = false, raf = 0, last = 0, stallAt = 0, loaded = false, lead = "";
  const segAt = (t) => { for (let i = segs.length - 1; i >= 0; i--) if (t >= segs[i].start) return i; return 0; };
  const narrow = () => matchMedia("(max-width: 720px)").matches;
  function load() { if (loaded || !v) return; loaded = true; v.preload = "auto"; v.src = "media/og-" + film + ".mp4"; }
  function vidAt(t) {
    if (!v) return;
    load();
    if (v.readyState >= 1) { if (Math.abs(v.currentTime - t) > 0.25) v.currentTime = t; }
    else v.addEventListener("loadedmetadata", () => { v.currentTime = t; }, { once: true });
  }
  function layout() {
    if (!film) return;
    if (narrow()) { root.classList.add("stacked"); viz.style.transform = ""; fwrap.style.transform = ""; fwrap.style.width = fwrap.style.height = ""; return; }
    root.classList.remove("stacked");
    const W = stage.clientWidth, H = stage.clientHeight, vw = viz.offsetWidth, vh = viz.offsetHeight, m = 18;
    const Rw = Math.round(W * 0.21), Lw = W - Rw - 3 * m, Lh = H - 2 * m, Rx = W - m - Rw;
    const fw = Math.min(Lw, Lh * 16 / 9), fh = fw * 9 / 16;
    fwrap.style.width = fw + "px"; fwrap.style.height = fh + "px";
    const big = Math.min(1, Lw / vw, Lh / vh), small = Rw / vw, fs = Rw / fw;
    let ih;
    if (lead === "film") {
      fwrap.style.transform = "translate(" + (m + (Lw - fw) / 2).toFixed(1) + "px," + (m + (Lh - fh) / 2).toFixed(1) + "px)";
      viz.style.transform = "translate(" + Rx + "px," + (m + 22) + "px) scale(" + small.toFixed(4) + ")";
      ih = vh * small;
    } else {
      viz.style.transform = "translate(" + (m + (Lw - vw * big) / 2).toFixed(1) + "px," + (m + (Lh - vh * big) / 2).toFixed(1) + "px) scale(" + big.toFixed(4) + ")";
      fwrap.style.transform = "translate(" + Rx + "px," + (m + 22) + "px) scale(" + fs.toFixed(4) + ")";
      ih = fh * fs;
    }
    chip.style.left = Rx + "px"; chip.style.top = m + "px";
    nowEl.style.left = Rx + "px"; nowEl.style.width = Rw + "px"; nowEl.style.top = (m + 22 + ih + 18).toFixed(1) + "px";
    chip.textContent = lead === "film" ? "The drawing, live" : "The film, " + (segs.some((s, j) => j > cur && s.kind === "film") ? "next" : "paused");
  }
  function setLead(k) {
    if (!film) return;
    if (k !== lead) { lead = k; root.dataset.lead = k; viz.classList.toggle("inset", k !== "viz"); fwrap.classList.toggle("inset", k !== "film"); }
    layout();
  }
  function enter(i, u) {
    cur = i; fired = 0; stallAt = 0;
    const s = segs[i];
    setLead(s.lead || (s.kind === "film" ? "film" : "viz"));
    if (s.kind === "film") { vidAt(s.t0 + u); if (running()) v.play().catch(() => {}); }
    else if (v) { v.pause(); const nx = segs.find((x, j) => j > i && x.kind === "film"); if (nx && loaded) vidAt(nx.t0); }
    bar.dataset.at = String(i);
    segEls.forEach((x, k) => x.classList.toggle("on", k === i));
    if (film) {
      const nx = segs[(i + 1) % segs.length];
      nowEl.replaceChildren(el("small", { text: s.kind === "film" ? "Now, in the film" : "Now, in the drawing" }), el("b", { text: s.label }),
        segs.length > 1 ? el("small", { cls: "nx", text: "Next: " + nx.label.charAt(0).toLowerCase() + nx.label.slice(1) }) : null);
    }
  }
  function fireTo(u, instant) {
    const s = segs[cur], st = s.steps || [], lim = s.kind === "film" ? s.t0 + u : u * 1000;
    while (fired < st.length && st[fired][0] <= lim + 1e-6) { st[fired][1](instant); fired++; }
  }
  function seekTo(t) {
    t = Math.max(0, Math.min(total - 0.02, t));
    if (cfg.reset) cfg.reset();
    const i = segAt(t);
    for (let j = 0; j < i; j++) { cur = j; fired = 0; fireTo(segs[j].dur + 1, true); }
    const u = t - segs[i].start;
    enter(i, u); fireTo(u, true);
    g = t; paint();
  }
  const running = () => seen && !user;
  function paint() {
    fills.forEach((f, j) => { const s = segs[j], k = j < cur ? 1 : j > cur ? 0 : Math.max(0, Math.min(1, (g - s.start) / s.dur)); f.style.transform = "scaleX(" + k.toFixed(4) + ")"; });
    bar.setAttribute("aria-valuenow", String(Math.round(g / total * 100)));
  }
  function tick(ts) {
    raf = 0;
    const dt = last ? Math.min(0.1, (ts - last) / 1000) : 0;
    last = ts;
    if (running()) {
      const s = segs[cur];
      let u = g - s.start;
      if (s.kind === "film") {
        const ok = v.readyState >= 3 && !v.paused && !v.seeking;
        if (ok) { u = v.currentTime - s.t0; stallAt = 0; }
        else {
          if (!stallAt) stallAt = ts;
          if (ts - stallAt > 1200) u += dt;
          if (v.readyState >= 2 && Math.abs(v.currentTime - (s.t0 + u)) > 0.6) v.currentTime = s.t0 + u;
          if (v.paused && loaded) v.play().catch(() => {});
        }
      } else u += dt;
      if (u >= s.dur) {
        fireTo(s.dur + 1, false);
        if (cur + 1 >= segs.length) { if (cfg.reset) cfg.reset(); g = 0; enter(0, 0); fireTo(0, false); }
        else { g = segs[cur + 1].start; enter(cur + 1, 0); fireTo(0, false); }
      } else { g = s.start + Math.max(0, u); fireTo(Math.max(0, u), false); }
    }
    paint();
    if (running()) raf = requestAnimationFrame(tick); else last = 0;
  }
  function go() { root.classList.remove("paused"); btn.setAttribute("aria-label", "Pause"); if (segs[cur].kind === "film") v.play().catch(() => {}); if (!raf) raf = requestAnimationFrame(tick); }
  function stop() { if (v) v.pause(); cancelAnimationFrame(raf); raf = 0; last = 0; root.classList.add("paused"); btn.setAttribute("aria-label", "Play"); }
  btn.addEventListener("click", () => { user = !user; if (user) stop(); else go(); });
  const fx = (e) => { const r = bar.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); };
  bar.addEventListener("pointerdown", (e) => { bar.setPointerCapture(e.pointerId); bar.classList.add("drag"); seekTo(fx(e) * total); });
  bar.addEventListener("pointermove", (e) => { if (bar.classList.contains("drag")) seekTo(fx(e) * total); });
  const up = () => { if (!bar.classList.contains("drag")) return; bar.classList.remove("drag"); if (running()) go(); };
  bar.addEventListener("pointerup", up);
  bar.addEventListener("pointercancel", up);
  bar.addEventListener("keydown", (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const i = Math.max(0, Math.min(segs.length - 1, cur + d));
    seekTo(segs[i].start); if (running()) go();
  });
  if (sound) sound.addEventListener("click", () => {
    user = true; stop();
    const s = segs[cur].kind === "film" ? segs[cur] : segs.find((x) => x.kind === "film");
    const dlg = $("#film-dlg"), fv = $("#film-v");
    fv.poster = "media/og-" + film + ".jpg"; fv.src = "media/og-" + film + ".mp4#t=" + s.t0; fv.muted = false;
    dlg.showModal(); fv.play().catch(() => {});
  });
  addEventListener("resize", layout);
  if (window.ResizeObserver) new ResizeObserver(layout).observe(stage);
  seekTo(0);
  if (reduce.matches) { user = true; seekTo(total - 0.05); stop(); return; }
  root.classList.add("paused");
  if (v) new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) load(); }), { rootMargin: "0px 0px 1200px 0px" }).observe(root);
  new IntersectionObserver((es) => es.forEach((e) => {
    seen = e.isIntersecting;
    if (seen && !user) go(); else if (!seen) { if (v) v.pause(); cancelAnimationFrame(raf); raf = 0; last = 0; }
  }), { threshold: 0.3 }).observe(root);
}

function scramble(node, target, instant) {
  if (instant || reduce.matches) { node.textContent = target; return; }
  const abc = Array.from({ length: 62 }, (_, i) => String.fromCharCode(i < 26 ? 65 + i : i < 52 ? 71 + i : i - 4)).join("");
  const t0 = performance.now(), D_ = 1300;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / D_), keep = Math.floor(k * target.length);
    let s = target.slice(0, keep);
    for (let i = keep; i < target.length; i++) s += target[i] === "…" ? "…" : abc[(Math.random() * abc.length) | 0];
    node.textContent = s;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function typeIn(node, text, instant) {
  if (instant || reduce.matches) { node.textContent = text; return; }
  const t0 = performance.now(), D_ = Math.min(1600, text.length * 28);
  const step = (now) => { const k = Math.min(1, (now - t0) / D_); node.textContent = text.slice(0, Math.round(k * text.length)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}

/* ---------------------------------------------------------------- part: the signed mandate, as a document: written, drafted, checked and signed, then one order through it */
function mandateDoc(opts) {
  const m = D.story.mandate, R = Object.fromEntries(m.rows), LM = D.layers.mandate;
  const band = R["Limit price within"].split(" ")[0];
  const syms = m.rows[0][1].split(", ");
  const rows = {};
  const rule = (k, label, value, formula) => {
    const f = el("code", { cls: "md-f", text: formula });
    const n = el("div", { cls: "md-row", "data-hk": "row-" + k + " " + (opts.keys[k] || "") }, [el("span", { cls: "md-k", text: label }), el("span", { cls: "md-v" }, value), f, el("i", { cls: "md-ok" })]);
    n._f = f; n._formula = formula; rows[k] = n;
    return n;
  };
  const body = el("div", { cls: "md-rows" }, [
    rule("names", "Names it may trade", syms.map((s) => el("code", { cls: "md-chip", text: s })), "ticker ∈ the list"),
    rule("sides", "Buy or sell", [T(R["Buy or sell"])], "side ∈ { buy, sell }"),
    rule("per", "Largest single order", [T(R["Largest single order"])], "qty × trusted price ≤ " + R["Largest single order"]),
    rule("step", "A person approves above", [T(R["A person approves any order over"])], "value > " + R["A person approves any order over"] + " → a person decides"),
    rule("daily", "All agents, per day", [T(R["All agents together, per day"])], "today, all agents, + order ≤ " + R["All agents together, per day"]),
    rule("band", "Limit price", [T("within " + band + " of the market")], "| limit − trusted | ÷ trusted ≤ " + band),
    rule("exp", "Expires", [T(R["Expires"])], "now < expiry"),
  ]);
  const purpose = el("span", { cls: "md-purpose" });
  const sig = el("code", { cls: "md-sig", text: m.signature });
  const seal = el("div", { cls: "md-seal", "data-hk": "row-sig key" }, [
    el("i", { cls: "md-stamp" }),
    el("div", {}, [el("small", { text: "Signature, Ed25519, over the canonical body" }), sig]),
    el("div", {}, [el("small", { text: "Your public key" }), el("code", { text: m.key })]),
    el("p", { cls: "md-nokey" }, [el("i", { cls: "ic ic-key" }), T("The agent never holds this key")]),
  ]);
  rows.sig = seal; seal._f = null;
  const doc = el("div", { cls: "mdoc" }, [
    el("header", { cls: "md-head", "data-hk": "row-purpose" }, [el("span", { cls: "md-title" }, [el("b", { text: "Signed mandate" }), el("small", { text: LM.name })]), el("span", { cls: "md-pk", text: "Purpose" }), purpose]),
    body,
    el("p", { cls: "md-more" }, [el("b", { text: "Also available" }), T(" a daily cap per name, a maximum position, a maximum number of orders a day")]),
    seal,
  ]);
  return { doc, rows, purpose, sig, purposeText: LM.purpose, signature: m.signature };
}
function partMandate() {
  const fig = $("#envelope"), part = $("#p-mandate");
  if (!fig) return;
  const hl = highlighter(part);
  const M_ = mandateDoc({ keys: { names: "tok", sides: "tok", per: "chk", step: "chk", daily: "chk", band: "chk", exp: "chk" } });
  const ex = L().engine.examples[0], chk = ex.check;
  const probe = el("div", { cls: "md-probe" }, [el("small", { text: "One order, checked line by line" }), el("b", { text: ex.order }), el("span", { cls: "md-verdict" }, [pill("allow", "Allowed"), T(" Sent to the broker, with a signed receipt")])]);
  fig.classList.add("mandate");
  fig.append(M_.doc, probe);
  const mk = $$("#make li");
  const lightMk = (i) => mk.forEach((li, j) => { li.classList.toggle("lit", j === i); li.classList.toggle("done", j < i); });
  const order = ["names", "sides", "per", "step", "daily", "band", "exp"];
  const reset = () => {
    fig.classList.remove("drafted", "scan", "signing", "signed", "probing", "passed");
    order.forEach((k) => { const r = M_.rows[k]; r.classList.remove("in", "ok", "pass"); r._f.textContent = r._formula; });
    M_.purpose.textContent = ""; M_.sig.textContent = M_.signature; lightMk(-1); hl("");
  };
  const s1 = [
    [0, (i) => { lightMk(0); hl("row-purpose"); typeIn(M_.purpose, M_.purposeText, i); }],
    [2400, () => { lightMk(1); fig.classList.add("drafted"); }],
    ...order.map((k, j) => [2400 + j * 360, () => { M_.rows[k].classList.add("in"); hl("row-" + k); }]),
    [5600, () => { lightMk(2); fig.classList.add("scan"); hl("scan"); }],
    ...order.map((k, j) => [5900 + j * 280, () => M_.rows[k].classList.add("ok")]),
    [8400, (i) => { lightMk(3); fig.classList.add("signing"); hl("row-sig"); scramble(M_.sig, M_.signature, i); }],
    [10000, () => { fig.classList.add("signed"); hl("key"); }],
  ];
  const s3 = [
    [0, () => { lightMk(-1); fig.classList.add("probing"); hl("chk"); }],
    ...order.map((k, j) => [300 + j * 520, () => { const r = M_.rows[k]; r._f.textContent = chk[k]; r.classList.add("pass"); hl("row-" + k); }]),
    [300 + order.length * 520 + 200, () => { M_.rows.sig.classList.add("pass"); hl("row-sig"); }],
    [300 + order.length * 520 + 900, () => { fig.classList.add("passed"); hl("inside"); }],
  ];
  director($("#mandate-duo"), { viz: fig, film: "order", reset, segs: [
    { kind: "viz", ms: 11500, label: "The mandate, written and signed", steps: s1 },
    { kind: "film", t0: 0.2, t1: 19.8, label: "One order, slowed down", steps: [[0.2, () => { lightMk(-1); hl("inside"); }], [2.2, () => hl("tok")], [9.6, () => hl("chk")], [15.6, () => hl("row-sig key")]] },
    { kind: "viz", ms: 7600, label: "Checked line by line", steps: s3 },
  ] });
}

/* ---------------------------------------------------------------- part: trusted data, a month of notes, then the film, then what the order may use */
function partData() {
  const fig = $("#memory"), part = $("#p-data");
  if (!fig) return;
  const M_ = L().memory, hl = highlighter(part);
  const verdict = { sourced: ["allow", "Matches the filing"], drift: ["refuse", "Doesn't match"], undeclared: ["refuse", "No author"],
    vague: ["hold", "Nothing to check"], stale: ["refuse", "Price moved"], single: ["hold", "One source"] };
  const hk = { drift: "figure drift", undeclared: "nosrc ver", vague: "nosrc", stale: "price", single: "nosrc ver", sourced: "figure" };
  const rows = M_.entries.map((e, i) => el("li", { cls: "mm-e", "data-kind": e.kind, "data-hk": hk[e.kind], style: "--i:" + i }, [
    el("span", { cls: "mm-day", text: e.day }),
    el("span", { cls: "mm-body" }, [el("b", { text: e.text }), el("small", { text: e.from }), e.check ? el("em", { cls: "mm-chk", text: e.check }) : null]),
    el("span", { cls: "mm-v" }, [pill(verdict[e.kind][0], verdict[e.kind][1])]),
  ]));
  const order = el("div", { cls: "mm-order", "data-hk": "order" }, [
    el("span", { cls: "mm-ok" }, [el("small", { text: "The order it builds" }), el("b", { text: M_.order })]),
    el("span", { cls: "mm-uses", text: "relies on " + word(M_.entries.length - 1) + " notes" }),
    el("span", { cls: "mm-out" }, [pill("hold", "Sent back"), T(" Rebuilt only on what has a source")]),
  ]);
  fig.append(el("p", { cls: "mo-k", text: "One agent's notes over a month" }), el("ol", { cls: "mm-log" }, rows), order, el("p", { cls: "fig-note", text: "Illustration. The figure and the price are recorded cases." }));
  const reset = () => { fig.classList.remove("built", "checked", "cut"); hl(""); };
  director($("#data-duo"), { viz: fig, film: "order", reset, segs: [
    { kind: "viz", ms: 7200, label: "A month of notes", steps: [[0, () => { fig.classList.add("built"); hl("drift"); }], [3600, () => hl("nosrc")], [5600, () => hl("order")]] },
    { kind: "film", t0: 36, t1: 54, label: "Every claim, traced", steps: [[36, () => hl("figure")], [40, () => { fig.classList.add("checked"); hl("price"); }], [44, () => { fig.classList.add("cut"); hl("nosrc"); }], [46, () => hl("ver")]] },
    { kind: "viz", ms: 6400, label: "What the order may use", steps: [[0, () => { fig.classList.add("checked", "cut"); hl("figure"); }], [2600, () => hl("order")]] },
  ] });
}

/* ---------------------------------------------------------------- part: the final check, the film first, then wave after wave */
function partFinal() {
  const fig = $("#final"), part = $("#p-final");
  if (!fig) return;
  const F = L().final, hl = highlighter(part);
  const checks = el("ol", { cls: "fn-checks", "data-hk": "facts" }, F.checks.map((c) => el("li", {}, [el("i"), el("span", { text: c })])));
  const now = el("p", { cls: "fn-now" });
  const why = el("p", { cls: "fn-why" });
  const waves = F.waves.map((w, wi) => el("div", { cls: "fn-wave", "data-hk": "waves" }, [el("small", { text: "Wave " + word(wi + 1) }), el("ol", {}, w.map((o) => el("li", { text: o.o })))]));
  const broker = el("div", { cls: "fn-broker" }, [el("small", { text: "Your broker" }), el("ol", { cls: "fn-sent" })]);
  fig.append(el("div", { cls: "fn-waves" }, waves), el("div", { cls: "fn-gate", "data-hk": "facts" }, [el("p", { cls: "mo-k", text: "The final check" }), now, checks, why]), broker,
    el("p", { cls: "fig-note", text: F.note }));
  const sent = $(".fn-sent", broker), cl = $$("li", checks);
  const steps = [];
  let t = 300;
  F.waves.forEach((w, wi) => {
    steps.push([t, () => { waves.forEach((x, j) => x.classList.toggle("on", j === wi)); hl("waves"); }]);
    t += 450;
    w.forEach((o, oi) => {
      const li = $$("li", waves[wi])[oi];
      steps.push([t, () => { li.classList.add("at"); now.textContent = o.o; why.textContent = ""; fig.classList.remove("fail"); cl.forEach((c) => c.classList.remove("ok", "bad")); hl("facts"); }]);
      F.checks.forEach((c, ci) => { if (o.fail !== undefined && ci > o.fail) return; steps.push([t + 200 + ci * 160, () => cl[ci].classList.add(o.fail === ci ? "bad" : "ok")]); });
      t += 200 + (o.fail === undefined ? F.checks.length : o.fail + 1) * 160 + 240;
      steps.push([t, () => {
        li.classList.remove("at");
        if (o.fail === undefined) { li.classList.add("gone"); sent.append(el("li", { text: o.o })); }
        else { li.classList.add("back"); fig.classList.add("fail"); why.textContent = o.why; }
      }]);
      t += o.fail === undefined ? 260 : 1800;
    });
  });
  const reset = () => { sent.replaceChildren(); $$(".fn-wave li", fig).forEach((li) => li.classList.remove("at", "gone", "back")); waves.forEach((x) => x.classList.remove("on")); cl.forEach((c) => c.classList.remove("ok", "bad")); now.textContent = ""; why.textContent = ""; fig.classList.remove("fail"); hl(""); };
  director($("#final-duo"), { viz: fig, film: "fits", reset, segs: [
    { kind: "film", t0: 6.4, t1: 17.6, label: "At the broker, before any effect", steps: [[6.4, () => hl("facts")], [12, () => hl("waves")]] },
    { kind: "viz", ms: t + 1600, label: "Wave after wave", steps },
  ] });
}

/* ---------------------------------------------------------------- part: the swarm risk model, its engine on real orders, then the benchmark */
function partRisk() {
  const fig = $("#swarmfig"), part = $("#p-risk");
  if (!fig) return;
  const E = L().engine, how = L().how, hl = highlighter(part);
  const N = E.names.length, ix = Object.fromEntries(E.names.map((n, i) => [n, i]));
  const tape = el("ol", { cls: "eg-tape" });
  const ocard = el("div", { cls: "eg-card" }, [el("small", { text: "Order under review" }), el("b", { cls: "eg-o" }), el("span", { cls: "eg-meta" }), el("span", { cls: "eg-truth" })]);
  const cells = new Array(N);
  const groups = E.groups.map((gp) => el("div", { cls: "eg-grp" }, [el("small", { text: gp.name }), el("div", { cls: "eg-cells" }, gp.f.map((f) => { const c = el("i", { title: f }); cells[ix[f]] = c; return c; }))]));
  const whys = el("ol", { cls: "eg-why" });
  const units = el("ol", { cls: "eg-units" }, E.examples[0].units.map((u) => el("li", {}, [el("span", {}, [el("b", { text: u.name }), el("small", { text: u.family.replace("_", " ") })]), el("i", { cls: "eg-ubar" }, [el("em")]), el("code", { text: "π " + u.pi })])));
  const trees = el("div", { cls: "eg-trees" });
  const leaves = []; for (let i = 0; i < E.examples[0].leaves.length; i++) { const c = el("i", { style: "--k:" + i }); leaves.push(c); trees.append(c); }
  const pv = el("b"), rv = el("b", { cls: "eg-risk" });
  const needle = el("i", { cls: "eg-needle" });
  const gauge = el("div", { cls: "eg-gauge" }, [el("span", { cls: "eg-arc" }), el("em", { cls: "eg-th hold", style: "--a:" + Math.sqrt(E.hold).toFixed(4) }), el("em", { cls: "eg-th refuse", style: "--a:" + Math.sqrt(E.refuse).toFixed(4) }), needle]);
  const act = el("p", { cls: "eg-act" });
  const col = (cls, title, hk, kids) => el("div", { cls: "eg-col " + cls, "data-hk": hk }, [el("p", { cls: "eg-h" }, title), ...kids]);
  fig.classList.add("engine");
  fig.append(
    col("eg-in", [T("Every order, as it arrives")], "p1", [tape, ocard]),
    col("eg-sig", [el("b", { "data-f": "launch.risk.features" }), T(" signals, each against the run so far")], "p2", [...groups, whys]),
    col("eg-model", [el("b", { text: L().families.detectors.text }), T(" detectors and "), el("b", { text: E.n_trees.text }), T(" trees")], "p3", [units, el("small", { cls: "eg-sub", text: "Trees, each one's vote" }), trees]),
    col("eg-out", [T("One score, one decision")], "p4", [
      el("code", { cls: "eg-formula", text: "risk = 1 − (1 − p) × Π (1 − π·u)" }),
      el("p", { cls: "eg-kv" }, [el("span", { text: "p, from the trees" }), pv]),
      gauge, el("p", { cls: "eg-kv big" }, [el("span", { text: "Risk" }), rv]), act,
      el("p", { cls: "eg-lat" }, [T("Scored in "), el("b", { text: how.latency_p50.text }), T(", median")]),
    ]),
    el("p", { cls: "fig-note eg-note", text: E.note }),
  );
  bind(fig);
  const actName = { none: ["allow", "Allowed"], hold: ["hold", "Held for a person"], refuse: ["refuse", "Refused"] };
  function show(i) {
    const x = E.examples[i];
    tape.replaceChildren(...x.tape.map((t) => el("li", { text: t })), el("li", { cls: "now", text: x.order.split(" @ ")[0] }));
    $(".eg-o", ocard).textContent = x.order;
    $(".eg-meta", ocard).textContent = x.usd + " · agent " + x.agent + " · " + x.env + " mandate";
    $(".eg-truth", ocard).replaceChildren(el("small", { text: "Recorded as" }), el("b", { text: x.title }));
    x.pct.forEach((p, j) => { cells[j].style.setProperty("--p", p); cells[j].classList.remove("top"); });
    whys.replaceChildren(...x.top.slice(0, 3).map((t) => el("li", {}, [el("code", { text: t.f }), T(" " + t.why)])));
    $$("li", units).forEach((li, j) => { li.style.setProperty("--a", x.units[j].a); li.classList.toggle("fired", x.units[j].a > 0); });
    const mx = Math.max(...x.leaves.map(Math.abs)) || 1;
    leaves.forEach((c, j) => c.style.setProperty("--v", (x.leaves[j] / mx).toFixed(3)));
    pv.textContent = x.p_text; rv.textContent = x.risk_text;
    needle.style.setProperty("--a", Math.sqrt(Math.min(1, x.risk)).toFixed(4));
    act.replaceChildren(pill(actName[x.action][0], actName[x.action][1]));
    fig.dataset.act = x.action;
  }
  const ph = (n) => { fig.classList.remove("ph1", "ph2", "ph3", "ph4", "ph5", "ph6"); for (let k = 1; k <= n; k++) fig.classList.add("ph" + k); };
  const segs = E.examples.map((x, i) => ({ kind: "viz", ms: 7600, label: x.title, steps: [
    [0, () => { show(i); ph(1); hl("p1 spread"); }],
    [700, () => { ph(2); hl("p2"); }],
    [1900, () => { x.top.slice(0, 3).forEach((t) => cells[ix[t.f]] && cells[ix[t.f]].classList.add("top")); ph(3); }],
    [3000, () => { ph(4); hl("p3 trained"); }],
    [4400, () => { ph(5); hl("p4 speed"); }],
    [5600, () => { ph(6); hl(x.action === "none" ? "p4 honest" : "p4 whole precision"); }],
  ] }));
  director($("#risk-duo"), { viz: fig, reset: () => ph(0), segs });
  benchChart();
}
function benchChart() {
  const fig = $("#bench");
  if (!fig) return;
  const B = L().bench2;
  const legend = el("div", { cls: "bc-legend" }, [
    el("span", { cls: "k0", text: "A standard learned model, never shown this failure" }),
    el("span", { cls: "k1", text: "OrderGuard's model, never shown it" }),
    el("span", { cls: "k2", text: "OrderGuard's model, trained on it" }),
  ]);
  const bar = (cls, f) => el("div", { cls: "bc-b " + cls }, [el("i", { style: "--w:" + Math.max(0.006, f.value).toFixed(4) }), el("b", { text: f.text })]);
  const rows = B.rows.map((r, i) => el("li", { style: "--i:" + i }, [
    el("div", { cls: "bc-n" }, [el("b", { text: r.name }), el("small", { text: r.size })]),
    el("div", { cls: "bc-bars" }, [bar("k0", r.base), bar("k1", r.zero), bar("k2", r.full)]),
    el("div", { cls: "bc-gain" }, [el("b", { text: "+" + r.gain }), el("small", { text: "points over the standard model" })]),
  ]));
  fig.append(el("div", { cls: "bc-head" }, [el("p", { cls: "bc-t", text: "Swarm benchmark: share of harmful dollars stopped, on recorded runs the model never trained on" }), legend]),
    el("ol", { cls: "bc-rows" }, rows),
    el("p", { cls: "fig-note", text: "Per-order limits alone stop none of these: every harmful order in this benchmark passed every per-order limit." }));
  onView(fig, (on) => { if (!on || fig.classList.contains("in")) return; fig.classList.add("in"); $$(".bc-gain b", fig).forEach((b, i) => setTimeout(() => countUp(b), 300 + i * 120)); }, 0.25);
}

/* ---------------------------------------------------------------- hero: three central features, each shown working */
function heroFeatures() {
  const root = $("#feat");
  if (!root) return;
  const tabs = $$(".ft-tab", root), panels = $$(".ft-panel", root);
  const m = D.story.mandate, R = Object.fromEntries(m.rows), ex = L().engine.examples[0];
  /* one: signed mandate */
  const p1 = panels[0];
  const M_ = mandateDoc({ keys: {} });
  const probes = el("div", { cls: "hp-probes" }, [
    el("div", { cls: "hp-probe ok" }, [el("code", { text: ex.order }), el("span", { cls: "hp-res" }, [pill("allow", "Inside every rule")])]),
    el("div", { cls: "hp-probe no" }, [el("code", { text: "transfer_funds " + L().page.amount.text }), el("span", { cls: "hp-res" }, [pill("refuse", "Not in the mandate")])]),
  ]);
  p1.append(el("div", { cls: "hp-doc" }, [M_.doc]), probes);
  const order = ["names", "sides", "per", "step", "daily", "band", "exp"];
  const run1 = (i) => [
    [0, () => { p1.classList.remove("signing", "signed", "pr1", "pr2"); order.forEach((k) => M_.rows[k].classList.remove("in", "lit")); M_.purpose.textContent = ""; typeIn(M_.purpose, M_.purposeText, i); }],
    ...order.map((k, j) => [500 + j * 330, () => { order.forEach((q) => M_.rows[q].classList.remove("lit")); M_.rows[k].classList.add("in", "lit"); }]),
    [500 + order.length * 330, () => { order.forEach((q) => M_.rows[q].classList.remove("lit")); p1.classList.add("signing"); scramble(M_.sig, M_.signature, i); }],
    [4200, () => p1.classList.add("signed")],
    [5200, () => p1.classList.add("pr1")],
    [6900, () => p1.classList.add("pr2")],
  ];
  /* two: the sandbox */
  const p2 = panels[1];
  const P = L().price, F_ = L().figure;
  const calls = [
    { c: "get_quote AAPL", port: "data", r: "OrderGuard's own feed: " + P.truth, k: "ok" },
    { c: "get_filing AAPL 10-K", port: "data", r: "SEC filing: revenue " + F_.truth, k: "ok" },
    { c: "read_web analyst blog", port: "web", r: "page text passed through the screen, hidden line removed", k: "warn" },
    { c: "place_order " + ex.order.split(" @ ")[0], port: "broker", r: "signed, checked, sent by OrderGuard", k: "ok" },
    { c: "transfer_funds " + L().page.amount.text, port: "none", r: "no such door: not in the mandate, and no key", k: "no" },
  ];
  const log = el("ol", { cls: "sb-log" });
  const ports = { data: el("span", { cls: "sb-port p-data", text: "Trusted data" }), web: el("span", { cls: "sb-port p-web", text: "The open web, screened" }), broker: el("span", { cls: "sb-port p-broker", text: "Receiver" }) };
  p2.append(el("div", { cls: "sb" }, [
    el("div", { cls: "sb-out sb-src" }, [el("b", { text: "Sources the agent can't touch" }), el("small", { text: "OrderGuard's price feed · SEC filings · two news outlets" })]),
    el("div", { cls: "sb-box" }, [el("p", { cls: "sb-k" }, [el("i", { cls: "sb-lock" }), T("Sandboxed runtime")]), el("div", { cls: "sb-agent" }, [el("i", { cls: "ic ic-bot" }), el("span", { text: "Your agent" })]), el("div", { cls: "sb-ports" }, [el("small", { text: "Its only doors" }), ports.data, ports.web, ports.broker]), log]),
    el("div", { cls: "sb-out sb-broker" }, [el("b", { text: "Your broker" }), el("small", { text: "The key lives in OrderGuard's vault, never with the agent" }), el("i", { cls: "sb-vault" })]),
  ]));
  const run2 = () => [[0, () => { log.replaceChildren(); Object.values(ports).forEach((x) => x.classList.remove("on", "no")); p2.classList.remove("blocked"); }],
    ...calls.flatMap((c, j) => [
      [400 + j * 1500, () => { Object.values(ports).forEach((x) => x.classList.remove("on")); log.append(el("li", { cls: "sb-c" }, [el("code", { text: "› " + c.c })])); if (ports[c.port]) ports[c.port].classList.add("on"); else p2.classList.add("blocked"); }],
      [400 + j * 1500 + 700, () => log.append(el("li", { cls: "sb-r " + c.k, text: c.r }))],
    ])];
  /* three: the swarm */
  const p3 = panels[2];
  const cv = el("canvas", { cls: "sw3" });
  const H = L().herd, risk = L().risk;
  p3.append(cv, el("div", { cls: "sw3-read" }, [
    el("p", {}, [el("b", { text: risk.corpus.text }), T(" labelled orders, self-trained")]),
    el("p", {}, [el("b", { text: risk.features.text }), T(" signals, "), el("b", { text: L().families.detectors.text }), T(" detectors, "), el("b", { text: L().engine.n_trees.text }), T(" trees")]),
    el("p", {}, [el("b", { text: L().how.latency_p50.text }), T(" per order")]),
    el("p", { cls: "sw3-v" }, [pill("hold", "Held for a person"), T(" " + word(H.agents.value, true) + " agents, one position: " + H.combined.text)]),
  ]));
  const cx = cv.getContext("2d");
  let seed = 5; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const dots = []; for (let i = 0; i < 420; i++) dots.push({ a: rnd() * 6.283, r: 0.28 + rnd() * 0.7, s: (rnd() - 0.5) * 0.0016, p: rnd() * 6.28 });
  const ring = [11, 97, 160, 233, 301].map((i) => dots[i]);
  let swOn = false, pulses = [], held = 0, t0s = 0;
  function paintSw(now) {
    if (!swOn) return;
    const w = cv.clientWidth, h = cv.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, h);
    const ox = w * 0.5, oy = h * 0.5, R0 = Math.min(w, h) * 0.46, t = (now - t0s) / 1000;
    const grey = css("--dot"), vio = css("--risk"), acc = css("--accent");
    cx.strokeStyle = vio; cx.globalAlpha = 0.25 + 0.15 * Math.sin(t * 2); cx.lineWidth = 1.2;
    cx.beginPath(); cx.arc(ox, oy, 26, 0, 6.283); cx.stroke();
    cx.globalAlpha = 1; cx.fillStyle = vio; cx.beginPath(); cx.arc(ox, oy, 6, 0, 6.283); cx.fill();
    if (rnd() < 0.5) { const d = dots[(rnd() * dots.length) | 0]; pulses.push({ d, k: 0 }); }
    for (const q of pulses) q.k += 0.025;
    pulses = pulses.filter((q) => q.k < 1);
    const pos = (d) => { const a = d.a + t * d.s * 40; return [ox + Math.cos(a) * d.r * R0, oy + Math.sin(a) * d.r * R0 * 0.62]; };
    cx.fillStyle = acc;
    for (const q of pulses) { const [x, y] = pos(q.d); cx.globalAlpha = 0.6 * (1 - q.k); cx.beginPath(); cx.arc(x + (ox - x) * q.k, y + (oy - y) * q.k, 1.6, 0, 6.283); cx.fill(); }
    const hot = held > 0;
    if (hot) {
      const pts = ring.map(pos);
      cx.strokeStyle = vio; cx.globalAlpha = Math.min(1, held) * 0.55;
      for (const [x, y] of pts) { cx.beginPath(); cx.moveTo(ox, oy); cx.lineTo(x, y); cx.stroke(); }
      cx.globalAlpha = Math.min(1, held) * 0.12; cx.fillStyle = vio; cx.beginPath();
      const mx = pts.reduce((a, p) => a + p[0], 0) / 5, my = pts.reduce((a, p) => a + p[1], 0) / 5;
      pts.sort((a, b) => Math.atan2(a[1] - my, a[0] - mx) - Math.atan2(b[1] - my, b[0] - mx)).forEach((p, i) => (i ? cx.lineTo(p[0], p[1]) : cx.moveTo(p[0], p[1])));
      cx.closePath(); cx.fill();
    }
    for (const d of dots) { const [x, y] = pos(d), on = hot && ring.includes(d); cx.globalAlpha = 1; cx.fillStyle = on ? vio : grey; cx.beginPath(); cx.arc(x, y, on ? 3.6 : 1.6, 0, 6.283); cx.fill(); }
    if (held > 0 && held < 1) held = Math.min(1, held + 0.03);
    requestAnimationFrame(paintSw);
  }
  const run3 = () => [[0, () => { held = 0; p3.classList.remove("held"); if (!swOn) { swOn = true; t0s = performance.now(); requestAnimationFrame(paintSw); } }], [3200, () => { held = 0.01; }], [4600, () => p3.classList.add("held")]];
  /* the rotation */
  const runs = [run1, run2, run3], DUR = [9200, 9000, 8200];
  let cur = -1, timers = [], live = false, user = false;
  function go(i, instant) {
    timers.forEach(clearTimeout); timers = [];
    if (cur === 2 && i !== 2) swOn = false;
    cur = i;
    tabs.forEach((t, j) => { t.setAttribute("aria-selected", String(j === i)); t.classList.toggle("on", j === i); t.style.setProperty("--d", DUR[j] + "ms"); });
    panels.forEach((p, j) => p.classList.toggle("on", j === i));
    root.dataset.f = String(i);
    for (const [ms, fn] of runs[i](instant)) { if (instant) fn(true); else timers.push(setTimeout(fn, ms)); }
    if (!instant && live && !user) timers.push(setTimeout(() => go((i + 1) % runs.length), DUR[i]));
  }
  tabs.forEach((t, i) => t.addEventListener("click", () => { user = false; go(i); }));
  root.addEventListener("pointerenter", () => root.classList.add("hov"));
  root.addEventListener("pointerleave", () => root.classList.remove("hov"));
  if (reduce.matches) { go(0, true); return; }
  new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting && !live) { live = true; go(cur < 0 ? 0 : cur); }
    else if (!e.isIntersecting && live) { live = false; timers.forEach(clearTimeout); timers = []; swOn = false; }
  }), { threshold: 0.3 }).observe(root);
}

/* ---------------------------------------------------------------- where you are: a rail down the left, with an order travelling along it */
function chapterRail() {
  const rail = $("#rail");
  if (!rail) return;
  const parts = [
    { id: "top", label: "OrderGuard" },
    { id: "story", label: "The problem" },
    { id: "system", label: "How it works", subs: [["p-mandate", "Signed mandate"], ["p-data", "Trusted data"], ["p-risk", "Swarm risk model"], ["p-adapter", "Decision adapter"], ["p-super", "Supervision"], ["p-final", "Final check"], ["p-queue", "Review queue"], ["p-ledger", "Ledger"]] },
    { id: "together", label: "Together" },
    { id: "scale", label: "At scale" },
    { id: "start", label: "Developers" },
  ];
  const line = el("span", { cls: "rl-line" }, [el("i", { cls: "rl-fill" })]);
  const token = el("span", { cls: "rl-token" }, [el("i"), el("b")]);
  const list = el("ol", { cls: "rl-list" });
  const nodes = [];
  parts.forEach((p, i) => {
    const a = el("a", { href: "#" + p.id, cls: "rl-a" }, [el("span", { cls: "rl-n", text: String(i + 1).padStart(2, "0") }), el("span", { cls: "rl-t", text: p.label })]);
    const li = el("li", { cls: "rl-ch" }, [a]);
    nodes.push({ id: p.id, li, label: p.label });
    if (p.subs) {
      const sub = el("ol", { cls: "rl-sub" }, p.subs.map(([id, t]) => { const s = el("li", {}, [el("a", { href: "#" + id, text: t })]); nodes.push({ id, li: s, label: t, sub: true, parent: li }); return s; }));
      li.append(sub);
    }
    list.append(li);
  });
  rail.append(line, token, list);
  const targets = nodes.map((n) => ({ n, el: n.id === "top" ? $(".x-hero") : document.getElementById(n.id) })).filter((x) => x.el);
  let ticking = false;
  function update() {
    ticking = false;
    const y = scrollY + innerHeight * 0.38, max = document.documentElement.scrollHeight - innerHeight;
    let on = targets[0], onSub = null;
    for (const t of targets) { const top = t.el.getBoundingClientRect().top + scrollY; if (top <= y) { if (t.n.sub) onSub = t; else { on = t; onSub = null; } } }
    if (onSub && onSub.n.parent !== on.n.li) onSub = null;
    nodes.forEach((n) => { n.li.classList.toggle("on", n === on.n || n === (onSub && onSub.n)); });
    rail.classList.toggle("in-sys", on.n.id === "system");
    rail.classList.toggle("in-story", on.n.id === "story");
    const f = Math.max(0, Math.min(1, scrollY / (max || 1)));
    line.firstChild.style.transform = "scaleY(" + f.toFixed(4) + ")";
    const a = (onSub ? onSub.n.li : on.n.li).getBoundingClientRect(), r = rail.getBoundingClientRect();
    token.style.transform = "translateY(" + (a.top - r.top + a.height / 2).toFixed(1) + "px)";
    $("b", token).textContent = onSub ? onSub.n.label : on.n.label;
    rail.classList.toggle("show", scrollY > innerHeight * 0.5);
  }
  addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
  addEventListener("resize", update);
  update();
}

function contagionCard(stage) {
  const C = L().contagion, cols = 6, src = C.tiles.indexOf(C.name);
  const dist = (i) => Math.hypot((i % cols) - (src % cols), Math.floor(i / cols) - Math.floor(src / cols));
  const tiles = C.tiles.map((t, i) => {
    const held = C.held.includes(t), me = t === C.name;
    return el("div", { cls: "cg-t" + (held ? " held" : "") + (me ? " src" : ""), style: "--d:" + (0.5 + dist(i) * 0.42).toFixed(2) + "s" },
      [el("b", { text: t }), el("small", { text: me ? "bought" : held ? "held" : dist(i) % 2 < 1 ? "forced sell" : "rule fired" })]);
  });
  const spike = S("svg", { viewBox: "0 0 120 36", cls: "cg-spark", "aria-hidden": "true" }, [S("path", { d: "M0 30 L20 29 L36 31 L52 28 L66 29 L78 26 L88 10 L96 4 L104 8 L120 3" })]);
  const film = el("button", { type: "button", cls: "link cg-film", text: "Watch this scene in the film" });
  film.addEventListener("click", () => {
    const f = D.layers.clips.problem, dlg = $("#film-dlg"), v = $("#film-v");
    v.poster = "media/og-" + f[0] + ".jpg"; v.src = "media/og-" + f[0] + ".mp4#t=" + f[1]; dlg.showModal(); v.play().catch(() => {});
  });
  const foot = [
    [T("You asked for watching, not buying.")],
    [T("A loose link and a price jump read as a signal. "), el("b", { text: "Nobody asked for this order." })],
    [T("Each forced sale trips the next rule, and the damage spreads. "), el("small", { cls: "cg-note", text: "Illustration, fictional tickers." }), film],
  ][stage];
  return el("div", { cls: "mo mo-cg cg-s" + stage }, [
    el("div", { cls: "cg-head" }, [
      el("p", { cls: "as-me", text: C.ask }),
      el("div", { cls: "cg-name" }, [el("b", { text: C.name }), el("small", { text: C.name_note }), spike]),
      el("div", { cls: "cg-order" }, [el("code", { text: C.order }), el("span", { cls: "cg-stamp", text: "Not what you asked for" })]),
    ]),
    el("p", { cls: "mo-k", text: "The portfolio" }),
    el("div", { cls: "cg-grid" }, tiles),
    el("p", { cls: "mo-foot" }, foot),
  ]);
}

/* ---------------------------------------------------------------- part: the decision adapter, purpose against the draft */
function partAdapter() {
  const fig = $("#adapter"), part = $("#p-adapter");
  if (!fig) return;
  const A = L().adapter2, A3 = L().adapter3, hl = highlighter(part);
  const bad = { over_broad: ["names", "per", "daily"], purpose_mismatched: ["sides"], sneaky: ["step"], appropriate: [] };
  const tabs = el("div", { cls: "ad-tabs", role: "tablist" }, [
    el("button", { type: "button", role: "tab", "data-st": "draft", text: "Before it gets authority" }),
    el("button", { type: "button", role: "tab", "data-st": "run", text: "While it runs" }),
  ]);
  const dots = el("ol", { cls: "ad-dots" });
  const qk = el("p", { cls: "mo-k" }), q = el("p", { cls: "ad-q" });
  const ak = el("p", { cls: "mo-k" }), tbl = el("dl", { cls: "ad-tbl" });
  const needle = el("i", { cls: "ad-needle" }), score = el("b", { cls: "ad-score" });
  const line = el("em", { cls: "ad-line" }, [el("small")]);
  const meter = el("div", { cls: "ad-meter" }, [el("span", { cls: "ad-track" }, [line, needle]), score]);
  const out = el("p", { cls: "ad-out" });
  fig.append(el("div", { cls: "ad-head" }, [tabs, dots]),
    el("div", { cls: "ad-card ad-purpose", "data-hk": "asked" }, [qk, q]),
    el("div", { cls: "ad-card ad-draft", "data-hk": "asks" }, [ak, tbl]), meter, out);
  const items = A.examples.map((x) => ({ st: "draft", x })).concat(A3.scope_ex.map((x) => ({ st: "run", x })));
  dots.replaceChildren(...items.map(() => el("li")));
  function render(i) {
    const it = items[i], x = it.x;
    $$("li", dots).forEach((d, j) => d.classList.toggle("on", j === i));
    $$("button", tabs).forEach((b) => b.setAttribute("aria-selected", String(b.dataset.st === it.st)));
    fig.dataset.st = it.st;
    fig.classList.remove("scored", "judged", "flagged");
    needle.style.left = 0; score.textContent = ""; out.replaceChildren();
    if (it.st === "draft") {
      qk.textContent = "The agent was asked to"; q.textContent = "“" + x.purpose + "”";
      ak.textContent = "It asks for";
      const rowsD = [["names", "Names", x.symbols ? x.symbols.join(", ") : x.n_symbols + " names"], ["sides", "Buy or sell", x.sides], ["per", "Per order", x.per], ["daily", "Per day", x.daily], ["step", "A person approves above", x.step]];
      tbl.replaceChildren(...rowsD.map(([k, a, b]) => el("div", { "data-f": k }, [el("dt", { text: a }), el("dd", { text: b })])));
      line.style.left = (A.threshold.value * 100) + "%"; line.firstChild.textContent = "Flag line " + A.threshold.text;
    } else {
      qk.textContent = "The agent says it is"; q.textContent = "“" + x.intent + "”";
      ak.textContent = "It sends";
      tbl.replaceChildren(el("div", { "data-f": "order" }, [el("dt", { text: "Order, inside the mandate" }), el("dd", { text: x.order })]));
      line.style.left = (A3.warn_at.value * 100) + "%"; line.firstChild.textContent = "Warn line " + A3.warn_at.text;
    }
  }
  function judge(i) {
    const it = items[i], x = it.x;
    if (it.st === "draft") {
      for (const k of bad[x.category]) { const r = $('[data-f="' + k + '"]', tbl); if (r) r.classList.add("bad"); }
      fig.classList.toggle("flagged", x.flagged);
      out.replaceChildren(x.flagged ? pill("hold", "Flagged") : pill("allow", "Fits"), T(" It " + x.why + "."));
    } else {
      if (x.held) { const r = $('[data-f="order"]', tbl); if (r) r.classList.add("bad"); }
      fig.classList.toggle("flagged", x.held);
      out.replaceChildren(x.held ? pill("hold", "Held for a person") : pill("allow", "Matches"), T(x.held ? " The order isn't what it said it was doing." : " The order is what it said it was doing."));
    }
    fig.classList.add("judged");
  }
  function scoreOf(i) { const x = items[i].x; return items[i].st === "draft" ? x.score : x.mismatch; }
  const STEP = 5200, steps = [];
  items.forEach((it, i) => {
    const t = i * STEP;
    steps.push([t, () => { render(i); hl(it.st === "draft" ? "asked code" : "runs code"); }], [t + 1200, () => hl(it.st === "draft" ? "asks params model" : "runs params model")],
      [t + 2100, () => { hl("scope speed"); fig.classList.add("scored"); const s = scoreOf(i); needle.style.left = (s.value * 100).toFixed(1) + "%"; score.textContent = s.text; }],
      [t + 3000, () => { judge(i); hl(it.st === "draft" ? "asks rank auth" : "runs held auth"); }]);
  });
  loopOnView(fig, { reset: () => render(0), steps, end: items.length * STEP,
    still: () => { render(1); fig.classList.add("scored"); const s = scoreOf(1); needle.style.left = (s.value * 100) + "%"; score.textContent = s.text; judge(1); } });
}

/* ---------------------------------------------------------------- part: supervision, the spiral and the flattened line */
function partSuper() {
  const fig = $("#spiral"), part = $("#p-super");
  if (!fig) return;
  const S_ = L().spiral, hl = highlighter(part);
  const svg = S("svg", { viewBox: "0 0 600 260", cls: "su-svg", preserveAspectRatio: "none", "aria-hidden": "true" });
  const up = S("path", { cls: "su-up", "data-hk": "crowd", d: "M0 200 C80 196 130 186 190 168 S280 110 340 72 S420 18 460 22 S510 120 540 190 S580 238 600 244" });
  const flat = S("path", { cls: "su-flat", "data-hk": "slow", d: "M0 200 C90 196 150 190 220 182 S330 172 420 168 S540 164 600 162" });
  const arrows = S("g", { cls: "su-buys" });
  for (let i = 0; i < 9; i++) arrows.append(S("path", { d: "M" + (150 + i * 34) + "," + (180 - i * 16) + " l0,-14 m-5,5 l5,-5 l5,5", style: "--i:" + i }));
  svg.append(arrows, up, flat);
  fig.append(svg, el("div", { cls: "su-legend" }, [el("span", { cls: "k-up", text: "Without OrderGuard" }), el("span", { cls: "k-flat", text: "With OrderGuard" })]));
  const max = Math.max(...[S_.dd_open, S_.dd_full].map((s) => money(s)));
  const row = (k, a, b) => el("div", { cls: "su-row" }, [el("span", { text: k }),
    el("i", { cls: "bad", style: "width:" + (money(a) / max * 100).toFixed(1) + "%" }), el("b", { cls: "bad", text: a }),
    el("i", { cls: "good", style: "width:" + Math.max(1, money(b) / max * 100).toFixed(1) + "%" }), el("b", { cls: "good", text: b })]);
  $("#super-stat").append(row("Worst drawdown", S_.dd_open, S_.dd_full), el("small", { text: "A crowded-market stress test with " + S_.agents.text + " agents, the mean of " + word(S_.seeds.value) + " runs." }));
  loopOnView(fig, {
    reset: () => { fig.classList.remove("crowd", "slow"); hl(""); },
    steps: [[500, () => { fig.classList.add("crowd"); hl("crowd"); }], [4200, () => { fig.classList.add("slow"); hl("slow"); }]],
    end: 9500,
    still: () => fig.classList.add("crowd", "slow"),
  });
}


/* ---------------------------------------------------------------- part: the review queue, sorted by money at stake */
function partQueue() {
  const fig = $("#queue"), part = $("#p-queue");
  if (!fig) return;
  const Q = L().queue, hl = highlighter(part);
  const items = L().held.map((h) => el("li", { cls: "q-it" + (h.v === L().herd.combined.value ? " top" : "") }, [el("span", { text: h.what }), el("small", { text: h.why }), el("b", { text: h.usd })]));
  const list = el("ol", { cls: "q-list", "data-hk": "rank" }, items);
  const person = el("div", { cls: "q-person", "data-hk": "time" }, [el("i", { cls: "ic ic-person" }), el("span", { text: "A person reviews from the top" })]);
  fig.append(person, list);
  const max = Q.fifo.value;
  $("#queue-stat").append(
    el("span", { cls: "q-race" }, [el("i", { cls: "good", style: "width:" + (Q.model.value / max * 100).toFixed(1) + "%" }), el("i", { cls: "bad" })]),
  );
  const sorted = [...items].sort((a, b) => money(b.lastChild.textContent) - money(a.lastChild.textContent));
  function place(order, animate) {
    const first = items.map((n) => n.getBoundingClientRect().top);
    list.replaceChildren(...order);
    if (!animate) return;
    items.forEach((n, i) => { const d = first[i] - n.getBoundingClientRect().top; if (d) n.animate([{ transform: "translateY(" + d + "px)" }, { transform: "none" }], { duration: 700, easing: "cubic-bezier(.22,1,.36,1)" }); });
  }
  loopOnView(fig, {
    reset: () => { place(items, false); fig.classList.remove("sorted", "review"); hl("rank"); },
    steps: [[1600, () => { place(sorted, true); fig.classList.add("sorted"); }], [3200, () => { fig.classList.add("review"); hl("time"); }]],
    end: 8500,
    still: () => { place(sorted, false); fig.classList.add("sorted", "review"); },
  });
}

/* ---------------------------------------------------------------- part: the ledger, sealed and then tampered with */
function partLedger() {
  const fig = $("#ledger"), part = $("#p-ledger");
  if (!fig) return;
  const hl = highlighter(part);
  const kind = (d) => (/^Allow/.test(d) ? "allow" : /^Held/.test(d) ? "hold" : "refuse");
  const blocks = D.flows.ledger.map((b) => {
    const order = el("b", { cls: "lg-order", text: b.order });
    const seal = el("code", { cls: "lg-seal", text: b.seal_short });
    const n = el("li", { cls: "lg-b", "data-hk": "seal" }, [el("code", { cls: "lg-prev", text: "after " + b.prev_short }), order, pill(kind(b.decision), b.decision), el("small", { text: b.reason }), seal]);
    n._o = b.order; n._s = b.seal_short; n._order = order; n._seal = seal;
    return n;
  });
  const chain = el("ol", { cls: "lg-chain" }, blocks);
  const verdict = el("p", { cls: "lg-v" }, [pill("refuse", "Chain broken"), T(" after the edited entry: the edit shows")]);
  fig.append(chain, verdict);
  const target = blocks[1];
  loopOnView(fig, {
    reset: () => { fig.classList.remove("sealing", "edited"); blocks.forEach((b) => { b.classList.remove("in", "broken"); b._order.textContent = b._o; b._seal.textContent = b._s; }); hl("seal"); },
    steps: [
      ...blocks.map((b, i) => [400 + i * 700, () => b.classList.add("in")]),
      [400 + blocks.length * 700 + 900, () => { hl("edit"); target._order.textContent = target._o.replace(/BUY (\S+)/, (m, q) => "BUY " + q + q.slice(-1)); fig.classList.add("edited"); }],
      [400 + blocks.length * 700 + 1700, () => { target._seal.textContent = target._s.split("").reverse().join(""); blocks.slice(1).forEach((b) => b.classList.add("broken")); }],
    ],
    end: 400 + blocks.length * 700 + 6000,
    still: () => blocks.forEach((b) => b.classList.add("in")),
  });
}

/* ---------------------------------------------------------------- how it comes together: rings, with the film trading places */
function together() {
  const rings = $("#tg-rings"), stage = $("#tg-stage");
  if (!rings) return;
  const v = $("#tg-video"), c = D.layers.clips.connect;
  const svg = S("svg", { viewBox: "0 0 640 430", cls: "tg-svg", role: "img", "aria-label": "Plain code at the centre: the signed mandate, the receiver and the ledger. Checks around it: input screen, trusted data, fact check. Models around those: the swarm risk model, the decision adapter, supervision." });
  const C0 = [320, 210];
  const ringDef = [
    { r: 186, k: "Models: can only make it stricter", cls: "r3", items: ["Swarm risk model", "Decision adapter", "Supervision"], at: [-2.4, -0.6, 2.0] },
    { r: 128, k: "Checks", cls: "r2", items: ["Input screen", "Trusted data", "Fact check"], at: [-1.5708, 0.75, 2.75] },
    { r: 66, k: "Plain code decides", cls: "r1", items: [], at: [] },
  ];
  svg.append(S("path", { cls: "tg-flow", d: "M10 210 L630 210" }));
  for (const R of ringDef) {
    svg.append(S("circle", { cx: C0[0], cy: C0[1], r: R.r, cls: "tg-ring " + R.cls }));
    R.items.forEach((t, i) => {
      const a = R.at[i], x = C0[0] + Math.cos(a) * R.r, y = C0[1] + Math.sin(a) * R.r;
      svg.append(S("g", { cls: "tg-item " + R.cls, style: "--i:" + i }, [S("rect", { x: x - t.length * 3.7 - 10, y: y - 13, width: t.length * 7.4 + 20, height: 26, rx: 13 }), S("text", { x, y: y + 4, "text-anchor": "middle", text: t })]));
    });
    if (R.cls !== "r1") svg.append(S("text", { x: C0[0], y: C0[1] + R.r + 18, "text-anchor": "middle", cls: "tg-k " + R.cls, text: R.k }));
  }
  ["Signed mandate", "Receiver", "Ledger"].forEach((t, i) => svg.append(S("text", { x: C0[0], y: C0[1] - 14 + i * 18, "text-anchor": "middle", cls: "tg-core", text: t })));
  svg.append(S("text", { x: 14, y: 196, cls: "tg-end", text: "Agents" }), S("text", { x: 626, y: 196, "text-anchor": "end", cls: "tg-end", text: "Broker" }));
  rings.append(svg, el("p", { cls: "tg-rule" }, [T("Every model can stop an order. "), el("b", { text: "Only what you signed can allow one." })]));
  v.poster = "media/og-" + c[0] + ".jpg";
  const lead = (k) => { stage.dataset.lead = k; };
  lead("rings");
  const playFilm = () => { lead("film"); if (!v.src) v.src = "media/og-" + c[0] + ".mp4#t=" + c[1] + "," + c[2]; else v.currentTime = c[1]; v.play().catch(() => lead("rings")); };
  v.addEventListener("timeupdate", () => { if (v.currentTime >= c[2] - 0.2) { v.pause(); lead("rings"); } });
  v.addEventListener("ended", () => lead("rings"));
  $("#tg-film").addEventListener("click", () => { if (stage.dataset.lead === "rings") playFilm(); });
  if (reduce.matches) { stage.classList.add("drawn"); return; }
  let started = false;
  new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting && !started) { started = true; stage.classList.add("drawn"); setTimeout(playFilm, 3200); }
    if (!e.isIntersecting) v.pause();
  }), { threshold: 0.45 }).observe(stage);
}

function sequencer(o) {
  const segs = o.segs, play = o.play, root = o.root, steps = o.steps, ctl = segs.parentNode;
  let cur = -1, timer = 0, playing = false, done = false, t0 = 0, remain = 0, userPaused = false, drag = false;
  steps.forEach((s, i) => {
    const b = el("button", { type: "button", "aria-label": "Step " + (i + 1) + ": " + (s.label || "") }, [el("i")]);
    b.addEventListener("click", (e) => { if (e.detail === 0) jump(i); });
    segs.append(el("li", {}, [b]));
  });
  const lis = Array.from(segs.children);
  const count = el("span", { cls: "st-count", "aria-hidden": "true" });
  const tip = el("span", { cls: "seg-tip", "aria-hidden": "true" });
  ctl.append(count, tip);
  function go(i) {
    cur = i; remain = 0;
    lis.forEach((li, j) => { li.classList.toggle("past", j < i); li.classList.remove("now"); });
    void segs.offsetWidth;
    lis[i].style.setProperty("--d", steps[i].ms + "ms");
    lis[i].classList.add("now");
    count.textContent = (i + 1) + " / " + steps.length;
    o.show(i);
  }
  function schedule() {
    clearTimeout(timer);
    if (!playing) return;
    t0 = performance.now();
    timer = setTimeout(() => {
      if (cur < steps.length - 1) { go(cur + 1); schedule(); }
      else { playing = false; done = true; root.classList.add("done"); play.setAttribute("aria-label", "Replay"); if (o.onPlay) o.onPlay(false); }
    }, remain || steps[cur].ms);
    remain = 0;
  }
  function start() {
    if (done) { done = false; root.classList.remove("done"); go(0); }
    if (cur < 0) go(0);
    playing = true; root.classList.remove("paused"); play.setAttribute("aria-label", "Pause"); schedule();
    if (o.onPlay) o.onPlay(true);
  }
  function pause() {
    if (!playing) return;
    playing = false; clearTimeout(timer);
    remain = Math.max(250, steps[cur].ms - (performance.now() - t0));
    root.classList.add("paused"); play.setAttribute("aria-label", "Play");
    if (o.onPlay) o.onPlay(false);
  }
  function jump(i) {
    i = Math.max(0, Math.min(steps.length - 1, i));
    done = false; root.classList.remove("done");
    go(i); userPaused = false; start();
  }
  function tipAt(i) {
    const r = lis[i].getBoundingClientRect(), c = ctl.getBoundingClientRect();
    tip.textContent = steps[i].label || "";
    const half = Math.min(150, c.width / 2);
    tip.style.left = Math.max(half, Math.min(c.width - half, r.left + r.width / 2 - c.left)) + "px";
    tip.classList.add("on");
  }
  const idxAt = (x) => { for (let i = 0; i < lis.length; i++) if (x <= lis[i].getBoundingClientRect().right + 2) return i; return lis.length - 1; };
  segs.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    drag = true; segs.setPointerCapture(e.pointerId); segs.classList.add("drag");
    clearTimeout(timer); root.classList.add("paused");
    const i = idxAt(e.clientX); go(i); tipAt(i);
    e.preventDefault();
  });
  segs.addEventListener("pointermove", (e) => {
    const i = idxAt(e.clientX);
    if (drag && i !== cur) go(i);
    tipAt(i);
  });
  const release = () => {
    if (!drag) return;
    drag = false; segs.classList.remove("drag"); tip.classList.remove("on");
    done = false; root.classList.remove("done"); userPaused = false; playing = false; start();
  };
  segs.addEventListener("pointerup", release);
  segs.addEventListener("pointercancel", release);
  segs.addEventListener("pointerleave", () => { if (!drag) tip.classList.remove("on"); });
  segs.addEventListener("keydown", (e) => {
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (d) { e.preventDefault(); jump(cur + d); const b = lis[cur].querySelector("button"); if (b) b.focus(); }
  });
  play.addEventListener("click", () => { if (playing) { userPaused = true; pause(); } else { userPaused = false; start(); } });
  go(0);
  if (reduce.matches) { root.classList.add("paused"); play.setAttribute("aria-label", "Play"); return; }
  root.classList.add("paused");
  new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting && !playing && !userPaused && !done) start();
    else if (!e.isIntersecting && playing) pause();
  }), { threshold: 0.55 }).observe(root);
}

function scaleZoom() {
  const root = $("#zoom");
  if (!root) return;
  const cv = $("#zm-cv"), panel = $("#zm-panel"), ruler = $("#zm-ruler"), cx = cv.getContext("2d");
  const run = D.story.run, sc = D.story.scene, A = L().attacks, sim = D.sim.facts;
  const grid2 = (n, k, cls) => { const g = el("div", { cls: "sc-sq " + cls }); for (let i = 0; i < n; i++) g.append(el("i", { cls: i < k ? "hit" : "" })); return g; };
  const bar = (cls, f, text) => el("div", { cls: "zb " + cls }, [el("i", { style: "width:" + (f * 100).toFixed(1) + "%" }), el("span", { text })]);
  const levels = [
    { k: "One agent", label: "One agent", head: "A live AI agent, attacked " + A.n.text + " times", big: A.with.text, sub: "attacks succeeded with OrderGuard, against " + A.without.text + " without",
      fig: () => el("div", { cls: "sc-pair" }, [el("div", {}, [el("small", { text: "Without OrderGuard" }), grid2(A.n.value, A.without.value, "bad")]), el("div", {}, [el("small", { text: "With OrderGuard" }), grid2(A.n.value, A.with.value, "good")])]),
      foot: "Each square is one attempt, hidden in a filing, a web page, a tool result or a price feed." },
    { k: "A thousand agents", label: "A thousand", head: sc.total_agents.text + " agents, " + word(run.days.value) + " trading days, recorded", big: run.after.text, sub: "of harmful orders reached the market with OrderGuard",
      fig: () => el("div", { cls: "zbars" }, [bar("all", 1, run.attempted.text + " of harmful orders sent"), bar("pass", run.passed.value / run.attempted.value, run.passed.text + " of it broke no per-order limit"), bar("after", 0.006, run.after.text + " got through OrderGuard")]),
      foot: "The cost: about one honest order in " + run.one_in.text + " waited for a person." },
    { k: "A million agents", label: "A million", head: sim.million_agents.text + " agents, " + word(sim.million_seeds.value) + " simulated runs", big: sim.million_breaches.text, sub: "limits broken, across " + sim.million_orders_total.text + " orders checked",
      fig: () => el("p", { cls: "zm-note", text: "Each dot in the background is a hundred agents." }), foot: "A simulated market at full scale, every order through the same checks." },
  ];
  levels.forEach((l) => ruler.append(el("li", {}, [el("i"), el("span", { text: l.label })])));
  /* the field: the focus agent, the recorded thousand around it, the million around those */
  let seed = 5; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const k1 = []; for (let i = 0; i < sc.total_agents.value; i++) { const a = rnd() * 6.283, r = Math.sqrt(rnd()); k1.push([Math.cos(a) * r, Math.sin(a) * r, rnd() < 0.05]); }
  /* world units: the recorded thousand fill a disc of radius one; the million fill a square thirty times wider; each drawn dot is a hundred agents */
  const nM = Math.round(sim.million_agents.value / 100), FAR = 30, k3 = [];
  while (k3.length < nM) { const a = rnd() * 6.283, r = FAR * Math.sqrt(rnd()); if (r > 1.2) k3.push([Math.cos(a) * r, Math.sin(a) * r, r / FAR]); }
  let z = 0, zTo = 0, live = false;
  function paint() {
    const w = cv.clientWidth, h = cv.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, h);
    z += (zTo - z) * (reduce.matches ? 1 : 0.05);
    const narrow = w < 1100, panelW = narrow ? 0 : Math.min(500, w * 0.42), left = narrow ? 0 : 190;
    const ox = narrow ? w / 2 : left + (w - panelW - left) / 2, oy = narrow ? h * 0.32 : h / 2, base = Math.min(narrow ? w * 0.9 : w - panelW - left, narrow ? h * 0.5 : h) * 0.44;
    const ppu = base * Math.pow(FAR, 1 - z);
    const grey = css("--dot"), red = css("--refuse"), blue = css("--accent"), green = css("--allow");
    const clamp = (v) => Math.max(0, Math.min(1, v));
    const a3 = clamp((z - 1.05) * 1.4);
    if (a3 > 0) {
      cx.fillStyle = green; cx.globalAlpha = a3 * 0.7;
      for (const p of k3) { const x = ox + p[0] * ppu, y = oy + p[1] * ppu; if (x < -2 || x > w + 2 || y < -2 || y > h + 2) continue; cx.globalAlpha = a3 * 0.75 * (1 - p[2] * p[2] * 0.7); cx.fillRect(x - 0.8, y - 0.8, 1.6, 1.6); }
    }
    cx.globalAlpha = clamp(z / 0.35);
    const r1 = Math.max(0.9, Math.min(2.6, 2.6 - (z - 1) * 1.7));
    for (const p of k1) {
      const x = ox + p[0] * ppu, y = oy + p[1] * ppu;
      if (x < -4 || x > w + 4 || y < -4 || y > h + 4) continue;
      cx.fillStyle = p[2] ? red : grey; cx.beginPath(); cx.arc(x, y, r1, 0, 6.283); cx.fill();
    }
    const fr = Math.max(3, 30 * Math.pow(0.1, z));
    cx.globalAlpha = 0.16; cx.fillStyle = blue; cx.beginPath(); cx.arc(ox, oy, fr * 2.4, 0, 6.283); cx.fill();
    cx.globalAlpha = 1; cx.beginPath(); cx.arc(ox, oy, fr, 0, 6.283); cx.fill();
    if (z < 0.4) { cx.globalAlpha = 1 - z / 0.4; cx.fillStyle = css("--text-2"); cx.font = "500 13px " + css("--sans"); cx.textAlign = "center"; cx.fillText("The assistant from the story", ox, oy + fr * 2.4 + 22); cx.globalAlpha = 1; }
    if (live) { if (Math.abs(zTo - z) > 0.0005) requestAnimationFrame(paint); else setTimeout(() => live && requestAnimationFrame(paint), 200); }
  }
  new IntersectionObserver((es) => es.forEach((e) => { const was = live; live = e.isIntersecting; if (live && !was) requestAnimationFrame(paint); }), { threshold: 0 }).observe(root);
  function show(i) {
    const l = levels[i];
    zTo = i;
    $$("li", ruler).forEach((li, j) => { li.classList.toggle("on", j === i); li.classList.toggle("past", j < i); });
    panel.replaceChildren(el("div", { cls: "zm-card" }, [el("p", { cls: "sc-k", text: l.head }), el("p", { cls: "sc-big", text: l.big }), el("p", { cls: "sc-sub", text: l.sub }), l.fig(), el("p", { cls: "sc-foot", text: l.foot })]));
    if (reduce.matches) requestAnimationFrame(paint);
  }
  sequencer({ root, segs: $("#zm-segs"), play: $("#zm-play"), steps: levels.map((l) => ({ label: l.k, ms: 6200 })), show });
}

function navDepth() {
  const bar = $(".bar"), links = $$(".nav a[href^='#']");
  addEventListener("scroll", () => bar.classList.toggle("raised", scrollY > 8), { passive: true });
  const map = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    const a = map.get(e.target.id);
    if (a && e.isIntersecting) { links.forEach((x) => x.removeAttribute("aria-current")); a.setAttribute("aria-current", "location"); }
  }), { rootMargin: "-" + 45 + "% 0px -" + 50 + "% 0px" });
  for (const id of map.keys()) { const s = document.getElementById(id); if (s) io.observe(s); }
}

/* ---------------------------------------------------------------- the full film, in a dialog */
function filmDialog() {
  const dlg = $("#film-dlg"), open = $("#film-open");
  if (!dlg || !open) return;
  const v = $("#film-v"), list = $("#chapters"), now = $("#film-now");
  const btns = [...list.querySelectorAll("button")];
  let cur = 0;
  function pick(i, play) {
    cur = i;
    btns.forEach((b, j) => b.setAttribute("aria-current", String(j === i)));
    const c = btns[i].dataset.clip;
    v.poster = "media/og-" + c + ".jpg"; v.src = "media/og-" + c + ".mp4";
    now.textContent = "Playing: " + btns[i].textContent;
    if (play) v.play().catch(() => {});
  }
  btns.forEach((b, i) => b.addEventListener("click", () => pick(i, true)));
  v.addEventListener("ended", () => { if (cur + 1 < btns.length) pick(cur + 1, true); });
  open.addEventListener("click", () => { $$("figure.clip video").forEach((x) => x.pause()); dlg.showModal(); pick(0, true); });
  $("#film-close").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", () => v.pause());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
}

/* ---------------------------------------------------------------- developer code tabs */
function codeTabs() {
  const body = $("#code-body");
  if (!body) return;
  const tabs = $$("#code [role=tab]"), copy = $("#code-copy");
  const text = (k) => (k === "sandbox" ? D.readme.try_blocks.join("\n\n") : D.snippets[k]);
  const show = (k) => { body.textContent = text(k); tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.k === k))); };
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.k)));
  show(tabs[0].dataset.k);
  if (copy) copy.addEventListener("click", () => {
    const done = () => { copy.textContent = "Copied"; setTimeout(() => { copy.textContent = "Copy"; }, 1600); };
    try { navigator.clipboard.writeText(body.textContent).then(done, () => {}); } catch (e) { /* clipboard may be blocked */ }
  });
}

/* ---------------------------------------------------------------- theme */
function theme() {
  const btn = $("#theme"), lab = $("#theme-label");
  const order = ["system", "light", "dark"], names = { system: "System", light: "Light", dark: "Dark" };
  let cur = document.documentElement.dataset.theme || "system";
  const apply = () => {
    if (cur === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = cur;
    lab.textContent = names[cur];
    btn.setAttribute("aria-label", "Colour theme: " + names[cur].toLowerCase() + ". Activate to change.");
    try { if (cur === "system") localStorage.removeItem("og-site-theme"); else localStorage.setItem("og-site-theme", cur); } catch (e) { /* storage may be blocked */ }
  };
  btn.addEventListener("click", () => { cur = order[(order.indexOf(cur) + 1) % order.length]; apply(); drawAll(); });
  apply();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => drawAll());
}

/* ---------------------------------------------------------------- boot */
function drawAll() { /* every drawing reads its colours when it paints, so a theme change needs no redraw */ }
async function boot() {
  try {
    const r = await fetch("data.json", { cache: "no-cache" });
    D = await r.json();
  } catch (e) {
    $("#main").prepend(el("p", { cls: "noscript", text: "The data file did not load. Serve this folder over HTTP (for example python3 -m http.server) and reload." }));
    return;
  }
  bind();
  lists();
  theme();
  drawAll();
  compareSetup();
  codeTabs();
  for (const f of [heroFeatures, chapterRail, storyStage, partMandate, partData, partRisk, partAdapter, partSuper, partFinal, partQueue, partLedger, together, scaleZoom, navDepth, sign3Scene, concScene, cfScene, loopScene, certScene]) {
    try { f(); } catch (e) { console.error(f.name, e); }
  }
  for (const id of ["#gap", "#parts", "#j-time"]) { const l = $(id); if (l) revealList(l, "on", id === "#j-time" ? 1100 : 450); }
  depth();
  filmDialog();
  let lastW = innerWidth, tm = 0;
  addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => { if (innerWidth !== lastW) { lastW = innerWidth; drawAll(); } }, 150); });
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
}
boot();
