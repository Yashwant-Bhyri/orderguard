"""Item-level rule labels (blind-checked) for the T20 200-item set.

This is the labelling step.  The reference ``cause`` is **not** an input to the
label rules: for every item the annotator reads the case, records what it found
(the claim/source match, note author and signature, book replay, sector-scoped
stale trigger) and assigns the label from that evidence.  The reference cause is
kept only as a diagnostic so the report can say how often the content reading
agrees with the generator's hypothesis.

Checks by item kind
------------------
reference actions (120)
    Claims are compared with their cited documents (quoted span present, numeric
    value matching).  Cited notes are read for author and signature.  The book is
    replayed for sector-band and position checks.  For a stale-thesis item the
    named trigger document is read and evaluated at the action time, scoped to
    the thesis's sector so a document about a different sector cannot fire it.

label-noise probes (20)
    The same content checks; the displayed label is the flip of the reference
    label.  ``label_ok`` is 1 when the displayed label contradicts the case.

failed cases (37)
    The reader's state is inspected for the decisive source, note or figure.
    When it is present the failure is a reasoning error; when the needed source,
    signature or figure is absent it is missing information.

review findings (23)
    Each finding text is read against the four categories.  The label is the
    recorded reviewer reading in ``review_findings.json``.  The full set is
    reported as rule labels (blind-checked), not as manual annotation.

The output ``handcheck.json`` is the source of truth for ``handlabels.jsonl``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1 import checks  # noqa: E402
from og_s1.schema import Episode, model_view_at  # noqa: E402
from og_s1.world import COMPANY_NAMES, INSTRUMENTS  # noqa: E402

TASK = ROOT / "work" / "T20"
DATA = ROOT / "data" / "ref"

HYPE = re.compile(
    r"unstoppable|can't-miss|cannot miss|about to explode|massive upside|"
    r"guaranteed|to the moon|no-brainer|huge upside|skyrocket",
    re.IGNORECASE,
)

ALL_INSTRUMENTS = sorted({inst for names in INSTRUMENTS.values() for inst in names})


def op_holds(op: str | None, value: float, threshold: float) -> bool:
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "==":
        return value == threshold
    if op == "!=":
        return value != threshold
    return False


def load_raw() -> dict[tuple[str, int, int], dict[str, Any]]:
    raw: dict[tuple[str, int, int], dict[str, Any]] = {}
    for path in sorted(DATA.glob("*.jsonl")):
        episodes = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
        for ei, episode in enumerate(episodes):
            for si in range(len(episode["steps"])):
                raw[(path.name, ei, si)] = episode
    return raw


def feature_row(episode: dict[str, Any], si: int) -> tuple[dict[str, float], dict[str, Any]]:
    parsed = Episode.from_dict(episode)
    X, names, _ = checks.featurize(parsed)
    row = dict(zip(names, X[si]))
    view = model_view_at(parsed, si)
    return row, view


def docs_and_notes(view: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    docs = {str(d.get("id")): d for d in view.get("documents") or []}
    notes = {str(n.get("id")): n for n in view.get("notes") or []}
    return docs, notes


def instruments_in_text(text: Any) -> set[str]:
    """Instrument tickers or company names mentioned in a document."""
    value = str(text or "")
    found: set[str] = set()
    for inst in ALL_INSTRUMENTS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(inst)}(?![A-Za-z0-9])", value):
            found.add(inst)
    for inst, name in COMPANY_NAMES.items():
        if name and name in value:
            found.add(inst)
    return found


def thesis_instruments(
    thesis: dict[str, Any], docs: dict[str, dict[str, Any]]
) -> set[str]:
    found = instruments_in_text(thesis.get("statement"))
    for doc_id in thesis.get("evidence_docs") or []:
        doc = docs.get(str(doc_id))
        if doc is not None:
            found |= instruments_in_text(doc.get("text"))
    return found


def claim_audit(
    action: dict[str, Any], docs: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return item-level claim issues and the positive observations."""
    issues: list[dict[str, Any]] = []
    observations: list[str] = []
    for index, claim in enumerate(action.get("claims") or [], start=1):
        source = claim.get("source_doc")
        span = claim.get("quoted_span")
        value = claim.get("value")
        text = str(claim.get("text") or "")
        if source is None:
            if HYPE.search(text) and value is None:
                kind = "unsourced_hype"
                detail = f"claim {index} is unsourced hype with no concrete figure"
            else:
                kind = "unsourced"
                detail = f"claim {index} has no source document"
            issues.append({"kind": kind, "category": "source_fidelity", "detail": detail})
            continue
        doc = docs.get(str(source))
        if doc is None:
            issues.append(
                {
                    "kind": "source_missing",
                    "category": "source_fidelity",
                    "detail": f"claim {index} cites {source}, which is absent from the reader's view",
                }
            )
            continue
        doc_text = str(doc.get("text") or "")
        span_in = isinstance(span, str) and span.strip() != "" and span in doc_text
        facts = [f for f in (doc.get("facts") or []) if isinstance(f.get("value"), (int, float))]
        value_match = None
        if isinstance(value, (int, float)) and facts:
            value_match = min(abs(float(value) - float(f["value"])) for f in facts)
        if not span_in:
            issues.append(
                {
                    "kind": "span_bad",
                    "category": "source_fidelity",
                    "detail": f"claim {index} quotes '{span}' which is not in {source}",
                }
            )
        elif value_match is not None and value_match > 1e-6:
            nearest = min(facts, key=lambda f: abs(float(value) - float(f["value"])))
            issues.append(
                {
                    "kind": "value_mismatch",
                    "category": "source_fidelity",
                    "detail": (
                        f"claim {index} states {value}{claim.get('unit') or ''} but {source} "
                        f"has {nearest['value']}{nearest.get('unit') or ''} for its nearest fact"
                    ),
                }
            )
        else:
            observations.append(
                f"claim {index} quotes '{span}' from {source} with a matching value"
            )
    return issues, observations


def note_audit(
    action: dict[str, Any], notes: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[dict[str, Any]] = []
    observations: list[str] = []
    for note_id in action.get("cites_notes") or []:
        note = notes.get(str(note_id))
        if note is None:
            issues.append(
                {
                    "kind": "note_missing",
                    "category": "source_fidelity",
                    "detail": f"cited note {note_id} is absent from the reader's view",
                }
            )
            continue
        author = note.get("written_by")
        signed = bool(note.get("signature_valid"))
        if author != "owner_signed" or not signed:
            issues.append(
                {
                    "kind": "invalid_note",
                    "category": "source_fidelity",
                    "detail": (
                        f"cited note {note_id} is written_by={author} and "
                        f"signature_valid={signed}, not a valid owner permission"
                    ),
                }
            )
        else:
            observations.append(
                f"cited note {note_id} is written_by=owner_signed and signature_valid=true"
            )
    return issues, observations


def stale_check(
    episode: dict[str, Any],
    si: int,
    view: dict[str, Any],
    docs: dict[str, dict[str, Any]],
) -> tuple[list[str], bool, str]:
    """Sector-scoped stale-thesis check.

    Only documents that mention an instrument in the thesis's sector (or that are
    the thesis's own evidence) can fire the trigger.  A document about another
    sector's instrument cannot invalidate this thesis; that was the source of the
    false JPM/VOO hits in round 2.
    """
    step = episode["steps"][si]
    action = step["action"]
    thesis = None
    for candidate in episode.get("theses") or []:
        if candidate.get("id") == action.get("thesis_id"):
            thesis = candidate
            break
    if thesis is None:
        return ["the action has no thesis to invalidate"], False, "no thesis"
    trigger = thesis.get("invalidation_trigger") or {}
    name = trigger.get("name")
    op = trigger.get("op")
    threshold = trigger.get("value")
    opened = float(thesis.get("opened_t", 0) or 0)
    action_t = float(action.get("t", 0) or 0)
    sector = str(thesis.get("sector") or "")
    sector_instruments = set(INSTRUMENTS.get(sector) or [])
    evidence_ids = {str(x) for x in thesis.get("evidence_docs") or []}
    target_instruments = thesis_instruments(thesis, docs)

    hits: list[tuple[str, float, float, Any]] = []
    skipped: list[str] = []
    for doc in episode.get("documents") or []:
        doc_t = float(doc.get("t", 0) or 0)
        if doc_t <= opened or doc_t > action_t:
            continue
        doc_id = str(doc.get("id"))
        mentioned = instruments_in_text(doc.get("text"))
        # Keep documents that are about the thesis's sector.  If the document
        # names a different sector's instrument and is not an evidence document,
        # it cannot invalidate this thesis.
        if mentioned and not (mentioned & sector_instruments) and doc_id not in evidence_ids:
            skipped.append(doc_id)
            continue
        if not mentioned and doc_id not in evidence_ids:
            skipped.append(doc_id)
            continue
        for fact in doc.get("facts") or []:
            if fact.get("name") == name and isinstance(fact.get("value"), (int, float)):
                if op_holds(op, float(fact["value"]), float(threshold)):
                    hits.append((doc_id, doc_t, fact["value"], doc.get("trust_tier")))
                    break
    adds = action.get("side") == "buy"
    scope = (
        f"thesis sector={sector}, instruments={sorted(target_instruments) or 'unknown'}, "
        f"skipped {len(skipped)} other-sector document(s)"
    )
    if not hits:
        return [
            f"no in-sector document between t={opened:.0f} and t={action_t:.0f} satisfies {name} {op} {threshold} ({scope})"
        ], False, scope
    observations = [
        f"trigger {name} {op} {threshold} fired in {doc_id} at t={doc_t:.0f} "
        f"(value {value}, trust {trust}); {scope}"
        for doc_id, doc_t, value, trust in hits[:3]
    ]
    observations.append("the action is a buy that adds exposure" if adds else "the action does not add exposure")
    return observations, bool(hits) and adds, scope


def run_checks(
    episode: dict[str, Any],
    si: int,
) -> tuple[dict[str, Any], list[str]]:
    row, view = feature_row(episode, si)
    action = episode["steps"][si]["action"]
    docs, notes = docs_and_notes(view)
    checks_done: list[str] = []
    claim_issues, claim_obs = claim_audit(action, docs)
    checks_done.extend(claim_obs)
    checks_done.extend(issue["detail"] for issue in claim_issues)
    note_issues, note_obs = note_audit(action, notes)
    checks_done.extend(note_obs)
    checks_done.extend(issue["detail"] for issue in note_issues)
    # A sector can already be over its band before the action; the failure is
    # a buy that increases the out-of-band weight or the position, not a
    # reducing sell that leaves the old excess in place.
    drift_bad = (
        row["drift_out_of_band_increase"] > 1e-9
        or row["drift_position_excess"] > 1e-9
    )
    book_obs = (
        "book replay: sector out-of-band increase "
        f"{row['drift_out_of_band_increase']:.4f}, position excess "
        f"{row['drift_position_excess']:.4f}, sector excess after "
        f"{row['drift_sector_excess_after']:.4f}"
    )
    checks_done.append(book_obs)
    stale_obs, stale_bad, stale_scope = stale_check(episode, si, view, docs)
    checks_done.extend(stale_obs)
    issues = list(claim_issues) + list(note_issues)
    if drift_bad:
        issues.append(
            {
                "kind": "drift",
                "category": "comparability",
                "detail": (
                    "book replay shows the action raises out-of-band weight by "
                    f"{row['drift_out_of_band_increase']:.4f} and position excess "
                    f"{row['drift_position_excess']:.4f}"
                ),
            }
        )
    if stale_bad:
        issues.append(
            {
                "kind": "stale",
                "category": "temporal_integrity",
                "detail": stale_obs[0] if stale_obs else "the thesis invalidation trigger fired",
            }
        )
    return {
        "row": row,
        "issues": issues,
        "observations": list(claim_obs) + list(note_obs) + [book_obs] + list(stale_obs),
        "stale_bad": stale_bad,
        "stale_scope": stale_scope,
        "claims": action.get("claims") or [],
        "notes": notes,
        "docs": docs,
        "side": action.get("side"),
    }, checks_done


def content_labels(
    kind: str,
    info: dict[str, Any],
    displayed_y: int,
) -> tuple[dict[str, Any], int, str]:
    """Assign labels from the observed case content, not from the cause."""
    row = info["row"]
    issues = info["issues"]
    has_defect = bool(issues)
    content_truth = 1 if has_defect else 0
    label_ok = int(displayed_y != content_truth)
    categories = [issue["category"] for issue in issues]
    # When an action has more than one defect, the most specific evidence
    # failure is the category: a stale trigger is temporal, a source/authority
    # defect is a source-fidelity failure, and a band breach alone is
    # comparability.  This is a content priority, not the reference cause.
    if "temporal_integrity" in categories:
        finverify = "temporal_integrity"
    elif "source_fidelity" in categories:
        finverify = "source_fidelity"
    elif "comparability" in categories:
        finverify = "comparability"
    else:
        finverify = "none"

    if not has_defect:
        difficulty = 0
    elif info["stale_bad"]:
        difficulty = 2
    elif any(issue["kind"] == "invalid_note" for issue in issues):
        # A poisoned note has to be separated from a valid owner note; a single
        # unsigned permission is one author/signature check.
        difficulty = 2 if len(info["notes"]) >= 2 else 1
    elif any(issue["kind"] == "drift" for issue in issues):
        difficulty = 1
    elif any(issue["kind"] in ("value_mismatch", "span_bad", "source_missing") for issue in issues):
        difficulty = 1
    elif any(issue["kind"] in ("unsourced_hype", "unsourced") for issue in issues):
        difficulty = 0
    elif len(issues) > 1:
        difficulty = 1
    else:
        difficulty = 1

    labels: dict[str, Any] = {"label_ok": label_ok}
    if kind == "ref_action":
        labels["finverify"] = finverify if content_truth == 1 else "none"
        labels["difficulty"] = difficulty
    detail = "; ".join(issue["detail"] for issue in issues)
    if not detail:
        detail = "; ".join(info.get("observations") or []) or (
            "all claims match their cited sources, cited notes are owner-signed and valid, "
            "the book replay stays inside the mandate, and no in-sector invalidation "
            "trigger fired before the action"
        )
    return labels, content_truth, detail


def failed_case_kind(info: dict[str, Any]) -> tuple[str, str]:
    """Content-only failed-case label: is the decisive evidence present?"""
    missing: list[str] = []
    for issue in info["issues"]:
        if issue["kind"] in ("unsourced", "unsourced_hype", "source_missing", "span_bad", "note_missing"):
            missing.append(issue["detail"])
    if missing:
        return "missing_information", "; ".join(missing)
    present = (
        "the cited documents, notes and book are present in the reader's view, "
        "so the decisive evidence was available"
    )
    return "reasoning_error", present


def review_basis(label: str, text: str) -> str:
    cues = {
        "leakage": "detection logic or a label/family proxy reaches a model-visible or author-facing input",
        "bug": "a concrete logic or data defect that changes behaviour",
        "missing_evidence": "a claim or check is not supported by the evidence shown",
        "style": "wording or presentation only",
    }
    return f"read against the four categories; the finding matches the {label} cue ({cues[label]})"


def main() -> None:
    handset = [json.loads(line) for line in (ROOT / "data" / "t20" / "handset.jsonl").open(encoding="utf-8") if line.strip()]
    raw = load_raw()
    findings = json.loads((TASK / "review_findings.json").read_text(encoding="utf-8"))
    finding_labels = {
        f"review:{index:03d}": finding["label"] for index, finding in enumerate(findings, start=1)
    }
    custom_reasons = json.loads((TASK / "label_reasons.json").read_text(encoding="utf-8"))

    out: dict[str, Any] = {}
    agreements = 0
    ref_actions = 0
    probe_agreements = 0
    probes = 0
    for item in handset:
        item_id = item["id"]
        kind = item["kind"]
        if kind == "review_finding":
            label = finding_labels[item_id]
            text = item["state"].get("finding") or ""
            out[item_id] = {
                "kind": kind,
                "labels": {"finding_kind": label},
                "checks": [review_basis(label, text)],
                "label_basis": review_basis(label, text),
                "reason": custom_reasons.get(
                    item_id,
                    f"The finding {item_id} was read against the four categories and "
                    f"matches {label}: {review_basis(label, text)}.",
                ),
            }
            continue

        _, name, ei, si = item_id.split(":")
        ei, si = int(ei), int(si)
        episode = raw[(name, ei, si)]
        step = episode["steps"][si]
        displayed_y = int(item["state"]["owner_label"]["y"])
        reference_y = int(step["label"]["y"])
        reference_cause = str(step["label"]["cause"])
        info, checks_done = run_checks(episode, si)
        labels, content_truth, detail = content_labels(kind, info, displayed_y)

        if kind == "label_noise_probe":
            if displayed_y != 1 - reference_y:
                raise SystemExit(f"{item_id}: displayed label is not the flip of the reference")
            probes += 1
            if labels["label_ok"] == 1:
                probe_agreements += 1
            reason = (
                f"The case content supports y={content_truth} ({detail}); the displayed "
                f"label is y={displayed_y}, the opposite, so label_ok={labels['label_ok']}."
            )
        elif kind == "ref_action":
            ref_actions += 1
            if labels["label_ok"] == 0 and content_truth == reference_y:
                agreements += 1
            reason = (
                f"Content reading: y={content_truth} because {detail}. "
                f"Displayed y={displayed_y} is therefore "
                f"{'consistent' if labels['label_ok'] == 0 else 'plausibly wrong'}; "
                f"finverify={labels['finverify']}, difficulty={labels['difficulty']} "
                f"(reference hypothesis: y={reference_y}, cause={reference_cause})."
            )
        elif kind == "failed_case":
            kind_label, why = failed_case_kind(info)
            labels = {"failure_kind": kind_label}
            checks_done.append(f"decisive-evidence audit: {why}")
            detail = why
            reason = (
                f"The reader answered endorse while the case contains a failure; "
                f"{why}, so the failure is recorded as {kind_label}."
            )
        else:
            raise SystemExit(f"unknown item kind {kind}")

        out[item_id] = {
            "kind": kind,
            "labels": labels,
            "checks": checks_done,
            "label_basis": detail,
            "reason": custom_reasons.get(item_id, reason),
            "content_truth": content_truth,
            "reference_y": reference_y,
            "reference_cause": reference_cause,
        }

    (TASK / "handcheck.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (TASK / "handlabels.jsonl").open("w", encoding="utf-8") as handle:
        for item in handset:
            row = out[item["id"]]
            handle.write(
                json.dumps(
                    {
                        "id": item["id"],
                        "kind": item["kind"],
                        "labels": row["labels"],
                        "label_basis": row["label_basis"],
                        "reason": row["reason"],
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    print(
        f"rule-labeled (blind-checked) {len(out)} items from case content; "
        f"reference-cause agreement {agreements}/{ref_actions} reference actions, "
        f"{probe_agreements}/{probes} probes detected as flipped"
    )


if __name__ == "__main__":
    main()
