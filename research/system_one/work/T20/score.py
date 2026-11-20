"""Score the hosted decision models on the 200-item set, from cache.

Every number in REPORT.md comes from this script.  It never touches the
network: the cache built by ``fetch_triage.py`` is the only source of answers.

The labels are **rule labels (blind-checked)**: a deterministic content rubric
whose agreement with the lead's two independent blind checks is reported by
``blind_check.py``.  Round 6 ranks only on ``finding_kind``: it is the one
question whose rule labels clear 0.85 agreement in both blind passes.  The
``label_ok`` reference is descriptive until T31/v2.1 fixes it.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1 import triage  # noqa: E402

MODELS = [
    {
        "id": "typesafe/jev-1.14",
        "label": "TypeSafe Jev 1.14",
        "role": "external decision model (T05 default)",
    },
    {
        "id": "cloudflare/clef-flash",
        "label": "Cloudflare Clef Flash",
        "role": "small open-weight 9B",
    },
    {
        "id": "liquid/d1.2-ultra",
        "label": "Liquid d1.2-ultra",
        "role": "largest Liquid decision model",
    },
    {
        "id": "perplexity/pplx-decider-v1.3:free",
        "label": "Perplexity Decider v1.3 (free)",
        "role": "free Perplexity decision model (no parameter count in the cached catalog)",
    },
]

QUESTIONS = ("label_ok", "finverify", "difficulty", "finding_kind", "failure_kind")
QUESTION_LABEL = {
    "label_ok": "label plausibly wrong",
    "finverify": "FinVerify category",
    "difficulty": "difficulty",
    "finding_kind": "reviewer finding kind",
    "failure_kind": "failure mechanism",
}


def wilson(correct: int, n: int, z: float = 1.959963984540054) -> list[float | None]:
    if n == 0:
        return [None, None]
    p = correct / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"models": [], "count": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    models = data.get("models") or []
    return {"models": models, "count": len(models), "fetched_at": data.get("fetched_at")}


def predicted_label(answer: dict[str, Any], question: str) -> Any:
    if question == "difficulty":
        value = answer.get("value")
        return None if value is None else int(round(float(value)))
    return answer.get("label")


def load_blind_agreement(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing blind agreement file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_reliability(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"missing reliability file: {path}; run work/T20/blind_check.py first"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data.get("reliable_questions") or []
    if not questions:
        raise SystemExit("no question clears the blind-agreement threshold; do not rank")
    # Round 6 ranks on finding_kind only.  Guard the generated file so a future
    # stale summary cannot silently reintroduce label_ok or difficulty.
    if questions != ["finding_kind"]:
        raise SystemExit(
            f"expected finding_kind as the only reliable question, got {questions}"
        )
    return data


def cache_files(cache_dir: Path) -> list[Path]:
    """Every triage cache in the folder, for the one lifetime $5 budget."""
    return sorted(path.resolve() for path in cache_dir.glob("triage*.jsonl"))


def global_cache_spend(cache_dir: Path) -> float:
    return sum(triage.cache_cost(path) for path in cache_files(cache_dir) if path.exists())



def question_summary(per_question: dict[str, Any], questions: list[str]) -> dict[str, Any]:
    correct = sum(int(per_question[q].get("correct") or 0) for q in questions)
    n = sum(int(per_question[q].get("n") or 0) for q in questions)
    return {
        "questions": list(questions),
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else None,
        "ci95": wilson(correct, n),
    }


def evaluate_model(
    model: dict[str, Any],
    items: list[dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    cache_path: Path,
) -> dict[str, Any]:
    results = triage.triage(
        items,
        model=model["id"],
        cache_path=cache_path,
        allow_network=False,
    )
    by_question: dict[str, list[tuple[bool, Any, Any, str]]] = defaultdict(list)
    correctness: dict[str, bool] = {}
    failures = []
    for item, result in zip(items, results):
        for question in item["questions"]:
            answer = result["answers"].get(question, {})
            predicted = predicted_label(answer, question)
            expected = labels[item["id"]][question]
            if predicted is None:
                correctness[f"{item['id']}|{question}"] = False
                by_question[question].append((False, None, expected, item["kind"]))
                failures.append({"id": item["id"], "question": question, "reason": "no answer"})
                continue
            correct = bool(predicted == expected)
            correctness[f"{item['id']}|{question}"] = correct
            by_question[question].append((correct, predicted, expected, item["kind"]))
            if not correct:
                failures.append(
                    {
                        "id": item["id"],
                        "question": question,
                        "predicted": predicted,
                        "expected": expected,
                    }
                )

    per_question: dict[str, Any] = {}
    total_correct = 0
    total_asked = sum(len(item["questions"]) for item in items)
    total_answered = 0
    for question in QUESTIONS:
        rows = by_question.get(question) or []
        n = len(rows)
        correct = sum(1 for ok, _, _, _ in rows if ok)
        answered = sum(1 for _, predicted, _, _ in rows if predicted is not None)
        total_correct += correct
        total_answered += answered
        per_question[question] = {
            "n": n,
            "answered": answered,
            "coverage": (answered / n) if n else 0.0,
            "correct": correct,
            "accuracy": (correct / n) if n else None,
            "ci95": wilson(correct, n),
            "label_counts": dict(Counter(str(expected) for _, _, expected, _ in rows)),
            "by_kind": {
                kind: {
                    "n": len(kind_rows),
                    "accuracy": sum(1 for ok, _, _, _ in kind_rows if ok) / len(kind_rows),
                }
                for kind in sorted({row[3] for row in rows})
                for kind_rows in [[row for row in rows if row[3] == kind]]
            },
            "confusion": {
                f"{predicted}->{expected}": count
                for (predicted, expected), count in Counter(
                    (str(predicted), str(expected)) for _, predicted, expected, _ in rows
                ).items()
            },
        }

    question_accuracies = [
        per_question[q]["accuracy"]
        for q in QUESTIONS
        if per_question[q]["accuracy"] is not None
    ]
    macro = statistics.mean(question_accuracies) if question_accuracies else None
    item_coverage = (
        sum(
            1
            for item, result in zip(items, results)
            if all(
                result["answers"].get(q, {}).get("label") is not None
                for q in item["questions"]
            )
        )
        / len(items)
        if items
        else 0.0
    )

    # Only rows for this 200-item set count.  If the cache also holds probe rows
    # or rows from another set, they must not inflate cost per 1,000 items.
    wanted = {
        triage.request_key(
            triage.request_body(
                model["id"],
                item.get("state"),
                triage.resolve_questions(item.get("questions")),
            )
        )
        for item in items
    }
    rows = triage.cache_rows(cache_path)
    model_rows = [
        row
        for row in rows
        if row.get("model") == model["id"] and row.get("key") in wanted
    ]
    cost = sum(
        float(((row.get("response") or {}).get("usage") or {}).get("cost", 0.0) or 0.0)
        for row in model_rows
    )
    latencies = sorted(float(row.get("latency_s", 0.0) or 0.0) for row in model_rows)
    # Cost is per item attempted, not per item answered: a model that refuses
    # half the items must not look half as expensive per item.
    n_cost = max(1, len(items))
    latency_mean = statistics.mean(latencies) if latencies else None
    latency_p50 = statistics.median(latencies) if latencies else None
    latency_p95 = (
        latencies[min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))]
        if latencies
        else None
    )
    return {
        "id": model["id"],
        "label": model["label"],
        "role": model["role"],
        "per_question": per_question,
        "macro_accuracy": macro,
        "all_answers_accuracy": (total_correct / total_asked) if total_asked else None,
        "total_asked": total_asked,
        "total_answered": total_answered,
        "item_coverage": item_coverage,
        "requests": len(model_rows),
        "cost_usd": cost,
        "cost_per_1000_usd": (cost / n_cost * 1000.0) if n_cost else None,
        "latency_s": {
            "mean": latency_mean,
            "p50": latency_p50,
            "p95": latency_p95,
            "n": len(latencies),
        },
        "n_failures": len(failures),
        "failure_examples": failures[:12],
        "correctness": correctness,
    }


def majority_baseline(label_rows: list[dict[str, Any]]) -> dict[str, Any]:
    per_question: dict[str, Any] = {}
    for question in QUESTIONS:
        values = [str(row["labels"][question]) for row in label_rows if question in row["labels"]]
        counts = Counter(values)
        n = len(values)
        majority, count = counts.most_common(1)[0] if counts else (None, 0)
        per_question[question] = {
            "n": n,
            "majority": majority,
            "correct": count,
            "accuracy": (count / n) if n else None,
            "label_counts": dict(counts),
        }
    accuracies = [per_question[q]["accuracy"] for q in QUESTIONS if per_question[q]["accuracy"] is not None]
    total_n = sum(per_question[q]["n"] for q in QUESTIONS)
    total_correct = sum(
        per_question[q]["accuracy"] * per_question[q]["n"]
        for q in QUESTIONS
        if per_question[q]["accuracy"] is not None
    )
    return {
        "per_question": per_question,
        "macro_accuracy": statistics.mean(accuracies) if accuracies else None,
        "micro_accuracy": (total_correct / total_n) if total_n else None,
        "n_questions": total_n,
    }


def displayed_label_baseline(
    items: list[dict[str, Any]], label_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Strongest trivial baseline that only reads the displayed owner label.

    For FinVerify, y=0 -> none and y=1 -> source_fidelity (the modal failure
    category).  For difficulty, y=0 -> easy and y=1 -> medium.  label_ok and the
    review/failure questions fall back to their majority classes, because the
    displayed label cannot answer them on its own.
    """
    labels = {row["id"]: row["labels"] for row in label_rows}
    per_question: dict[str, dict[str, Any]] = {}
    total_correct = 0
    total_asked = 0
    for question in QUESTIONS:
        correct = 0
        n = 0
        for item in items:
            if question not in item["questions"]:
                continue
            y = (item["state"].get("owner_label") or {}).get("y")
            if question == "label_ok":
                predicted: Any = 0
            elif question == "finverify":
                predicted = "none" if (y is None or int(y) == 0) else "source_fidelity"
            elif question == "difficulty":
                predicted = 0 if (y is None or int(y) == 0) else 1
            elif question == "failure_kind":
                predicted = "reasoning_error"
            elif question == "finding_kind":
                predicted = "leakage"
            else:
                predicted = None
            expected = labels[item["id"]][question]
            n += 1
            if predicted == expected:
                correct += 1
        total_correct += correct
        total_asked += n
        per_question[question] = {
            "n": n,
            "correct": correct,
            "accuracy": (correct / n) if n else None,
        }
    accuracies = [per_question[q]["accuracy"] for q in QUESTIONS if per_question[q]["accuracy"] is not None]
    return {
        "per_question": per_question,
        "macro_accuracy": statistics.mean(accuracies) if accuracies else None,
        "micro_accuracy": (total_correct / total_asked) if total_asked else None,
        "n_questions": total_asked,
    }


def section_baseline(
    items: list[dict[str, Any]], label_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Review-finding baseline that reads only the REVIEW.md section name."""
    labels = {row["id"]: row["labels"] for row in label_rows}
    by_section: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if item["kind"] != "review_finding":
            continue
        section = item["state"].get("section") or "unknown"
        by_section[section].append(labels[item["id"]]["finding_kind"])
    majority = {
        section: Counter(values).most_common(1)[0][0]
        for section, values in by_section.items()
    }
    correct = 0
    n = 0
    for item in items:
        if item["kind"] != "review_finding":
            continue
        section = item["state"].get("section") or "unknown"
        n += 1
        if majority[section] == labels[item["id"]]["finding_kind"]:
            correct += 1
    return {
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else None,
        "majority_by_section": majority,
    }


def _item_counts(
    evaluation: dict[str, Any],
    items: list[dict[str, Any]],
    questions: list[str] | None = None,
) -> list[tuple[float, int]]:
    """(correct answers, questions) per item, in item order.

    ``questions`` restricts the count to the named questions, which is how the
    ranking avoids the unreliable FinVerify, failure-kind and difficulty strata.
    """
    correctness = evaluation.get("correctness") or {}
    selected = set(questions) if questions is not None else None
    rows = []
    for item in items:
        asked = [q for q in item["questions"] if selected is None or q in selected]
        correct = sum(1 for q in asked if correctness.get(f"{item['id']}|{q}"))
        rows.append((float(correct), len(asked)))
    return rows


def paired_bootstrap(
    evaluations: list[dict[str, Any]],
    items: list[dict[str, Any]],
    reps: int = 2000,
    seed: int = 20261119,
    questions: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Bootstrap the item-weighted (micro) accuracy and each model's gap to the best.

    Resampling items, not questions, keeps the within-item correlation of the
    questions asked about one item.  A model is treated as statistically
    indistinguishable from the best when the 95% interval of (best - model)
    contains zero.  ``questions`` selects the reliable questions; all five are
    used only for the legacy descriptive interval.
    """
    if not evaluations:
        return {}
    rng = random.Random(seed)
    ids = list(range(len(items)))
    counts = {e["id"]: _item_counts(e, items, questions) for e in evaluations}
    boot: dict[str, list[float]] = {e["id"]: [] for e in evaluations}
    for _ in range(reps):
        sample = [rng.choice(ids) for _ in ids]
        for e in evaluations:
            rows = counts[e["id"]]
            num = sum(rows[i][0] for i in sample)
            den = sum(rows[i][1] for i in sample)
            boot[e["id"]].append(num / den if den else 0.0)
    point = {
        e["id"]: (sum(c for c, _ in counts[e["id"]]) / sum(n for _, n in counts[e["id"]]))
        for e in evaluations
        if sum(n for _, n in counts[e["id"]])
    }
    best_id = max(point, key=lambda key: point[key])
    out: dict[str, dict[str, Any]] = {}
    for e in evaluations:
        key = e["id"]
        if key not in point:
            continue
        diffs = sorted(boot[best_id][i] - boot[key][i] for i in range(reps))
        lo = diffs[int(0.025 * (reps - 1))]
        hi = diffs[int(0.975 * (reps - 1))]
        out[key] = {
            "micro_accuracy": point[key],
            "boot_ci95": [
                sorted(boot[key])[int(0.025 * (reps - 1))],
                sorted(boot[key])[int(0.975 * (reps - 1))],
            ],
            "gap_to_best": point[best_id] - point[key],
            "gap_ci95": [lo, hi],
            "indistinguishable_from_best": lo <= 0.0 <= hi,
        }
    return {
        "models": out,
        "best": best_id,
        "reps": reps,
        "seed": seed,
        "questions": list(questions) if questions is not None else None,
    }


def recommend(
    evaluations: list[dict[str, Any]],
    baseline: dict[str, Any],
    items: list[dict[str, Any]],
    questions: list[str],
) -> dict[str, Any]:
    eligible = [
        e for e in evaluations
        if (e["item_coverage"] or 0.0) >= 0.95 and e["reliable"]["accuracy"] is not None
    ]
    if not eligible:
        return {"model": None, "reason": "no model had at least 95% item coverage"}
    boot = paired_bootstrap(eligible, items, questions=questions)
    stats = boot["models"]
    best_id = boot["best"]
    # Any model whose gap to the best has a 95% interval containing zero is a
    # candidate; among those, choose the cheapest, then the fastest.
    candidates = [
        e for e in eligible
        if stats.get(e["id"], {}).get("indistinguishable_from_best")
    ]
    if not candidates:
        candidates = [e for e in eligible if e["id"] == best_id]
    candidates.sort(
        key=lambda e: (
            e["cost_per_1000_usd"] if e["cost_per_1000_usd"] is not None else float("inf"),
            e["latency_s"]["mean"] if e["latency_s"]["mean"] is not None else float("inf"),
            -(e["reliable"]["accuracy"] or 0.0),
        )
    )
    chosen = candidates[0]
    best = next(e for e in eligible if e["id"] == best_id)
    baseline_reliable = question_summary(baseline["per_question"], questions)
    baseline_micro = baseline_reliable["accuracy"]
    margin = (
        chosen["reliable"]["accuracy"] - baseline_micro
        if baseline_micro is not None
        else None
    )
    chosen_stats = stats.get(chosen["id"], {})
    paid_close = [
        e for e in candidates
        if (e["cost_per_1000_usd"] or 0.0) > 0.0 and e["id"] != chosen["id"]
    ]
    reason = (
        f"The best finding-kind accuracy (the only reliable question) is "
        f"{best['reliable']['accuracy']:.3f} ({best['label']}). The chosen default is "
        f"`{chosen['label']}` at ${chosen['cost_per_1000_usd']:.6f} per 1,000 items and "
        f"{chosen['latency_s']['mean']:.3f} s mean latency. "
    )
    if chosen["id"] != best_id:
        lo, hi = chosen_stats.get("gap_ci95", [0.0, 0.0])
        reason += (
            f"The best model is {chosen_stats.get('gap_to_best', 0.0):+.3f} above it "
            f"(95% bootstrap interval [{lo:+.3f}, {hi:+.3f}]), so the two are "
            "statistically indistinguishable. "
        )
    if paid_close:
        # Select the paid alternative by reliable accuracy, not by raw macro,
        # because FinVerify, failure kind and difficulty are not rankable.
        paid_close.sort(key=lambda e: -(e["reliable"]["accuracy"] or 0.0))
        paid = paid_close[0]
        reason += (
            f"`{paid['label']}` is the paid alternative with the highest finding-kind "
            f"accuracy ({paid['reliable']['accuracy']:.3f}) and all-question micro "
            f"{paid['all_answers_accuracy']:.3f}, but it costs "
            f"${paid['cost_per_1000_usd']:.6f} per 1,000 and buys no clear accuracy gain. "
        )
    reason += (
        " The ranking is 23 reviewer findings, so its interval is wide; `label_ok` is "
        "descriptive only because its reference is defective until T31/v2.1.  This is a "
        "reviewer-finding sorter, not a general label-audit gate."
    )
    if margin is not None and margin < 0.05:
        reason += (
            f" Caution: its finding-kind accuracy is {margin:+.3f} versus the "
            f"majority-class baseline ({baseline_micro:.3f}), so it is a sorting aid for "
            f"a human, not an autonomous gate."
        )
    return {
        "model": chosen["id"],
        "label": chosen["label"],
        "micro_accuracy": chosen["reliable"]["accuracy"],
        "macro_accuracy": chosen["macro_accuracy"],
        "best_micro_model": best["id"],
        "best_micro_accuracy": best["reliable"]["accuracy"],
        "baseline_micro_accuracy": baseline_micro,
        "baseline_macro_accuracy": baseline.get("macro_accuracy"),
        "margin_over_baseline_micro": margin,
        "cost_per_1000_usd": chosen["cost_per_1000_usd"],
        "latency_mean_s": chosen["latency_s"]["mean"],
        "reliable_questions": list(questions),
        "paired_bootstrap": boot,
        "reason": reason,
    }


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def table_markdown(
    evaluations: list[dict[str, Any]],
    rec: dict[str, Any],
    baseline: dict[str, Any],
    displayed: dict[str, Any] | None = None,
    *,
    title: str = "T20 comparison - rule labels (blind-checked)",
) -> str:
    questions = rec.get("reliable_questions") or []
    lines = [
        f"# {title}",
        "",
        "Ranking uses `finding_kind` only: it is the one question whose rule labels "
        "clear 0.85 agreement with both blind checks (rules shown 14/15, rules "
        "removed 14/15).  `label_ok` is descriptive and its reference is defective "
        "until T31/v2.1.  FinVerify and failure kind are descriptive negative "
        "results; difficulty is not rankable.",
        "",
        "| Model | Finding-kind accuracy (ranking) | 95% Wilson | Label ok (descriptive) | Cost / 1k | Mean latency | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    baseline_reliable = question_summary(baseline["per_question"], questions)
    for name, base, cost, latency, coverage in (
        ("Majority-class baseline", baseline, "$0.000000", "n/a", "-"),
    ):
        bq = base["per_question"]
        lo, hi = baseline_reliable["ci95"]
        lines.append(
            f"| {name} | "
            + " | ".join(
                [
                    fmt(baseline_reliable["accuracy"], 3) + f" (n={baseline_reliable['n']})",
                    f"[{lo:.3f}, {hi:.3f}]",
                    fmt(bq["label_ok"]["accuracy"], 3) + f" ({bq['label_ok']['n']})",
                    cost,
                    latency,
                    coverage,
                ]
            )
            + " |"
        )
    if displayed is not None:
        bq = displayed["per_question"]
        disp_reliable = question_summary(bq, questions)
        lo, hi = disp_reliable["ci95"]
        lines.append(
            "| Displayed-label rule | "
            + " | ".join(
                [
                    fmt(disp_reliable["accuracy"], 3) + f" (n={disp_reliable['n']})",
                    f"[{lo:.3f}, {hi:.3f}]",
                    fmt(bq["label_ok"]["accuracy"], 3) + f" ({bq['label_ok']['n']})",
                    "$0.000000",
                    "n/a",
                    "-",
                ]
            )
            + " |"
        )
    for e in evaluations:
        pq = e["per_question"]
        reliable = e["reliable"]
        lo, hi = reliable["ci95"]
        cells = [
            e["label"],
            fmt(reliable["accuracy"], 3) + f" (n={reliable['n']})",
            f"[{lo:.3f}, {hi:.3f}]",
            fmt(pq["label_ok"]["accuracy"], 3) + f" ({pq['label_ok']['n']})",
            f"${e['cost_per_1000_usd']:.6f}" if e["cost_per_1000_usd"] is not None else "n/a",
            fmt(e["latency_s"]["mean"], 3) + " s",
            fmt(e["item_coverage"], 3),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    total_asked = evaluations[0]["total_asked"] if evaluations else 0
    lines.append(
        "Ranking metric = correct `finding_kind` answers / asked `finding_kind` "
        f"questions ({evaluations[0]['reliable']['n'] if evaluations else 0} of "
        f"{total_asked}); a missing or refused answer counts as wrong.  "
        "The Label ok column is descriptive: its reference drops to 22/30 once the "
        "blind reader cannot see the rules, so it is not a ranking signal.  "
        "FinVerify and failure kind are on the 60-item side-by-side table; "
        "difficulty is on a different scale."
    )
    lines.append("")
    lines.append(f"**Recommendation:** `{rec.get('model')}`. {rec.get('reason', '')}")
    return "\n".join(lines) + "\n"




def interval_table(evaluations: list[dict[str, Any]]) -> str:
    lines = [
        "== per-question accuracy and 95% Wilson intervals (descriptive) ==",
        "FinVerify, failure kind and difficulty are not used for ranking.",
    ]
    for e in evaluations:
        parts = []
        for q in QUESTIONS:
            pq = e["per_question"][q]
            lo, hi = pq["ci95"]
            parts.append(f"{q} {pq['accuracy']:.3f} [{lo:.3f}, {hi:.3f}] (n={pq['n']})")
        lines.append(f"{e['label']}: " + "; ".join(parts))
    return "\n".join(lines)


def cost_table(evaluations: list[dict[str, Any]]) -> str:
    lines = ["== cost and latency =="]
    for e in evaluations:
        lat = e["latency_s"]
        lines.append(
            f"{e['label']}: mean {lat['mean']:.3f}s p50 {lat['p50']:.3f}s "
            f"p95 {lat['p95']:.3f}s; ${e['cost_per_1000_usd']:.6f}/1k; "
            f"{e['requests']} requests"
        )
    return "\n".join(lines)


def bootstrap_table(rec: dict[str, Any], evaluations: list[dict[str, Any]]) -> str:
    boot = rec.get("paired_bootstrap") or {}
    stats = boot.get("models") or {}
    order = sorted(
        evaluations,
        key=lambda e: -(e["reliable"]["accuracy"] or 0.0),
    )
    lines = ["== finding-kind accuracy (the ranking metric), paired item bootstrap =="]
    for e in order:
        st = stats.get(e["id"])
        if not st:
            continue
        lo, hi = st["boot_ci95"]
        glo, ghi = st["gap_ci95"]
        lines.append(
            f"{e['label']}: finding-kind accuracy {st['micro_accuracy']:.3f} "
            f"[{lo:.3f}, {hi:.3f}]; gap to best {st['gap_to_best']:+.3f} "
            f"[{glo:+.3f}, {ghi:+.3f}]"
        )
    return "\n".join(lines)


def diagnostics(
    evaluations: list[dict[str, Any]],
    items: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
) -> str:
    """Print the subset counts the report quotes, from the same confusion data.

    The reference-action denominators come from the label file, not from
    hard-coded 117/3, so they cannot go stale after a label change.
    """
    kind_by_id = {item["id"]: item["kind"] for item in items}
    ref_neg = sum(
        1
        for row in label_rows
        if kind_by_id.get(row["id"]) == "ref_action"
        and int(row["labels"]["label_ok"]) == 0
    )
    ref_pos = sum(
        1
        for row in label_rows
        if kind_by_id.get(row["id"]) == "ref_action"
        and int(row["labels"]["label_ok"]) == 1
    )
    lines = ["== diagnostics =="]
    for e in evaluations:
        lk = e["per_question"]["label_ok"]["by_kind"]
        ref = lk.get("ref_action") or {"accuracy": 0.0, "n": 0}
        probe = lk.get("label_noise_probe") or {"accuracy": 0.0, "n": 0}
        fv = e["per_question"]["finverify"]["confusion"]
        fv_counts = {
            cls: fv.get(f"{cls}->{cls}", 0)
            for cls in ("comparability", "source_fidelity", "temporal_integrity", "none")
        }
        fv_n = {
            cls: sum(v for key, v in fv.items() if key.endswith(f"->{cls}"))
            for cls in ("comparability", "source_fidelity", "temporal_integrity", "none")
        }
        pred_failure: dict[str, int] = {}
        for key, value in e["per_question"]["failure_kind"]["confusion"].items():
            predicted = key.split("->")[0]
            pred_failure[predicted] = pred_failure.get(predicted, 0) + value
        pred_difficulty: dict[str, int] = {}
        for key, value in e["per_question"]["difficulty"]["confusion"].items():
            predicted = key.split("->")[0]
            pred_difficulty[predicted] = pred_difficulty.get(predicted, 0) + value
        lk_conf = e["per_question"]["label_ok"]["confusion"]
        false_alarms = lk_conf.get("True->0", 0)
        missed_all = lk_conf.get("False->1", 0)
        probe_correct = probe["accuracy"] * probe["n"]
        ref_missed = missed_all - (probe["n"] - probe_correct)
        lines.append(
            f"{e['label']}: label_ok ref {ref['accuracy']*ref['n']:.0f}/{ref['n']}, "
            f"probe {probe_correct:.0f}/{probe['n']}, "
            f"false alarms {false_alarms}/{ref_neg} ref, missed {ref_missed:.0f}/{ref_pos} ref; "
            f"FinVerify correct "
            + ", ".join(f"{k} {fv_counts[k]}/{fv_n[k]}" for k in fv_counts)
            + f"; clean predicted comparability {fv.get('comparability->none', 0)}"
            + f"; failure_kind predictions {dict(sorted(pred_failure.items()))}; "
            f"difficulty predictions {dict(sorted(pred_difficulty.items()))}"
        )
    return "\n".join(lines)


def catalog_table(catalog: dict[str, Any]) -> str:
    lines = [
        "| # | id | name | context | prompt price / token | input |",
        "|---:|---|---|---:|---:|---|",
    ]
    for index, model in enumerate(catalog["models"], start=1):
        pricing = model.get("pricing") or {}
        modalities = model.get("input_modalities") or []
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    f"`{model.get('id')}`",
                    str(model.get("name") or ""),
                    str(model.get("context_length") or 0),
                    str(pricing.get("prompt") or 0),
                    ", ".join(modalities) if modalities else "text",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def hint_table(displayed: dict[str, Any], section: dict[str, Any]) -> str:
    bq = displayed["per_question"]
    lines = [
        "== hint baselines (the state exposes these fields) ==",
        f"Displayed-label rule: micro {fmt(displayed.get('micro_accuracy'), 3)}, "
        f"macro {fmt(displayed.get('macro_accuracy'), 3)}; "
        f"FinVerify {fmt(bq['finverify']['accuracy'], 3)} "
        f"({bq['finverify']['correct']}/{bq['finverify']['n']}), "
        f"difficulty {fmt(bq['difficulty']['accuracy'], 3)} "
        f"({bq['difficulty']['correct']}/{bq['difficulty']['n']}).",
        f"Review-section rule: {section['correct']}/{section['n']} = "
        f"{fmt(section.get('accuracy'), 3)} on finding_kind "
        f"(majority per section: {section['majority_by_section']}).",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--handset", default=str(ROOT / "data" / "t20" / "handset.jsonl")
    )
    parser.add_argument("--labels", default=str(ROOT / "work" / "T20" / "handlabels.jsonl"))
    parser.add_argument(
        "--cache",
        default=str(ROOT / "work" / "T20" / "cache" / "triage_responses.jsonl"),
    )
    parser.add_argument(
        "--catalog",
        default=str(ROOT / "work" / "T20" / "cache" / "model_catalog.json"),
    )
    parser.add_argument(
        "--agreement",
        default=str(ROOT / "work" / "T20" / "blind_lead" / "agreement.json"),
    )
    parser.add_argument(
        "--reliability",
        default=str(ROOT / "work" / "T20" / "blind_reliability.json"),
    )
    parser.add_argument("--out", default=str(ROOT / "work" / "T20" / "results.json"))
    parser.add_argument("--table", default=str(ROOT / "work" / "T20" / "table.md"))
    parser.add_argument(
        "--title",
        default="T20 comparison - rule labels (blind-checked)",
    )
    args = parser.parse_args()

    items = load_jsonl(Path(args.handset))
    label_rows = load_jsonl(Path(args.labels))
    labels = {row["id"]: row["labels"] for row in label_rows}
    missing_labels = [item["id"] for item in items if item["id"] not in labels]
    if missing_labels:
        raise SystemExit(f"missing rule labels (blind-checked) for {len(missing_labels)} items")
    if len(items) != 200:
        raise SystemExit(f"expected 200 items, got {len(items)}")

    catalog = load_catalog(Path(args.catalog))
    catalog_ids = {m.get("id") for m in catalog["models"]}
    for model in MODELS:
        if catalog_ids and model["id"] not in catalog_ids:
            raise SystemExit(f"model {model['id']} is not in the cached decision-model catalog")

    agreement = load_blind_agreement(Path(args.agreement))
    reliability = load_reliability(Path(args.reliability))
    reliable_questions = list(reliability["reliable_questions"])

    evaluations = []
    for model in MODELS:
        evaluation = evaluate_model(model, items, labels, Path(args.cache))
        evaluation["reliable"] = question_summary(
            evaluation["per_question"], reliable_questions
        )
        evaluations.append(evaluation)

    # One lifetime budget across every cache in the folder, not one cap per file.
    cache_dir = Path(args.cache).parent
    total_spend = triage.cache_cost(Path(args.cache))
    global_spend = global_cache_spend(cache_dir)
    if global_spend > 5.0:
        raise SystemExit(
            f"lifetime cache spend ${global_spend:.4f} exceeds the $5 cap"
        )
    baseline = majority_baseline(label_rows)
    displayed = displayed_label_baseline(items, label_rows)
    section = section_baseline(items, label_rows)
    rec = recommend(evaluations, baseline, items, reliable_questions)

    payload = {
        "n_items": len(items),
        "n_questions": sum(len(item["questions"]) for item in items),
        "catalog_count": catalog["count"],
        "catalog_fetched_at": catalog.get("fetched_at"),
        "models": evaluations,
        "recommendation": rec,
        "majority_baseline": baseline,
        "displayed_label_baseline": displayed,
        "section_baseline": section,
        "reliable_questions": reliable_questions,
        "blind_agreement": agreement,
        "blind_reliability": reliability,
        "cache_cost_usd": total_spend,
        "global_cache_cost_usd": global_spend,
        "cache_files": [str(path.relative_to(ROOT)) for path in cache_files(cache_dir)],
        "item_kind_counts": dict(Counter(item["kind"] for item in items)),
        "hand_label_counts": {
            question: dict(Counter(str(row["labels"][question]) for row in label_rows if question in row["labels"]))
            for question in QUESTIONS
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    table = table_markdown(evaluations, rec, baseline, displayed, title=args.title)
    Path(args.table).write_text(table)
    catalog_md = catalog_table(catalog)
    (ROOT / "work" / "T20" / "model_catalog.md").write_text(catalog_md)

    print(f"Decision models on OpenRouter (cached catalog): {catalog['count']}")
    print(f"Catalog snapshot: {catalog.get('fetched_at')}")
    print(
        f"Items: {len(items)}; answered questions: "
        f"{sum(len(i['questions']) for i in items)}; "
        f"ranking questions: {', '.join(reliable_questions)}"
    )
    print(f"Cache spend (this file): ${total_spend:.6f}")
    print(
        f"Lifetime spend across {', '.join(p.name for p in cache_files(cache_dir))}: "
        f"${global_spend:.6f} (cap $5)"
    )
    print()
    print(table)
    print(interval_table(evaluations))
    print()
    print(cost_table(evaluations))
    print()
    print(bootstrap_table(rec, evaluations))
    print()
    print("== legacy all-question micro/macro (descriptive, not used for ranking) ==")
    for e in evaluations:
        print(
            f"{e['label']}: all-question micro {fmt(e['all_answers_accuracy'], 3)}, "
            f"macro {fmt(e['macro_accuracy'], 3)}"
        )
    print()
    print(diagnostics(evaluations, items, label_rows))
    print()
    print(hint_table(displayed, section))
    print("== decision-model catalog (from cache/model_catalog.json) ==")
    print(catalog_md)


if __name__ == "__main__":
    main()
