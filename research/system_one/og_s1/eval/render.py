"""Four deterministic renderings of a :class:`og_s1.eval.cases.Case`.

The renderings are the experiment-R input forms from ``COMBOS.md`` section 3:
raw text, typed fact slots written as text, claim/evidence pairs, and a package
built from the why graph.  Each renderer is a pure function of the Case, so two
runs on the same Case produce byte-identical strings.  No rendering reads a
label, ``meta`` or any field a Case does not already carry.
"""

from __future__ import annotations

import json
from typing import Any

from og_s1.eval.cases import Case

RENDERINGS: tuple[str, ...] = ("raw", "typed_facts", "claim_evidence", "why_package")


def _num(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return json.dumps(value, allow_nan=False)
    return str(value)


def _facts_text(facts: Any) -> str:
    parts = []
    for fact in facts:
        parts.append(f"{fact.get('name')}={_num(fact.get('value'))}{fact.get('unit') or ''}")
    return "; ".join(parts) if parts else "none"


def _raw(case: Case) -> str:
    action = case.action
    lines = [
        "ACTION "
        f"index={case.index} t={action.get('t')} instrument={action.get('instrument')} "
        f"side={action.get('side')} sector={action.get('sector')} "
        f"notional={_num(action.get('notional'))} thesis={action.get('thesis_id')} "
        f"opens_thesis={_num(bool(action.get('opens_thesis')))}",
        f"RATIONALE: {action.get('rationale') or ''}",
    ]
    for j, claim in enumerate(case.claims):
        lines.append(f"CLAIM {j}: {claim.text}")
        if claim.source_available:
            lines.append(
                f"  SOURCE {claim.source_doc} trust={claim.source_trust_tier} "
                f"kind={claim.source_kind} publisher={claim.source_publisher} "
                f"t={claim.source_t}: {claim.source_text}"
            )
        elif claim.has_source:
            lines.append(f"  SOURCE {claim.source_doc} UNAVAILABLE")
        else:
            lines.append("  SOURCE none")
    for note in case.notes:
        if note.available:
            lines.append(
                f"NOTE {note.id} writer={note.written_by} "
                f"signature_valid={_num(note.signature_valid)} t={note.t}: {note.text}"
            )
            for doc in note.cited_docs:
                lines.append(
                    f"  NOTE_SOURCE {doc.id} trust={doc.trust_tier} kind={doc.kind}: {doc.text}"
                )
        else:
            lines.append(f"NOTE {note.id} UNAVAILABLE")
    if case.thesis is not None:
        lines.append(
            f"THESIS {case.thesis.id} opened_t={case.thesis.opened_t} "
            f"sector={case.thesis.sector}: {case.thesis.statement} "
            f"invalidation={case.thesis.invalidation}"
        )
    return "\n".join(lines)


def _typed_facts(case: Case) -> str:
    action = case.action
    lines = [
        f"action.instrument={action.get('instrument')}",
        f"action.side={action.get('side')}",
        f"action.sector={action.get('sector')}",
        f"action.notional={_num(action.get('notional'))}",
        f"action.t={action.get('t')}",
        f"action.thesis_id={action.get('thesis_id')}",
        f"action.opens_thesis={_num(bool(action.get('opens_thesis')))}",
        f"case.n_claims={len(case.claims)}",
        f"case.n_cited_notes={len(case.notes)}",
        f"trust.owner_key={case.trust.get('owner_key')}",
        f"trust.owner_purpose={case.trust.get('owner_purpose')}",
        f"trust.min_source_trust={_num(case.trust.get('min_source_trust'))}",
    ]
    for j, claim in enumerate(case.claims):
        prefix = f"claim[{j}]"
        lines.append(f"{prefix}.text={claim.text}")
        lines.append(f"{prefix}.value={_num(claim.value)}")
        lines.append(f"{prefix}.unit={claim.unit}")
        lines.append(f"{prefix}.source_doc={claim.source_doc}")
        lines.append(f"{prefix}.quoted_span={claim.quoted_span}")
        lines.append(f"{prefix}.source_available={_num(claim.source_available)}")
        lines.append(f"{prefix}.facts={_facts_text(claim.source_facts)}")
    for j, note in enumerate(case.notes):
        prefix = f"note[{j}]"
        lines.append(f"{prefix}.id={note.id}")
        lines.append(f"{prefix}.written_by={note.written_by}")
        lines.append(f"{prefix}.signature_valid={_num(note.signature_valid)}")
        lines.append(f"{prefix}.text={note.text}")
        lines.append(f"{prefix}.cited_docs={','.join(d.id for d in note.cited_docs) or 'none'}")
    return "\n".join(lines)


def _claim_evidence(case: Case) -> str:
    lines: list[str] = []
    for j, claim in enumerate(case.claims):
        lines.append(f"CLAIM {j}: {claim.text}")
        lines.append(f"QUOTE {j}: {claim.quoted_span if claim.quoted_span is not None else 'NONE'}")
        if claim.source_available:
            lines.append(f"EVIDENCE {j}: {claim.source_text}")
            lines.append(f"FACTS {j}: {_facts_text(claim.source_facts)}")
        else:
            lines.append(f"EVIDENCE {j}: UNAVAILABLE ({claim.source_doc})")
    for note in case.notes:
        if note.available:
            lines.append(f"MEMORY: {note.id} ({note.written_by}): {note.text}")
            for doc in note.cited_docs:
                lines.append(f"MEMORY_EVIDENCE: {doc.id} ({doc.kind}): {doc.text}")
        else:
            lines.append(f"MEMORY: {note.id} UNAVAILABLE")
    return "\n".join(lines)


def _why_package(case: Case) -> str:
    action = case.action
    package: dict[str, Any] = {
        "case_id": case.case_id,
        "entity": action.get("instrument"),
        "period": action.get("t"),
        "action": {
            "side": action.get("side"),
            "sector": action.get("sector"),
            "notional": action.get("notional"),
            "thesis_id": action.get("thesis_id"),
            "opens_thesis": bool(action.get("opens_thesis")),
            "rationale": action.get("rationale"),
        },
        "claims": [],
        "notes": [],
        "trust": {
            "owner_key": case.trust.get("owner_key"),
            "owner_purpose": case.trust.get("owner_purpose"),
            "min_source_trust": case.trust.get("min_source_trust"),
            "all_cited_notes_signed": case.trust.get("all_cited_notes_signed"),
        },
    }
    for claim in case.claims:
        package["claims"].append(
            {
                "claim": claim.text,
                "value": claim.value,
                "unit": claim.unit,
                "quote": claim.quoted_span,
                "quote_present": claim.quoted_span_present,
                "quote_in_source": claim.quoted_span_in_source,
                "value_matches_source_fact": claim.value_matches_source_fact,
                "source": {
                    "doc": claim.source_doc,
                    "available": claim.source_available,
                    "trust_tier": claim.source_trust_tier,
                    "kind": claim.source_kind,
                    "publisher": claim.source_publisher,
                    "t": claim.source_t,
                    "facts": [dict(f) for f in claim.source_facts],
                },
            }
        )
    for note in case.notes:
        package["notes"].append(
            {
                "id": note.id,
                "writer": note.written_by,
                "signed": note.signature_valid,
                "t": note.t,
                "text": note.text,
                "cited_docs": [
                    {
                        "id": doc.id,
                        "trust_tier": doc.trust_tier,
                        "kind": doc.kind,
                        "t": doc.t,
                        "facts": [dict(f) for f in doc.facts],
                    }
                    for doc in note.cited_docs
                ],
                "missing_cited_docs": list(note.missing_cited_docs),
            }
        )
    if case.thesis is not None:
        package["thesis"] = {
            "id": case.thesis.id,
            "opened_t": case.thesis.opened_t,
            "sector": case.thesis.sector,
            "statement": case.thesis.statement,
            "invalidation": case.thesis.invalidation,
            "invalidation_trigger": case.thesis.invalidation_trigger,
        }
    return json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_RENDERERS = {
    "raw": _raw,
    "typed_facts": _typed_facts,
    "claim_evidence": _claim_evidence,
    "why_package": _why_package,
}


def render_case(case: Case, rendering: str = "raw") -> str:
    """Render one Case.  ``rendering`` must be one of :data:`RENDERINGS`."""
    try:
        fn = _RENDERERS[rendering]
    except KeyError as exc:
        raise ValueError(f"unknown rendering {rendering!r}; choose from {RENDERINGS}") from exc
    return fn(case)


def render_lengths(case: Case) -> dict[str, dict[str, int]]:
    """Character and whitespace-token lengths of every rendering."""
    out: dict[str, dict[str, int]] = {}
    for name in RENDERINGS:
        text = render_case(case, name)
        out[name] = {"chars": len(text), "tokens": len(text.split())}
    return out
