"""Case extraction and evaluation-only tagging for the System One bench.

A :class:`Case` is the one input every reader receives.  It is built **only**
from :func:`og_s1.schema.model_view_at`: the action, the documents it could see
at that time, the notes it could see, and the theses opened by then.  Labels,
``meta``, final thesis status and every later document, note or action are not
read.  ``cases`` is the extraction entry point; the shift-axis tagging is a
separate, evaluation-only step (:func:`tag_shift_axes`) so that no metadata can
reach a reader through a Case.

The module deliberately does not import or call the whole-episode
``model_view``; the guard test in ``work/T15`` enforces that.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from og_s1.checks import FEATURE_NAMES, GROUPS, featurize
from og_s1.schema import model_view_at

SHIFT_AXES: tuple[str, ...] = (
    "semantic",
    "financial",
    "temporal",
    "behavioural",
    "adversarial",
)

#: Which axes a reference family exercises.  This table is evaluation-only:
#: it names the planted family, so it must never be given to a reader.
FAMILY_AXES: dict[str, tuple[str, ...]] = {
    "clean": (),
    "drift": ("behavioural",),
    "unsupported_claim": ("semantic",),
    "misquote": ("semantic", "financial"),
    "vague_hype": ("adversarial", "semantic"),
    "poisoned_note": ("adversarial",),
    "authority_spoof": ("adversarial",),
    "stale_thesis": ("temporal",),
}

TRUTH_TYPES: tuple[str, ...] = ("formal", "evidential", "preference")

#: Cause -> truth type.  Formal means a rule over structured fields decides it;
#: evidential means a source has to be read; preference means it depends on the
#: owner's purpose.  ``clean`` is an owner endorsement, so it is tagged
#: preference.  It is a *synthetic* label: it is never reported as real owner
#: preference, and it has no positive preference examples in the reference
#: corpora.
CAUSE_TRUTH_TYPE: dict[str, str] = {
    "clean": "preference",
    "drift": "formal",
    "authority_spoof": "formal",
    "unsupported_claim": "evidential",
    "misquote": "evidential",
    "vague_hype": "evidential",
    "poisoned_note": "evidential",
    "stale_thesis": "evidential",
}


def truth_type_for(cause: str) -> str:
    """Return the truth type for a cause, defaulting to evidential."""
    return CAUSE_TRUTH_TYPE.get(str(cause), "evidential")


@dataclass(frozen=True)
class DocView:
    """A document as it was available to one action."""

    id: str
    kind: str
    publisher: str
    trust_tier: int
    t: int
    text: str
    facts: tuple[dict[str, Any], ...]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "publisher": self.publisher,
            "trust_tier": self.trust_tier,
            "t": self.t,
            "text": self.text,
            "facts": [dict(f) for f in self.facts],
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class NoteView:
    """A note the action cites, with the documents it cites."""

    id: str
    t: int
    text: str
    written_by: str
    signature_valid: bool
    cites: tuple[str, ...]
    cited_docs: tuple[DocView, ...]
    missing_cited_docs: tuple[str, ...]
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "t": self.t,
            "text": self.text,
            "written_by": self.written_by,
            "signature_valid": self.signature_valid,
            "cites": list(self.cites),
            "cited_docs": [d.to_dict() for d in self.cited_docs],
            "missing_cited_docs": list(self.missing_cited_docs),
            "available": self.available,
        }


def _values_match(a: float, b: float) -> bool:
    scale = max(abs(float(a)), abs(float(b)), 1e-12)
    return abs(float(a) - float(b)) / scale <= 1e-6


def _fact_matches(value: float | None, unit: str | None, facts: Sequence[Mapping[str, Any]]) -> bool | None:
    """Whether a numeric claim matches a source fact with the same unit.

    A missing claim unit only matches a source fact that is also unitless.  It
    is never a wildcard: otherwise a future world could report a false
    ``value_matches_source_fact=True`` by attaching a unitless claim to a fact
    in any unit.
    """
    if value is None:
        return None
    for fact in facts:
        fv = fact.get("value")
        if fv is None:
            continue
        if not isinstance(fv, (int, float)) or isinstance(fv, bool):
            continue
        if fact.get("unit") != unit:
            continue
        if _values_match(float(value), float(fv)):
            return True
    return False


@dataclass(frozen=True)
class ClaimView:
    """One claim, its quoted span, and the source text and facts it cites."""

    text: str
    value: float | None
    unit: str | None
    source_doc: str | None
    quoted_span: str | None
    has_source: bool
    source_available: bool
    source_text: str | None
    source_facts: tuple[dict[str, Any], ...]
    source_trust_tier: int | None
    source_kind: str | None
    source_publisher: str | None
    source_t: int | None
    quoted_span_present: bool
    quoted_span_in_source: bool
    value_matches_source_fact: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "value": self.value,
            "unit": self.unit,
            "source_doc": self.source_doc,
            "quoted_span": self.quoted_span,
            "has_source": self.has_source,
            "source_available": self.source_available,
            "source_text": self.source_text,
            "source_facts": [dict(f) for f in self.source_facts],
            "source_trust_tier": self.source_trust_tier,
            "source_kind": self.source_kind,
            "source_publisher": self.source_publisher,
            "source_t": self.source_t,
            "quoted_span_present": self.quoted_span_present,
            "quoted_span_in_source": self.quoted_span_in_source,
            "value_matches_source_fact": self.value_matches_source_fact,
        }


@dataclass(frozen=True)
class ThesisView:
    """The thesis the action is anchored to, without its final status."""

    id: str
    statement: str
    sector: str
    opened_t: int
    evidence_docs: tuple[str, ...]
    invalidation: str
    invalidation_trigger: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "sector": self.sector,
            "opened_t": self.opened_t,
            "evidence_docs": list(self.evidence_docs),
            "invalidation": self.invalidation,
            "invalidation_trigger": dict(self.invalidation_trigger) if self.invalidation_trigger else None,
        }


@dataclass(frozen=True)
class Case:
    """The model-neutral input: one action and only what was knowable then."""

    case_id: str
    episode_key: str
    index: int
    action: dict[str, Any]
    claims: tuple[ClaimView, ...]
    notes: tuple[NoteView, ...]
    thesis: ThesisView | None
    trust: dict[str, Any]
    provenance: dict[str, Any]
    code_features: tuple[float, ...] = ()
    code_feature_names: tuple[str, ...] = ()
    shift_axes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "episode_key": self.episode_key,
            "index": self.index,
            "action": copy.deepcopy(self.action),
            "claims": [c.to_dict() for c in self.claims],
            "notes": [n.to_dict() for n in self.notes],
            "thesis": self.thesis.to_dict() if self.thesis else None,
            "trust": copy.deepcopy(self.trust),
            "provenance": copy.deepcopy(self.provenance),
            "code_features": list(self.code_features),
            "code_feature_names": list(self.code_feature_names),
            "shift_axes": list(self.shift_axes),
        }

    def with_shift_axes(self, axes: Iterable[str]) -> "Case":
        return replace(self, shift_axes=tuple(axes))

    def reader_view(self) -> "Case":
        """The exact object handed to a reader: evaluation tags are stripped."""
        return replace(self, shift_axes=())


def _doc_view(doc: Mapping[str, Any]) -> DocView:
    return DocView(
        id=str(doc["id"]),
        kind=str(doc["kind"]),
        publisher=str(doc["publisher"]),
        trust_tier=int(doc["trust_tier"]),
        t=int(doc["t"]),
        text=str(doc["text"]),
        facts=tuple(dict(f) for f in (doc.get("facts") or [])),
        content_hash=str(doc.get("content_hash", "")),
    )


def _claim_view(claim: Mapping[str, Any], docs_by_id: Mapping[str, Mapping[str, Any]]) -> ClaimView:
    source_doc = claim.get("source_doc")
    has_source = source_doc is not None
    doc = docs_by_id.get(str(source_doc)) if has_source else None
    source_available = doc is not None
    source_text = str(doc["text"]) if doc is not None else None
    source_facts = tuple(dict(f) for f in (doc.get("facts") or [])) if doc is not None else ()
    quoted_span = claim.get("quoted_span")
    span_present = isinstance(quoted_span, str) and bool(quoted_span.strip())
    span_in_source = bool(span_present and source_text is not None and quoted_span in source_text)
    return ClaimView(
        text=str(claim.get("text", "")),
        value=claim.get("value"),
        unit=claim.get("unit"),
        source_doc=str(source_doc) if source_doc is not None else None,
        quoted_span=quoted_span,
        has_source=has_source,
        source_available=source_available,
        source_text=source_text,
        source_facts=source_facts,
        source_trust_tier=int(doc["trust_tier"]) if doc is not None else None,
        source_kind=str(doc["kind"]) if doc is not None else None,
        source_publisher=str(doc["publisher"]) if doc is not None else None,
        source_t=int(doc["t"]) if doc is not None else None,
        quoted_span_present=span_present,
        quoted_span_in_source=span_in_source,
        value_matches_source_fact=_fact_matches(claim.get("value"), claim.get("unit"), source_facts),
    )


def _note_view(note: Mapping[str, Any], docs_by_id: Mapping[str, Mapping[str, Any]]) -> NoteView:
    cites = tuple(str(c) for c in (note.get("cites") or []))
    docs = tuple(_doc_view(docs_by_id[c]) for c in cites if c in docs_by_id)
    missing = tuple(c for c in cites if c not in docs_by_id)
    return NoteView(
        id=str(note["id"]),
        t=int(note["t"]),
        text=str(note["text"]),
        written_by=str(note["written_by"]),
        signature_valid=bool(note["signature_valid"]),
        cites=cites,
        cited_docs=docs,
        missing_cited_docs=missing,
        available=True,
    )


def _missing_note(note_id: str) -> NoteView:
    return NoteView(
        id=str(note_id),
        t=-1,
        text="",
        written_by="unknown",
        signature_valid=False,
        cites=(),
        cited_docs=(),
        missing_cited_docs=(),
        available=False,
    )


def _thesis_view(theses: Sequence[Mapping[str, Any]], thesis_id: str) -> ThesisView | None:
    for thesis in theses:
        if str(thesis.get("id")) == str(thesis_id):
            return ThesisView(
                id=str(thesis["id"]),
                statement=str(thesis["statement"]),
                sector=str(thesis["sector"]),
                opened_t=int(thesis["opened_t"]),
                evidence_docs=tuple(str(d) for d in (thesis.get("evidence_docs") or [])),
                invalidation=str(thesis["invalidation"]),
                invalidation_trigger=dict(thesis["invalidation_trigger"])
                if thesis.get("invalidation_trigger")
                else None,
            )
    return None


def _episode_key(owner: Mapping[str, Any], first_action: Mapping[str, Any], book: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {
            "owner": owner.get("signing_key_id"),
            "first_action": first_action,
            "initial_book": book,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _case_from_view(
    view: Mapping[str, Any],
    index: int,
    episode_key: str,
    code_features: Sequence[float],
    code_feature_names: Sequence[str],
) -> Case:
    action = copy.deepcopy(dict(view["action"]))
    docs = view.get("documents") or []
    notes = view.get("notes") or []
    docs_by_id = {str(d["id"]): d for d in docs}
    notes_by_id = {str(n["id"]): n for n in notes}
    owner = view.get("owner") or {}

    claims = tuple(_claim_view(c, docs_by_id) for c in (action.get("claims") or []))
    cited_notes = tuple(
        _note_view(notes_by_id[str(nid)], docs_by_id) if str(nid) in notes_by_id else _missing_note(str(nid))
        for nid in (action.get("cites_notes") or [])
    )
    thesis = _thesis_view(view.get("theses") or [], action.get("thesis_id"))

    source_tiers = [c.source_trust_tier for c in claims if c.source_available and c.source_trust_tier is not None]
    note_doc_tiers = [d.trust_tier for n in cited_notes if n.available for d in n.cited_docs]
    all_tiers = source_tiers + note_doc_tiers
    bands = owner.get("sector_bands") or {}
    band = bands.get(action.get("sector"))
    unsigned = sorted(n.id for n in cited_notes if n.available and not n.signature_valid)
    external_tool = sorted(
        n.id for n in cited_notes if n.available and n.written_by in ("external", "tool")
    )

    trust: dict[str, Any] = {
        "owner_key": owner.get("signing_key_id"),
        "owner_purpose": owner.get("purpose"),
        "instrument": action.get("instrument"),
        "sector": action.get("sector"),
        "side": action.get("side"),
        "notional": action.get("notional"),
        "thesis_id": action.get("thesis_id"),
        "opens_thesis": bool(action.get("opens_thesis")),
        "sector_band": {"min": band.get("min"), "max": band.get("max")} if band else None,
        "instrument_cap": owner.get("max_position_pct"),
        "turnover_cap": owner.get("max_daily_turnover_pct"),
        "min_source_trust": min(source_tiers) if source_tiers else None,
        "max_source_trust": max(source_tiers) if source_tiers else None,
        "min_cited_doc_trust": min(note_doc_tiers) if note_doc_tiers else None,
        "max_cited_doc_trust": max(note_doc_tiers) if note_doc_tiers else None,
        "available_source_count": sum(1 for c in claims if c.source_available),
        "claim_count": len(claims),
        "cited_note_count": len(cited_notes),
        "all_cited_notes_signed": all(n.signature_valid for n in cited_notes if n.available),
        "unsigned_note_ids": unsigned,
        "external_tool_note_ids": external_tool,
        "has_unavailable_source": any(c.has_source and not c.source_available for c in claims),
        "has_unsourced_claim": any(not c.has_source for c in claims),
    }
    provenance: dict[str, Any] = {
        "index": index,
        "t": action.get("t"),
        "history_len": index,
        "n_documents": len(docs),
        "n_notes": len(notes),
        "n_theses": len(view.get("theses") or []),
        "source_doc_ids": sorted({c.source_doc for c in claims if c.source_doc is not None}),
        "cited_note_ids": sorted(n.id for n in cited_notes),
        "thesis_opened_t": thesis.opened_t if thesis else None,
    }
    return Case(
        case_id=f"{episode_key}:{index}",
        episode_key=episode_key,
        index=index,
        action=action,
        claims=claims,
        notes=cited_notes,
        thesis=thesis,
        trust=trust,
        provenance=provenance,
        code_features=tuple(float(x) for x in code_features),
        code_feature_names=tuple(str(x) for x in code_feature_names),
    )



@dataclass(frozen=True)
class LabelRecord:
    """One action label with the truth type the bench reports by."""

    y: int
    cause: str
    cause_refs: tuple[str, ...]
    truth_type: str
    source: str = "synthetic_reference"

    def to_dict(self) -> dict[str, Any]:
        return {
            "y": self.y,
            "cause": self.cause,
            "cause_refs": list(self.cause_refs),
            "truth_type": self.truth_type,
            "source": self.source,
        }


def labels(episode: Any) -> list[LabelRecord]:
    """Read the evaluation-only labels and attach a truth type to each.

    This is the only label reader in the package.  It is never called by
    :func:`cases`, and a Case never carries a ``LabelRecord``.
    """
    steps = episode.steps if hasattr(episode, "steps") else (episode.get("steps") or [])
    out: list[LabelRecord] = []
    for step in steps:
        label = step.label if hasattr(step, "label") else step["label"]
        cause = str(label.cause if hasattr(label, "cause") else label["cause"])
        y = int(label.y if hasattr(label, "y") else label["y"])
        refs = label.cause_refs if hasattr(label, "cause_refs") else label["cause_refs"]
        out.append(
            LabelRecord(
                y=y,
                cause=cause,
                cause_refs=tuple(str(r) for r in refs),
                truth_type=truth_type_for(cause),
                source="synthetic_reference",
            )
        )
    return out


def _n_steps(episode: Any) -> int:
    if hasattr(episode, "steps"):
        return len(episode.steps)  # type: ignore[union-attr]
    return len(episode.get("steps") or [])


def cases(episode: Any, *, code_features: bool = True) -> list[Case]:
    """Return every action's :class:`Case`, in step order.

    Only :func:`og_s1.schema.model_view_at` is used for the causal content.
    ``code_features`` attaches T03's causal feature row to each Case so the
    trivial code-feature baseline can consume a Case without seeing the
    episode; the features themselves come from ``checks.featurize``, which
    reads the same per-action causal view.
    """
    n = _n_steps(episode)
    if n == 0:
        return []
    if code_features:
        X, names, _ = featurize(episode)
    else:
        X, names = None, []

    out: list[Case] = []
    episode_key: str | None = None
    for i in range(n):
        view = model_view_at(episode, i)
        if episode_key is None:
            episode_key = _episode_key(
                view.get("owner") or {},
                view.get("action") or {},
                view.get("initial_book") or {},
            )
        out.append(
            _case_from_view(
                view,
                i,
                episode_key,
                X[i] if X is not None else (),
                names,
            )
        )
    return out


def axes_for_meta(meta: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Evaluation-only shift-axis tag for one episode.

    Uses ``meta.family`` (the planted family) and ``meta.shifted``.  The result
    is attached by :func:`tag_shift_axes`; it is stripped before a reader is
    called.
    """
    if not meta:
        return ()
    axes = set(FAMILY_AXES.get(str(meta.get("family", "clean")), ()))
    if meta.get("shifted"):
        axes.add("semantic")
    return tuple(a for a in SHIFT_AXES if a in axes)


def tag_shift_axes(cases_in: Sequence[Case], meta: Mapping[str, Any] | None) -> list[Case]:
    """Attach evaluation-only shift axes to every Case."""
    axes = axes_for_meta(meta)
    return [case.with_shift_axes(axes) for case in cases_in]


def reader_inputs(cases_in: Sequence[Case]) -> list[Case]:
    """Strip evaluation-only tags from every Case before a reader sees it."""
    return [case.reader_view() for case in cases_in]


def feature_names() -> tuple[str, ...]:
    return tuple(FEATURE_NAMES)


def feature_groups() -> dict[str, str]:
    return dict(GROUPS)
