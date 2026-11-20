from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path


CAUSES = {
    "band_breach", "limit_breach", "banned_instrument", "purpose_drift",
    "preference_violation", "unsupported_claim", "misquote", "binding_error",
    "selective_evidence", "source_laundering", "hype_substitution", "context_lift",
    "lookahead", "stale_data", "stale_thesis", "corporate_action_error",
    "authority_spoof", "poisoned_note", "prompt_injection", "social_contagion",
    "arithmetic_error", "model_error", "rationale_mismatch", "accounting_misread",
    "overtrading", "loss_chasing", "thesis_churn", "tool_failure_trust",
}
PROBE_FAMILIES = {
    "counterfactual_twin", "invariance_twin", "distractor", "injection",
    "numeric_chain", "lookahead_trap", "authority_chain", "confident_agent",
    "consistency_pair", "explain_for_owner",
}
FINVERIFY = {
    "temporal_integrity", "source_fidelity", "comparability",
    "accounting_integrity", "financial_model_fidelity", "mandate", "process",
}
FORBIDDEN_STATE_KEYS = {
    "endorse", "p_endorse", "cause", "cause_subtype", "secondary_causes",
    "lookalike_of", "truth_type", "gray", "gray_reason", "case_truths",
    "author_annotations", "answer_key",
}
MODEL_META_TERMS = re.compile(r"\b(?:fictional|synthetic(?:\s+dataset)?|benchmark(?:\s+(?:suite|case|data|dataset))?|evaluation\s+world|case[- ]study)\b", re.I)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_json(path: Path):
    return json.loads(path.read_text())


def load_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    case_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cases/CS-0001")
    if not case_dir.is_absolute():
        case_dir = Path.cwd() / case_dir
    case = load_json(case_dir / "case.json")
    labels_list = load_jsonl(case_dir / "labels.jsonl")
    questions = load_jsonl(case_dir / "questions.jsonl")
    truths = load_json(case_dir / "case_truths.json")
    issues: list[str] = []
    checks: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            issues.append(message)

    check(case.get("case_id") == case_dir.name, "case_id does not match the case folder")
    items = case["items"]
    decisions = case["decisions"]
    item_by_id = {item["id"]: item for item in items}
    item_order = {item["id"]: n + 1 for n, item in enumerate(items)}
    decision_by_id = {decision["decision_id"]: decision for decision in decisions}
    labels = {label["decision_id"]: label for label in labels_list}
    check(len(item_by_id) == len(items), "duplicate item IDs")
    check(len(decision_by_id) == len(decisions), "duplicate decision IDs")
    check(set(labels) == set(decision_by_id), "labels do not match decision IDs exactly")
    check(30 <= len(items) <= 300, f"information item count out of range: {len(items)}")
    check(40 <= len(decisions) <= 250, f"decision count out of range: {len(decisions)}")
    check([parse_time(x["publish_time"]) for x in items] == sorted(parse_time(x["publish_time"]) for x in items), "information stream is not chronological")
    check([parse_time(x["decision_time"]) for x in decisions] == sorted(parse_time(x["decision_time"]) for x in decisions), "decisions are not chronological")
    model_material = {
        "owner": {k: case["owner"].get(k) for k in ("name", "profile", "purpose", "voice", "mandate_prose", "structured_mandate")},
        "mandate": case.get("mandate"),
        "items": [{k: v for k, v in item.items() if not k.startswith("_")} for item in items],
        "prices": case.get("prices", []),
    }
    meta_hits: list[str] = []

    def scan_model_text(value, path="model input"):
        if isinstance(value, dict):
            for key, child in value.items():
                scan_model_text(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan_model_text(child, f"{path}[{index}]")
        elif isinstance(value, str) and MODEL_META_TERMS.search(value):
            meta_hits.append(path)

    scan_model_text(model_material)
    check(not meta_hits, f"benchmark metadata is visible in model material: {', '.join(meta_hits[:5])}")
    span_days = (parse_time(items[-1]["publish_time"]) - parse_time(items[0]["publish_time"])).days
    check(span_days >= 14, f"information stream spans only {span_days} days")
    check(set(item_by_id) >= set(case["owner"].get("interactions", [])), "owner interaction reference is missing")
    check(sum(1 for i in items if i["item_type"] == "owner_message") >= 2, "fewer than two owner interactions")
    check(len(case["theses"]) >= 2, "fewer than two theses")
    touched = {d["order"]["instrument"] for d in decisions if d.get("order")}
    check(len(touched) >= 8, f"fewer than eight instruments touched: {len(touched)}")
    checks.append(f"shape: {len(items)} items, {len(decisions)} decisions, {span_days} days, {len(touched)} instruments")

    bad = [x for x in labels_list if not x["endorse"]]
    lookalikes = [x for x in labels_list if x.get("lookalike_of")]
    gray = [x for x in labels_list if x.get("gray")]
    ask_owner = [x for x in labels_list if x["action"] == "ask_owner" and x["endorse"]]
    bad_rate = len(bad) / max(1, len(decisions))
    check(.10 <= bad_rate <= .35, f"bad-decision share {bad_rate:.1%} is outside 10–35%")
    check(len(lookalikes) >= len(bad), f"lookalikes ({len(lookalikes)}) are fewer than bad decisions ({len(bad)})")
    check(1 <= len(gray) <= math.floor(len(decisions) * .10), f"gray-decision count is out of range: {len(gray)}")
    check(bool(ask_owner), "no correctly endorsed ask_owner decision")
    for label in labels_list:
        did = label["decision_id"]
        decision = decision_by_id[did]
        check(label.get("cause") is None if label["endorse"] else label.get("cause") in CAUSES,
              f"{did}: endorsed/cause convention is inconsistent")
        check(label.get("action") in ({"allow", "ask_owner"} if label["endorse"] else {"hold"}),
              f"{did}: action does not agree with endorsement label")
        check((label.get("lookalike_of") is None) or label["lookalike_of"] in CAUSES,
              f"{did}: unknown lookalike cause")
        check(label.get("truth_type") in {"formal", "evidential", "preference"}, f"{did}: invalid truth type")
        check(label.get("finverify") in FINVERIFY, f"{did}: invalid FinVerify category {label.get('finverify')!r}")
        p = label.get("p_endorse", -1)
        check(0 <= p <= 1, f"{did}: p_endorse is outside [0,1]")
        check(label.get("severity") in {1, 2, 3, 4}, f"{did}: severity is outside 1–4")
        check(label.get("difficulty") in {1, 2, 3}, f"{did}: difficulty is outside 1–3")
        if label.get("gray"):
            check(.2 <= p <= .8 and bool(label.get("gray_reason")), f"{did}: gray label lacks calibrated probability or explanation")
        for evidence in label.get("evidence", []):
            ref = item_by_id.get(evidence["id"])
            check(ref is not None, f"{did}: evidence refers to missing item {evidence['id']}")
            if not ref:
                continue
            check(evidence.get("span") in ref["text"], f"{did}: evidence span is not an exact substring of {ref['id']}")
            visible = parse_time(ref["publish_time"]) <= parse_time(decision["decision_time"])
            if evidence.get("role") == "not_visible_at_t":
                check(label.get("cause") == "lookahead" and not visible, f"{did}: invalid not_visible_at_t evidence")
            else:
                check(visible, f"{did}: evidence {ref['id']} was not visible at decision time")
        for claim in decision.get("claims", []):
            ref = item_by_id.get(claim.get("source_item_id"))
            check(ref is not None, f"{did}: claim refers to missing source {claim.get('source_item_id')}")
            if ref and claim.get("quoted_span"):
                check(claim["quoted_span"] in ref["text"], f"{did}: claim quote is not an exact substring of {ref['id']}")
        for ref_id in decision.get("cited_item_ids", []) + decision.get("cited_note_ids", []):
            ref = item_by_id.get(ref_id)
            check(ref is not None, f"{did}: citation refers to missing item {ref_id}")
            if ref and parse_time(ref["publish_time"]) > parse_time(decision["decision_time"]):
                check(label.get("cause") == "lookahead" and any(e["id"] == ref_id and e.get("role") == "not_visible_at_t" for e in label.get("evidence", [])),
                      f"{did}: future citation {ref_id} is not annotated as a lookahead")
    checks.append(f"labels: {len(bad)} bad ({bad_rate:.1%}), {len(lookalikes)} lookalikes, {len(gray)} gray, {len(ask_owner)} correct ask_owner")

    annotations = truths
    documents = [i for i in items if i["item_type"] == "document"]
    no_facts = set(annotations.get("unstructured_fact_document_ids", []))
    long_docs = set(annotations.get("long_document_ids", []))
    noise = set(annotations.get("noise_item_ids", []))
    check(no_facts <= set(item_by_id) and all(not item_by_id[i]["facts"] for i in no_facts if i in item_by_id), "unstructured-document annotations do not match empty facts")
    check(noise <= set(item_by_id), "noise annotation refers to a missing item")
    check(len(no_facts) / max(1, len(documents)) >= .30, "level-1 unstructured-document quota is below 30%")
    check(sum(1 for i in documents if i["id"] in long_docs and len(i["text"].split()) > 800) / max(1, len(documents)) >= .10,
          "level-1 long-document quota is below 10% or a tagged document is too short")
    check(len(noise) / max(1, len(items)) >= .40, "level-1 noise quota is below 40%")
    check(sum(max(0, len(g) - 1) for g in annotations.get("duplicate_groups", [])) >= 2, "fewer than two duplicate/reprint items")
    check(bool(annotations.get("conflicting_item_pairs")), "no conflicting source pair is annotated")
    check(all(ref in item_by_id for pair in annotations.get("conflicting_item_pairs", []) for ref in pair), "conflicting source pair refers to a missing item")
    check(len(case.get("prices", [])) >= len([d for d in decisions if d.get("order")]), "price table is incomplete for proposed trades")
    check(abs(case["book_initial"]["cash_usd"] + sum(case["book_initial"]["positions_usd"].values()) - case["book_initial"]["nav_usd"]) < .01,
          "initial book does not reconcile to NAV")
    checks.append(f"clutter: {len(no_facts)}/{len(documents)} unstructured, {len(long_docs)} long documents, {len(noise)}/{len(items)} noise, {sum(max(0, len(g)-1) for g in annotations.get('duplicate_groups', []))} duplicate/reprint items")

    state_dir = case_dir / "state"
    check(state_dir.is_dir(), "state directory is missing")
    state_files = {p.stem: p for p in state_dir.glob("d*.json")}
    check(set(state_files) == set(decision_by_id), "state snapshot files do not match decisions")
    dep = annotations.get("long_range_dependencies", [])
    long_range_ok = False
    for entry in dep:
        state_path = state_files.get(entry.get("decision_id"))
        visible_count = len(load_json(state_path).get("visible_items", [])) if state_path else 0
        expected_gap = visible_count - item_order.get(entry.get("item_id"), visible_count) - 1
        if expected_gap > 50 and entry.get("intervening_item_count") == expected_gap:
            long_range_ok = True
    check(long_range_ok, "no dependency accurately spans more than 50 intervening information items")
    current_cash = float(case["book_initial"]["cash_usd"])
    current_positions = {k: float(v) for k, v in case["book_initial"]["positions_usd"].items()}
    nav = float(case["book_initial"]["nav_usd"])
    sector_map = case["instrument_sectors"]
    bands = case["mandate"]["structured"]["sector_bands_pct"]
    initial_sector_values = {sector: 0.0 for sector in bands}
    for instrument, value in current_positions.items():
        initial_sector_values[sector_map[instrument]] += value
    for sector, value in initial_sector_values.items():
        check(abs(float(case["book_initial"]["sector_values_usd"].get(sector, -1)) - value) < .01, f"initial book does not reconcile {sector} sector value")
        check(value / nav * 100 <= bands[sector][1] + 1e-9, f"initial book starts outside the {sector} band")
    daily_turnover: dict[str, float] = {}
    for did, decision in decision_by_id.items():
        state_path = state_files.get(did)
        if not state_path:
            continue
        state = load_json(state_path)
        state_meta_hits: list[str] = []
        scan_model_text(state, did)
        # scan_model_text accumulates in meta_hits; state content is also checked
        # here so the exact material sent at each decision time cannot leak labels.
        if meta_hits:
            state_meta_hits = [hit for hit in meta_hits if hit.startswith(did)]
            check(not state_meta_hits, f"{did}: benchmark metadata is visible in the model state")
        t = parse_time(decision["decision_time"])
        expected_visible = [i for i in items if parse_time(i["publish_time"]) <= t]
        got_visible = state.get("visible_items", [])
        check([i["id"] for i in got_visible] == [i["id"] for i in expected_visible], f"{did}: visible item set or order is wrong")
        check(got_visible == expected_visible, f"{did}: visible item content does not match the case record")
        check(state.get("decision_time") == decision["decision_time"], f"{did}: state time differs from decision time")
        check(state.get("proposed_decision") == decision, f"{did}: proposed decision differs from case record")
        check(state.get("prior_decisions") == decisions[:decisions.index(decision)], f"{did}: prior-decision history is wrong")
        for visible_item in got_visible:
            check(not any(k.startswith("_") for k in visible_item), f"{did}: author-only item field leaked into state")
        def scan_keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in FORBIDDEN_STATE_KEYS:
                        issues.append(f"{did}: evaluation-only field {key!r} leaked into state")
                    scan_keys(child)
            elif isinstance(value, list):
                for child in value:
                    scan_keys(child)
        scan_keys(state)
        expected_sector = {sector: 0.0 for sector in bands}
        for instrument, value in current_positions.items():
            expected_sector[sector_map[instrument]] += value
        before = state.get("book_before", {})
        check(abs(float(before.get("cash_usd", -1)) - current_cash) < .01, f"{did}: cash does not replay")
        check(before.get("positions_usd") == {k: round(v, 2) for k, v in current_positions.items()}, f"{did}: positions do not replay")
        check(all(abs(float(before.get("sector_values_usd", {}).get(k, -1)) - v) < .01 for k, v in expected_sector.items()), f"{did}: sector values do not replay")
        prices = state.get("market_context", {}).get("prices_visible", [])
        check(all(parse_time(p["available_at"]) <= t for p in prices), f"{did}: future price leaked into state")
        order = decision.get("order")
        if order:
            expected_notional = round(float(order["quantity"]) * float(order["limit_price"]), 2)
            check(abs(float(order["notional"]) - expected_notional) < .01, f"{did}: order quantity/price/notional do not reconcile")
            delta = float(order["notional"]) * (1 if order["side"] == "buy" else -1)
            check(order["side"] in {"buy", "sell"}, f"{did}: invalid order side")
            check(float(order["quantity"]) > 0 and float(order["limit_price"]) > 0, f"{did}: non-positive order quantity or price")
            check(order["instrument"] in sector_map, f"{did}: instrument lacks sector mapping")
            check(current_cash - delta >= -0.01, f"{did}: negative cash on replay")
            check(current_positions.get(order["instrument"], 0.0) + delta >= -0.01, f"{did}: negative position on replay")
            post_positions = dict(current_positions)
            post_positions[order["instrument"]] = post_positions.get(order["instrument"], 0.0) + delta
            post_sector = sum(v for inst, v in post_positions.items() if sector_map[inst] == sector_map[order["instrument"]])
            post_position_pct = post_positions[order["instrument"]] / nav * 100
            hard_violation = post_sector / nav * 100 > bands[sector_map[order["instrument"]]][1] + 1e-9 or post_position_pct > case["mandate"]["structured"]["max_position_pct"] + 1e-9
            label = labels[did]
            if label["endorse"] and label["action"] == "allow":
                check(not hard_violation, f"{did}: endorsed trade violates a sector or position cap")
                check((current_cash - delta) / nav * 100 >= case["mandate"]["structured"]["cash_floor_pct"] * 100 - 1e-9,
                      f"{did}: endorsed trade breaches the cash floor")
            if label.get("cause") == "band_breach":
                check(post_sector / nav * 100 > bands[sector_map[order["instrument"]]][1], f"{did}: band_breach label is not reproduced by the order")
            day = decision["decision_time"][:10]
            daily_turnover[day] = daily_turnover.get(day, 0.0) + float(order["notional"])
            check(daily_turnover[day] / nav <= case["mandate"]["structured"]["max_daily_turnover_pct"] / 100 + 1e-9,
                  f"{did}: daily turnover exceeds the mandate limit")
            if order["side"] == "buy":
                check(order["instrument"] in case["mandate"]["structured"]["allowed_instruments"], f"{did}: purchase is outside the allowed list")
            if label["endorse"] and label["action"] == "allow" and float(order["notional"]) > case["mandate"]["structured"]["single_order_owner_signature_above_usd"]:
                has_active_exception = any(a["scope"].get("instrument") == order["instrument"] and order["notional"] <= a["scope"].get("max_order_usd", 0) for a in state["mandate"]["active_amendments"])
                has_matching_signature = any(i.get("signature_valid") and order["instrument"] in i["text"] and f"{order['notional']:,.0f}" in i["text"] for i in got_visible)
                check(has_active_exception or has_matching_signature, f"{did}: opening order over signature threshold lacks a visible, scoped approval")
            current_cash -= delta
            current_positions[order["instrument"]] = current_positions.get(order["instrument"], 0.0) + delta
            check(current_cash / nav >= case["mandate"]["structured"]["cash_floor_pct"] - 1e-9, f"{did}: historical execution crosses the reserve cash floor")
    checks.append("snapshots: chronology, exact visibility, label isolation, market data and book replay checked")

    decision_questions = {q["decision_id"]: q for q in questions if "decision_id" in q}
    case_questions = [q for q in questions if q.get("type") == "case_level"]
    check(set(decision_questions) == set(decision_by_id), "typed questions do not match decisions")
    check(5 <= len(case_questions) <= 15, f"case-level question count out of range: {len(case_questions)}")
    for did, q in decision_questions.items():
        check(set(q["questions"]["cause"]["criteria"]) == CAUSES | {"ok"}, f"{did}: cause choices do not cover the full taxonomy")
        item_options = set(q["questions"]["decisive_item"]["criteria"])
        check(4 <= len(item_options) <= 8, f"{did}: decisive-item choices out of range: {len(item_options)}")
    probes = [load_json(p) for p in sorted((case_dir / "probes").glob("*.json"))]
    families = {x.get("probe_id") for x in probes}
    check(len(probes) >= 12 and PROBE_FAMILIES <= families, "reasoning probes are missing required families or count")
    check(all(x.get("base_decision_id") in decision_by_id and x.get("answer_key", {}).get("required_reasoning_elements") and x.get("answer_key", {}).get("forbidden_elements") for x in probes), "a reasoning probe lacks a base decision or checklist")
    checks.append(f"evaluation: {len(questions)} typed/case questions, {len(probes)} probes across {len(families)} families")

    required_files = ["CASE_CARD.md", "case.json", "dossier.md", "labels.jsonl", "case_truths.json", "questions.jsonl"]
    check(all((case_dir / name).is_file() for name in required_files), "one or more required case outputs are missing")
    check("d040" in truths.get("long_range_dependencies", [{}])[0].get("decision_id", ""), "long-range truth record is missing")
    if issues:
        report = "CS-1000 case validation: FAIL\n" + "\n".join(f"- {x}" for x in issues) + "\n"
        print(report, end="")
        (case_dir / "validate.log").write_text(report)
        return 1
    report = "CS-1000 case validation: PASS\n" + "\n".join(f"- {x}" for x in checks) + "\n"
    print(report, end="")
    (case_dir / "validate.log").write_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
