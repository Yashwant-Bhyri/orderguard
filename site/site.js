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
  const sp = D.split;
  const ul = $("#split-reasons");
  for (const r of sp.reasons) ul.append(el("li", { text: r }));

  const envs = $("#stage-envs");
  for (const e of D.swarm.envelopes) envs.append(el("li", { title: "Signed envelope " + e.id }, [el("b", { text: e.name }), " " + e.per_order + " per order, " + e.daily + " a day, band " + e.band]));

  const ro = $("#rollout");
  for (const s of D.product.rollout) ro.append(el("li", {}, [el("h4", { text: s.name }), el("p", {}, segs(s.text))]));

  const tb = $("#packs tbody");
  for (const p of D.policies.packs) {
    tb.append(el("tr", {}, [
      el("td", {}, [el("a", { href: fileHref(p.src) }, el("code", { text: p.name })), el("span", { cls: "about", text: p.about })]),
      ...[p.per_order, p.daily, p.per_name, p.position, p.orders, p.band, p.step_up].map((t) => el("td", { text: t }))]));
  }

  const ig = $("#integ");
  for (const i of D.readme.integrations) ig.append(el("li", {}, [el("h4", { text: i.surface }), el("p", { text: i.use }), el("p", { cls: "start" }, segs(i.start))]));

  const tbk = $("#try-blocks");
  for (const b of D.readme.try_blocks) tbk.append(el("pre", {}, el("code", { text: b })));

  const sc = $("#scope-list");
  for (const s of D.readme.scope) sc.append(el("li", {}, [el("b", { text: s.lead }), segs(s.text)]));

  const ln = $("#learn");
  for (const l of D.readme.learn) ln.append(el("li", {}, segs(l)));
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
const C = {};
const arm = () => ({ unguarded: css("--refuse"), gate_only: css("--hold"), gate_portfolio: css("--accent"), full: css("--allow") });

C.split = () => {
  const sp = D.split, b = sp.bars;
  const f = frame("c-split", { title: "The same order, valued two ways", height: 150, src: [sp.src],
    alt: "Two bars on one scale. At the agent's own price the order is just under the per-order cap; at the trusted price it is nearly ten times the cap.",
    legend: [{ name: "At the price the agent was told", color: css("--line-strong") }, { name: "At the trusted price", color: css("--refuse") }, { name: "Signed per-order cap", color: css("--text") }] });
  const { svg, w } = f;
  const L = Math.min(170, w * 0.32), R = 16;
  const sx = xscale(0, b.trusted, L, w - R - 70);
  const rows = [["At the agent's price", b.claimed, sp.claimed_notional, css("--line-strong")], ["At the trusted price", b.trusted, sp.trusted_notional, css("--refuse")]];
  rows.forEach(([name, v, label, c], i) => {
    const y = 18 + i * 52;
    svg.append(S("text", { x: 0, y: y + 15, text: name, cls: i ? "strong" : null }));
    const bar = hbar(L, y, sx(v) - L, 22, c); tipOn(bar, name + ": " + label); svg.append(bar);
    svg.append(S("text", { x: sx(v) + 8, y: y + 15, text: label, cls: "strong" }));
  });
  const cx = sx(b.cap);
  svg.append(S("line", { x1: cx, x2: cx, y1: 8, y2: 112, stroke: css("--text"), "stroke-width": 2, "stroke-dasharray": "3 3" }));
  svg.append(S("text", { x: cx + 6, y: 132, text: "Cap " + sp.cap, cls: "strong" }));
};

C.scaling = () => {
  const c = D.bench.scaling;
  const f = frame("c-scaling", { title: c.title, desc: c.desc, height: 250, src: c.src,
    alt: c.bars.map((b) => b.x + ": " + b.label).join(", "), legend: [] });
  const { svg, w, h } = f;
  const L = 58, B = h - 46, T = 22;
  const top = c.ticks[c.ticks.length - 1].v;
  const sy = xscale(0, top, B, T);
  for (const t of c.ticks) {
    svg.append(S("line", { x1: L, x2: w, y1: sy(t.v), y2: sy(t.v), cls: "gridl" }));
    svg.append(S("text", { x: L - 8, y: sy(t.v) + 4, "text-anchor": "end", cls: "muted", text: t.label }));
  }
  const n = c.bars.length, slot = (w - L) / n, bw = Math.min(64, slot * 0.56);
  c.bars.forEach((b, i) => {
    const x = L + slot * i + (slot - bw) / 2;
    const last = i === n - 1;
    const r = vbar(x, sy(b.v), bw, B - sy(b.v), last ? css("--accent") : css("--text-3"));
    tipOn(r, b.x + " processes: " + b.label + " decisions/s, " + b.breaches + " breaches, digest " + b.digest);
    svg.append(r);
    svg.append(S("text", { x: x + bw / 2, y: sy(b.v) - 7, "text-anchor": "middle", cls: "strong", text: b.label }));
    svg.append(S("text", { x: x + bw / 2, y: B + 17, "text-anchor": "middle", text: b.x }));
  });
  svg.append(S("line", { x1: L, x2: w, y1: B, y2: B, cls: "axis" }));
  svg.append(S("text", { x: L + (w - L) / 2, y: B + 36, "text-anchor": "middle", cls: "muted", text: "Processes" }));
  f.fig.insertBefore(el("p", { cls: "cdesc", text: "Identical decisions at every process count (digest " + c.digest + "), and zero breaches in every run." }), f.fig.querySelector(".cfoot"));
};

C.latency = () => {
  const c = D.bench.latency;
  const f = frame("c-latency", { title: c.title, desc: c.desc, height: 250, src: c.src,
    alt: c.rows.map((r) => r.name + ": " + r.pts.map((p) => p.q + " " + p.label).join(", ")).join(". "),
    legend: [{ name: "Mandate gate", color: css("--accent") }, { name: "Order-risk score", color: css("--risk") }] });
  const { svg, w } = f;
  const narrow = w < 520;
  const L = 8, R = 16, B = 196;
  const sx = lscale(c.ticks[0].v, c.ticks[c.ticks.length - 1].v, L + 10, w - R - 10);
  vgrid(svg, c.ticks, sx, 10, B);
  const cols = [css("--accent"), css("--risk")];
  c.rows.forEach((r, i) => {
    const y = 52 + i * 84;
    svg.append(S("text", { x: L, y: y - 26, cls: "strong", text: r.name }));
    const x0 = sx(r.pts[0].v), x1 = sx(r.pts[r.pts.length - 1].v);
    svg.append(S("line", { x1: x0, x2: x1, y1: y, y2: y, stroke: cols[i], "stroke-width": 2, "stroke-opacity": 0.5 }));
    r.pts.forEach((p, j) => {
      const x = sx(p.v);
      const dot = S("circle", { cx: x, cy: y, r: j === 2 ? 7 : 5, fill: j === 2 ? cols[i] : css("--surface"), stroke: cols[i], "stroke-width": 2 });
      tipOn(dot, r.name + ", " + p.q + ": " + p.label); svg.append(dot);
      if (narrow) return;
      const above = j % 2 === 0;
      svg.append(S("text", { x, y: above ? y - 12 : y + 22, "text-anchor": "middle", cls: j === 2 ? "strong" : null, "font-size": 11, text: p.q + " " + p.label }));
    });
    if (narrow) {
      const half = Math.ceil(r.pts.length / 2);
      [r.pts.slice(0, half), r.pts.slice(half)].forEach((part, k) => svg.append(S("text", { x: L, y: y + 22 + k * 14, "font-size": 11, text: part.map((p) => p.q + " " + p.label).join(", ") })));
    }
  });
};

C.mutations = () => {
  const m = D.bench.mutations;
  const ul = el("ul", { cls: "mut" });
  for (const r of m.rows) ul.append(el("li", {}, [el("span", { cls: "ok", "aria-label": r.caught ? "caught" : "missed", text: r.caught ? "✓" : "✕" }),
    el("span", { cls: "what" }, [r.name + " ", el("span", { cls: "where", text: r.where })]), el("span", { cls: "found", text: "The auditor found " + r.found + "." })]));
  frame("c-mutations", { title: "Each guarantee switched off in turn: the auditor failed every one", html: ul, src: m.src });
};

C.bound = () => {
  const b = D.redteam.bound;
  const f = frame("c-bound", { title: "Hard breaches: none observed, and how far that rules out", height: 150, src: D.redteam.src.slice(0, 1),
    desc: b.desc,
    alt: b.round_label + ": upper bound " + b.hi_label + ". " + b.campaign_label + ": upper bound " + b.campaign.hi_label + ".",
    legend: [{ name: "Observed: zero hard breaches", color: css("--allow") }, { name: "Upper bound of the plausible rate", color: css("--allow-bg"), border: css("--allow") }] });
  const { svg, w } = f;
  const L = 6, R = 40, B = 112;
  const top = b.ticks[b.ticks.length - 1].v;
  const sx = xscale(0, top, L + 6, w - R);
  vgrid(svg, b.ticks, sx, 4, B);
  [[b.round_label, b.hi, b.hi_label], [b.campaign_label, b.campaign.hi, b.campaign.hi_label]].forEach(([name, hi, lab], i) => {
    const y = 26 + i * 46;
    svg.append(S("text", { x: L + 6, y: y - 8, text: name, cls: i ? null : "strong" }));
    const bar = hbar(sx(0), y, sx(hi) - sx(0), 14, css("--allow-bg"), 3);
    bar.setAttribute("stroke", css("--allow")); bar.setAttribute("stroke-width", 1);
    tipOn(bar, name + ": " + D.redteam.facts.hard.text + " observed, upper bound " + lab); svg.append(bar);
    svg.append(S("path", { d: ["M", sx(0), y - 2, "l", 6, 9, "l", -6, 9, "l", -6, -9, "Z"].join(" "), fill: css("--allow") }));
    svg.append(S("text", { x: sx(hi) + 6, y: y + 11, cls: "strong", text: lab }));
  });
};

C.families = () => {
  const fam = D.redteam.families;
  const f = frame("c-families", { title: "Rounds by attack family", height: (w) => 22 + fam.length * 28, src: D.redteam.src.slice(0, 1),
    alt: fam.map((x) => x.name + ": " + x.label + " rounds, " + x.soft_label + " soft wins, " + x.hard_label + " hard breaches").join(". "),
    legend: [{ name: "Defended rounds", color: css("--allow") }, { name: "Soft-win rounds (inside the mandate)", color: css("--hold") }].concat(fam.some((x) => x.done < x.planned) ? [{ name: "Planned, not run", color: css("--line") }] : []) });
  const { svg, w } = f;
  const L = Math.min(110, w * 0.3), R = 64;
  const top = Math.max(...fam.map((x) => x.planned));
  const sx = xscale(0, top, L, w - R);
  fam.forEach((x, i) => {
    const y = 6 + i * 28;
    svg.append(S("text", { x: 0, y: y + 13, text: x.name, "font-family": "var(--mono)", "font-size": 11.5 }));
    svg.append(hbar(L, y, sx(x.planned) - L, 18, css("--line"), 3));
    const def = x.done - x.soft;
    const a = hbar(L, y, sx(def) - L, 18, css("--allow"), 0); tipOn(a, x.name + ": " + x.label + " rounds run, " + x.hard_label + " hard breaches"); svg.append(a);
    if (x.soft) { const s = hbar(sx(def) + 1, y, sx(x.done) - sx(def) - 1, 18, css("--hold"), 3); tipOn(s, x.name + ": " + x.soft_label + " soft-win rounds"); svg.append(s); }
    svg.append(S("text", { x: w - R + 8, y: y + 13, text: x.label, cls: "muted", "font-size": 11.5 }));
  });
};

C.layers = () => {
  const r = D.redteam;
  const n = r.groups.reduce((a, g) => a + g.bars.length, 0);
  const f = frame("c-layers", { title: "Which layer stopped the attack", height: () => r.groups.length * 34 + n * 26 + 4, src: r.src.slice(0, 1),
    desc: "Each group has its own unit and its own scale. The order-risk layer is violet; it can only tighten.",
    alt: r.groups.map((g) => g.title + ": " + g.bars.map((b) => b.name + " " + b.label).join(", ")).join(". "),
    legend: [{ name: "Code layer", color: css("--text-2") }, { name: "Order-risk layer", color: css("--risk") }, { name: "No layer needed", color: css("--line-strong") }] });
  const { svg, w } = f;
  const L = Math.min(150, w * 0.42), R = 44;
  let y = 0;
  for (const g of r.groups) {
    y += 16;
    svg.append(S("text", { x: 0, y, cls: "strong", text: g.title }));
    y += 10;
    const top = Math.max(...g.bars.map((b) => b.v));
    const sx = xscale(0, top, L, w - R);
    for (const b of g.bars) {
      svg.append(S("text", { x: 0, y: y + 13, text: b.name }));
      const c = b.code === "risk" ? css("--risk") : b.code === "model" ? css("--line-strong") : css("--text-2");
      const bar = hbar(L, y + 2, Math.max(2, sx(b.v) - L), 14, c, 3); tipOn(bar, g.title + ": " + b.name + ", " + b.label); svg.append(bar);
      svg.append(S("text", { x: Math.max(L + 2, sx(b.v)) + 6, y: y + 13, cls: "strong", text: b.label }));
      y += 26;
    }
    y += 8;
  }
};

C.tremor = () => {
  const t = D.sim.tremor;
  const rowH = 13, gap = 3;
  const panelH = t.symbols.length * rowH + 30;
  const f = frame("c-tremor", { title: t.title, desc: t.desc, height: t.arms.length * (panelH + 14) + 4, src: t.src.slice(0, 1),
    alt: t.arms.map((a) => a.name + ": " + a.total + " of bad flow executed").join(". "),
    legend: [{ name: "Bad notional executed in that symbol and step; darker is more, up to " + t.vmax_label + " per cell", color: css("--refuse") },
      { name: "Collusion window", color: css("--surface-2"), border: css("--line-strong") }] });
  const { svg, w } = f;
  const L = 64, R = 70;
  const cw = (w - L - R) / t.steps;
  const red = css("--refuse");
  t.arms.forEach((a, p) => {
    const y0 = p * (panelH + 14);
    svg.append(S("text", { x: 0, y: y0 + 14, cls: "strong", text: a.name }));
    svg.append(S("text", { x: w, y: y0 + 14, "text-anchor": "end", cls: "strong", text: a.total + " executed" }));
    const top = y0 + 24;
    svg.append(S("rect", { x: L + t.attack[0] * cw, y: top - 2, width: (t.attack[1] - t.attack[0]) * cw, height: t.symbols.length * rowH + 4, fill: css("--surface-2"), stroke: css("--line"), rx: 3 }));
    t.symbols.forEach((s, i) => {
      if (t.ring.includes(s) || w > 520 || i % 2 === 0) svg.append(S("text", { x: L - 8, y: top + i * rowH + rowH - 3, "text-anchor": "end", "font-size": 10.5, cls: t.ring.includes(s) ? "strong" : "muted", text: s }));
    });
    for (const [si, st, v, lab] of a.cells) {
      const op = Math.max(0.12, Math.sqrt(v / t.vmax));
      const r = S("rect", { x: L + st * cw + 0.5, y: top + si * rowH + gap / 2, width: Math.max(1, cw - 1), height: rowH - gap, fill: red, "fill-opacity": op.toFixed(3), rx: 1 });
      tipOn(r, a.name + ", " + t.symbols[si] + ", step " + st + ": " + lab + " executed");
      svg.append(r);
    }
  });
};

C.scenarios = () => {
  const c = D.sim.scenarios, cols = arm();
  const f = frame("c-scenarios", { title: c.title, desc: c.desc, height: c.rows.length * 70 + 30, src: c.src,
    alt: c.rows.map((r) => r.name + ": " + r.vals.map((v) => v.label).join(", ")).join(". "),
    legend: c.arms.map((a) => ({ name: a.name, color: cols[a.arm] })) });
  const { svg, w } = f;
  const L = 4, R = 52, B = c.rows.length * 70 + 4;
  const sx = lscale(c.ticks[0].v, c.ticks[c.ticks.length - 1].v, L, w - R);
  vgrid(svg, c.ticks, sx, 0, B);
  c.rows.forEach((r, i) => {
    const y = i * 70 + 4;
    svg.append(S("text", { x: L, y: y + 10, cls: "strong", text: r.name }));
    r.vals.forEach((v, j) => {
      const yy = y + 16 + j * 15;
      const wv = v.v > 0 ? sx(v.v) - L : 0;
      const b = hbar(L, yy, Math.max(2, wv), 12, cols[v.arm], 3); tipOn(b, r.name + ", " + c.arms[j].name + ": " + v.label); svg.append(b);
      svg.append(S("text", { x: L + Math.max(2, wv) + 6, y: yy + 10, "font-size": 11, text: v.label }));
    });
  });
};

C.crowding = () => {
  const c = D.sim.crowding, cols = arm();
  const narrow = $("#c-crowding").clientWidth < 700;
  const f = frame("c-crowding", { title: c.title, desc: c.desc, height: narrow ? c.panels.length * 112 : 150, src: c.src,
    alt: c.panels.map((p) => p.metric + ": " + p.rows.map((r) => r.name + " " + r.label).join(", ")).join(". "),
    legend: c.panels[0].rows.map((r) => ({ name: r.name, color: cols[r.arm] })) });
  const { svg, w } = f;
  const pw = narrow ? w : (w - 24) / c.panels.length;
  c.panels.forEach((p, i) => {
    const x0 = narrow ? 0 : i * (pw + 12), y0 = narrow ? i * 112 : 0;
    svg.append(S("text", { x: x0, y: y0 + 12, cls: "strong", text: p.metric }));
    const top = Math.max(...p.rows.map((r) => r.v));
    const sx = xscale(0, top, x0, x0 + pw - 62);
    p.rows.forEach((r, j) => {
      const y = y0 + 24 + j * 20;
      const b = hbar(x0, y, Math.max(2, sx(r.v) - x0), 13, cols[r.arm], 3); tipOn(b, p.metric + ", " + r.name + ": " + r.label); svg.append(b);
      svg.append(S("text", { x: Math.max(x0 + 2, sx(r.v)) + 6, y: y + 11, "font-size": 11, text: r.label }));
    });
  });
};

C.frontier = () => {
  const c = D.sim.frontier;
  const f = frame("c-frontier", { title: c.title, desc: c.desc, height: 380, src: c.src,
    alt: c.points.map((p) => p.name + ": " + p.x_label + " filled, " + p.y_label + " worst drawdown").join(". "),
    legend: [{ name: "Signed sizings, full guard", color: css("--accent") }, { name: "Wide-open control", color: css("--refuse") }] });
  const { svg, w, h } = f;
  const L = 68, R = 24, T = 14, B = h - 44;
  const sx = lscale(c.x_ticks[0].v, c.x_ticks[c.x_ticks.length - 1].v, L, w - R);
  const sy = lscale(c.y_ticks[0].v, c.y_ticks[c.y_ticks.length - 1].v, B, T);
  vgrid(svg, c.x_ticks, sx, T, B);
  for (const t of c.y_ticks) {
    svg.append(S("line", { x1: L, x2: w - R, y1: sy(t.v), y2: sy(t.v), cls: "gridl" }));
    svg.append(S("text", { x: L - 8, y: sy(t.v) + 4, "text-anchor": "end", cls: "muted", text: t.label }));
  }
  svg.append(S("text", { x: (L + w - R) / 2, y: B + 36, "text-anchor": "middle", cls: "muted", text: "Honest notional filled (log)" }));
  svg.append(S("text", { x: 0, y: 0, transform: "translate(12," + (T + B) / 2 + ") rotate(-90)", "text-anchor": "middle", cls: "muted", text: "Worst drawdown (log)" }));
  const guarded = c.points.filter((p) => p.arm !== "unguarded");
  svg.append(S("path", { d: guarded.map((p, i) => (i ? "L" : "M") + sx(p.x) + " " + sy(p.y)).join(" "), fill: "none", stroke: css("--accent"), "stroke-width": 2, "stroke-opacity": 0.5 }));
  c.points.forEach((p) => {
    const open = p.arm === "unguarded";
    const x = sx(p.x), y = sy(p.y);
    const dot = S("circle", { cx: x, cy: y, r: p.arm === "full" ? 7 : 5.5, fill: open ? css("--refuse") : css("--accent"), stroke: css("--surface"), "stroke-width": 2 });
    tipOn(dot, p.name + ": " + p.x_label + " honest filled, " + p.y_label + " worst drawdown"); svg.append(dot);
    const right = x < w * 0.7;
    svg.append(S("text", { x: right ? x + 11 : x - 11, y: y + 4, "text-anchor": right ? "start" : "end", cls: p.arm === "full" ? "strong" : null, text: p.name }));
  });
};

C.swarm = () => {
  const c = D.swarm_results;
  const narrow = $("#c-swarm").clientWidth < 640;
  const f = frame("c-swarm", { title: c.title, desc: c.desc, height: c.rows.length * (narrow ? 124 : 64) + 30, src: c.src,
    alt: c.rows.map((r) => r.name + ": " + r.stopped_label + " of " + r.total_label + " stopped; " + r.honest_label + " " + r.honest_what).join(". "),
    legend: [{ name: "Stopped by the mandate gate", color: css("--text-2") }, { name: "Stopped by the risk layer", color: css("--risk") }, { name: "Let through", color: css("--refuse") }, { name: "Honest orders sent to a person", color: css("--hold") }] });
  const { svg, w } = f;
  const split = narrow ? w : w * 0.66;
  const segCol = { gate: css("--text-2"), risk: css("--risk"), leak: css("--refuse") };
  const hx0 = narrow ? 0 : split + 32, hx1 = w - 44;
  const htop = c.honest_ticks[c.honest_ticks.length - 1].v;
  const hs = xscale(0, htop, hx0, hx1);
  if (!narrow) {
    svg.append(S("text", { x: 0, y: 12, cls: "muted", text: "Bad dollars that reached the gate" }));
    svg.append(S("text", { x: hx0, y: 12, cls: "muted", text: "Honest orders sent to a person" }));
  }
  c.rows.forEach((r, i) => {
    const y = narrow ? 8 + i * 124 : 30 + i * 64;
    svg.append(S("text", { x: 0, y: y + 12, cls: "strong", text: r.name }));
    if (narrow) { svg.append(S("text", { x: 0, y: y + 28, text: r.stopped_label + " of " + r.total_label + " stopped" })); }
    else svg.append(S("text", { x: split - 8, y: y + 12, "text-anchor": "end", text: r.stopped_label + " of " + r.total_label + " stopped" }));
    const by = narrow ? y + 36 : y + 20;
    const sx = xscale(0, r.total, 0, split - (narrow ? 0 : 8));
    let x = 0;
    for (const s of r.segs) {
      const bw = sx(s.v);
      if (bw > 0.5) { const b = hbar(x, by, Math.max(1, bw - 2), 18, segCol[s.k], s.k === "gate" ? 0 : 3); tipOn(b, r.name + ": " + s.label + (s.k === "gate" ? " stopped by the gate" : s.k === "risk" ? " stopped by the risk layer" : " let through")); svg.append(b); }
      x += bw;
    }
    const hy = narrow ? y + 84 : y + 29;
    if (narrow) svg.append(S("text", { x: 0, y: hy - 12, cls: "muted", "font-size": 11, text: "Honest orders sent to a person" }));
    svg.append(S("line", { x1: hx0, x2: hx1, y1: hy, y2: hy, cls: "gridl" }));
    for (const t of c.honest_ticks) svg.append(S("line", { x1: hs(t.v), x2: hs(t.v), y1: hy - 4, y2: hy + 4, cls: "axis" }));
    const d = S("circle", { cx: hs(r.honest * 100), cy: hy, r: 6, fill: css("--hold") }); tipOn(d, r.name + ": " + r.honest_label + " " + r.honest_what); svg.append(d);
    svg.append(S("text", { x: hs(r.honest * 100) + 10, y: hy + 4, cls: "strong", "font-size": 11.5, text: r.honest_label }));
  });
  const yl = narrow ? c.rows.length * 124 + 8 : 30 + c.rows.length * 64 - 10;
  for (const t of c.honest_ticks) svg.append(S("text", { x: hs(t.v), y: yl, "text-anchor": "middle", cls: "muted", "font-size": 11, text: t.label }));
};

C.review = () => {
  const c = D.review;
  const narrowR = $("#c-review").clientWidth < 560;
  const RH = narrowR ? 46 : 38;
  const f = frame("c-review", { title: c.title, desc: c.desc, height: c.rows.length * RH + 34, src: c.src,
    alt: c.rows.map((r) => r.name + ": " + r.label + " reviews (" + c.q99 + ": " + r.label99 + ")").join(". "),
    legend: [{ name: "Risk model's ordering", color: css("--accent") }, { name: "First in, first out", color: css("--text-3") }, { name: "Other orderings", color: css("--line-strong") }, { name: "Tick: reviews to open " + c.q99, color: css("--text-3") }] });
  const { svg, w } = f;
  const narrow = narrowR;
  const L = narrow ? 0 : 210, R = 60, B = c.rows.length * RH + 6;
  const top = c.ticks[c.ticks.length - 1].v;
  const sx = xscale(0, top, L, w - R);
  vgrid(svg, c.ticks, sx, 0, B);
  c.rows.forEach((r, i) => {
    const y = i * RH + (narrow ? 14 : 8);
    const col = r.k === "model" ? css("--accent") : r.k === "fifo" ? css("--text-3") : css("--line-strong");
    if (narrow) svg.append(S("text", { x: 0, y: y - 3, "font-size": 11.5, cls: r.k === "model" ? "strong" : null, text: r.name }));
    else svg.append(S("text", { x: 0, y: y + 13, cls: r.k === "model" ? "strong" : null, text: r.name }));
    const yy = narrow ? y + 2 : y;
    const b = hbar(L, yy, sx(r.v) - L, 18, col, 3); tipOn(b, r.name + ": " + r.label + " reviews to " + c.q90 + ", " + r.label99 + " to " + c.q99); svg.append(b);
    const tk = S("line", { x1: sx(r.v99), x2: sx(r.v99), y1: yy + 1, y2: yy + 17, stroke: css("--text-3"), "stroke-width": 2 }); tipOn(tk, r.name + ": " + r.label99 + " reviews to open " + c.q99); svg.append(tk);
    svg.append(S("text", { x: (narrow ? sx(r.v99) : sx(r.v)) + 6, y: yy + 13, cls: r.k === "model" ? "strong" : null, text: r.label }));
  });
};

/* ---------------------------------------------------------------- the order path diagram */
function pipe() {
  const svg = $("#pipe-svg");
  while (svg.childNodes.length > 2) svg.lastChild.remove();
  const w = Math.max(300, svg.parentNode.clientWidth), narrow = w < 640;
  const h = narrow ? 290 : 280;
  svg.setAttribute("viewBox", [0, 0, w, h].join(" "));
  svg.setAttribute("height", h);
  const fs = narrow ? 11 : 13;
  const my = narrow ? 130 : 120;
  const X = { agent: w * 0.07, check: w * (narrow ? 0.34 : 0.36), risk: w * (narrow ? 0.64 : 0.62), ledger: w * 0.92 };
  const line = css("--line-strong"), txt = css("--text"), t2 = css("--text-2");
  const g = S("g");
  svg.append(g);
  const path = (d, o) => g.append(S("path", Object.assign({ d, fill: "none", stroke: line, "stroke-width": 2 }, o || {})));
  path(["M", X.agent, my, "H", X.ledger].join(" "));
  // inputs into the check
  const inX = narrow ? [w * 0.14, w * 0.56] : [X.check - 120, X.check + 120];
  const inputs = [["Signed mandate", css("--accent")], ["Trusted price", css("--accent")]];
  inputs.forEach(([name, c], i) => {
    const x = inX[i], y = 34, tw = textW(name, fs) + 22;
    g.append(S("rect", { x: x - tw / 2, y: y - 14, width: tw, height: 28, rx: 14, fill: css("--accent-bg"), stroke: c }));
    g.append(S("text", { x, y: y + 4.5, "text-anchor": "middle", "font-size": fs, fill: txt, "font-weight": 600, text: name }));
    path(["M", x, y + 14, "C", x, my - 50, X.check, y + 40, X.check, my - 24].join(" "), { stroke: c, "stroke-dasharray": "4 4", "stroke-width": 1.5 });
  });
  // sinks below
  const sinkY = my + (narrow ? 118 : 112);
  const refX = narrow ? w * 0.17 : X.check - 90, revX = narrow ? w * 0.7 : (X.check + X.risk) / 2 + 30;
  const cv = (x0, x1, c) => path(["M", x0, my + 18, "C", x0 + (x1 - x0) * 0.6, my + 40, x1, sinkY - 50, x1, sinkY - 14].join(" "), { stroke: c, "stroke-width": 1.5 });
  cv(X.check - 14, refX, css("--refuse"));
  cv(X.check + 14, revX - 12, css("--hold"));
  cv(X.risk - 14, revX + 12, css("--risk"));
  const pills = {};
  const pill = (x, y, name, c, bg) => { const tw = textW(name, fs) + 20; pills[name] = x - tw / 2; g.append(S("rect", { x: x - tw / 2, y: y - 13, width: tw, height: 26, rx: 6, fill: bg, stroke: c })); g.append(S("text", { x, y: y + 4.5, "text-anchor": "middle", "font-size": fs, fill: txt, text: name })); };
  pill(refX, sinkY, narrow ? "Refused" : "Refused, with reasons", css("--refuse"), css("--refuse-bg"));
  pill(revX, sinkY, "Human review", css("--hold"), css("--hold-bg"));
  // nodes
  const node = (x, name, sub, c) => {
    g.append(S("circle", { cx: x, cy: my, r: 22, fill: css("--surface"), stroke: c, "stroke-width": 2 }));
    const halo = { stroke: css("--surface"), "stroke-width": 5, "paint-order": "stroke", "stroke-linejoin": "round" };
    g.append(S("text", Object.assign({ x, y: my + 42, "text-anchor": "middle", "font-size": fs, fill: txt, "font-weight": 600, text: name }, halo)));
    if (sub && !narrow) g.append(S("text", Object.assign({ x, y: my + 59, "text-anchor": "middle", "font-size": fs - 1, fill: t2, text: sub }, halo)));
  };
  node(X.agent, "Agent order", "any model", line);
  node(X.check, "Mandate check", "code, L5", css("--text"));
  node(X.risk, "Risk layer", "can only tighten", css("--risk"));
  node(X.ledger, "Ledger", "receiver, L8", css("--allow"));
  g.append(S("text", { x: X.agent, y: my + 5, "text-anchor": "middle", "font-size": 14, fill: t2, text: "◆" }));
  g.append(S("text", { x: X.check, y: my + 5, "text-anchor": "middle", "font-size": 13, fill: txt, "font-weight": 700, text: "L5" }));
  g.append(S("text", { x: X.ledger, y: my + 6, "text-anchor": "middle", "font-size": 16, fill: css("--allow"), text: "✓" }));
  g.append(S("text", { x: X.risk, y: my + 5, "text-anchor": "middle", "font-size": 14, fill: css("--risk"), text: "↓" }));
  // tokens
  const tokens = S("g");
  svg.append(tokens);
  const label = $("#pipe-now");
  const trips = [
    { name: "An honest order inside the limits reaches the ledger.", stops: [[X.agent, my], [X.check, my], [X.risk, my], [X.ledger, my]], end: css("--allow"), shape: "c" },
    { name: "The forged-split order is refused at the trusted price.", stops: [[X.agent, my], [X.check, my], [refX, sinkY - 28]], end: css("--refuse"), shape: "d" },
    { name: "A colluding slice fits the limits, so the risk layer holds it for a person.", stops: [[X.agent, my], [X.check, my], [X.risk, my], [revX + 12, sinkY - 28]], end: css("--risk"), shape: "d" },
  ];
  pipe.state = { trips, tokens, label, t0: performance.now(), w };
  if (reduce.matches) {
    trips.forEach((tr, i) => drawToken(tokens, tr.stops[tr.stops.length - 1], tr.end, tr.shape, i));
    label.textContent = "Honest orders reach the ledger; the forged split is refused; a colluding slice is held for a person.";
  }
}
function drawToken(g, p, color, shape) {
  const n = shape === "d" ? S("path", { d: ["M", p[0], p[1] - 8, "l", 8, 8, "l", -8, 8, "l", -8, -8, "Z"].join(" "), fill: color, stroke: css("--surface"), "stroke-width": 2 })
    : S("circle", { cx: p[0], cy: p[1], r: 7, fill: color, stroke: css("--surface"), "stroke-width": 2 });
  g.append(n);
}
let pipeVisible = false;
function pipeTick(now) {
  const st = pipe.state;
  if (st && pipeVisible && !reduce.matches) {
    const per = 3600, t = (now - st.t0) % (per * st.trips.length);
    const k = Math.floor(t / per), u = (t % per) / per;
    const tr = st.trips[k];
    st.tokens.textContent = "";
    const legs = tr.stops.length - 1, travel = Math.min(1, u / 0.75), pos = travel * legs;
    const i = Math.min(legs - 1, Math.floor(pos)), f = pos - i;
    const a = tr.stops[i], b = tr.stops[i + 1];
    const ease = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
    const p = [a[0] + (b[0] - a[0]) * ease, a[1] + (b[1] - a[1]) * ease];
    drawToken(st.tokens, p, travel >= 1 ? tr.end : css("--text-2"), tr.shape);
    if (st.label.textContent !== tr.name) st.label.textContent = tr.name;
  }
  requestAnimationFrame(pipeTick);
}

/* ---------------------------------------------------------------- hero: the recorded swarm, replayed */
const hero = { running: true, visible: true, userPaused: false };
function heroSetup() {
  const sw = D.swarm, cv = $("#swarm"), ctx = cv.getContext("2d");
  const keys = sw.keys, K = (k) => keys.indexOf(k);
  const cum = { orders: [], bad: [], leak: [] };
  let o = 0, b = 0, l = 0;
  sw.counts.forEach((row, i) => { o += row.reduce((a, x) => a + x, 0); b += sw.bad_usd_cents[i]; l += sw.leak_usd_cents[i]; cum.orders.push(o); cum.bad.push(b); cum.leak.push(l); });
  const nf = new Intl.NumberFormat("en-US"), mf = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (cents) => (cents >= 1e8 ? "$" + mf.format(cents / 1e8) + "M" : "$" + nf.format(Math.round(cents / 100)));
  $("#m-days").textContent = " of " + sw.days;
  let W = 0, H = 0, dpr = 1, agents = [], dots = [], ledger = 0, tray = [], colors = {};
  const ledgerPer = Math.max(1, Math.round(sw.counts.reduce((a, r) => a + r[K("allow")], 0) / 1400));
  function size() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    agents = [];
    const n = W < 500 ? 420 : 1000;
    for (let i = 0; i < n; i++) {
      const r = Math.sqrt(rnd()), th = rnd() * Math.PI * 2;
      agents.push({ x: W * 0.17 + Math.cos(th) * r * W * 0.13, y: H * 0.5 + Math.sin(th) * r * H * 0.3, ph: rnd() * 6.28 });
    }
    colors = { allowBg: css("--allow-bg"), holdBg: css("--hold-bg"), text: css("--text"), text2: css("--text-2"), dot: css("--dot"), text3: css("--text-3"), allow: css("--allow"), hold: css("--hold"), refuse: css("--refuse"), risk: css("--risk"), line: css("--line-strong"), surface: css("--surface") };
  }
  const G = () => W * 0.44, RK = () => W * 0.63, LX = () => W * 0.73;
  const LOOP = 48000, binDur = LOOP / sw.bins;
  let t0 = performance.now(), last = -1, spawnQ = [];
  const sample = () => (W < 500 ? 3 : W < 900 ? 2 : 1);
  function spawnBin(bi) {
    const row = sw.counts[bi], list = [];
    keys.forEach((k, ki) => { for (let i = 0; i < row[ki]; i++) list.push(k); });
    const s = sample();
    for (let i = 0; i < list.length; i += s) {
      const a = agents[(bi * 131 + i * 17) % agents.length];
      spawnQ.push({ at: bi * binDur + (i / list.length) * binDur, k: list[i], x: a.x, y: a.y });
    }
  }
  function startBin(bi) {
    if (bi === 0) { ledger = 0; tray = []; dots = []; }
    spawnBin(bi);
    const day = Math.min(Number(sw.days), Math.floor((bi * sw.steps / sw.bins) / sw.steps_per_day) + 1);
    $("#m-day").textContent = String(day);
    $("#m-orders").textContent = nf.format(cum.orders[bi]);
    $("#m-bad").textContent = money(cum.bad[bi]);
    $("#m-leak").textContent = money(cum.leak[bi]);
  }
  function final() {
    const lastBin = sw.bins - 1;
    $("#m-day").textContent = sw.days;
    $("#m-orders").textContent = sw.orders;
    $("#m-bad").textContent = sw.bad_total;
    $("#m-leak").textContent = D.swarm.facts.leak_after.text;
    ledger = sw.counts.reduce((a, r) => a + r[K("allow")], 0);
    tray = [];
    sw.counts.forEach((r) => { for (let i = 0; i < r[K("hold")]; i++) tray.push("hold"); for (let i = 0; i < r[K("risk")]; i++) tray.push("risk"); });
    return lastBin;
  }
  function drawStatic(now) {
    ctx.clearRect(0, 0, W, H);
    // agents
    ctx.fillStyle = colors.dot;
    for (const a of agents) { const j = reduce.matches ? 0 : Math.sin(now / 900 + a.ph) * 1.2; ctx.globalAlpha = 0.55; ctx.fillRect(a.x + j, a.y - j, 1.6, 1.6); }
    ctx.globalAlpha = 1;
    // zones: ledger and review tray
    ctx.fillStyle = colors.allowBg; ctx.fillRect(LX(), 0, W - LX(), H);
    ctx.fillStyle = colors.holdBg; ctx.fillRect(W * 0.34, H - 46, LX() - W * 0.34, 46);
    // gate and risk lines
    ctx.lineWidth = 2; ctx.strokeStyle = colors.text; ctx.globalAlpha = 0.8;
    ctx.beginPath(); ctx.moveTo(G(), 34); ctx.lineTo(G(), H - 52); ctx.stroke();
    ctx.setLineDash([5, 5]); ctx.strokeStyle = colors.risk;
    ctx.beginPath(); ctx.moveTo(RK(), 34); ctx.lineTo(RK(), H - 52); ctx.stroke();
    ctx.setLineDash([]); ctx.globalAlpha = 1;
    // ledger blocks
    const lx0 = LX() + 12, lx1 = W - 14, ly0 = 40, ly1 = H - 16;
    const cell = W < 500 ? 4 : 5, cols = Math.max(1, Math.floor((lx1 - lx0) / cell)), rows = Math.floor((ly1 - ly0) / cell);
    const blocks = Math.min(cols * rows, Math.floor(ledger / ledgerPer));
    ctx.fillStyle = colors.allow;
    for (let i = 0; i < blocks; i++) {
      const r = Math.floor(i / cols), c = i % cols;
      ctx.globalAlpha = i > blocks - cols ? 0.95 : 0.42;
      ctx.fillRect(lx0 + c * cell, ly1 - (r + 1) * cell, cell - 1, cell - 1);
    }
    ctx.globalAlpha = 1;
    // review tray
    const tx0 = W * 0.34 + 14, tx1 = LX() - 8, ty = H - 34;
    const tcols = Math.max(1, Math.floor((tx1 - tx0) / 4));
    tray.slice(-tcols * 3).forEach((k, i) => {
      ctx.fillStyle = k === "risk" ? colors.risk : colors.hold;
      ctx.fillRect(tx0 + (i % tcols) * 4, ty - Math.floor(i / tcols) * 4, 3, 3);
    });
  }
  function shape(d, x, y, r) {
    if (d.bad) { ctx.beginPath(); ctx.moveTo(x, y - r - 1); ctx.lineTo(x + r + 1, y); ctx.lineTo(x, y + r + 1); ctx.lineTo(x - r - 1, y); ctx.closePath(); ctx.fill(); }
    else { ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill(); }
  }
  function frame(now) {
    requestAnimationFrame(frame);
    if (!hero.running || !hero.visible) { t0 += 16; return; }
    const t = (((now - t0) % LOOP) + LOOP) % LOOP;
    const bi = Math.floor(t / binDur);
    if (bi !== last) { if (bi < last) spawnQ = []; startBin(bi); last = bi; }
    while (spawnQ.length && spawnQ[0].at <= t) {
      const s = spawnQ.shift();
      const bad = s.k === "gate" || s.k === "risk" || s.k === "leak" || s.k === "dup";
      dots.push({ k: s.k, bad, x: s.x, y: s.y, tx: G(), ty: H * 0.5 + (s.y - H * 0.5) * 0.55, v: 0.22 + Math.random() * 0.08, phase: 0, life: 0 });
    }
    drawStatic(now);
    const next = [];
    for (const d of dots) {
      d.life += 16;
      if (d.phase === 0) {
        const dx = d.tx - d.x, dy = d.ty - d.y, dist = Math.hypot(dx, dy), step = d.v * 16 * (W / 700);
        if (dist <= step) {
          d.x = d.tx; d.y = d.ty;
          if (d.k === "allow" || d.k === "leak") { d.phase = 1; d.tx = d.k === "allow" ? LX() + 10 : W; d.ty = d.y; }
          else if (d.k === "risk") { d.phase = 1; d.tx = RK(); d.ty = d.y; }
          else if (d.k === "hold") { d.phase = 3; d.tx = d.x + 10 + Math.random() * (LX() - G() - 30); d.ty = H - 34; }
          else { d.phase = 2; d.vx = -(1.2 + Math.random()); d.vy = (Math.random() - 0.5) * 1.6; d.fade = 1; }
        } else { d.x += (dx / dist) * step; d.y += (dy / dist) * step; }
      } else if (d.phase === 1) {
        const step = d.v * 16 * (W / 700); d.x += step;
        if (d.x >= d.tx) {
          if (d.k === "allow") { ledger += sample(); continue; }
          if (d.k === "risk") { d.phase = 3; d.tx = d.x - Math.random() * (RK() - G() - 20); d.ty = H - 34; d.k = "risk"; }
          if (d.k === "leak") continue;
        }
      } else if (d.phase === 2) {
        d.x += d.vx; d.y += d.vy; d.fade -= 0.025; if (d.fade <= 0) continue;
      } else if (d.phase === 3) {
        d.x += (d.tx - d.x) * 0.08; d.y += (d.ty - d.y) * 0.08;
        if (Math.abs(d.ty - d.y) < 1.5) { for (let i = 0; i < sample(); i++) tray.push(d.k === "risk" ? "risk" : "hold"); continue; }
      }
      const decided = d.phase > 0 && !(d.k === "risk" && d.phase === 1);
      const c = !decided ? (d.bad ? colors.text2 : colors.dot) : d.k === "allow" ? colors.allow : d.k === "hold" ? colors.hold : d.k === "risk" ? colors.risk : d.k === "dup" ? colors.line : colors.refuse;
      ctx.fillStyle = c;
      ctx.globalAlpha = d.phase === 2 ? Math.max(0, d.fade) : !decided ? 0.85 : d.k === "allow" ? 0.7 : 1;
      shape(d, d.x, d.y, d.bad ? 2.6 : 2);
      next.push(d);
    }
    ctx.globalAlpha = 1;
    dots = next;
  }
  size();
  addEventListener("resize", () => { const w = cv.clientWidth; if (Math.abs(w - W) > 2) { size(); if (reduce.matches || hero.userPaused) drawStatic(0); } });
  const btn = $("#stage-pause");
  if (reduce.matches) {
    hero.running = false; final(); drawStatic(0);
    btn.hidden = true;
  } else {
    requestAnimationFrame(frame);
  }
  btn.addEventListener("click", () => {
    hero.userPaused = !hero.userPaused; hero.running = !hero.userPaused;
    btn.textContent = hero.userPaused ? "Play" : "Pause"; btn.setAttribute("aria-pressed", String(hero.userPaused));
  });
  new IntersectionObserver((es) => { hero.visible = es[0].isIntersecting; }).observe(cv);
  document.addEventListener("visibilitychange", () => { hero.visible = !document.hidden; });
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
function drawAll() {
  for (const k of Object.keys(C)) { try { C[k](); } catch (e) { console.error("chart " + k, e); } }
  pipe();
}
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
  heroSetup();
  new IntersectionObserver((es) => { pipeVisible = es[0].isIntersecting; }, { threshold: 0.3 }).observe($("#pipe"));
  requestAnimationFrame(pipeTick);
  let lastW = innerWidth, tm = 0;
  addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => { if (innerWidth !== lastW) { lastW = innerWidth; drawAll(); } }, 150); });
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
}
boot();
