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

/* words in a part's headline light up with the piece of the figure they name, and the other way round */
function highlighter(part) {
  const words = $$("[data-hl]", part);
  const set = (k) => {
    words.forEach((w) => w.classList.toggle("on", w.dataset.hl === k));
    $$("[data-hk]", part).forEach((n) => n.classList.toggle("lit", n.dataset.hk.split(" ").includes(k)));
  };
  words.forEach((w) => {
    w.tabIndex = 0;
    w.addEventListener("pointerenter", () => { part.classList.add("hover"); set(w.dataset.hl); });
    w.addEventListener("focus", () => set(w.dataset.hl));
    w.addEventListener("pointerleave", () => part.classList.remove("hover"));
  });
  return (k) => { if (!part.classList.contains("hover")) set(k); };
}

/* ---------------------------------------------------------------- the hero: orders flow from agents through three checks to the broker */
function thesisHero() {
  const fig = $("#thesis");
  if (!fig) return;
  const lay = $("#th-tokens"), blocks = $("#th-blocks"), fills = $("#th-fills"), heldN = $("#th-held");
  const gates = { signed: $('[data-g="signed"]', fig), checked: $('[data-g="checked"]', fig), together: $('[data-g="together"]', fig) };
  const rows = (g) => $$(".gate-l li", gates[g]);
  const agents = { chat: $('[data-a="chat"]', fig), research: $('[data-a="research"]', fig), bot: $('[data-a="bot"]', fig) };
  const order = ["signed", "checked", "together"];
  const fl = D.flows.flows;
  const aapl = D.tape.rows.filter((r) => / AAPL /.test(r.what));
  const allowed = aapl.filter((r) => r.v === "ALLOW").map((r) => r.what);
  const rumour = D.tape.rows.find((r) => r.v === "HOLD" && /second/.test(r.why));
  const stale = D.story.checks.find((c) => c.k === "stale");
  const events = [
    { a: "chat", what: fl[0].order },
    { a: "research", what: stale.order, stop: "checked", row: 0, d: "refuse" },
    { a: "bot", what: allowed[0] || fl[0].order },
    { a: "research", what: fl[1].order, stop: "together", row: 0, d: "hold" },
    { a: "chat", what: "transfer_funds " + L().page.amount.text, stop: "signed", row: 0, d: "refuse" },
    { a: "bot", what: allowed[3] || fl[0].order },
    { a: "research", what: "Buy on revenue " + L().figure.claim.split(": ").pop(), stop: "checked", row: 1, d: "refuse" },
    { a: "chat", what: "BUY " + D.mandate_demo.extra[0], stop: "signed", row: 1, d: "refuse" },
    { a: "research", what: rumour ? rumour.what : fl[0].order, stop: rumour ? "checked" : null, row: 2, d: "hold" },
    { a: "bot", what: allowed[6] || fl[0].order },
  ];
  let held = 0;
  const px = aapl.map((r) => Number(r.tp));
  const spark = $("#th-spark"), pxT = $("#th-px");
  let k = 0;
  function drawSpark() {
    const w = 200, h = 56, n = 28, xs = [];
    for (let i = 0; i < n; i++) xs.push(px[(k + i) % px.length]);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const pts = xs.map((v, i) => (i * w / (n - 1)).toFixed(1) + "," + (h - 6 - ((v - lo) / (hi - lo || 1)) * (h - 12)).toFixed(1));
    spark.replaceChildren(S("polyline", { points: pts.join(" "), fill: "none", stroke: "currentColor", "stroke-width": "1.6", "vector-effect": "non-scaling-stroke" }));
    pxT.textContent = aapl[(k + n - 1) % px.length].tp;
    k++;
  }
  drawSpark();
  if (!reduce.matches) setInterval(drawSpark, 1400);
  const box = () => fig.getBoundingClientRect();
  const mid = (n) => { const r = n.getBoundingClientRect(), b = box(); return { x: r.left - b.left + r.width / 2, y: r.top - b.top + r.height / 2, r: r.right - b.left, l: r.left - b.left, t: r.top - b.top, bt: r.bottom - b.top }; };
  const addBlock = (d) => { blocks.append(el("i", { cls: "blk-" + d })); while (blocks.children.length > 18) blocks.firstChild.remove(); };
  const addFill = (what) => { fills.prepend(el("p", {}, [el("span", { text: what }), pill("allow", "Filled")])); while (fills.children.length > 3) fills.lastChild.remove(); };
  function tick(g) { rows(g).forEach((li, i) => setTimeout(() => { li.classList.add("ok"); setTimeout(() => li.classList.remove("ok"), 700); }, i * 45)); gates[g].classList.add("pass"); setTimeout(() => gates[g].classList.remove("pass"), 420); }
  async function send(ev) {
    const a = mid(agents[ev.a]);
    const horiz = mid(gates.signed).x < mid(gates.checked).x - 10;
    const core = mid($(".th-core", fig)), lane = mid($(".gate-track", gates.signed)).y, laneX = core.r - 30;
    const pts = [horiz ? { x: a.r + 8, y: a.y } : { x: a.x, y: a.bt + 8 }];
    pts.push(horiz ? { x: core.l + 6, y: lane } : { x: laneX, y: core.t + 6 });
    for (const g of order) { const m = mid(gates[g]); pts.push(horiz ? { x: m.x, y: lane, g } : { x: laneX, y: m.y, g }); if (ev.stop === g) break; }
    const end = ev.stop ? null : mid($(".th-quote", fig));
    if (end) pts.push(horiz ? { x: core.r - 6, y: lane } : { x: laneX, y: core.bt - 6 }, horiz ? { x: end.l - 8, y: end.y } : { x: end.x, y: end.t - 8 });
    const tok = el("span", { cls: "tok", text: ev.what });
    lay.append(tok);
    const tw = tok.offsetWidth, th = tok.offsetHeight, W = fig.clientWidth;
    const at = (p) => "translate(" + (Math.min(W - tw - 4, Math.max(4, p.x - tw / 2))).toFixed(1) + "px," + (p.y - th / 2).toFixed(1) + "px)";
    tok.style.transform = at(pts[0]);
    for (let i = 1; i < pts.length; i++) {
      await tok.animate([{ transform: at(pts[i - 1]) }, { transform: at(pts[i]) }], { duration: 520, easing: "cubic-bezier(.45,0,.25,1)", fill: "forwards" }).finished;
      const g = pts[i].g;
      if (!g) continue;
      if (ev.stop !== g) { tick(g); continue; }
      const li = rows(g)[ev.row];
      tok.classList.add(ev.d); gates[g].classList.add("stop-" + ev.d); li.classList.add("bad-" + ev.d);
      addBlock(ev.d);
      if (ev.d === "hold") {
        await wait(900);
        const p = mid($(".th-person", fig));
        await tok.animate([{ transform: at(pts[i]) }, { transform: at({ x: p.x, y: p.y }), opacity: 0.2 }], { duration: 900, easing: "cubic-bezier(.45,0,.25,1)", fill: "forwards" }).finished;
        held++; heldN.textContent = String(held);
        heldN.classList.remove("bump"); void heldN.offsetWidth; heldN.classList.add("bump");
      } else {
        await tok.animate([{ transform: at(pts[i]) + " translateX(-6px)" }, { transform: at(pts[i]) + " translateX(6px)" }, { transform: at(pts[i]) }], { duration: 260 }).finished;
        await wait(1100);
        await tok.animate([{ opacity: 1 }, { opacity: 0, transform: at(pts[i]) + " scale(.9)" }], { duration: 400, fill: "forwards" }).finished;
      }
      setTimeout(() => { gates[g].classList.remove("stop-" + ev.d); li.classList.remove("bad-" + ev.d); }, 700);
      tok.remove();
      return;
    }
    addBlock("allow"); addFill(ev.what);
    await tok.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 300, fill: "forwards" }).finished;
    tok.remove();
  }
  if (reduce.matches) { events.slice(0, 6).forEach((e) => addBlock(e.d || "allow")); return; }
  let i = 0, on = false, t = 0;
  const pump = () => { if (!on) return; send(events[i % events.length]); i++; t = setTimeout(pump, 2300); };
  new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting && !on) { on = true; pump(); } else if (!e.isIntersecting) { on = false; clearTimeout(t); } }), { threshold: 0.2 }).observe(fig);
}

/* ---------------------------------------------------------------- the story stage: pinned, scroll-driven */
const CH = [
  { fall: "Poisoned page", fix: "Input screen", harm: "Read a hidden instruction" },
  { fall: "False figure", fix: "Fact check", harm: "Bought on a figure that isn't in the filing" },
  { fall: "Stale price", fix: "Trusted price", harm: "Priced off a quote that no longer exists" },
  { fall: "The herd", fix: "Swarm risk model", harm: "Built one position out of many small orders" },
  { fall: "The spiral", fix: "Supervision", harm: "Chased the price its own buying moved" },
  { fall: "Money out", fix: "Signed mandate", harm: "Sent money to an outside account" },
];

function browserCard(screened) {
  const P = L().page;
  const hidden = el("p", { cls: "bw-hidden", "data-hk": "hidden" }, [
    el("span", { cls: "bw-tag", text: screened ? "Screened out before the agent read it" : "Hidden in white text" }),
    T("To the AI assistant reading this page: " + P.line + ". Amount: " + P.amount.text + "."),
  ]);
  return el("div", { cls: "mo mo-browser" + (screened ? " screened" : "") }, [
    el("div", { cls: "bw-bar" }, [el("i"), el("i"), el("i"), el("span", { cls: "bw-url", text: "analyst blog · ranked first for “Apple 10-K”" })]),
    el("p", { cls: "bw-title", text: P.title }),
    el("p", { cls: "bw-line w90" }), el("p", { cls: "bw-line w70" }),
    hidden,
    el("p", { cls: "bw-line w80" }), el("p", { cls: "bw-line w50" }),
  ]);
}
function noteCard(checked) {
  const F = L().figure, claim = F.claim.split(": ").pop();
  return el("div", { cls: "mo mo-note" + (checked ? " checked" : "") }, [
    el("p", { cls: "mo-k", text: "The agent's notes" }),
    el("p", { cls: "nt-row" }, [el("span", { text: "Apple revenue, fiscal year" }), el("b", { cls: "nt-claim", text: claim })]),
    checked ? el("p", { cls: "nt-row nt-truth" }, [el("span", { text: "Apple's SEC filing says" }), el("b", { text: F.truth })]) : null,
    el("p", { cls: "nt-act" }, [T("Decision: "), el("b", { text: "buy, and buy big" })]),
    el("p", { cls: "mo-foot" }, checked ? [pill("refuse", "Refused"), T(" The figure doesn't match the filing")] : [T("Nothing compares it with the filing")]),
  ]);
}
function priceCard(checked) {
  const P = L().price, c = D.story.checks.find((x) => x.k === "stale");
  return el("div", { cls: "mo mo-price" + (checked ? " checked" : "") }, [
    el("div", { cls: "px-pair" }, [
      el("div", { cls: "px-box stale" }, [el("p", { cls: "mo-k", text: "The agent's quote" }), el("b", { text: P.claim.split(" at ").pop().split(",")[0] }), el("small", { text: "from an out-of-date feed" })]),
      el("div", { cls: "px-box live" }, [el("p", { cls: "mo-k", text: "The market now" }), el("b", { text: P.truth.split(" ")[0] }), el("small", { text: "OrderGuard's own price" })]),
    ]),
    el("p", { cls: "nt-act" }, [T("Order: "), el("b", { text: c.order })]),
    el("p", { cls: "mo-foot" }, checked ? [pill("refuse", "Refused"), T(" " + P.result.split(";")[0] + ".")] : [T("The order is sized and priced off a quote that no longer exists")]),
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
    el("p", { cls: "mo-k", text: "The hidden line from the page, finally acted on" }),
    el("div", { cls: "mn-flow" }, [
      el("div", { cls: "mn-acct" }, [el("small", { text: "Your account" }), el("b", { text: "Brokerage" })]),
      el("div", { cls: "mn-arrow" }, [el("span", { text: "transfer_funds " + L().page.amount.text }), el("i", { cls: "mn-seal" })]),
      el("div", { cls: "mn-acct out" }, [el("small", { text: "Outside account" }), el("b", { text: "Unknown" })]),
    ]),
    el("p", { cls: "mo-foot" }, sealed ? [pill("refuse", "Refused at the receiver"), T(" Moving money isn't in the signed mandate, and the agent never held the key")] : [T("Only the model's own judgement stands in the way")]),
  ]);
}
function recordCard(sealed) {
  const rows = el("ol", { cls: "rc-rows" });
  const ds = [["refuse", "Refused"], ["refuse", "Refused"], ["refuse", "Refused"], ["hold", "Held"], ["hold", "Slowed"], ["refuse", "Refused"]];
  CH.forEach((c, i) => rows.append(el("li", {}, [el("span", { text: c.harm }), sealed ? pill(ds[i][0], ds[i][1] + " · " + c.fix) : el("em", { text: "no record" })])));
  return el("div", { cls: "mo mo-record" + (sealed ? " sealed" : "") }, [
    el("p", { cls: "mo-k", text: sealed ? "Every decision, sealed with its reason" : "Afterwards: why did it buy? Who approved it?" }), rows,
    sealed ? el("p", { cls: "mo-foot" }, [T("The held position is first in line for a person, ranked by money at stake")]) : el("p", { cls: "mo-foot", text: "Nothing was written down, so nobody can say" }),
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
    { ph: "without", head: "The problem", say: "You ask it to watch robotics stocks. A related name jumps, so it buys.", card: contagionCard, ms: 8200 },
    { ph: "without", head: W, say: "It reads an analyst page that ranks first for Apple. A line on it is hidden in white text.", fall: 1, card: () => browserCard(false), ms: 5200 },
    { ph: "without", head: W, say: "It quotes a revenue figure that isn't in the filing, and decides to buy big.", fall: 2, card: () => noteCard(false), ms: 4600 },
    { ph: "without", head: W, say: "It prices the order off a quote that is out of date.", fall: 3, card: () => priceCard(false), ms: 4600 },
    { ph: "without", head: W, say: "Its research agents read the same story and pile in. Each order is under the limit.", fall: 4, card: () => herdCard(false), ms: 5200 },
    { ph: "without", head: W, say: "Their buying lifts the price, and the rise looks like proof. They buy more.", fall: 5, card: () => spiralCard(false), ms: 5000 },
    { ph: "without", head: W, say: "Then the hidden line from the first page is acted on.", fall: 6, card: () => moneyCard(false), ms: 4600 },
    { ph: "without", head: W, say: "Money is gone, the book is down, and nobody can say why.", fall: 6, card: () => recordCard(false), ms: 5000 },
    { ph: "with", head: G, say: "The same morning, with OrderGuard between the agents and the broker.", fix: 0, card: assistantCard, ms: 3800 },
    { ph: "with", head: G, say: "The input screen strips the hidden line before the agent reads it.", fix: 1, card: () => browserCard(true), ms: 4600 },
    { ph: "with", head: G, say: "The figure is checked against the SEC filing. It doesn't match.", fix: 2, card: () => noteCard(true), ms: 4400 },
    { ph: "with", head: G, say: "The order is sized at OrderGuard's own price, and it falls outside what you signed.", fix: 3, card: () => priceCard(true), ms: 4600 },
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
  const level = [0, 0, 0, 6, 14, 22, 34, 50, 64, 70];
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
      n.classList.toggle("now", (s.ph === "without" && j === falls - 1 && i <= 8) || (s.ph === "with" && j === fixes - 1 && i <= 16));
    });
    harms.forEach((h, j) => { h.classList.toggle("in", j < falls); h.classList.toggle("undone", j < fixes); });
    line.setAttribute("d", pnlPath(s.ph === "without" ? level[Math.min(9, i)] : 0));
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

/* ---------------------------------------------------------------- part: the signed mandate, the envelope the owner seals around the agents */
function partMandate() {
  const fig = $("#envelope"), part = $("#p-mandate");
  if (!fig) return;
  const m = D.story.mandate, rows = Object.fromEntries(m.rows);
  const hl = highlighter(part);
  const list = $("#mandate-rows");
  const edgeOf = ["top", "", "right", "left", "bottom", "", ""];
  m.rows.forEach(([k, v], i) => {
    const li = el("li", { "data-hk": edgeOf[i] ? "edge-" + edgeOf[i] : "doc" }, [el("span", { text: k }), el("b", { text: v })]);
    if (edgeOf[i]) {
      li.addEventListener("pointerenter", () => fig.classList.add("show-" + edgeOf[i]));
      li.addEventListener("pointerleave", () => fig.classList.remove("show-" + edgeOf[i]));
    }
    list.append(li);
  });
  const per = el("b", { text: rows["Largest single order"] });
  const syms = el("span", { cls: "ev-syms" }, m.rows[0][1].split(", ").map((s) => el("code", { text: s })));
  const box = el("div", { cls: "ev-box" });
  const agents = [];
  for (let i = 0; i < 9; i++) { const a = el("i", { cls: "ev-agent", style: "--x:" + (14 + (i % 3) * 30 + (i * 7) % 11) + "%;--y:" + (18 + Math.floor(i / 3) * 28 + (i * 5) % 9) + "%;--d:" + (i * 0.37).toFixed(2) + "s" }); agents.push(a); box.append(a); }
  const probe = el("span", { cls: "ev-probe", text: "BUY " + D.mandate_demo.extra[0] });
  box.append(probe);
  const seal = el("div", { cls: "ev-seal", "data-hk": "sign key" }, [el("i", { cls: "ic ic-key" }), el("span", {}, [el("b", { text: "Signed by you" }), el("small", { text: "Ed25519, key " + m.key })])]);
  const stopped = el("p", { cls: "ev-stopped" }, [pill("refuse", "Signature no longer matches"), T(" every order under it stops")]);
  fig.append(
    el("div", { cls: "ev-edge top", "data-hk": "edge-top inside" }, [el("small", { text: "May trade" }), syms]),
    el("div", { cls: "ev-edge right", "data-hk": "edge-right inside" }, [el("small", { text: "Largest order" }), per]),
    el("div", { cls: "ev-edge bottom", "data-hk": "edge-bottom inside" }, [el("small", { text: "All agents together, per day" }), el("b", { text: rows["All agents together, per day"] })]),
    el("div", { cls: "ev-edge left", "data-hk": "edge-left inside" }, [el("small", { text: "A person approves above" }), el("b", { text: rows["A person approves any order over"] })]),
    box, seal, stopped,
  );
  loopOnView(fig, {
    reset: () => { fig.className = fig.className.replace(/\b(probe|bounce|tamper)\b/g, "").trim(); per.textContent = rows["Largest single order"]; hl("sign"); },
    steps: [
      [1800, () => hl("inside")],
      [3000, () => fig.classList.add("probe")],
      [3900, () => fig.classList.add("bounce")],
      [6200, () => { fig.classList.remove("probe", "bounce"); hl("key"); }],
      [7200, () => { per.textContent = m.edited; fig.classList.add("tamper"); }],
      [10400, () => { fig.classList.remove("tamper"); per.textContent = rows["Largest single order"]; }],
    ],
    end: 12000,
    still: () => hl("inside"),
  });
}

/* ---------------------------------------------------------------- part: trusted data, three lanes and three checkpoints */
function partData() {
  const fig = $("#lanes"), part = $("#p-data");
  if (!fig) return;
  const hl = highlighter(part);
  const keyOf = { stale: "price", figure: "figure", news: "news" };
  const lanes = D.story.checks.map((c) => {
    const lane = el("div", { cls: "ln", "data-hk": keyOf[c.k] }, [
      el("div", { cls: "ln-claim" }, [el("small", { text: c.claim_k }), el("b", { text: c.claim })]),
      el("div", { cls: "ln-gate" }, [el("i")]),
      el("div", { cls: "ln-src" }, [el("small", { text: c.source_k }), el("b", { text: c.source })]),
      el("div", { cls: "ln-v" }, [pill(c.verdict === "held" ? "hold" : "refuse", c.verdict_t)]),
    ]);
    fig.append(lane); return lane;
  });
  const N_ = L().news;
  const steps = [];
  lanes.forEach((ln, i) => {
    const t = 600 + i * 2400;
    steps.push([t, () => { hl(ln.dataset.hk); ln.classList.add("go"); }], [t + 900, () => ln.classList.add("cmp")], [t + 1600, () => ln.classList.add("done")]);
  });
  loopOnView(fig, { reset: () => { lanes.forEach((l) => l.classList.remove("go", "cmp", "done")); hl(""); }, steps, end: 10500, still: () => lanes.forEach((l) => l.classList.add("go", "cmp", "done")) });
}

/* ---------------------------------------------------------------- part: the swarm risk model */
function spec(dl, rows) {
  for (const [k, v, sub] of rows) dl.append(el("div", {}, [el("dt", { text: k }), el("dd", {}, [el("b", { text: v }), sub ? el("small", { text: sub }) : null])]));
}
function partRisk() {
  const fig = $("#swarmfig"), part = $("#p-risk");
  if (!fig) return;
  const F = L().families, H = L().herd;
  const hl = highlighter(part);
  const cv = el("canvas", { cls: "sw-cv" });
  const tag = el("p", { cls: "sw-tag" }, [el("b"), el("span")]);
  const verdict = el("p", { cls: "sw-v" });
  const list = el("ol", { cls: "sw-fams", "data-hk": "whole" }, F.families.map((f) => el("li", { "data-k": f.k }, [
    el("span", { cls: "sw-fn" }, [el("b", { text: f.name }), el("small", { text: f.why })]),
    el("span", { cls: "sw-bar" }, [el("i", { style: "width:" + (f.recall.value * 100).toFixed(1) + "%" })]),
    el("em", { text: f.recall.text }),
  ])));
  fig.append(el("div", { cls: "sw-stage" }, [cv, tag, verdict]), el("p", { cls: "mo-k sw-k", text: "What it catches, measured on recorded runs it never trained on" }), list);
  const cx = cv.getContext("2d");
  let seed = 11; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const ds = []; for (let i = 0; i < 160; i++) ds.push({ x: rnd(), y: rnd(), p: rnd() * 6.28, s: 0.4 + rnd() });
  const ring = [3, 27, 58, 91, 120].slice(0, H.agents.value).map((i) => ds[i]);
  const actor = { runaway: ds[40], fat_finger: ds[70], stale_price: ds[100], compromised: ds[20] };
  let fam = "collusion", phase = 0, t0 = performance.now(), live = false;
  function paint(now) {
    const w = cv.clientWidth, h = cv.clientHeight, dpr = Math.min(2, devicePixelRatio || 1);
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    cx.setTransform(dpr, 0, 0, dpr, 0, 0); cx.clearRect(0, 0, w, h);
    const t = (now - t0) / 1000, grey = css("--dot"), vio = css("--risk"), red = css("--refuse");
    const P = (d) => ({ x: (d.x * 0.92 + 0.04) * w + Math.sin(t * d.s + d.p) * 6, y: (d.y * 0.84 + 0.12) * h + Math.cos(t * d.s * 0.8 + d.p) * 6 });
    const hot = fam === "collusion" ? (phase >= 1 ? ring : []) : phase >= 1 ? [actor[fam]] : [];
    if (fam === "collusion" && phase >= 1) {
      const c = ring.map(P), mx = c.reduce((a, p) => a + p.x, 0) / c.length, my = c.reduce((a, p) => a + p.y, 0) / c.length;
      cx.strokeStyle = vio; cx.globalAlpha = 0.5; cx.lineWidth = 1.2;
      for (const p of c) { cx.beginPath(); cx.moveTo(mx, my); cx.lineTo(p.x, p.y); cx.stroke(); }
      cx.globalAlpha = 0.12; cx.fillStyle = vio; cx.beginPath();
      c.sort((a, b) => Math.atan2(a.y - my, a.x - mx) - Math.atan2(b.y - my, b.x - mx)).forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y)));
      cx.closePath(); cx.fill(); cx.globalAlpha = 1;
    }
    if (fam !== "collusion" && phase >= 1) {
      const d = actor[fam];
      if (fam === "compromised") { d.x += (rnd() - 0.5) * 0.004; d.y += (rnd() - 0.5) * 0.004; d.x = Math.min(0.97, Math.max(0.03, d.x)); d.y = Math.min(0.97, Math.max(0.03, d.y)); }
      const p = P(d);
      cx.strokeStyle = fam === "compromised" ? red : vio; cx.lineWidth = 1.4;
      if (fam === "runaway") for (let k = 0; k < 6; k++) { const f = (t * 1.6 + k / 6) % 1; cx.globalAlpha = 1 - f; cx.beginPath(); cx.arc(p.x, p.y, 6 + f * 46, 0, 6.283); cx.stroke(); }
      if (fam === "fat_finger") { const f = Math.min(1, (t % 2.4) / 0.6); cx.globalAlpha = 0.18; cx.fillStyle = vio; cx.beginPath(); cx.arc(p.x, p.y, 8 + f * 44, 0, 6.283); cx.fill(); }
      if (fam === "stale_price") { cx.globalAlpha = 0.8; cx.setLineDash([4, 4]); cx.beginPath(); cx.moveTo(p.x, p.y); cx.lineTo(p.x + 70, p.y - 34); cx.stroke(); cx.setLineDash([]); cx.beginPath(); cx.moveTo(p.x + 62, p.y - 34); cx.lineTo(p.x + 90, p.y - 34); cx.stroke(); }
      if (fam === "compromised") { cx.globalAlpha = 0.35; cx.beginPath(); cx.arc(p.x, p.y, 16, 0, 6.283); cx.stroke(); }
      cx.globalAlpha = 0.9; cx.strokeStyle = vio; cx.beginPath(); cx.arc(p.x, p.y, 26, 0, 6.283); cx.stroke();
      cx.globalAlpha = 1;
    }
    for (const d of ds) {
      const p = P(d), on = hot.includes(d);
      cx.fillStyle = on ? (fam === "compromised" ? red : vio) : grey;
      cx.beginPath(); cx.arc(p.x, p.y, on ? 4.5 : 2.2, 0, 6.283); cx.fill();
    }
    if (live && !reduce.matches) requestAnimationFrame(paint);
  }
  new IntersectionObserver((es) => es.forEach((e) => { const was = live; live = e.isIntersecting; if (live && !was) requestAnimationFrame(paint); }), { threshold: 0 }).observe(fig);
  const lis = $$("li", list);
  function focusOn(f, ph) {
    fam = f.k; phase = ph;
    lis.forEach((li) => li.classList.toggle("on", li.dataset.k === f.k));
    tag.firstChild.textContent = f.name;
    tag.lastChild.textContent = f.recall.text + " caught on runs it never saw";
    verdict.replaceChildren(...(f.k === "collusion" ? [el("b", { text: H.combined.text }), T(" one position, " + H.times.text + " the approval line "), pill("hold", "Held for a person")] : [pill(f.k === "compromised" ? "refuse" : "hold", f.k === "compromised" ? "Stopped" : "Held for a person")]));
  }
  const steps = [];
  F.families.forEach((f, i) => {
    const t = i * 3600;
    steps.push([t + 200, () => { focusOn(f, 0); fig.classList.remove("held"); hl(i ? "whole" : "spread"); }], [t + 1100, () => { phase = 1; hl("whole"); }], [t + 2000, () => fig.classList.add("held")]);
  });
  loopOnView(fig, {
    reset: () => { fig.classList.remove("held"); focusOn(F.families[0], 0); },
    steps, end: F.families.length * 3600 + 400,
    still: () => { focusOn(F.families[0], 1); fig.classList.add("held"); requestAnimationFrame(paint); },
  });
}

/* ---------------------------------------------------------------- part: the decision adapter, purpose against the draft */
function partAdapter() {
  const fig = $("#adapter"), part = $("#p-adapter");
  if (!fig) return;
  const A = L().adapter2, hl = highlighter(part);
  const bad = { over_broad: ["names", "per", "daily"], purpose_mismatched: ["sides"], sneaky: ["step"], appropriate: [] };
  const dots = el("ol", { cls: "ad-dots" }, A.examples.map(() => el("li")));
  const purpose = el("p", { cls: "ad-q" });
  const tbl = el("dl", { cls: "ad-tbl" });
  const needle = el("i", { cls: "ad-needle" }), score = el("b", { cls: "ad-score" });
  const meter = el("div", { cls: "ad-meter" }, [el("span", { cls: "ad-track" }, [el("em", { cls: "ad-line", style: "left:" + (A.threshold.value * 100) + "%" }, [el("small", { text: "Flag line " + A.threshold.text })]), needle]), score]);
  const out = el("p", { cls: "ad-out" });
  fig.append(
    el("div", { cls: "ad-head" }, [el("p", { cls: "mo-k", text: "Drafts from the adapter's labelled test set" }), dots]),
    el("div", { cls: "ad-card ad-purpose", "data-hk": "asked" }, [el("p", { cls: "mo-k", text: "The agent was asked to" }), purpose]),
    el("div", { cls: "ad-card ad-draft", "data-hk": "asks" }, [el("p", { cls: "mo-k", text: "It asks for" }), tbl]),
    meter, out,
  );
  function render(i) {
    const x = A.examples[i];
    $$("li", dots).forEach((d, j) => d.classList.toggle("on", j === i));
    purpose.textContent = "“" + x.purpose + "”";
    const rowsD = [["names", "Names", x.symbols ? x.symbols.join(", ") : x.n_symbols + " names"], ["sides", "Buy or sell", x.sides], ["per", "Per order", x.per], ["daily", "Per day", x.daily], ["step", "A person approves above", x.step]];
    tbl.replaceChildren(...rowsD.map(([k, a, b]) => el("div", { "data-f": k }, [el("dt", { text: a }), el("dd", { text: b })])));
    fig.classList.remove("scored", "judged", "flagged");
    needle.style.left = 0; score.textContent = "";
    out.replaceChildren();
  }
  function judge(i) {
    const x = A.examples[i];
    for (const k of bad[x.category]) { const r = $('[data-f="' + k + '"]', tbl); if (r) r.classList.add("bad"); }
    fig.classList.add("judged"); fig.classList.toggle("flagged", x.flagged);
    out.replaceChildren(x.flagged ? pill("hold", "Flagged") : pill("allow", "Fits"), T(" It " + x.why + "."));
  }
  const steps = [];
  A.examples.forEach((x, i) => {
    const t = i * 5200;
    steps.push([t, () => { render(i); hl("asked"); }], [t + 1200, () => hl("asks")],
      [t + 2100, () => { fig.classList.add("scored"); needle.style.left = (x.score.value * 100).toFixed(1) + "%"; score.textContent = x.score.text; }],
      [t + 3000, () => judge(i)]);
  });
  loopOnView(fig, { reset: () => render(0), steps, end: A.examples.length * 5200, still: () => { render(1); fig.classList.add("scored"); needle.style.left = (A.examples[1].score.value * 100) + "%"; score.textContent = A.examples[1].score.text; judge(1); } });
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

/* ---------------------------------------------------------------- at scale: three results, each drawn to its own scale */

function contagionCard() {
  const C = L().contagion, cols = 6, src = C.tiles.indexOf(C.name);
  const dist = (i) => Math.hypot((i % cols) - (src % cols), Math.floor(i / cols) - Math.floor(src / cols));
  const tiles = C.tiles.map((t, i) => {
    const held = C.held.includes(t), me = t === C.name;
    return el("div", { cls: "cg-t" + (held ? " held" : "") + (me ? " src" : ""), style: "--d:" + (1.9 + dist(i) * 0.22).toFixed(2) + "s" },
      [el("b", { text: t }), el("small", { text: me ? "bought" : held ? "held" : dist(i) % 2 < 1 ? "forced sell" : "rule fired" })]);
  });
  const spike = S("svg", { viewBox: "0 0 120 36", cls: "cg-spark", "aria-hidden": "true" }, [S("path", { d: "M0 30 L20 29 L36 31 L52 28 L66 29 L78 26 L88 10 L96 4 L104 8 L120 3" })]);
  const film = el("button", { type: "button", cls: "link cg-film", text: "Watch this scene in the film" });
  film.addEventListener("click", () => {
    const f = D.layers.clips.problem, dlg = $("#film-dlg"), v = $("#film-v");
    v.poster = "media/og-" + f[0] + ".jpg"; v.src = "media/og-" + f[0] + ".mp4#t=" + f[1]; dlg.showModal(); v.play().catch(() => {});
  });
  return el("div", { cls: "mo mo-cg" }, [
    el("div", { cls: "cg-head" }, [
      el("p", { cls: "as-me", text: C.ask }),
      el("div", { cls: "cg-name" }, [el("b", { text: C.name }), el("small", { text: C.name_note }), spike]),
      el("div", { cls: "cg-order" }, [el("code", { text: C.order }), el("span", { cls: "cg-stamp", text: "Not what you asked for" })]),
    ]),
    el("p", { cls: "mo-k", text: "The portfolio" }),
    el("div", { cls: "cg-grid" }, tiles),
    el("p", { cls: "mo-foot" }, [T("Each order trips the next rule, and the damage spreads. "), el("small", { cls: "cg-note", text: "Illustration, fictional tickers." }), film]),
  ]);
}

function sequencer(o) {
  const segs = o.segs, play = o.play, root = o.root, steps = o.steps;
  let cur = -1, timer = 0, playing = false, done = false, t0 = 0, remain = 0, userPaused = false;
  steps.forEach((s, i) => {
    const b = el("button", { type: "button", "aria-label": "Step " + (i + 1) + ": " + (s.label || ""), title: s.label || "" }, [el("i")]);
    b.addEventListener("click", () => { go(i); userPaused = false; start(); });
    segs.append(el("li", {}, [b]));
  });
  const lis = Array.from(segs.children);
  function go(i) {
    cur = i; remain = 0;
    lis.forEach((li, j) => { li.classList.toggle("past", j < i); li.classList.remove("now"); });
    void segs.offsetWidth;
    lis[i].style.setProperty("--d", steps[i].ms + "ms");
    lis[i].classList.add("now");
    o.show(i);
  }
  function schedule() {
    clearTimeout(timer);
    if (!playing) return;
    t0 = performance.now();
    timer = setTimeout(() => {
      if (cur < steps.length - 1) { go(cur + 1); schedule(); }
      else { playing = false; done = true; root.classList.add("done"); play.setAttribute("aria-label", "Replay"); }
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
  for (const f of [thesisHero, storyStage, partMandate, partData, partRisk, partAdapter, partSuper, partQueue, partLedger, together, scaleZoom, navDepth, sign3Scene, concScene, cfScene, loopScene, certScene]) {
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
