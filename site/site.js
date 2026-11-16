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

/* ---------------------------------------------------------------- shared formatting */
const NF = new Intl.NumberFormat("en-US"), MF = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usdShort = (v) => (v >= 1e6 ? "$" + MF.format(v / 1e6) + "M" : "$" + NF.format(Math.round(v)));
const pad2 = (n) => String(n).padStart(2, "0");

/* ---------------------------------------------------------------- hero console: a recorded episode, replayed */
function consoleSetup() {
  if (!$("#c-chart")) return;
  const R = D.console, cv = $("#c-chart"), ctx = cv.getContext("2d");
  const N = R.steps, main = R.strip[0].px, spd = D.swarm.steps_per_day, env = R.envelope;
  const byStep = Array.from({ length: N }, () => []);
  R.orders.forEach((o) => byStep[o.s].push(o));
  // the strip
  const strip = $("#c-strip"), sparks = [];
  R.strip.forEach((m) => {
    const sc = el("canvas", { "aria-hidden": "true" }), p = el("span", { cls: "p" }), ch = el("span", { cls: "ch" });
    strip.append(el("li", {}, [el("span", { cls: "s", text: m.sym }), sc, el("span", {}, [p, " ", ch])]));
    sparks.push({ m, sc, p, ch });
  });
  $$("#c-checks").forEach((ul) => { for (const c of R.focus.checks) ul.append(el("li", { text: c })); });
  const feed = $("#c-feed"), alert = $("#c-alert"), btn = $("#c-pause");
  let k = 0, running = !reduce.matches, visible = true, timer = 0, W = 0, H = 0;
  const lo = Math.min(...main) * 0.996, hi = Math.max(...main) * 1.004;
  function size() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const col = { allowed: "--allow", stopped: "--risk", refused: "--refuse", held: "--hold" };
  function drawChart() {
    const padL = 8, padR = 56, padT = 8, padB = 22;
    const x = (i) => padL + (i / (N - 1)) * (W - padL - padR), y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);
    ctx.clearRect(0, 0, W, H);
    ctx.font = "11px " + css("--sans"); ctx.textBaseline = "middle";
    ctx.strokeStyle = css("--grid"); ctx.fillStyle = css("--text-3"); ctx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
      const v = lo + ((hi - lo) * g) / 4, yy = Math.round(y(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(W - padR, yy); ctx.stroke();
      ctx.textAlign = "left"; ctx.fillText(MF.format(v), W - padR + 8, yy);
    }
    // orders, where each was priced
    for (let i = 0; i <= k; i++) {
      byStep[i].forEach((o, j) => {
        ctx.globalAlpha = i > k - 3 ? 1 : 0.55; ctx.fillStyle = css(col[o.v]);
        ctx.beginPath(); ctx.arc(x(i) + ((j % 3) - 1) * 1.5, y(o.limit), o.v === "allowed" ? 2 : 2.6, 0, 6.2832); ctx.fill();
      });
    }
    ctx.globalAlpha = 1;
    // the focus moment
    if (k >= R.focus_step) {
      const fx = Math.round(x(R.focus_step)) + 0.5;
      ctx.strokeStyle = css("--risk"); ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(fx, padT); ctx.lineTo(fx, H - padB); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = css("--risk"); ctx.textAlign = "left"; ctx.fillText(R.title, fx + 6, padT + 8);
    }
    // the price
    ctx.beginPath();
    for (let i = 0; i <= k; i++) { const xx = x(i), yy = y(main[i]); if (i) ctx.lineTo(xx, yy); else ctx.moveTo(xx, yy); }
    ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2; ctx.stroke();
    ctx.lineTo(x(k), H - padB); ctx.lineTo(x(0), H - padB); ctx.closePath(); ctx.globalAlpha = 0.07; ctx.fillStyle = css("--accent"); ctx.fill(); ctx.globalAlpha = 1;
    ctx.fillStyle = css("--accent"); ctx.beginPath(); ctx.arc(x(k), y(main[k]), 4, 0, 6.2832); ctx.fill();
  }
  function drawSpark(sp) {
    const c = sp.sc, w = c.clientWidth, h = c.clientHeight;
    if (!w) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1), g = c.getContext("2d");
    if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    const v = sp.m.px.filter((x) => x != null), a = Math.min(...v), b = Math.max(...v);
    const up = sp.m.px[k] >= sp.m.px[0];
    g.beginPath();
    for (let i = 0; i <= k; i++) { const xx = (i / (N - 1)) * w, yy = h - 2 - ((sp.m.px[i] - a) / (b - a || 1)) * (h - 4); if (i) g.lineTo(xx, yy); else g.moveTo(xx, yy); }
    g.strokeStyle = css(up ? "--allow" : "--refuse"); g.lineWidth = 1.5; g.stroke();
  }
  function feedPush(i) {
    const list = byStep[i];
    if (!list.length) return;
    const o = list.find((x) => x.v !== "allowed" && i % 2) || list[i % list.length];
    feed.prepend(el("li", {}, [
      el("span", { cls: "o", text: o.side.toUpperCase() + " " + o.qty + " " + R.sym + " · " + o.usd }),
      el("span", { cls: "pill " + o.v, text: o.v.charAt(0).toUpperCase() + o.v.slice(1) }),
      el("span", { cls: "a", text: o.agent + (o.why ? " · " + o.why : "") })]));
    while (feed.children.length > 9) feed.lastElementChild.remove();
  }
  function render() {
    const st = R.first_step + k, mins = Math.floor(((st % spd) * 390) / spd) + 570;
    $("#c-clock").textContent = "Day " + (Math.floor(st / spd) + 1) + " · " + pad2(Math.floor(mins / 60)) + ":" + pad2(mins % 60);
    $("#c-px").textContent = MF.format(main[k]);
    sparks.forEach((sp) => {
      const v = sp.m.px[k], d = (v / sp.m.px[0] - 1) * 100;
      sp.p.textContent = MF.format(v);
      sp.ch.textContent = (d >= 0 ? "+" : "") + d.toFixed(2) + "%"; sp.ch.className = "ch " + (d >= 0 ? "up" : "down");
      drawSpark(sp);
    });
    $("#c-comb").textContent = usdShort(R.combined[k]);
    $("#c-ags").textContent = String(R.agents[k]);
    $("#c-fill").style.width = Math.min(100, (R.combined[k] / env.daily_n) * 100) + "%";
    alert.hidden = k < R.focus_step;
    drawChart();
  }
  function tick() {
    if (running && visible && !document.hidden) {
      k += 1;
      if (k >= N) { k = 0; feed.textContent = ""; }
      feedPush(k);
      render();
    }
    timer = setTimeout(tick, k === N - 1 ? 2600 : 190);
  }
  size();
  if (reduce.matches) {
    k = N - 1; for (let i = N - 9; i < N; i++) feedPush(i); render(); btn.hidden = true;
  } else {
    for (let i = 0; i < 6; i++) { k = i; feedPush(i); }
    render(); tick();
  }
  btn.addEventListener("click", () => {
    running = !running; btn.textContent = running ? "Pause" : "Play"; btn.setAttribute("aria-pressed", String(!running));
  });
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; }).observe(cv);
  addEventListener("resize", () => { size(); render(); });
  consoleRedraw = render;
}
let consoleRedraw = () => {};

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
function timeline() {
  // a cancellable chain of timed steps, so a demo can be restarted cleanly
  let ids = [];
  return {
    at(ms, fn) { ids.push(setTimeout(fn, ms)); },
    clear() { ids.forEach(clearTimeout); ids = []; },
  };
}

/* ---------------------------------------------------------------- hero: five agents, one position */
function authDemo() {
  const box = $("#auth");
  if (!box) return;
  const sw = D.flows.swarm, env = D.console.envelope, list = $("#auth-orders");
  const slice = money(sw.slice), limit = env.per_order_n, total = $("#auth-total"), fill = $("#auth-fill");
  const verdict = $("#auth-verdict"), vh = $("#auth-v-head"), vb = $("#auth-v-body"), add = $("#auth-add"), count = $("#auth-count");
  const max = sw.agents.length * slice * 1.04;
  env.symbols.forEach((s) => $("#auth-syms").append(el("span", { text: s })));
  $("#auth-limit").style.left = (limit / max) * 100 + "%";
  $("#auth-limit-l").style.left = (limit / max) * 100 + "%";
  const T = timeline();
  let n = 0, auto = true;
  function set(state, head, body) { verdict.dataset.state = state; vh.textContent = head; vb.textContent = body; }
  function paint() {
    const v = n * slice;
    total.textContent = n === sw.agents.length ? sw.combined : usdN(v);
    fill.style.width = (v / max) * 100 + "%";
    fill.classList.toggle("over", v > limit);
    count.textContent = n ? n + " of " + sw.agents.length : "";
    add.disabled = n >= sw.agents.length;
    if (n < 2) set("pass", "Each order is inside the mandate", "Every per-order check passes: symbol, size, approval threshold, price band.");
    else set(v > limit ? "warn" : "pass", "Each order still passes every check",
      "Together they are already " + (v / limit).toFixed(1) + "× the per-order limit, on the same stock and side.");
  }
  function addOne() {
    if (n >= sw.agents.length) return;
    const li = el("li", { cls: "in" }, [el("span", { cls: "a-ag", text: "agent-" + pad4(sw.agents[n]) }), el("span", { cls: "a-ord", text: sw.order }),
      el("span", { cls: "a-usd", text: sw.slice }), el("span", { cls: "pill allowed", text: "Passes limits" })]);
    list.append(li);
    n += 1;
    paint();
    if (n === sw.agents.length) T.at(reduce.matches ? 0 : 1100, held);
  }
  function held() {
    $$("#auth-orders .pill").forEach((p) => { p.className = "pill stopped"; p.textContent = "Held"; });
    set("hold", "Held for a person · risk " + sw.risk, sw.reason + ". One position, split across agents to stay under the approval threshold.");
    box.classList.add("done");
  }
  function reset() {
    T.clear(); list.textContent = ""; n = 0; box.classList.remove("done"); paint();
  }
  function play() {
    reset();
    for (let i = 0; i < sw.agents.length; i++) T.at(500 + i * 1000, addOne);
  }
  add.addEventListener("click", () => { auto = false; if (n === 0) T.clear(); addOne(); });
  $("#auth-replay").addEventListener("click", () => { auto = true; play(); });
  if (reduce.matches) { reset(); for (let i = 0; i < sw.agents.length; i++) addOne(); return; }
  reset();
  let started = false;
  onView(box, (vis) => { if (vis && !started && auto) { started = true; play(); } });
}

/* ---------------------------------------------------------------- signed mandate: the real document, annotated */
function mandateJson() {
  const box = $("#mj");
  if (!box) return;
  const M = D.layers.mandate, md = D.mandate_demo, T = timeline();
  const lines = $("#mj-lines"), note = $("#mj-note"), state = $("#mj-state");
  $("#mj-name").textContent = "Mandate " + M.name;
  $("#mj-purpose").textContent = M.purpose;
  let mode = "read", vis = false, hover = false;
  const short = (v) => (typeof v === "string" && v.length > 28 ? v.slice(0, 12) + "…" + v.slice(-8) : v);
  function val(v) {
    if (Array.isArray(v)) return el("span", { cls: "mj-arr" }, v.map((x) => el("span", { cls: "chip", "data-s": x, text: x })));
    if (typeof v === "number") return el("span", { cls: "mj-num", text: String(v) });
    return el("span", { cls: "mj-str", text: JSON.stringify(short(v)) });
  }
  function render(rows) {
    lines.textContent = "";
    lines.append(el("li", { cls: "mj-brace", text: "{" }));
    rows.forEach((r, i) => {
      const li = el("li", { cls: "mj-row", "data-k": r.k }, [el("span", { cls: "mj-k", text: JSON.stringify(r.k) + ": " }), val(r.v), i < rows.length - 1 ? "," : ""]);
      li.addEventListener("mouseenter", () => { if (mode === "read") { hover = true; focus(li, r.note); } });
      li.addEventListener("mouseleave", () => { hover = false; });
      lines.append(li);
    });
    lines.append(el("li", { cls: "mj-brace", text: "}" }));
  }
  function focus(li, text, cls) {
    $$(".mj-row", lines).forEach((x) => x.classList.toggle("on", x === li));
    note.textContent = text; note.className = "mj-note " + (cls || "");
  }
  const row = (k) => $('.mj-row[data-k="' + k + '"]', lines);
  function pill(cls, text) { state.className = "pill " + cls; state.textContent = text; }
  function runRead() {
    render(M.rows); pill("allowed", "Signature valid"); box.dataset.state = "ok";
    const rs = $$(".mj-row", lines);
    rs.forEach((li, i) => T.at(i * 2200, () => { if (!hover) focus(li, M.rows[i].note); }));
    T.at(rs.length * 2200 + 400, () => { if (vis && mode === "read") runRead(); });
  }
  function runEdit() {
    render(M.rows); pill("allowed", "Signature valid"); box.dataset.state = "ok";
    focus(row("signature"), "Signed with the owner's key. Agents get a reference to the mandate, never the key.");
    T.at(2000, () => {
      const li = row("maxOrderNotionalUsd"), n = $(".mj-num", li);
      n.textContent = String(money(md.parent_per_order)); n.classList.add("edited");
      focus(li, "agent-" + pad4(D.flows.swarm.agents[3]) + " raises its own per-order limit.", "warn");
    });
    T.at(4000, () => {
      row("signature").classList.add("bad"); box.dataset.state = "bad"; pill("refused", "Signature broken");
      focus(row("signature"), "The signature no longer matches what the owner signed. Every order under it is refused, and nothing reaches the market.", "bad");
    });
    T.at(10000, () => { if (vis && mode === "edit") runEdit(); });
  }
  function runDraft() {
    const K = { "Per order": "maxOrderNotionalUsd", "Per day": "maxDailyNotionalUsd", "Sides": "sides", "Price band": "priceBandPct", "Person approves above": "stepUpAboveUsd" };
    const rows = [{ k: "purpose", v: md.purpose_full }, { k: "symbols", v: md.symbols }].concat(md.kv.map(([k, v]) => ({
      k: K[k] || k, v: K[k] === "sides" ? v.split(" and ") : money(v) }))).filter((r) => r.k !== "priceBandPct");
    render(rows); pill("held", "Draft, reviewing"); box.dataset.state = "ok";
    focus(row("purpose"), "An agent drafts a narrower mandate for one task. Code proves every limit sits inside the one you signed.");
    const chips = $$(".chip", row("symbols"));
    chips.forEach((c, i) => T.at(2200 + i * 600, () => {
      chips.forEach((x) => x.classList.remove("scan")); c.classList.add("scan");
      if (md.extra.includes(c.dataset.s)) c.classList.add("flag");
    }));
    const t = 2200 + chips.length * 600 + 200;
    T.at(t, () => { chips.forEach((x) => x.classList.remove("scan")); focus(row("symbols"), "Decision adapter, post-trained on an underlying decision model: " + md.concern + ".", "warn"); });
    T.at(t + 2600, () => {
      chips.filter((c) => md.extra.includes(c.dataset.s)).forEach((c) => c.classList.add("cut"));
      pill("refused", "Sent back"); box.dataset.state = "bad";
      focus(row("symbols"), "Sent back to the agent with the reason. The owner is asked to sign " + md.kept.join(" and ") + " only.", "bad");
    });
    T.at(t + 9000, () => { if (vis && mode === "draft") runDraft(); });
  }
  const run = () => { T.clear(); hover = false; ({ read: runRead, edit: runEdit, draft: runDraft })[mode](); };
  const tabs = $$("#mj-tabs [role=tab]");
  tabs.forEach((b) => b.addEventListener("click", () => { mode = b.dataset.k; tabs.forEach((x) => x.setAttribute("aria-selected", String(x === b))); run(); }));
  run();
  if (!reduce.matches) onView(box, (v) => { const was = vis; vis = v; if (v && !was) run(); });
}

/* ---------------------------------------------------------------- trusted data: what an order relies on, checked */
function factsCheck() {
  const box = $("#facts");
  if (!box) return;
  const L = D.layers, rum = D.flows.flows.find((f) => f.end === "person" && f.steps[0][0] === "hold");
  const PILL = { confirmed: ["allowed", "Matches the filing"], contradicted: ["refused", "Contradicted"] };
  const items = [
    ["Price", L.price.agent + " · " + L.price.order, ["allowed", "Within the band"], L.price.check.replace(/^Price: /, "") + ". " + L.price.size.replace(/^Size: /, "") + "."],
    ...L.figures.map((f) => ["Filing figure", "Agent cites " + f.claim, PILL[f.status] || ["held", f.status], f.status === "contradicted" ? "The filing reports " + f.truth + ". The order is refused." : "Checked against the company's filing."]),
    ["News", rum ? rum.agent + " · " + rum.order : "", ["held", "Held"], rum ? rum.steps[0][1] + "." : ""],
  ];
  const T = timeline();
  function run() {
    T.clear(); box.textContent = "";
    items.forEach(([kind, what, [cls, verdict], why], i) => T.at(reduce.matches ? 0 : 200 + i * 900, () => box.append(el("li", { cls: "in" }, [
      el("p", { cls: "fx-top" }, [el("span", { cls: "fx-kind", text: kind }), el("span", { cls: "grow" }), el("span", { cls: "pill " + cls, text: verdict })]),
      el("p", { cls: "fx-what", text: what }), el("p", { cls: "fx-why", text: why })]))));
  }
  run();
  if (!reduce.matches) { let vis = false; onView(box, (v) => { const was = vis; vis = v; if (v && !was) run(); }); }
}

/* ---------------------------------------------------------------- film segments pinned to each layer */
function clips() {
  for (const fig of $$("figure.clip")) {
    const c = D.layers.clips[fig.dataset.clip], v = $("video", fig);
    if (!c || !v) continue;
    const [name, a, b] = c;
    v.poster = "media/og-" + name + ".jpg";
    v.src = "media/og-" + name + ".mp4#t=" + a + "," + b;
    v.addEventListener("loadedmetadata", () => { v.currentTime = a; });
    v.addEventListener("timeupdate", () => { if (v.currentTime >= b || v.currentTime < a - 0.5) v.currentTime = a; });
    if (reduce.matches) { v.controls = true; continue; }
    onView(fig, (vis) => { if (vis) v.play().catch(() => {}); else v.pause(); }, 0.4);
  }
}

/* ---------------------------------------------------------------- results, each with its context */
function proofGrid() {
  const box = $("#proof-grid");
  if (!box) return;
  for (const o of D.layers.outcomes) box.append(el("div", { cls: "p-item" }, [el("p", { cls: "p-big", text: o.big }), el("p", { cls: "p-lab", text: o.label }),
    el("p", { cls: "p-ctx", text: o.ctx }), el("a", { cls: "src", href: fileHref(o.src), text: o.src })]));
}

/* ---------------------------------------------------------------- risk: one order through the five stops */
function flowScene() {
  const svg = $("#flow-svg");
  if (!svg) return;
  const F = D.flows, st = F.stations, W = 560, H = 150, x0 = 48, x1 = W - 48, y = 64;
  const xs = st.map((_, i) => x0 + (i * (x1 - x0)) / (st.length - 1));
  svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  const head = el("p", { cls: "flow-order" });
  svg.before(head);
  svg.append(S("line", { x1: x0, y1: y, x2: x1, y2: y, cls: "f-track" }));
  const prog = S("line", { x1: x0, y1: y, x2: x0, y2: y, cls: "f-prog" });
  svg.append(prog);
  const nodes = xs.map((x, i) => {
    const g = S("g", { cls: "f-st" }, [S("circle", { cx: x, cy: y, r: 13 }), S("text", { x, y: y + 4, "text-anchor": "middle", cls: "f-ic", text: "" }),
      S("text", { x, y: y + 36, "text-anchor": "middle", cls: "f-lb" }, st[i].split(" ").length > 2
        ? [S("tspan", { x, dy: 0, text: st[i].split(" ").slice(0, 2).join(" ") }), S("tspan", { x, dy: 14, text: st[i].split(" ").slice(2).join(" ") })]
        : [S("tspan", { x, text: st[i] })])]);
    svg.append(g);
    return g;
  });
  const tok = S("circle", { cx: x0, cy: y, r: 20, cls: "f-tok" });
  svg.append(tok);
  const cap = $("#flow-cap"), checks = $("#flow-checks"), tabs = $("#flow-tabs");
  const ICON = { pass: "✓", stop: "✕", hold: "‖", note: "!", idle: "" };
  const T = timeline();
  let cur = 0, cycling = true, vis = false;
  F.flows.forEach((f, i) => {
    const b = el("button", { type: "button", role: "tab", "aria-selected": String(i === 0), text: f.name });
    b.addEventListener("click", () => { cycling = false; show(i); });
    tabs.append(b);
  });
  function setNode(i, s) { nodes[i].setAttribute("class", "f-st " + s); nodes[i].querySelector(".f-ic").textContent = ICON[s] || ""; }
  function moveTo(x, s) { tok.setAttribute("cx", x); tok.setAttribute("class", "f-tok " + (s || "")); prog.setAttribute("x2", x); }
  function show(i) {
    T.clear();
    cur = i;
    const f = F.flows[i];
    $$("button", tabs).forEach((b, j) => b.setAttribute("aria-selected", String(j === i)));
    head.textContent = "";
    head.append(el("span", { cls: "f-ag", text: f.agent }), el("b", { text: f.order }));
    nodes.forEach((_, j) => setNode(j, "wait"));
    checks.textContent = "";
    cap.textContent = "Order sent";
    cap.className = "flow-cap";
    moveTo(x0 - 30, "");
    const step = reduce.matches ? 0 : 1300;
    let t = 300, stopped = false;
    f.steps.forEach(([s, text], j) => {
      if (stopped) return;
      T.at(t, () => {
        moveTo(xs[j], s === "idle" ? "" : s);
        setNode(j, s === "idle" ? "skip" : s);
        if (text) { cap.textContent = ""; cap.append(el("small", { text: st[j] }), text); cap.className = "flow-cap " + s; }
        if (j === 1 && f.checks.length) f.checks.forEach((c, k) => T.at(k * 120, () => checks.append(el("li", { cls: "in", text: c }))));
      });
      t += s === "idle" ? step * 0.45 : step;
      if (s === "stop" && f.end === "refused") stopped = true;
    });
    T.at(t + 200, () => { if (f.end === "refused") nodes.forEach((n, j) => { if (n.getAttribute("class") === "f-st wait") setNode(j, "skip"); }); });
    if (!reduce.matches) T.at(t + 4200, () => { if (cycling && vis) show((cur + 1) % F.flows.length); });
  }
  show(0);
  onView(svg, (v) => { const was = vis; vis = v; if (v && !was && cycling) show(cur); });
}

/* ---------------------------------------------------------------- record: decisions sealed into a chain */
function ledgerDemo() {
  const box = $("#chain");
  if (!box) return;
  const L = D.flows.ledger, T = timeline();
  const cap = el("p", { cls: "chain-cap", "aria-live": "polite" });
  box.after(cap);
  const PILL = { "Allowed": "allowed", "Held for a person": "held", "Refused": "refused" };
  let vis = false;
  async function sha(text) {
    try {
      const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
      return Array.from(new Uint8Array(b)).map((x) => x.toString(16).padStart(2, "0")).join("");
    } catch (e) { return ""; }
  }
  function block(r) {
    return el("li", { cls: "blk in" }, [
      el("p", { cls: "blk-top" }, [el("span", { cls: "pill " + PILL[r.decision], text: r.decision }), el("span", { cls: "grow" }), el("code", { cls: "blk-prev", text: "after " + r.prev_short })]),
      el("p", { cls: "blk-ord" }, [el("span", { cls: "f-ag", text: r.agent }), " ", el("b", { text: r.order })]),
      el("p", { cls: "blk-why", text: r.reason }),
      el("p", { cls: "blk-seal" }, ["seal ", el("code", { text: r.seal_short })])]);
  }
  function run() {
    T.clear(); box.textContent = ""; cap.textContent = ""; cap.className = "chain-cap"; box.classList.remove("broken");
    const gap = reduce.matches ? 0 : 700;
    L.forEach((r, i) => T.at(200 + i * gap, () => box.append(block(r))));
    if (reduce.matches) { cap.textContent = "Each record's seal covers the record and the seal before it."; return; }
    const t0 = 200 + L.length * gap;
    T.at(t0 + 600, () => { cap.textContent = "Each record's seal covers the record and the seal before it."; });
    const vi = L.findIndex((r) => r.decision !== "Allowed");
    T.at(t0 + 3200, async () => {
      const li = box.children[vi], r = L[vi];
      const p = li.querySelector(".pill");
      p.className = "pill allowed"; p.textContent = "Allowed";
      li.classList.add("edited");
      const fake = await sha(JSON.stringify({ ...r, decision: "Allowed" }));
      li.querySelector(".blk-seal code").textContent = fake.slice(0, r.seal_short.length) || "changed";
      cap.textContent = "Someone quietly changes a held order to Allowed.";
      cap.className = "chain-cap warn";
    });
    T.at(t0 + 4800, () => {
      const nxt = box.children[vi + 1];
      if (nxt) nxt.classList.add("mismatch");
      box.classList.add("broken");
      cap.textContent = "Its seal changes, the next record no longer matches, and the ledger fails verification.";
      cap.className = "chain-cap bad";
    });
    T.at(t0 + 10500, () => { if (vis) run(); });
  }
  run();
  if (!reduce.matches) onView(box, (v) => { const was = vis; vis = v; if (v && !was) run(); });
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

function accScene() {
  const box = $("#acc");
  if (!box) return;
  const A = D.vision.accumulate, grid = $("#acc-agents"), T = timeline();
  const techPct = parseFloat(A.tech_pct) / 100;
  const dots = Array.from({ length: A.agents }, (_, i) => {
    const d = el("span", { cls: "acc-ag", title: "Agent " + (i + 1) + " · order within the " + A.cap + " cap" });
    grid.append(d);
    return d;
  });
  const fill = (k) => { $("#acc-tech").style.width = (k.tech * 100) + "%"; $("#acc-other").style.width = (k.other * 100) + "%"; };
  function run() {
    T.clear(); box.classList.remove("shocked"); $("#acc-shock").hidden = true;
    dots.forEach((d) => d.className = "acc-ag");
    fill({ tech: 0, other: 0 }); $("#acc-v").textContent = A.violations; $("#acc-u").textContent = A.unauthorized; $("#acc-p").textContent = "";
    const step = reduce.matches ? 0 : 260;
    dots.forEach((d, i) => T.at(200 + i * step, () => {
      d.classList.add(i < A.tech_n ? "t" : "o");
      const k = (i + 1) / A.agents, t = Math.min(i + 1, A.tech_n) / A.agents;
      fill({ tech: t, other: k - t });
      $("#acc-p").textContent = Math.round((t / k) * 100) + "%";
    }));
    const t0 = 200 + A.agents * step + (reduce.matches ? 0 : 900);
    T.at(t0, () => {
      $("#acc-p").textContent = A.tech_pct;
      box.classList.add("shocked");
      $("#acc-shock").hidden = false;
      $("#acc-loss").textContent = A.loss;
      $("#acc-loss-t").textContent = "The theme falls " + A.shock_pct + ". That is " + A.loss_pct + " of the whole " + A.portfolio + " portfolio, and no agent ever broke its limit.";
      $("#acc-tech").style.width = techPct * 100 * (1 - parseFloat(A.shock_pct) / 100) + "%";
    });
  }
  $("#acc-replay").addEventListener("click", run);
  replayOnView(box, run);
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
  accScene(); sign3Scene(); concScene(); cfScene(); loopScene(); certScene();
  for (const id of ["#gap", "#parts", "#j-time"]) { const l = $(id); if (l) revealList(l, "on", id === "#j-time" ? 1100 : 450); }
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
  const tabs = $$("#code [role=tab]");
  const show = (k) => { body.textContent = D.snippets[k]; tabs.forEach((t) => t.setAttribute("aria-selected", String(t.dataset.k === k))); };
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.k)));
  show("mcp");
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
  for (const k of Object.keys(C)) { if (!document.getElementById("c-" + k)) continue; try { C[k](); } catch (e) { console.error("chart " + k, e); } }
  consoleRedraw();
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
  consoleSetup();
  compareSetup();
  codeTabs();
  authDemo();
  mandateJson();
  factsCheck();
  flowScene();
  ledgerDemo();
  clips();
  proofGrid();
  visionScenes();
  filmDialog();
  let lastW = innerWidth, tm = 0;
  addEventListener("resize", () => { clearTimeout(tm); tm = setTimeout(() => { if (innerWidth !== lastW) { lastW = innerWidth; drawAll(); } }, 150); });
  if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView(); }
}
boot();
