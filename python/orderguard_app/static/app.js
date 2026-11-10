"use strict";
/* No HTML string injection anywhere: every string from the server or the user is added with textContent. */
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = "og_token";
let token = "";
try { token = sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { /* storage may be blocked */ }

function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v; else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}
const pill = (text, cls) => h("span", { class: "pill " + cls }, text);
const msg = (text, cls) => h("div", { class: "msg " + cls, role: cls === "bad" ? "alert" : null }, text);
const json = (x) => h("pre", {}, JSON.stringify(x, null, 2));
const show = (id, ...nodes) => { const o = $(id); o.replaceChildren(...nodes.flat().filter(Boolean)); };
const list = (items) => h("ul", { class: "plain" }, items.map((t) => h("li", {}, t)));

async function api(path, body) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = "Bearer " + token;
  let r;
  try {
    r = await fetch(path, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) { throw new Error("The server could not be reached."); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* not JSON */ }
  if (r.status === 401) { $("auth-form").hidden = false; $("token").focus(); throw new Error("This server needs an access token."); }
  if (!r.ok) {
    const d = data && data.details ? ": " + data.details.map((x) => x.where + " " + x.problem).join("; ") : "";
    throw new Error(((data && data.error) || "Request failed (" + r.status + ")") + d);
  }
  return data;
}

async function run(btn, outId, fn) {
  if (btn) btn.disabled = true;
  try { await fn(); } catch (e) { show(outId, msg(e.message, "bad")); } finally { if (btn) btn.disabled = false; }
}
const submitter = (e) => e.submitter || e.target.querySelector("button[type=submit]");

/* ---- status ---- */
async function loadStatus() {
  try {
    const d = await api("/api/health");
    const rows = [
      ["Provider", d.provider], ["API key configured", d.key_configured ? "yes" : "no"], ["LLM mode", d.llm_mode],
      ["Model", d.model], ["Budget", "US$" + d.budget.budget_usd + " (spent US$" + d.budget.spent_usd + ", " + d.budget.calls + " calls)"],
      ["Classifier", d.classifier_available ? "available" : "not installed"], ["Receiver", d.receiver_configured ? "configured" : "not connected"],
      ["Version", "orderguard " + (d.versions.orderguard || "?") + ", app " + d.versions.app],
    ];
    $("status-body").replaceChildren(...rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
    $("auth-form").hidden = true;
    return true;
  } catch (e) {
    $("status-body").replaceChildren(h("dt", {}, "Status"), h("dd", {}, e.message));
    return false;
  }
}
$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  token = $("token").value.trim();
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch (x) { /* ignore */ }
  $("token").value = "";
  if (await loadStatus()) init();
});

/* ---- screen ---- */
$("screen-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(submitter(e), "screen-out", async () => {
    const d = await api("/api/screen", { text: $("screen-text").value, kind: $("screen-kind").value });
    const l1 = d.l1.findings.length ? [list(d.l1.findings), d.l1.severe.length ? msg("Hidden or deceptive characters found: the chunk is quarantined by code, before any model reads it.", "bad") : null]
      : [h("p", {}, "Nothing hidden was found.")];
    const l2 = d.l2.status === "ok"
      ? [h("p", {}, pill(d.l2.flag ? "flagged: " + d.l2.category : "clean", d.l2.flag ? "bad" : "ok"), " ", d.l2.why, d.l2.cached ? " (cached)" : "")]
      : [msg("Model screen unavailable: " + d.l2.reason, "warn")];
    const cls = d.classifier ? (d.classifier.status === "ok"
      ? [h("h3", {}, "Classifier"), h("p", {}, pill(d.classifier.label, d.classifier.p_attack >= 0.5 ? "bad" : "ok"), " attack probability " + d.classifier.p_attack.toFixed(3))]
      : [h("h3", {}, "Classifier"), msg("The classifier failed (" + d.classifier.reason + ").", "warn")]) : [];
    show("screen-out", h("p", {}, "Verdict: ", pill(d.verdict, d.verdict)), h("h3", {}, "L1 normalise"), l1, h("h3", {}, "L2 model screen"), l2, cls);
  });
});

/* ---- order ---- */
let customMandate = null;
function renderMandate(info) {
  const m = info.mandate || {};
  const rows = [["Source", info.source], ["Id", info.id], ["Signed", info.signed ? "yes" : "no"],
    ["Signature checked", info.signature_checked ? "yes, against the " + info.signature_checked_against : "no (integrity only if you supply a public key)"],
    ["Symbols", (m.symbols || []).join(", ")], ["Sides", (m.sides || []).join(", ")], ["Per order cap", "$" + m.maxOrderNotionalUsd],
    ["Daily cap", "$" + m.maxDailyNotionalUsd], ["Price band", m.priceBandPct + "%"], ["Step-up above", m.stepUpAboveUsd != null ? "$" + m.stepUpAboveUsd : "none"],
    ["Expires", m.expiresAt]];
  $("mandate-view").replaceChildren(h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])));
}
async function loadMandate() {
  try {
    const d = await api("/api/mandate");
    renderMandate({ source: "demo", id: "(demo)", signed: true, signature_checked: true, signature_checked_against: "demo key", mandate: d.mandate });
  } catch (e) { $("mandate-view").replaceChildren(msg(e.message, "bad")); }
}
$("order-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(submitter(e), "order-out", async () => {
    const body = { order: { ticker: $("o-ticker").value, side: $("o-side").value, quantity: Number($("o-qty").value), limit_price: Number($("o-limit").value) },
      as_of: $("o-asof").value, daily_total_usd: Number($("o-daily").value || 0), require_figures: $("o-req").checked };
    const figs = $("o-figs").value.trim();
    if (figs) {
      try { body.order.key_figures = JSON.parse(figs); } catch (x) { throw new Error("Cited figures are not valid JSON."); }
    }
    const mj = $("m-json").value.trim();
    if (mj) {
      let parsed;
      try { parsed = JSON.parse(mj); } catch (x) { throw new Error("The mandate is not valid JSON."); }
      body.mandate = { mandate: parsed };
      if ($("m-key").value.trim()) body.mandate.public_key = $("m-key").value.trim();
    }
    const d = await api("/api/check-order", body);
    renderMandate(d.mandate);
    const c = d.checks || {};
    const facts = [["Trusted price", c.trusted_price != null ? "$" + c.trusted_price + " (" + (c.price_source || "unknown") + ")" : "none"],
      ["Value at trusted price", c.notional_usd != null ? "$" + c.notional_usd.toLocaleString() : "n/a"],
      ["Value at the order's own limit", c.limit_notional_usd != null ? "$" + c.limit_notional_usd.toLocaleString() : "n/a"],
      ["Limit vs trusted", c.limit_vs_trusted_pct != null ? c.limit_vs_trusted_pct + "%" : "n/a"]];
    const figs2 = (c.figures || []).map((f) => h("tr", {}, h("td", {}, f.figure.metric + " FY" + f.figure.fiscal_year), h("td", {}, f.figure.value + " " + (f.figure.unit || "")),
      h("td", {}, pill(f.status, f.status === "confirmed" ? "ok" : f.status === "unverifiable" ? "warn" : "bad")), h("td", {}, f.truth == null ? "" : f.truth)));
    show("order-out", h("p", {}, "Decision: ", pill(d.decision, d.decision)), d.reasons.length ? list(d.reasons) : h("p", {}, "Every check passed."),
      h("dl", { class: "kv" }, facts.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
      figs2.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Figure", "Cited", "Status", "Filed"].map((x) => h("th", {}, x)))), h("tbody", {}, figs2))) : null,
      h("details", {}, h("summary", {}, "Raw checks"), json(d.checks)));
  });
});
$("o-preset-split").addEventListener("click", () => { $("o-qty").value = 440; $("o-limit").value = 22.3; $("o-figs").value = ""; });
$("o-preset-fig").addEventListener("click", () => {
  $("o-qty").value = 40; $("o-limit").value = 222.9;
  $("o-figs").value = JSON.stringify([{ metric: "revenue", fiscal_year: 2024, value: 431035, unit: "USD millions" }]);
});
$("m-clear").addEventListener("click", () => { $("m-json").value = ""; $("m-key").value = ""; loadMandate(); });

/* ---- trigger graph ---- */
$("graph-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(submitter(e), "graph-out", async () => {
    const d = await api("/api/trigger-graph", { preset: $("g-preset").value });
    const rows = d.guarded.map((g) => {
      const naive = d.naive.find((n) => n.rule === g.rule);
      return h("tr", {}, h("td", {}, g.rule), h("td", {}, naive && naive.fires ? "fires: " + naive.side + " $" + naive.notional.toLocaleString() : "no"),
        h("td", {}, pill(g.fires ? "fires" : g.held_reason ? "held" : "quiet", g.fires ? "warn" : g.held_reason ? "ok" : "unknown")),
        h("td", {}, g.held_reason || ""));
    });
    const blast = d.blast_radius.map((b) => h("tr", {}, h("td", {}, b.lie_pct + "%"), h("td", {}, "$" + b.naive_notional.toLocaleString()), h("td", {}, "$" + b.guarded_notional.toLocaleString())));
    show("graph-out",
      h("p", {}, "A naive rule would trade $" + d.naive_notional.toLocaleString() + "; the guarded graph trades $" + d.guarded_notional.toLocaleString() + "."),
      h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Rule", "Naive", "Guarded", "Why"].map((x) => h("th", {}, x)))), h("tbody", {}, rows))),
      h("h3", {}, "Blast radius if one venue lies about every price"),
      h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Lie", "Naive sells", "Guarded sells"].map((x) => h("th", {}, x)))), h("tbody", {}, blast))));
  });
});

/* ---- scenarios ---- */
async function loadScenarios() {
  try {
    const d = await api("/api/scenarios");
    $("scn-id").replaceChildren(...d.scenarios.map((s) => h("option", { value: s.id }, s.id + ": " + s.title)));
  } catch (e) { show("scn-out", msg(e.message, "bad")); }
}
function stepNode(s) {
  const kids = [h("div", {}, h("span", { class: "tool" }, s.tool || "(quarantined output)"),
    s.args && Object.keys(s.args).length ? h("span", {}, " " + JSON.stringify(s.args).slice(0, 200)) : null)];
  for (const q of s.quarantined || []) {
    kids.push(h("div", {}, h("span", { class: "layer" }, q.layer || "L2"), pill("quarantined: " + q.category, "bad"), " " + (q.why || "")));
  }
  if (s.gate) {
    kids.push(h("div", {}, h("span", { class: "layer" }, s.gate.layer), pill(s.gate.decision, s.gate.decision)));
    if (s.gate.reasons && s.gate.reasons.length) kids.push(list(s.gate.reasons));
    for (const f of s.gate.figures || []) {
      kids.push(h("div", {}, h("span", { class: "layer" }, "L6"), f.figure.metric + " FY" + f.figure.fiscal_year + ": ", pill(f.status, f.status === "confirmed" ? "ok" : "warn")));
    }
  } else if (s.result && typeof s.result === "object" && s.result.status) {
    kids.push(h("div", {}, "result: " + s.result.status));
  }
  return h("li", {}, kids);
}
$("scn-form").addEventListener("submit", (e) => {
  e.preventDefault();
  run(submitter(e), "scn-out", async () => {
    const body = { scenario: $("scn-id").value };
    if ($("scn-arm").value) body.arm = $("scn-arm").value;
    const d = await api("/api/run-scenario", body);
    show("scn-out",
      h("p", {}, "Agent: " + d.agent + ". Arm: " + d.arm + "."),
      d.error ? msg(d.error, d.replay_miss ? "warn" : "bad") : null,
      d.judged && Object.keys(d.judged).length ? h("p", {}, Object.entries(d.judged).map(([k, v]) => k + ": " + JSON.stringify(v)).join("  |  ")) : null,
      h("h3", {}, "Layers that acted"), list(d.layers),
      h("h3", {}, "Timeline"), h("ol", { class: "timeline" }, d.timeline.map(stepNode)),
      d.final ? h("details", {}, h("summary", {}, "Agent's final answer"), h("pre", {}, d.final)) : null);
  });
});

/* ---- ledger ---- */
$("ledger-load").addEventListener("click", (e) => run(e.currentTarget, "ledger-out", async () => {
  const d = await api("/api/ledger");
  if (!d.connected) return show("ledger-out", msg(d.message, "warn"));
  const orders = d.snapshot.orders || [];
  show("ledger-out", h("p", {}, "Ledger integrity: ", pill(d.snapshot.ledgerIntegrity ? "intact" : "BROKEN", d.snapshot.ledgerIntegrity ? "ok" : "bad"), " " + orders.length + " orders"),
    orders.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Order", "Symbol", "Side", "Qty", "Limit"].map((x) => h("th", {}, x)))),
      h("tbody", {}, orders.map((o) => h("tr", {}, [o.orderId, o.symbol, o.side, o.quantity, o.limitPrice].map((x) => h("td", {}, x))))))) : null);
}));

/* ---- results ---- */
let resultSections = [];
function renderResult() {
  const s = resultSections[Number($("res-sec").value)];
  if (!s) return;
  show("res-out", s.text.length ? h("p", {}, s.text.join(" ")) : null, s.tables.map((t) => h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, t.headers.map((x) => h("th", {}, x)))), h("tbody", {}, t.rows.map((r) => h("tr", {}, r.map((x) => h("td", {}, x)))))))));
}
async function loadResults() {
  try {
    const d = await api("/api/results");
    resultSections = d.sections.filter((s) => s.tables.length);
    $("res-sec").replaceChildren(...resultSections.map((s, i) => h("option", { value: i }, s.title)));
    renderResult();
  } catch (e) { show("res-out", msg(e.message, "warn")); }
}
$("res-sec").addEventListener("change", renderResult);

function init() { loadMandate(); loadScenarios(); loadResults(); }
loadStatus().then((ok) => { if (ok) init(); });
