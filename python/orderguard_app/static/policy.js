"use strict";
(() => {
  const { $, h, show, errorBox, table, usd, pct } = OG;
  const path = "/api/arena/policy";
  const labels = {
    bad_allowed_usd_per_day: "Harmful notional allowed / day",
    legitimate_allowed_usd_per_day: "Legitimate notional allowed / day",
    false_refusal_rate: "Legitimate orders refused",
    holds_per_day: "Orders held / day",
    bad_filled_usd_per_day: "Harmful paper fills / day",
    legitimate_filled_usd_per_day: "Legitimate paper fills / day",
    daily_cap_refusals: "Orders refused at the daily cap",
    proposals: "Total proposals",
  };
  let parent = null;
  let parentId = null;
  let loadId = 0;

  function format(key, value) {
    if (key.includes("_usd_")) return usd(value);
    if (key.endsWith("_rate")) return pct(100 * value, 1, false);
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  function modelWarning(warning) {
    return warning && h("p", { class: "msg" }, "Model warning · Likely over the limit for " + labels[warning.metric].toLowerCase() + ".");
  }

  function setDraft(draft) {
    $("policy-symbols").value = draft.symbols.join(", ");
    $("policy-sides").value = draft.sides.length === 2 ? "both" : draft.sides[0];
    $("policy-order").value = draft.maxOrderNotionalUsd;
    $("policy-daily").value = draft.maxDailyNotionalUsd;
    $("policy-band").value = draft.priceBandPct;
    $("policy-approval").value = draft.stepUpAboveUsd ?? "";
  }

  async function loadParent() {
    const id = ++loadId;
    parent = null;
    $("policy-fields").disabled = true;
    show("policy-out", null);
    show("policy-options", null);
    show("policy-parent", OG.skeleton("Loading parent policy"));
    try {
      const data = await OG.api(path + "?source=" + $("policy-source").value);
      if (id !== loadId) return;
      parent = data.parent;
      parentId = data.parent_id;
      setDraft(data.suggested_draft);
      show("policy-parent", h("p", { class: "hint" }, "Verified parent allows " + parent.symbols.join(", ") + ". " +
        usd(parent.maxOrderNotionalUsd) + " per order and " + usd(parent.maxDailyNotionalUsd) + " per day. Expires " + parent.expiresAt + "."));
      $("policy-fields").disabled = false;
    } catch (err) {
      if (id !== loadId) return;
      show("policy-parent", errorBox(err.title || "Parent policy unavailable", err.next || err.message));
    }
  }

  function readDraft() {
    const symbols = $("policy-symbols").value.split(/[\s,]+/).filter(Boolean);
    const side = $("policy-sides").value;
    const draft = {
      symbols, sides: side === "both" ? ["buy", "sell"] : [side],
      maxOrderNotionalUsd: $("policy-order").valueAsNumber,
      maxDailyNotionalUsd: $("policy-daily").valueAsNumber,
      priceBandPct: $("policy-band").valueAsNumber,
      expiresAt: parent.expiresAt,
      referencePrices: Object.fromEntries(Object.entries(parent.referencePrices || {}).filter(([s]) => symbols.includes(s))),
    };
    if ($("policy-approval").value) draft.stepUpAboveUsd = $("policy-approval").valueAsNumber;
    return draft;
  }

  function render(data) {
    if (!data.fit.fits) {
      show("policy-out", h("div", { class: "msg bad", role: "status" }, h("b", {}, "Draft rejected"),
        OG.list(data.fit.violations.map((v) => v.reason))));
      return;
    }
    const draftFile = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(data.fit.draft, null, 2) + "\n");
    const status = [h("p", { class: "msg ok" }, "Draft fits the signed parent."),
      h("p", { class: "hint" }, h("a", { href: draftFile, download: "orderguard-draft.json" }, "Download unsigned draft"),
        $("policy-source").value === "configured" ? [". Activate with ", h("code", {}, "orderguard activate-draft"), "."] : null),
      modelWarning(data.estimate?.warning)];
    const rows = [];
    if (data.simulation) {
      const { results, scenario, limits } = data.simulation;
      for (const [key, title] of Object.entries(labels)) {
        rows.push({ cells: [title, format(key, results.parent[key]), format(key, results.draft[key])] });
      }
      show("policy-out", h("div", {}, status, h("h3", {}, "Observed in the simulation"),
        h("p", { class: "hint" }, scenario.agents + " agents, " + scenario.steps + " ticks, seed " + scenario.seed + ". Each policy gets the same market and starting population."),
        limits ? h("p", { class: "msg " + (limits.met ? "ok" : "bad") }, limits.met ? "The draft met the entered limits in this run." : "The draft exceeded at least one limit in this run.") : null,
        table(["Outcome", "Parent", "Draft"], rows, { num: [1, 2], caption: "Paper simulation outcomes" })));
    } else if (data.estimate) {
      const { status: kind, outcomes } = data.estimate;
      if (!outcomes) {
        show("policy-out", h("div", {}, status, h("p", {}, kind === "outside_training_domain" ? "Outside the forecast’s training range. Run the simulation." : "Forecast unavailable. You can still run the simulation.")));
        return;
      }
      for (const [key, v] of Object.entries(outcomes)) {
        rows.push({ cells: [labels[key], format(key, v.estimate), format(key, v.lower) + " to " + format(key, v.upper)] });
      }
      show("policy-out", h("div", {}, status, h("h3", {}, kind === "experimental" ? "Experimental estimate" : "Model estimate"),
        h("p", { class: "hint" }, "Run the simulation to measure these outcomes before signing."),
        table(["Outcome", "Estimate", "Range"], rows, { num: [1, 2], caption: "Estimated paper outcomes" })));
    } else {
      show("policy-out", status);
    }
  }

  function renderCandidate(candidate, selected, first) {
    const { name, draft, simulation } = candidate;
    const state = simulation ? (simulation.limits ? (simulation.limits.met ? "Meets limits" : "Exceeds limits") : "Simulated") : (candidate.warning ? "Model warning" : "Untested");
    const dollars = (value) => usd(value, value % 1 !== 0);
    const terms = [["Per order", dollars(draft.maxOrderNotionalUsd)], ["Per day", dollars(draft.maxDailyNotionalUsd)],
      ["Price band", draft.priceBandPct.toLocaleString(undefined, { maximumFractionDigits: 6 }) + "%"],
      ["Approval above", draft.stepUpAboveUsd == null ? "No separate threshold" : dollars(draft.stepUpAboveUsd)]];
    const metrics = ["bad_allowed_usd_per_day", "legitimate_filled_usd_per_day", "false_refusal_rate", "holds_per_day"];
    const pairs = (items) => h("dl", { class: "policy-facts" }, items.map(([label, value]) =>
      h("div", {}, h("dt", {}, label), h("dd", {}, value))));
    const exceeded = simulation?.limits ? Object.entries(simulation.limits.checks)
      .filter(([, check]) => !check.met).map(([key]) => labels[key]) : [];
    const edit = h("button", { type: "button", class: "ghost sm", "aria-label": "Edit draft for " + name,
      on: { click: () => { setDraft(draft); show("policy-out", null); $("policy-symbols").focus(); } } }, "Edit this draft");
    return h("details", { class: "policy-candidate", open: selected || first },
      h("summary", {}, h("b", {}, name), h("span", { class: "hint" }, selected ? "Highest legitimate fill value · " + state : state)),
      pairs(terms), modelWarning(candidate.warning), simulation ? pairs(metrics.map((key) => [labels[key], format(key, simulation.metrics[key])])) : null,
      exceeded.length ? h("p", { class: "hint" }, "Exceeded limits for " + exceeded.join(", ").toLowerCase() + ".") : null, edit);
  }

  function renderOptions(data) {
    const { candidates, mode, ranking, scenario, simulated, match_count, selected_rank } = data;
    if (!candidates.length) {
      show("policy-options", h("p", { class: "msg" }, "The signed parent’s terms leave no distinct draft options."));
      return;
    }
    const count = candidates.length;
    const heading = mode === "rank" ? "Draft ranking preview" : "Compared " + simulated + " draft options";
    const summary = mode === "rank" ? (ranking.method === "point_forecast" ?
      "Forecast order. Compare drafts to measure outcomes." : "Generated order. Compare drafts to measure outcomes.") :
      (match_count === null ? "Enter risk limits to identify qualifying drafts." :
        (match_count === 0 ? "None of the " + count + " drafts met the entered limits in this run." :
          match_count + " of " + count + " met the entered limits. " + (selected_rank === null ?
            "None of those drafts filled a legitimate order in this run." : "The highlighted draft had the highest legitimate fill value.")));
    const ordered = [...candidates];
    if (selected_rank !== null) ordered.sort((a, b) => Number(b.rank === selected_rank) - Number(a.rank === selected_rank));
    const cards = ordered.map((candidate, index) => renderCandidate(candidate, candidate.rank === selected_rank, index === 0));
    show("policy-options", h("div", {}, h("h3", {}, heading), h("p", { class: "hint" }, summary),
      h("p", { class: "hint" }, scenario.agents + " agents, " + scenario.steps + " ticks, seed " + scenario.seed + ". All drafts keep the parent’s symbols and sides."),
      Object.keys(data.limits).length ? h("ul", { class: "policy-limits" }, Object.entries(data.limits)
        .map(([key, maximum]) => h("li", {}, labels[key] + " ≤ " + format(key, maximum)))) : null,
      data.unobserved_symbols.length ? h("p", { class: "msg" }, "Symbols outside this market feed are untested. " + data.unobserved_symbols.join(", ")) : null,
      h("div", { class: "policy-candidates" }, cards)));
  }

  function readLimits() {
    const limits = {};
    for (const [id, name, divisor] of [["policy-max-bad", "bad_allowed_usd_per_day", 1],
      ["policy-max-refusal", "false_refusal_rate", 100], ["policy-max-holds", "holds_per_day", 1]]) {
      const input = $(id);
      if (input.value !== "") limits[name] = input.valueAsNumber / divisor;
    }
    return limits;
  }

  $("policy-source").addEventListener("change", loadParent);
  $("policy-form").addEventListener("input", (event) => {
    show("policy-out", null);
    if ($("policy-scenario").contains(event.target)) show("policy-options", null);
  });

  async function submitPolicy(button) {
    if (!parent || $("policy-fields").disabled) return;
    const mode = button?.value || "fit";
    const batch = mode === "rank" || mode === "search";
    const settings = $("policy-scenario");
    const badSetting = [...settings.querySelectorAll("input")].find((input) => !input.validity.valid);
    if (badSetting) { settings.open = true; badSetting.reportValidity(); return; }
    if (!batch) {
      const invalid = [...$("policy-draft-fields").querySelectorAll("input")].find((input) => !input.validity.valid);
      if (invalid) { invalid.reportValidity(); return; }
    }
    const body = { source: $("policy-source").value, mode: mode === "search" ? "simulate" : mode,
      agents: $("policy-agents").valueAsNumber, steps: $("policy-steps").valueAsNumber,
      seed: $("policy-seed").valueAsNumber, regime: $("policy-regime").value, limits: readLimits() };
    if (!batch) body.draft = readDraft();
    const output = batch ? "policy-options" : "policy-out";
    const busy = { fit: "Checking the draft", estimate: "Estimating outcomes", simulate: "Simulating both policies",
      rank: "Ranking draft options", search: "Comparing draft options" };
    $("policy-source").disabled = $("policy-fields").disabled = true;
    try {
      await OG.run(button, output, busy[mode], async () => {
        const data = await OG.api(batch ? path + "/search" : path, body);
        const currentId = batch ? data.parent_id : data.fit.parent_id;
        if (currentId && currentId !== parentId) {
          await loadParent();
          throw new Error("The signed parent changed. Review the current policy and try again.");
        }
        if (batch) renderOptions(data);
        else render(data);
      });
    } finally {
      $("policy-source").disabled = false;
      $("policy-fields").disabled = !parent;
      if (button && document.activeElement === document.body) button.focus({ preventScroll: true });
    }
  }

  $("policy-compare").addEventListener("click", (event) => submitPolicy(event.currentTarget));
  $("policy-rank").addEventListener("click", (event) => submitPolicy(event.currentTarget));
  $("policy-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitPolicy(event.submitter);
  });
  const original = OG.pages.arena.empty;
  OG.pages.arena.empty = () => { original(); if (!parent) loadParent(); };
})();
