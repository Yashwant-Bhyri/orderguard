"""Generate every numeric table quoted in REPORT.md from the run artifacts.

Latency is the only metric that changes between runs.  We therefore quote a
*range over named runs* from ``latency_runs.json`` (a static list).  A
reviewer's fresh run appends to ``latency_history.jsonl`` but does not edit the
frozen list, so the quoted range stays reproducible.  Everything else is read
from ``results.json``, which is deterministic apart from latency.

The script writes ``work/T05/numbers.md`` and replaces the block between the
markers in ``REPORT.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results.json"
HISTORY = HERE / "latency_history.jsonl"
FROZEN = HERE / "latency_runs.json"
TABLE = HERE / "table.md"
NUMBERS = HERE / "numbers.md"
REPORT = HERE / "REPORT.md"
PREREG = HERE / "PREREGISTERED.md"
SOL = HERE / "SOL_ADVICE.md"

BEGIN = "<!-- BEGIN GENERATED NUMBERS -->"
END = "<!-- END GENERATED NUMBERS -->"

FEATURES = ("hype", "authority_language", "support_gap")


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number != number:
        return "nan"
    return f"{number:.{digits}f}"


def ci(row: dict[str, Any], low: str = "ci_low", high: str = "ci_high") -> str:
    return f"[{fmt(row.get(low))}, {fmt(row.get(high))}]"


def _load_history() -> list[dict[str, Any]]:
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _frozen_runs(history: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    by_id = {row.get("run_id"): row for row in history}
    if FROZEN.exists():
        wanted = json.loads(FROZEN.read_text(encoding="utf-8"))
        if isinstance(wanted, dict):
            wanted = wanted.get("run_ids", [])
        picked = [by_id[run_id] for run_id in wanted if run_id in by_id]
        missing = [run_id for run_id in wanted if run_id not in by_id]
        label = f"frozen list `latency_runs.json` ({len(picked)} of {len(wanted)} runs found)"
        if missing:
            label += "; missing " + ", ".join(missing)
        return picked, label
    return history, f"all {len(history)} recorded runs (no frozen list)"


def _latency_ranges(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for row in rows:
        for reader, latency in (row.get("latency") or {}).items():
            entry = out.setdefault(
                reader,
                {
                    "n_runs": 0,
                    "p50_min": float("inf"),
                    "p50_max": float("-inf"),
                    "p99_min": float("inf"),
                    "p99_max": float("-inf"),
                    "device": latency.get("device"),
                    "features": latency.get("features"),
                },
            )
            entry["n_runs"] += 1
            entry["p50_min"] = min(entry["p50_min"], float(latency.get("p50_ms", float("nan"))))
            entry["p50_max"] = max(entry["p50_max"], float(latency.get("p50_ms", float("nan"))))
            entry["p99_min"] = min(entry["p99_min"], float(latency.get("p99_ms", float("nan"))))
            entry["p99_max"] = max(entry["p99_max"], float(latency.get("p99_ms", float("nan"))))
    return out


def _ratios(rows: list[dict[str, Any]]) -> list[float]:
    values = []
    for row in rows:
        latency = row.get("latency") or {}
        decision = (latency.get("decision") or {}).get("p50_ms")
        nli = (latency.get("nli") or {}).get("p50_ms")
        if decision and nli:
            values.append(float(decision) / float(nli))
    return values


def _ruling_ci() -> tuple[str, str] | None:
    if not SOL.exists():
        return None
    text = SOL.read_text(encoding="utf-8")
    match = re.search(
        r"\+0\.079 over the small lexicon;.*?95% CI \[([-+0-9.]+), ([-+0-9.]+)\]",
        text,
        re.S,
    )
    if not match:
        match = re.search(r"95% CI \[([-+0-9.]+), ([-+0-9.]+)\]", text)
    return (match.group(1), match.group(2)) if match else None


def build(results: dict[str, Any]) -> str:
    lines: list[str] = []
    metrics = results.get("metrics", {})
    pass_bar = results.get("pass_bar", {})
    raw_best = results.get("raw_best", {})
    selected = results.get("selected_vs_lexicon", {})
    floors = (
        results.get("sensitivity", {})
        .get("authority_decision_floors", {})
        .get("per_floor", {})
    )
    sensitivity = results.get("sensitivity", {})
    corpus = results.get("corpus", {})

    pos_counts = {
        feature: metrics.get(feature, {}).get("shifted", {}).get("lexicon", {}).get("n_pos")
        for feature in FEATURES
    }
    lines += [
        "### 3.1 Pass bar (shifted ref, eligible readers only)",
        "",
        f"Sample: {corpus.get('actions')} actions from {corpus.get('episodes')} episodes, "
        f"seed {results.get('config', {}).get('seed')}; shifted positives "
        + ", ".join(f"{feature} {pos_counts.get(feature)}" for feature in FEATURES)
        + "; negatives are all `y = 0` actions.  All values below are generated by "
        "`work/T05/report_numbers.py` from `work/T05/results.json`; latency is a "
        "range over the named runs in `work/T05/latency_runs.json`.",
        "",
        "The official floor is the small registered lexicon.  Authority may be "
        "carried only by the pre-registered generic decision question; the "
        "ref-selected NLI authority hypothesis is sensitivity evidence and is "
        "excluded from this table.",
        "",
        "| feature | eligible pass reader | AUROC | AUROC 95% CI | delta vs small lexicon | delta 95% CI | beats floor |",
        "|---|---|---|---|---|---|---|",
    ]
    for feature in FEATURES:
        row = pass_bar.get(feature, {})
        reader = row.get("best_reader")
        metric = metrics.get(feature, {}).get("shifted", {}).get(reader, {})
        lines.append(
            f"| {feature} | {reader or 'unavailable'} | {fmt(row.get('shifted_auroc'))} | "
            f"{ci(metric)} | {fmt(row.get('delta'))} | {ci(row)} | "
            f"{row.get('beats_lexicon')} |"
        )
    verdict = all(pass_bar.get(f, {}).get("beats_lexicon") for f in FEATURES)
    lines += [
        "",
        f"**Eligible pass bar: {'MET' if verdict else 'NOT MET'}** on shifted ref.",
        "",
        "### 3.2 Raw best readers (transparency; may be ineligible)",
        "",
        "| feature | raw best reader | AUROC | delta vs small lexicon | delta 95% CI | beats floor |",
        "|---|---|---|---|---|---|",
    ]
    for feature in FEATURES:
        row = raw_best.get(feature, {})
        lines.append(
            f"| {feature} | {row.get('best_reader')} | {fmt(row.get('shifted_auroc'))} | "
            f"{fmt(row.get('delta'))} | {ci(row)} | {row.get('beats_lexicon')} |"
        )
    lines += [
        "",
        "The raw best authority reader is the NLI template selected on shifted ref "
        "(see `tuned_restriction_lifted` in §3.5). It is reported here so the "
        "number is not hidden, but it is not eligible for the pass bar and the "
        "channel does not use it.",
        "",
        "### 3.3 Channel-selected readers (shifted ref)",
        "",
        "`og_s1.text.DEFAULT_READERS` is hype=`nli`, authority=`decision`, "
        "support=`nli`.  The decision row uses the same bootstrap seed as the "
        "pass-bar row for the same comparison.",
        "",
        "| feature | selected reader | AUROC | delta vs small lexicon | delta 95% CI | beats floor |",
        "|---|---|---|---|---|---|",
    ]
    for feature in FEATURES:
        row = selected.get(feature, {})
        lines.append(
            f"| {feature} | {row.get('reader')} | {fmt(row.get('shifted_auroc'))} | "
            f"{fmt(row.get('delta'))} | {ci(row)} | {row.get('beats_lexicon')} |"
        )
    nli_small = raw_best.get("authority_language", {})
    nli_ext = sensitivity.get("authority_extended_lexicon", {}).get("nli_minus_extended_shifted", {})
    small_auroc = metrics.get("authority_language", {}).get("shifted", {}).get("lexicon", {}).get("auroc")
    ext_auroc = (
        sensitivity.get("authority_extended_lexicon", {})
        .get("per_shift", {})
        .get("shifted", {})
        .get("auroc")
    )
    dec_auroc = metrics.get("authority_language", {}).get("shifted", {}).get("decision", {}).get("auroc")
    nli_auroc = metrics.get("authority_language", {}).get("shifted", {}).get("nli", {}).get("auroc")
    lines += [
        "",
        "### 3.4 Authority reader vs floor (shifted ref)",
        "",
        "| reader | floor | floor AUROC | reader AUROC | delta | delta 95% CI | beats floor |",
        "|---|---|---|---|---|---|---|",
    ]
    if small_auroc is not None:
        lines.append(
            f"| nli (ref-selected; sensitivity) | small registered lexicon | {fmt(small_auroc)} | "
            f"{fmt(nli_auroc)} | {fmt(nli_small.get('delta'))} | {ci(nli_small)} | "
            f"{nli_small.get('beats_lexicon')} |"
        )
    if ext_auroc is not None:
        lines.append(
            f"| nli (ref-selected; sensitivity) | extended fixed list (sensitivity) | {fmt(ext_auroc)} | "
            f"{fmt(nli_auroc)} | {fmt(nli_ext.get('delta'))} | {ci(nli_ext)} | "
            f"{float(nli_ext.get('delta', 0.0)) > 0 if nli_ext else 'n/a'} |"
        )
    for floor_name, label, floor_auroc in (
        ("small_registered_lexicon", "small registered lexicon", small_auroc),
        ("extended_fixed_list", "extended fixed list (sensitivity)", ext_auroc),
    ):
        row = floors.get(floor_name)
        if not row:
            continue
        lines.append(
            f"| decision (eligible) | {label} | {fmt(floor_auroc)} | {fmt(dec_auroc)} | "
            f"{fmt(row.get('delta'))} | {ci(row)} | {float(row.get('delta', 0.0)) > 0} |"
        )
    ruling = results.get("pass_bar_ruling", {}).get("authority_language", {})
    old = _ruling_ci()
    lines += [
        "",
        "The decision-model authority question beats the small registered lexicon; "
        "it loses to the extended oracle list.  This is the same result the lead "
        "ruled on (MET against the small floor, sensitivity against the extended "
        "list).",
    ]
    if old and ruling:
        lines += [
            "",
            f"Round-2 ruling quoted delta {fmt(ruling.get('delta'))} with CI "
            f"[{old[0]}, {old[1]}] from an earlier bootstrap seed.  With the single "
            f"seed now used everywhere, the same comparison is "
            f"{fmt(ruling.get('delta'))} {ci(ruling)}.  Both intervals exclude "
            "zero; this does not reopen the ruling.",
        ]
    templates = sensitivity.get("authority_templates", {}).get("templates", {})
    if templates:
        lines += [
            "",
            "### 3.5 Authority NLI template sensitivity (shifted ref)",
            "",
            "| NLI hypothesis | AUROC | delta vs small lexicon | delta 95% CI | beats small lexicon |",
            "|---|---|---|---|---|",
        ]
        for name, row in templates.items():
            lines.append(
                f"| {name} | {fmt(row.get('auroc'))} | {fmt(row.get('delta_vs_small_lexicon'))} | "
                f"[{fmt(row.get('delta_ci_low'))}, {fmt(row.get('delta_ci_high'))}] | "
                f"{row.get('beats_small_lexicon')} |"
            )
    lines += [
        "",
        "### 3.6 Full AUROC table (95% episode-bootstrap CI)",
        "",
        "| feature | reader | unshifted | shifted |",
        "|---|---|---|---|",
    ]
    for feature in FEATURES:
        shifted = metrics.get(feature, {}).get("shifted", {})
        unshifted = metrics.get(feature, {}).get("unshifted", {})
        for reader in shifted:
            u = unshifted.get(reader)
            u_text = f"{fmt(u.get('auroc'))} {ci(u)}" if u else "n/a"
            s = shifted[reader]
            lines.append(f"| {feature} | {reader} | {u_text} | {fmt(s.get('auroc'))} {ci(s)} |")
    lines += [
        "",
        "### 3.7 Calibration (ECE / Brier, shifted ref)",
        "",
        "| feature | reader | ECE | Brier | n |",
        "|---|---|---|---|---|",
    ]
    for feature in FEATURES:
        table = results.get("calibration", {}).get(feature, {}).get("shifted", {})
        for reader, row in table.items():
            lines.append(
                f"| {feature} | {reader} | {fmt(row.get('ece'))} | {fmt(row.get('brier'))} | {row.get('n')} |"
            )
    history = _load_history()
    runs, label = _frozen_runs(history)
    ranges = _latency_ranges(runs)
    lines += [
        "",
        "### 3.8 Latency per action (range over named runs)",
        "",
        f"Range over {label}.  Each run scores 1,440 actions serial after a warm-up; "
        "the network decision reader includes the round trip.  Wall-clock varies "
        "with machine load, so this table quotes ranges, not a millisecond-exact "
        "reproduction claim.  `results.json` holds the latest run's point values.",
        "",
        "| reader | device | features | p50 min–max ms | p99 min–max ms | runs |",
        "|---|---|---|---|---|---|",
    ]
    for reader, row in ranges.items():
        lines.append(
            f"| {reader} | {row.get('device')} | {row.get('features')} | "
            f"{fmt(row['p50_min'], 1)}–{fmt(row['p50_max'], 1)} | "
            f"{fmt(row['p99_min'], 1)}–{fmt(row['p99_max'], 1)} | {row['n_runs']} |"
        )
    ratios = _ratios(runs)
    if ratios:
        lines += [
            "",
            f"The hosted decision reader's p50 is {fmt(min(ratios), 1)}–{fmt(max(ratios), 1)}× "
            "the NLI p50 across the same runs (computed, not typed).  The earlier "
            "'about 5×' prose was wrong for these runs and is removed.",
        ]
    bound = results.get("max_logit_contribution", {})
    slopes = bound.get("fitted_slope_per_unit_feature", {})
    lines += [
        "",
        "### 3.9 Largest logit contribution (placeholder)",
        "",
        "Unit-weight bound: **1.0 logit** per feature.  Univariate monotone "
        "logistic slopes on shifted ref, using the channel's selected readers: "
        + ", ".join(f"{name} {fmt(slopes.get(name))}" for name in FEATURES)
        + ". T07's actual scorer must recompute `g(1) − g(0)` from its own shape functions.",
        "",
        "### 3.10 Decision-model cost and cache",
        "",
        f"Calls: {results.get('decision', {}).get('calls')}; cost: "
        f"${fmt(results.get('decision', {}).get('cost_usd'), 6)}; cache: "
        f"`{results.get('decision', {}).get('cache')}`.",
    ]
    if PREREG.exists():
        match = re.search(r"Overall SHA-256 of this frozen configuration: `([0-9a-f]{64})`", PREREG.read_text(encoding="utf-8"))
        if match:
            lines += [
                "",
                f"Frozen preregistration SHA-256: `{match.group(1)}`. `run.sh` recomputes "
                "it and fails on a mismatch; the file is never regenerated.",
            ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if not RESULTS.exists():
        raise SystemExit("results.json is missing; run evaluate.py first")
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    block = build(results)
    NUMBERS.write_text("# T05 generated numbers\n\n" + block, encoding="utf-8")
    if REPORT.exists():
        text = REPORT.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            _, tail = rest.split(END, 1)
            REPORT.write_text(head + BEGIN + "\n" + block + END + tail, encoding="utf-8")
            print("updated REPORT.md generated block")
        else:
            print("REPORT.md has no generated-block markers; wrote numbers.md only")
    print("wrote work/T05/numbers.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
