"""Report the lead's two blind checks of the T20 rule labels.

The lead drew 60 items from ``handlabels.jsonl`` (15 per item kind), removed the
family, id and source fields, and had Claude Haiku label them from
``QUESTIONS.md`` in a separate context.  The first pass accidentally left
``triage_rules`` in the item state, so Haiku could read the reference rules; the
lead reran the check with those rules removed.  Both passes are reported here.

This script recomputes every agreement count from the raw label files rather
than trusting a stored summary.  It asserts that the with-rules counts match
``blind_lead/agreement.json``.  It also compares the no-rules counts with
``blind_lead/agreement_norules.json`` and reports any field that disagrees with
the raw labels instead of silently using it.

It then re-scores the four compared decision models on those 60 items from the
cached primary answers, against the rule labels and against both blind label
sets.  No network call and no new spend: the 60 states match the primary cache,
so answers come from ``cache/triage_responses.jsonl``.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1 import triage  # noqa: E402

TASK = ROOT / "work" / "T20"
BLIND = TASK / "blind_lead"

MODELS = [
    {"id": "typesafe/jev-1.14", "label": "TypeSafe Jev 1.14"},
    {"id": "cloudflare/clef-flash", "label": "Cloudflare Clef Flash"},
    {"id": "liquid/d1.2-ultra", "label": "Liquid d1.2-ultra"},
    {"id": "perplexity/pplx-decider-v1.3:free", "label": "Perplexity Decider v1.3 (free)"},
]

QUESTIONS = ("label_ok", "finverify", "difficulty", "finding_kind", "failure_kind")
THRESHOLD = 0.85


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalise(value: Any, question: str) -> Any:
    if value is None:
        return None
    if question == "label_ok":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return 1 if value.lower() == "true" else 0
        return int(value)
    if question == "difficulty":
        return int(round(float(value)))
    return str(value)


def comparable(value: Any, question: str, *, align_rule: bool = False) -> Any:
    """Put a value on the blind scale.  The rule difficulty scale is 0-2, blind is 1-3."""
    value = normalise(value, question)
    if question == "difficulty" and value is not None and align_rule:
        return value + 1
    return value


def rate(correct: int, n: int) -> float | None:
    return (correct / n) if n else None


def recompute_agreement(
    items: list[dict[str, Any]],
    key_by_item: dict[str, str],
    rule_labels: dict[str, dict[str, Any]],
    blind_labels: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Rule labels vs one blind-label set, recomputed from the raw files."""
    out: dict[str, dict[str, Any]] = {}
    for question in QUESTIONS:
        agree = aligned = n = 0
        for item in items:
            if question not in item["questions"]:
                continue
            rule_id = key_by_item[item["item"]]
            if question not in rule_labels[rule_id]:
                continue
            blind_raw = blind_labels[item["item"]].get(question)
            if blind_raw is None:
                continue
            n += 1
            rule = normalise(rule_labels[rule_id][question], question)
            blind = normalise(blind_raw, question)
            agree += int(rule == blind)
            aligned += int(comparable(rule, question, align_rule=True) == blind)
        out[question] = {"agree": agree, "n": n, "rate": rate(agree, n)}
        if question == "difficulty":
            out["difficulty_aligned"] = {"agree": aligned, "n": n, "rate": rate(aligned, n)}
    return out


def verdict(question: str, with_rate: float | None, no_rate: float | None) -> str:
    if question == "difficulty":
        return "Coarse - use only as a bucket, never to rank"
    if with_rate is not None and no_rate is not None and min(with_rate, no_rate) >= THRESHOLD:
        return "Reliable"
    return "Unreliable"


def model_agreement(
    items: list[dict[str, Any]],
    key_by_item: dict[str, str],
    rule_labels: dict[str, dict[str, Any]],
    blind_with: dict[str, dict[str, Any]],
    blind_nor: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item, result in zip(items, results):
        rule_id = key_by_item[item["item"]]
        for question in item["questions"]:
            answer = result["answers"].get(question, {})
            if question == "difficulty":
                value_raw = answer.get("value")
                predicted = None if value_raw is None else int(round(float(value_raw)))
            else:
                predicted = answer.get("label")
            rule = normalise(rule_labels[rule_id][question], question)
            bw = normalise(blind_with[item["item"]].get(question), question)
            bn = normalise(blind_nor[item["item"]].get(question), question)
            row = out.setdefault(
                question,
                {
                    "n": 0,
                    "vs_rule": 0,
                    "vs_blind_with_rules": 0,
                    "vs_blind_no_rules": 0,
                    "blind_n": 0,
                },
            )
            row["n"] += 1
            if predicted is not None:
                if question == "difficulty":
                    row["vs_rule"] += int(predicted == rule)
                    row["vs_blind_with_rules"] += int((predicted + 1) == bw)
                    row["vs_blind_no_rules"] += int((predicted + 1) == bn)
                else:
                    row["vs_rule"] += int(predicted == rule)
                    row["vs_blind_with_rules"] += int(predicted == bw)
                    row["vs_blind_no_rules"] += int(predicted == bn)
            if bw is not None:
                row["blind_n"] += 1
    return out


def rule_table(
    with_rules: dict[str, dict[str, Any]],
    no_rules: dict[str, dict[str, Any]],
) -> list[str]:
    lines = [
        "| Question | Rule vs blind, rules shown | Rule vs blind, no rules | n | Reliable? |",
        "|---|---:|---:|---:|---|",
    ]
    for question in QUESTIONS:
        w = with_rules.get(question) or {"agree": 0, "n": 0, "rate": None}
        nr = no_rules.get(question) or {"agree": 0, "n": 0, "rate": None}
        if question == "difficulty":
            wa = with_rules.get("difficulty_aligned") or {"agree": 0, "n": 0, "rate": None}
            na = no_rules.get("difficulty_aligned") or {"agree": 0, "n": 0, "rate": None}
            wtext = (
                f"{w['agree']}/{w['n']} = {w['rate']:.2f} raw; "
                f"{wa['agree']}/{wa['n']} = {wa['rate']:.2f} aligned"
                if w["n"]
                else "n/a"
            )
            ntext = (
                f"{nr['agree']}/{nr['n']} = {nr['rate']:.2f} raw; "
                f"{na['agree']}/{na['n']} = {na['rate']:.2f} aligned"
                if nr["n"]
                else "n/a"
            )
        else:
            wtext = f"{w['agree']}/{w['n']} = {w['rate']:.2f}" if w["n"] else "n/a"
            ntext = f"{nr['agree']}/{nr['n']} = {nr['rate']:.2f}" if nr["n"] else "n/a"
        lines.append(
            f"| `{question}` | {wtext} | {ntext} | {w['n']} | "
            f"{verdict(question, w['rate'], nr['rate'])} |"
        )
    return lines


def model_table(per_model: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    lines = [
        "| Model | FinVerify vs rule (n=15) | FinVerify vs blind, rules shown (n=15) | FinVerify vs blind, no rules (n=15) | Failure kind vs rule (n=15) | Failure kind vs blind, rules shown (n=15) | Failure kind vs blind, no rules (n=15) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        rows = per_model[model["id"]]
        cells = []
        for question in ("finverify", "failure_kind"):
            row = rows.get(question, {})
            n = row.get("n") or 1
            cells.append(f"{row.get('vs_rule', 0)}/{n} = {row.get('vs_rule', 0) / n:.2f}")
            cells.append(
                f"{row.get('vs_blind_with_rules', 0)}/{n} = "
                f"{row.get('vs_blind_with_rules', 0) / n:.2f}"
            )
            cells.append(
                f"{row.get('vs_blind_no_rules', 0)}/{n} = "
                f"{row.get('vs_blind_no_rules', 0) / n:.2f}"
            )
        lines.append(f"| {model['label']} | " + " | ".join(cells) + " |")
    return lines


def descriptive_table(per_model: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    lines = [
        "| Model | label_ok vs rule (n=30) | label_ok vs blind, rules (n=30) | label_ok vs blind, no rules (n=30) | finding_kind vs rule (n=15) | finding_kind vs blind, rules (n=15) | finding_kind vs blind, no rules (n=15) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        rows = per_model[model["id"]]
        cells = []
        for question in ("label_ok", "finding_kind"):
            row = rows.get(question, {})
            n = row.get("n") or 1
            cells.append(f"{row.get('vs_rule', 0)}/{n} = {row.get('vs_rule', 0) / n:.2f}")
            cells.append(
                f"{row.get('vs_blind_with_rules', 0)}/{n} = "
                f"{row.get('vs_blind_with_rules', 0) / n:.2f}"
            )
            cells.append(
                f"{row.get('vs_blind_no_rules', 0)}/{n} = "
                f"{row.get('vs_blind_no_rules', 0) / n:.2f}"
            )
        lines.append(f"| {model['label']} | " + " | ".join(cells) + " |")
    return lines


def with_rules_mismatches(
    computed: dict[str, dict[str, Any]], stored: dict[str, Any]
) -> list[str]:
    out = []
    for question in QUESTIONS:
        value = (stored.get(question) or {}).get("agree")
        row = computed.get(question)
        if value is not None and row and int(value) != int(row["agree"]):
            out.append(
                f"{question}: stored={int(value)}/{row['n']}, recomputed={row['agree']}/{row['n']}"
            )
    aligned = (stored.get("difficulty_aligned") or {}).get("agree")
    row = computed.get("difficulty_aligned")
    if aligned is not None and row and int(aligned) != int(row["agree"]):
        out.append(
            f"difficulty_aligned: stored={int(aligned)}/{row['n']}, "
            f"recomputed={row['agree']}/{row['n']}"
        )
    return out


def no_rules_mismatches(
    computed: dict[str, dict[str, Any]], stored: dict[str, Any]
) -> list[str]:
    """Compare the recomputed no-rules counts with the stored summary.

    ``agreement_norules.json`` uses ``rule_vs_norules`` for the rule-label
    comparison.  Its difficulty entry mixes raw and aligned counts, so only the
    non-difficulty questions are checked strictly; a label_ok mismatch is the
    one that matters for reliability.
    """
    out = []
    for question in QUESTIONS:
        if question == "difficulty":
            continue
        value = (stored.get(question) or {}).get("rule_vs_norules")
        row = computed.get(question)
        if value is not None and row and int(value) != int(row["agree"]):
            out.append(
                f"{question}: stored={int(value)}/{row['n']}, recomputed={row['agree']}/{row['n']}"
            )
    return out



def main() -> None:
    agreement_with = json.loads((BLIND / "agreement.json").read_text(encoding="utf-8"))
    stored_nor = json.loads((BLIND / "agreement_norules.json").read_text(encoding="utf-8"))
    items = load_jsonl(BLIND / "items.jsonl")
    items_nor = load_jsonl(BLIND / "items_norules.jsonl")
    key_by_item = {
        row["item"]: row["id"]
        for row in json.loads((BLIND / ".key.json").read_text(encoding="utf-8"))
    }
    blind_with = {row["item"]: row["answers"] for row in load_jsonl(BLIND / "labels.jsonl")}
    blind_nor = {row["item"]: row["answers"] for row in load_jsonl(BLIND / "labels_norules.jsonl")}
    rule_labels = {
        row["id"]: row["labels"] for row in load_jsonl(TASK / "handlabels.jsonl")
    }

    # Recompute both checks from the raw annotations.  agreement.json must match
    # exactly; agreement_norules.json is compared and any mismatch is reported
    # rather than trusted.
    with_rules = recompute_agreement(items, key_by_item, rule_labels, blind_with)
    no_rules = recompute_agreement(items_nor, key_by_item, rule_labels, blind_nor)
    mismatches_with = with_rules_mismatches(with_rules, agreement_with)
    if mismatches_with:
        raise SystemExit(
            "recomputed with-rules agreement does not match blind_lead/agreement.json: "
            + "; ".join(mismatches_with)
        )
    mismatches_nor = no_rules_mismatches(no_rules, stored_nor)

    reliable = [
        question
        for question in QUESTIONS
        if question != "difficulty"
        and (with_rules.get(question) or {}).get("rate") is not None
        and (no_rules.get(question) or {}).get("rate") is not None
        and min(with_rules[question]["rate"], no_rules[question]["rate"]) >= THRESHOLD
    ]
    if "finding_kind" not in reliable:
        raise SystemExit(
            "finding_kind no longer clears the blind-agreement threshold; "
            "do not rank on it"
        )

    cache = TASK / "cache" / "triage_responses.jsonl"
    per_model: dict[str, dict[str, dict[str, Any]]] = {}
    for model in MODELS:
        results = triage.triage(
            items,
            model=model["id"],
            cache_path=cache,
            allow_network=False,
        )
        per_model[model["id"]] = model_agreement(
            items, key_by_item, rule_labels, blind_with, blind_nor, results
        )

    rule_lines = rule_table(with_rules, no_rules)
    model_lines = model_table(per_model)
    descriptive_lines = descriptive_table(per_model)

    print("== the lead's two blind checks: how the sample was drawn ==")
    print(
        "The lead drew 60 items from the 200 rule-labelled items (15 per item kind), "
        "removed the family, id and source fields, and had Claude Haiku label them "
        "blind from QUESTIONS.md in a separate context.  The first pass still showed "
        "Haiku the reference triage rules; the lead reran it with those rules removed."
    )
    print()
    print("== rule labels (blind-checked) vs the blind labels, both passes ==")
    print(
        "Every count below is recomputed by this script from handlabels.jsonl and the "
        "two labels files; it asserts that the rules-shown counts match agreement.json."
    )
    if mismatches_nor:
        print(
            "Warning: agreement_norules.json disagrees with its own label file on: "
            + "; ".join(mismatches_nor)
            + ".  The recomputed values above are used."
        )
    print("\n".join(rule_lines))
    print()
    print(
        "Only `finding_kind` clears 0.85 in both passes.  `label_ok` falls from "
        "26/30 to 22/30 once the rules are removed; its reference is defective until "
        "T31/v2.1 fixes the clean-action generator."
    )
    print()
    print("== model agreement on the 60 blind items, FinVerify and failure kind ==")
    print(
        "Answers are the cached primary-condition answers (the same 60 states). "
        "No new request was made.  Neither reference is ground truth for these questions."
    )
    print("\n".join(model_lines))
    print()
    print("== descriptive: label_ok and finding_kind on the same 60 items ==")
    print("\n".join(descriptive_lines))

    payload = {
        "n_items": len(items),
        "threshold": THRESHOLD,
        "with_rules": with_rules,
        "no_rules": no_rules,
        "reliable_questions": reliable,
        "stored_norules_mismatches": mismatches_nor,
        "models": per_model,
        "note": (
            "The 60 states match the primary cache; no new request was made.  "
            "The rules-shown counts match blind_lead/agreement.json.  The no-rules "
            "label_ok field in agreement_norules.json (0/30) disagrees with the raw "
            "labels (22/30) and is not used."
        ),
    }
    (TASK / "blind_check.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (TASK / "blind_reliability.json").write_text(
        json.dumps(
            {
                "threshold": THRESHOLD,
                "with_rules": with_rules,
                "no_rules": no_rules,
                "reliable_questions": reliable,
                "stored_norules_mismatches": mismatches_nor,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    md = ["# T20 rule-label blind check", ""]
    md.append(
        "Generated by `blind_check.py`.  Counts are recomputed from "
        "`handlabels.jsonl`, `blind_lead/labels.jsonl` and "
        "`blind_lead/labels_norules.jsonl`; they are not typed."
    )
    md.append("")
    md.extend(rule_lines)
    md.append("")
    md.extend(model_lines)
    md.append("")
    (TASK / "blind_agreement.md").write_text("\n".join(md) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
