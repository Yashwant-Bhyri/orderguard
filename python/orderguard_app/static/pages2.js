"use strict";
/* pages2.js: Triggers (trigger board and blast radius), Scenarios (timeline), Ledger and Results (tiles, grouped bar chart, filterable tables). */
(function () {
const { h, svg, $, show, usd, pct, pill, list, table, rail, verdictCard, empty, errorBox } = OG;
const { setErr, firstInvalid, submitter, submitForm } = OG;
const preset = (group, label, page, run) => OG.presets.push({ group, label, page, run });
const num = (n) => Number(n).toLocaleString("en-US");

/* ---------- 1. Triggers ---------- */
const GRAPH_PRESETS = { single_venue_crash: "one venue's crash", takeover_echo: "fake takeover echoed by three wires", real_crash: "real crash on every venue", honest: "quiet morning" };
for (const [k, label] of Object.entries(GRAPH_PRESETS)) preset("Triggers", "Triggers: " + label, "graph", () => { $("g-preset").value = k; submitForm("graph-form"); });

/* Blast radius: for each size of lie, the dollars at risk with a naive rule (hatched red) and with the guarded graph (green). */
function blastChart(rows) {
  const W = 640, left = 76, right = 150, bw = W - left - right, rowH = 52, top = 8, H = top + rows.length * rowH + 8;
  const maxV = Math.max(1, ...rows.flatMap((r) => [r.naive_notional, r.guarded_notional]));
  const s = svg("svg", { class: "blast", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Dollars at risk if " + (rows[0] ? rows[0].source : "a source") + " lies, for each size of lie, naive rule against guarded graph" });
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    s.append(svg("text", { x: 0, y: y + 22, class: "lab" }, pct(r.lie_pct, 0)));
    for (const [k, v, cls, label, dy] of [["naive", r.naive_notional, "bn", "naive", 0], ["guarded", r.guarded_notional, "bg", "guarded", 22]]) {
      s.append(svg("rect", { x: left, y: y + dy + 2, width: Math.max(2, bw * v / maxV), height: 16, rx: 3, class: cls }));
      s.append(svg("text", { x: left + Math.max(2, bw * v / maxV) + 6, y: y + dy + 15 }, label + " " + usd(v) + (v ? " (" + ((k === "naive" ? r.naive_fires : r.guarded_fires).join(", ") || "none") + ")" : "")));
    }
  });
  return s;
}
function renderGraph(d) {
  const fires = d.guarded.filter((g) => g.fires), held = d.guarded.filter((g) => g.held_reason), naiveFires = d.naive.some((n) => n.fires);
  const kind = fires.length ? "allow" : held.length ? "hold" : "clean";
  const lead = naiveFires && !fires.length ? "Held: a naive rule would have traded " + usd(d.naive_notional) + "; the guarded graph trades " + usd(d.guarded_notional) + "."
    : fires.length ? "The guarded graph fires and trades " + usd(d.guarded_notional) + " (a naive rule: " + usd(d.naive_notional) + ")." : "No rule fires.";
  const srcRows = (d.sources || []).map((s) => ({ cls: s.quarantined ? "struck" : null,
    cells: [h("span", {}, s.source, s.quarantined ? h("span", { class: "keep" }, " ", pill("quarantined", "quarantine", "◆")) : null), s.kind === "price" ? "price" : "claim", s.subject,
      s.kind === "price" ? pct(s.pct, 1) : s.text, s.group] }));
  const rulesRows = (d.rule_details || []).map((r) => {
    const naive = d.naive.find((n) => n.rule === r.id);
    return [[h("b", {}, r.id), h("div", { class: "cap" }, r.text)], r.threshold,
      r.inputs.map((i) => h("div", { class: "num" }, i.name + ": " + (i.median == null ? "no data" : i.name.includes("_") ? (i.median ? "claim confirmed" : "no claim") : "median " + pct(i.median, 2)), h("span", { class: "cap" }, " from " + i.sources + (i.sources === 1 ? " source" : " sources")))),
      naive && naive.fires ? pill("fires " + naive.side + " " + usd(naive.notional), "refuse", "✕") : pill("quiet", "off"),
      [r.outcome === "fires" ? pill("fires", "allow", "✓") : r.outcome === "held" ? pill("held", "hold", "‖") : pill("quiet", "off"),
        r.need ? h("div", { class: "cap" }, r.need.charAt(0).toUpperCase() + r.need.slice(1) + ".") : null, r.held_reason ? h("div", { class: "cap" }, r.held_reason) : null]];
  });
  const b = d.blast_radius, src = b[0] ? b[0].source : "a source";
  show("graph-out", verdictCard({ verdict: kind, by: kind === "clean" ? null : "L7 trigger graph", lead, reasons: held.map((g) => g.held_reason), raw: d }),
    h("section", { class: "card" }, h("h3", {}, "Sources"), h("p", { class: "hint" }, "Independent sources are counted by group; a quarantined source is struck through and ignored."),
      table(["Source", "Kind", "Subject", "Value", "Independence group"], srcRows, { caption: "Sources behind this run" })),
    h("section", { class: "card" }, h("h3", {}, "Rules and outcome"), table(["Rule", "Threshold", "Inputs and median", "Naive", "Guarded (needs " + (d.min_sources || 2) + " independent sources)"], rulesRows, { caption: "Standing rules" })),
    h("section", { class: "card" }, h("h3", {}, "Blast radius"), h("p", { class: "hint" }, "If " + src + " lies about every price by the size shown, these rules fire and this much is at risk."),
      blastChart(b), h("details", {}, h("summary", {}, "Show as a table"),
        table(["Lie", "Naive fires", "Naive at risk", "Guarded fires", "Guarded at risk"], b.map((x) => [pct(x.lie_pct, 0), x.naive_fires.join(", ") || "none", usd(x.naive_notional), x.guarded_fires.join(", ") || "none", usd(x.guarded_notional)]), { caption: "Blast radius", num: [2, 4] }))));
}
$("graph-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const quarantined = $("g-quar").value.split(",").map((s) => s.trim()).filter(Boolean), blast = $("g-blast").value.trim();
  const okq = setErr("g-quar", quarantined.every((s) => /^[\w .-]{1,80}$/.test(s)) ? "" : "Use plain source names separated by commas.");
  const okb = setErr("g-blast", /^[\w .-]{0,80}$/.test(blast) ? "" : "Use a plain source name, for example VenueC.");
  if (!okq || !okb) return firstInvalid(["g-quar", "g-blast"]);
  OG.run(submitter(e), "graph-out", "Evaluating the rules", async () => {
    const body = { preset: $("g-preset").value, quarantined_sources: quarantined };
    if (blast) body.blast_source = blast;
    renderGraph(await OG.api("/api/trigger-graph", body));
  });
});
OG.pages.graph = { empty: () => show("graph-out", empty("Each source, the median, the rule and whether it fires or is held will appear here, with the blast radius of one lying source.", "Try an example", () => OG.runPreset(OG.presets.find((p) => p.label.startsWith("Triggers: one"))))) };

/* ---------- 2. Scenarios ---------- */
const STRONG = { refuse: 3, quarantine: 2, hold: 1 };
const argSummary = (a) => { try { const t = JSON.stringify(a); return t.length > 200 ? t.slice(0, 197) + "..." : t; } catch (e) { return ""; } };
const figNote = (f) => { const x = f.figure || {}; return x.metric + " FY" + x.fiscal_year + ": " + (f.status || "").replace(/_/g, " "); };
function stepNode(s) {
  const notes = [];
  for (const q of s.quarantined || []) notes.push(h("div", { class: "note q" }, pill("quarantined", "quarantine", "◆"), h("span", { class: "lcode" }, q.layer || "L2"), "Output of " + (q.tool || "a tool") + " looked like " + (q.category || "an instruction") + (q.why ? ": " + q.why : ".")));
  if (s.gate) {
    const g = s.gate, w = g.decision;
    notes.push(h("div", { class: "note" }, pill(w, w === "allow" ? "allow" : w === "hold" ? "hold" : "refuse", w === "allow" ? "✓" : w === "hold" ? "‖" : "✕"), h("span", { class: "lcode" }, g.layer),
      w === "allow" ? "The order passed the gate." : null, (g.reasons || []).length ? list(g.reasons) : null));
    for (const f of g.figures || []) notes.push(h("div", { class: "note" }, h("span", { class: "lcode" }, "L6"), figNote(f)));
  } else if (s.result && typeof s.result === "object" && s.result.status && !(s.quarantined || []).length) notes.push(h("div", { class: "note" }, "Tool result: " + s.result.status));
  return h("li", {}, h("div", { class: "tl-h" }, h("span", { class: "tool" }, s.tool || "(quarantined output)"), s.path ? rail(s.path, { mini: true, label: "Layers that acted on step " + s.step }) : null),
    s.args && Object.keys(s.args).length ? h("p", { class: "args" }, argSummary(s.args)) : null, notes);
}
const SCN = { "demo-1": "honest trade", "demo-2": "fake split in the feed", "demo-3": "fake filing figures", "demo-4": "injected transfer" };
function runScenario(id, arm) { $("scn-id").value = id; $("scn-arm").value = arm || ""; submitForm("scn-form"); }
for (const [k, label] of Object.entries(SCN)) preset("Scenario", "Scenario: " + label, "scenario", () => runScenario(k));
for (const b of document.querySelectorAll("[data-scn]")) b.addEventListener("click", () => runScenario(b.dataset.scn));
function renderScenario(d) {
  const acted = (d.run_path || []).filter((s) => s.state === "acted");
  const top = acted.reduce((m, s) => (STRONG[s.verdict] > STRONG[m] ? s.verdict : m), "hold");
  const verdict = d.error ? "unknown" : acted.length ? top : "allow";
  const by = acted.length ? acted.map((s) => s.id).join(" and ") + (acted.length > 1 ? " (" + acted.map((s) => OG.LAYERS[s.id][0].toLowerCase()).join(", ") + ")" : " " + OG.LAYERS[acted[0].id][0].toLowerCase()) : null;
  const lead = d.error ? d.error : acted.length ? "At least one layer stopped, held or quarantined something in this run." : "No layer had to step in; the run completed.";
  const j = d.judged || {};
  const steps = (d.timeline || []).map(stepNode);
  const finalCard = h("li", { class: "final" }, h("div", { class: "tl-h" }, h("span", { class: "tool" }, "Run ended")),
    h("div", { class: "mt8" }, verdictCard({ verdict, by, lead, reasons: d.error ? null : d.layers, raw: d })),
    d.final ? h("details", {}, h("summary", {}, "Agent's final answer"), h("pre", {}, d.final)) : null);
  show("scn-out",
    h("section", { class: "card" }, h("h3", {}, "The run on one rail"), h("div", { class: "rail-wrap" }, rail(d.run_path || [], { label: "Layers across the whole run" })),
      OG.kv([["Agent", d.agent], ["Arm", d.arm], d.task ? ["Task", d.task] : null, d.expected_stop ? ["Layer the lab expected", d.expected_stop] : null,
        ...Object.entries(j).map(([k, v]) => [k.replace(/_/g, " "), String(v)])])),
    h("section", { class: "card" }, h("h3", {}, "Timeline"), h("ol", { class: "timeline" }, steps.length ? steps : h("li", {}, h("p", { class: "hint" }, "The agent made no tool calls.")), finalCard)));
}
OG.pages.scenario = {
  async load() {
    try { const d = await OG.api("/api/scenarios"); $("scn-id").replaceChildren(...d.scenarios.map((s) => h("option", { value: s.id }, s.id + ": " + s.title))); }
    catch (e) { show("scn-out", errorBox(e.title || "Scenarios could not be loaded.", e.next || e.message)); }
  },
  empty: () => show("scn-out", empty("The agent's calls, the layers that acted on each and the run's verdict will appear here.", "Try an example", () => runScenario("demo-4"))),
};
$("scn-form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (!setErr("scn-id", $("scn-id").value ? "" : "Pick a scenario.")) return firstInvalid(["scn-id"]);
  OG.run(submitter(e), "scn-out", "Replaying the run", async () => {
    const body = { scenario: $("scn-id").value };
    if ($("scn-arm").value) body.arm = $("scn-arm").value;
    renderScenario(await OG.api("/api/run-scenario", body));
  });
});

/* ---------- 3. Ledger ---------- */
OG.pages.ledger = { empty: () => show("ledger-out", empty("Receiver orders and the hash-chain check will appear here.", "Refresh ledger", () => $("ledger-load").click())) };
$("ledger-load").addEventListener("click", (e) => OG.run(e.currentTarget, "ledger-out", "Reading the ledger", async () => {
  const d = await OG.api("/api/ledger");
  if (!d.connected) return show("ledger-out", errorBox("The receiver is not connected.", "Set ORDERGUARD_RECEIVER_URL to the L8 receiver bridge and restart `orderguard serve`. Until then orders go to the in-process local ledger.", "warn"));
  const orders = d.snapshot.orders || [], ok = d.snapshot.ledgerIntegrity;
  show("ledger-out", h("p", {}, "Ledger integrity: ", ok ? pill("intact", "allow", "✓") : pill("broken", "refuse", "✕"), " " + orders.length + (orders.length === 1 ? " order" : " orders")),
    orders.length ? table(["Order", "Symbol", "Side", "Qty", "Limit"], orders.map((o) => [o.orderId, o.symbol, o.side, o.quantity, o.limitPrice]), { caption: "Orders", num: [3, 4] }) : empty("No orders yet."), OG.rawJson(d));
}));

/* ---------- 4. Results ---------- */
let charts = [], sections = [];
const rate = (c) => (c ? c.k + " of " + c.n + " (" + c.rate + "%, 95% interval " + c.lo + " to " + c.hi + "%)" : "no data");
function tile(label, c, cls, extra) {
  return h("div", { class: "tile " + (cls || "") }, h("span", { class: "tl" }, label),
    h("span", { class: "tn" }, c ? c.k + " / " + num(c.n) : "n/a"), h("span", { class: "ti" }, c ? c.rate + "% (95% interval " + c.lo + " to " + c.hi + "%)" : ""), extra ? h("span", { class: "cap" }, extra) : null);
}
function renderTiles(hd, target) {
  const comparison = (c) => c ? " Bare model: " + rate(c) + "." : "";
  show(target || "res-head", h("div", { class: "tiles" },
    tile("Attacker actions executed, full guard", hd.executed_full, hd.executed_full && hd.executed_full.k ? "hot" : "good",
      "Live fixed cases pooled across both DeepSeek Flash variants, families A–D." + comparison(hd.executed_naive) +
      (hd.dos_full ? " With the full guard, agents dropped a legitimate trade in " + hd.dos_full.k + " of " + hd.dos_full.n + " family E trials." : "")),
    tile("Attack goals achieved, full guard", hd.full_success_ad, hd.full_success_ad && hd.full_success_ad.k ? "hot" : "good",
      "Live fixed cases pooled across both DeepSeek Flash variants, families A–D." + comparison(hd.naive_success_ad)),
    tile("Clean-control tasks completed, full guard", hd.utility_full, "good", comparison(hd.utility_naive).trim()),
    h("div", { class: "tile" }, h("span", { class: "tl" }, "Recorded lab model spend"),
      h("span", { class: "tn" }, hd.spend_usd == null ? "n/a" : "$" + hd.spend_usd.toFixed(2)),
      h("span", { class: "cap" }, "Across logged model calls. Provider details appear in the Spend table."))));
}
OG.renderTiles = renderTiles;
/* Grouped bars: attack success by family for each arm, Wilson 95% whiskers. Naive is hatched red, gate_only dotted amber, full solid green, and each bar is labelled. */
const ARMS = ["naive", "gate_only", "full"];
function barChart(c) {
  const fams = c.families, W = 680, H = 330, L = 44, R = 12, T = 44, B = 52, pw = W - L - R, ph = H - T - B, gw = pw / Math.max(1, fams.length), bw = Math.min(30, (gw - 24) / 3);
  const y = (v) => T + ph * (1 - v / 100);
  const s = svg("svg", { class: "chart", viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Attack success by family and arm for " + c.model + ". " + fams.map((f) => f.id + " " + f.name + ": " + ARMS.map((a) => a + " " + (f.arms[a] ? f.arms[a].rate + "%" : "no data")).join(", ")).join("; ") });
  s.append(svg("defs", {},
    svg("pattern", { id: "p-naive", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, svg("rect", { width: 6, height: 6, class: "pbg" }), svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "pa-naive", "stroke-width": 3 })),
    svg("pattern", { id: "p-gate", width: 6, height: 6, patternUnits: "userSpaceOnUse" }, svg("rect", { width: 6, height: 6, class: "pbg" }), svg("circle", { cx: 3, cy: 3, r: 1.4, class: "pa-gate" }))));
  ARMS.forEach((a, i) => {
    const x = L + i * 150;
    s.append(svg("rect", { x, y: 10, width: 14, height: 14, rx: 2, class: "b-" + a }), svg("text", { x: x + 20, y: 22 }, a));
  });
  for (const t of [0, 25, 50, 75, 100]) s.append(svg("line", { x1: L, x2: W - R, y1: y(t), y2: y(t), class: "gl" }), svg("text", { x: L - 6, y: y(t) + 4, "text-anchor": "end" }, t + "%"));
  s.append(svg("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "ax" }));
  fams.forEach((f, i) => {
    const gx = L + gw * i + (gw - (bw * 3 + 12)) / 2;
    ARMS.forEach((a, j) => {
      const v = f.arms[a];
      if (!v) return;
      const x = gx + j * (bw + 6), top = y(v.rate), hi = y(v.hi), lo = y(v.lo), cx = x + bw / 2;
      s.append(svg("rect", { x, y: top, width: bw, height: Math.max(1, y(0) - top), rx: 2, class: "b-" + a }, svg("title", {}, f.id + " " + a + ": " + rate(v))));
      s.append(svg("path", { class: "wh", d: "M" + cx + " " + hi + "V" + lo + "M" + (cx - 4) + " " + hi + "H" + (cx + 4) + "M" + (cx - 4) + " " + lo + "H" + (cx + 4) }));
      s.append(svg("text", { x: cx, y: hi - 5, "text-anchor": "middle", class: "vl" }, Math.round(v.rate) + "%"));
    });
    s.append(svg("text", { x: L + gw * i + gw / 2, y: H - 28, "text-anchor": "middle", class: "vl" }, f.id), svg("text", { x: L + gw * i + gw / 2, y: H - 12, "text-anchor": "middle" }, f.name));
  });
  return s;
}
/* Default to the live run with the most runs: the strongest evidence, not the first table in the file. */
function bestChart() {
  let best = 0;
  charts.forEach((c, i) => { const b = charts[best]; if ((c.kind === "live") > (b.kind === "live") || ((c.kind === "live") === (b.kind === "live") && (c.runs || 0) > (b.runs || 0))) best = i; });
  return best;
}
function renderChart(idx) {
  const c = charts[idx];
  if (!c) return show("res-chart", empty("No per-family results were found in docs/RESULTS.md."));
  const head = h("div", { class: "filters" }, h("div", { class: "field" }, h("label", { for: "res-model" }, "Chart for"),
    h("select", { id: "res-model", on: { change: (e) => renderChart(Number(e.target.value)) } }, charts.map((x, i) => h("option", { value: i, selected: i === idx }, x.model + " (" + x.kind + ", " + x.runs + " runs)")))));
  show("res-chart", h("h3", {}, "Attack success by family"), h("p", { class: "hint" }, "Share of attack runs that succeeded, per family and arm, with the Wilson 95% interval as a whisker. "
    + (c.kind === "offline" ? "Offline rows use scripted stand-in agents, not a real model: they test the pipeline." : "Live rows are one cheap model family with few repeats: intervals are wide.")),
    head, barChart(c), h("details", {}, h("summary", {}, "Show the numbers"), table(["Family", ...ARMS], c.families.map((f) => [f.id + " " + f.name, ...ARMS.map((a) => rate(f.arms[a]))]), { caption: "Attack success by family and arm" })));
  const sel = $("res-model");
  if (sel) sel.value = String(idx);
}
function renderTable() {
  const s = sections[Number($("res-sec").value)];
  if (!s) return show("res-out", empty("No table selected."));
  const fam = $("res-fam").value, arm = $("res-arm").value, body = [];
  const bullets = s.text.filter((t) => t.startsWith("- ")), prose = s.text.filter((t) => !t.startsWith("- "));
  if (prose.length) body.push(h("p", { class: "hint" }, prose.join(" ")));
  if (bullets.length) body.push(list(bullets.map((t) => t.slice(2))));
  let filtered = false;
  for (const t of s.tables) {
    const fi = t.headers.indexOf("family"), ai = t.headers.indexOf("arm");
    const rows = t.rows.filter((r) => (!fam || fi < 0 || r[fi].startsWith(fam + " ")) && (!arm || ai < 0 || r[ai] === arm));
    filtered = filtered || ((fam || arm) && (fi >= 0 || ai >= 0));
    body.push(rows.length ? table(t.headers, rows, { caption: s.title }) : empty("No rows match this family and arm."));
  }
  if ((fam || arm) && !filtered) body.unshift(h("p", { class: "cap" }, "This table has no family or arm column, so the filters do not apply."));
  show("res-out", body);
}
OG.pages.results = {
  async load() {
    $("res-head").setAttribute("aria-busy", "true");
    show("res-head", OG.skeleton("Reading the results"));
    try {
      const d = await OG.api("/api/results");
      sections = d.sections.filter((s) => s.tables.length); charts = d.charts || [];
      $("res-sec").replaceChildren(...sections.map((s, i) => h("option", { value: i }, s.title)));
      const letters = new Map();
      for (const c of charts) for (const f of c.families) letters.set(f.id, f.name);
      $("res-fam").replaceChildren(h("option", { value: "" }, "all families"), ...[...letters].map(([k, n]) => h("option", { value: k }, k + " " + n)));
      renderTiles(d.headline || {});
      const limits = d.sections.find((s) => s.title === "Limits");
      const headline = d.headline || {};
      const records = num(headline.live_runs || 0) + " live fixed-case records across " + (headline.models || []).length + " model variants.";
      const errors = headline.live_errors ? " Runs ending in an error are included in that count and excluded from rates." : "";
      const caveats = [records + errors, "Each rate uses the eligible runs in its denominator. Intervals are Wilson 95%."]
        .concat(limits ? limits.text.map((t) => t.replace(/^- /, "")) : []);
      show("res-caveat-body", list(caveats));
      renderChart(bestChart());
      renderTable();
    } catch (e) {
      const box = errorBox(e.title || "The results could not be loaded.", e.next || e.message);
      show("res-head", box); show("res-chart"); show("res-out");
    } finally { $("res-head").setAttribute("aria-busy", "false"); }
  },
};
for (const id of ["res-sec", "res-fam", "res-arm"]) $(id).addEventListener("change", renderTable);
})();
