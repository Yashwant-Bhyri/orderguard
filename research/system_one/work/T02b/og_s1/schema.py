"""Typed, JSON-serialisable dataclasses for the OrderGuard System One world.

Every class round-trips through ``to_dict`` / ``from_dict`` and contains only
JSON-native values (str, int, float, bool, list, dict, None), so an Episode can
be written as one JSON line in a JSONL file.
"""
from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any

PURPOSES = ("income", "balanced", "growth", "capital_preservation")
DOC_KINDS = ("filing", "news", "analyst", "social", "tool_output")
NOTE_WRITERS = ("agent", "tool", "owner_signed", "external")
THESIS_STATUSES = ("active", "weakened", "abandoned", "invalidated")
SIDES = ("buy", "sell")
OPS = ("<", "<=", ">", ">=", "==", "!=")
KNOWN_CAUSES = (
    "clean",
    "drift",
    "unsupported_claim",
    "misquote",
    "vague_hype",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
)
SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Owner:
    purpose: str
    sector_bands: dict[str, dict[str, float]]
    max_position_pct: float
    max_daily_turnover_pct: float
    allowed_instruments: list[str]
    signing_key_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "sector_bands": {k: dict(v) for k, v in self.sector_bands.items()},
            "max_position_pct": self.max_position_pct,
            "max_daily_turnover_pct": self.max_daily_turnover_pct,
            "allowed_instruments": list(self.allowed_instruments),
            "signing_key_id": self.signing_key_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Owner":
        return cls(
            purpose=d["purpose"],
            sector_bands={k: dict(v) for k, v in d["sector_bands"].items()},
            max_position_pct=d["max_position_pct"],
            max_daily_turnover_pct=d["max_daily_turnover_pct"],
            allowed_instruments=list(d["allowed_instruments"]),
            signing_key_id=d["signing_key_id"],
        )


@dataclass
class Document:
    id: str
    kind: str
    publisher: str
    trust_tier: int
    t: int
    text: str
    facts: list[dict[str, Any]]
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = content_hash(self.text)

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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Document":
        return cls(
            id=d["id"],
            kind=d["kind"],
            publisher=d["publisher"],
            trust_tier=d["trust_tier"],
            t=d["t"],
            text=d["text"],
            facts=[dict(f) for f in d["facts"]],
            content_hash=d.get("content_hash", ""),
        )


@dataclass
class Note:
    id: str
    t: int
    text: str
    written_by: str
    signature_valid: bool
    cites: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "t": self.t,
            "text": self.text,
            "written_by": self.written_by,
            "signature_valid": self.signature_valid,
            "cites": list(self.cites),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Note":
        return cls(
            id=d["id"],
            t=d["t"],
            text=d["text"],
            written_by=d["written_by"],
            signature_valid=d["signature_valid"],
            cites=list(d["cites"]),
        )


@dataclass
class Claim:
    text: str
    value: float | None
    unit: str | None
    source_doc: str | None
    quoted_span: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "value": self.value,
            "unit": self.unit,
            "source_doc": self.source_doc,
            "quoted_span": self.quoted_span,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Claim":
        return cls(
            text=d["text"],
            value=d.get("value"),
            unit=d.get("unit"),
            source_doc=d.get("source_doc"),
            quoted_span=d.get("quoted_span"),
        )


@dataclass
class Thesis:
    id: str
    statement: str
    sector: str
    opened_t: int
    evidence_docs: list[str]
    invalidation: str
    invalidation_trigger: dict[str, Any] | None
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "sector": self.sector,
            "opened_t": self.opened_t,
            "evidence_docs": list(self.evidence_docs),
            "invalidation": self.invalidation,
            "invalidation_trigger": dict(self.invalidation_trigger) if self.invalidation_trigger else None,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Thesis":
        return cls(
            id=d["id"],
            statement=d["statement"],
            sector=d["sector"],
            opened_t=d["opened_t"],
            evidence_docs=list(d["evidence_docs"]),
            invalidation=d["invalidation"],
            invalidation_trigger=dict(d["invalidation_trigger"]) if d.get("invalidation_trigger") else None,
            status=d["status"],
        )


@dataclass
class Action:
    t: int
    sector: str
    instrument: str
    side: str
    notional: float
    thesis_id: str
    opens_thesis: bool
    claims: list[Claim]
    cites_notes: list[str]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "sector": self.sector,
            "instrument": self.instrument,
            "side": self.side,
            "notional": self.notional,
            "thesis_id": self.thesis_id,
            "opens_thesis": self.opens_thesis,
            "claims": [c.to_dict() for c in self.claims],
            "cites_notes": list(self.cites_notes),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        return cls(
            t=d["t"],
            sector=d["sector"],
            instrument=d["instrument"],
            side=d["side"],
            notional=d["notional"],
            thesis_id=d["thesis_id"],
            opens_thesis=d["opens_thesis"],
            claims=[Claim.from_dict(c) for c in d["claims"]],
            cites_notes=list(d["cites_notes"]),
            rationale=d["rationale"],
        )


@dataclass
class Label:
    y: int
    cause: str
    cause_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"y": self.y, "cause": self.cause, "cause_refs": list(self.cause_refs)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Label":
        return cls(y=d["y"], cause=d["cause"], cause_refs=list(d["cause_refs"]))


@dataclass
class Step:
    action: Action
    pre_notes: list[Note]
    new_notes: list[Note]
    label: Label

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "pre_notes": [n.to_dict() for n in self.pre_notes],
            "new_notes": [n.to_dict() for n in self.new_notes],
            "label": self.label.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(
            action=Action.from_dict(d["action"]),
            pre_notes=[Note.from_dict(n) for n in d["pre_notes"]],
            new_notes=[Note.from_dict(n) for n in d["new_notes"]],
            label=Label.from_dict(d["label"]),
        )


@dataclass
class Book:
    """A portfolio snapshot: cash plus market value per instrument and sector.

    ``sectors`` is the per-sector total of ``positions`` (instruments are
    assigned to sectors by ``Episode.instrument_sectors``); it is carried
    explicitly so a reader can audit the book without re-deriving it.
    """

    cash: float
    positions: dict[str, float]
    sectors: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cash": self.cash,
            "positions": dict(self.positions),
            "sectors": dict(self.sectors),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Book":
        return cls(
            cash=d["cash"],
            positions=dict(d["positions"]),
            sectors=dict(d["sectors"]),
        )


@dataclass
class Episode:
    owner: Owner
    documents: list[Document]
    initial_notes: list[Note]
    theses: list[Thesis]
    initial_book: Book
    instrument_sectors: dict[str, str]
    steps: list[Step]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner.to_dict(),
            "documents": [d.to_dict() for d in self.documents],
            "initial_notes": [n.to_dict() for n in self.initial_notes],
            "theses": [t.to_dict() for t in self.theses],
            "initial_book": self.initial_book.to_dict(),
            "instrument_sectors": dict(self.instrument_sectors),
            "steps": [s.to_dict() for s in self.steps],
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Episode":
        return cls(
            owner=Owner.from_dict(d["owner"]),
            documents=[Document.from_dict(x) for x in d["documents"]],
            initial_notes=[Note.from_dict(x) for x in d["initial_notes"]],
            theses=[Thesis.from_dict(x) for x in d["theses"]],
            initial_book=Book.from_dict(d["initial_book"]),
            instrument_sectors=dict(d["instrument_sectors"]),
            steps=[Step.from_dict(x) for x in d["steps"]],
            meta=dict(d["meta"]),
        )


def model_view(episode: "Episode | dict[str, Any]") -> dict[str, Any]:
    """Return the model-facing view of an episode.

    Evaluation-only data is stripped: the top-level ``meta`` (which names the
    planted failure family) and every step's ``label`` (the ground truth).
    Downstream features and models must consume this view, never the full
    episode. Accepts an ``Episode`` or an already-serialised dict; returns a
    new JSON-serialisable dict and never mutates the input.
    """
    if hasattr(episode, "to_dict"):
        d = episode.to_dict()  # type: ignore[union-attr]
    else:
        d = copy.deepcopy(episode)
    d.pop("meta", None)
    for s in d.get("steps", []):
        s.pop("label", None)
    return d


def model_view_at(episode: "Episode | dict[str, Any]", i: int) -> dict[str, Any]:
    """The causal, per-action model input for step ``i``: only what was knowable when action ``i`` was taken.

    - documents with ``t <= action.t``;
    - notes: initial notes, every note written in earlier steps, and this step's ``pre_notes`` (not its ``new_notes``);
    - theses opened at or before ``action.t``, **without** ``status`` (the final status is end-of-episode state);
    - the earlier actions (``history``) and the current action, with no labels and no ``meta``.

    Every per-action feature, reader and model must use this view. ``model_view`` (whole episode, labels stripped) is
    only for episode-level summaries that are computed causally by the caller.
    """
    d = model_view(episode)
    steps = d["steps"]
    cur = steps[i]
    t = cur["action"]["t"]
    notes = list(d["initial_notes"])
    for s in steps[:i]:
        notes += s.get("pre_notes", []) + s.get("new_notes", [])
    notes += cur.get("pre_notes", [])
    theses = []
    for th in d["theses"]:
        if th["opened_t"] <= t:
            th = dict(th)
            th.pop("status", None)
            theses.append(th)
    return {
        "owner": d["owner"],
        "initial_book": d["initial_book"],
        "instrument_sectors": d["instrument_sectors"],
        "documents": [doc for doc in d["documents"] if doc["t"] <= t],
        "notes": [n for n in notes if n["t"] <= t],
        "theses": theses,
        "history": [s["action"] for s in steps[:i]],
        "action": cur["action"],
    }
