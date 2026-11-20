"""Binding-coherence checks for System One actions.

An action is *coherent* when its words are attached to the thing it trades:
the side matches the rationale's direction, the rationale talks about the
traded instrument (or stays at sector level without naming a peer), and the
claims are about the traded instrument, the thesis evidence that supports it,
or its sector.  A claim must also be attached to the right entity and period:
a figure from a sibling's filing is not evidence about the traded name, and an
old figure is not the current one when a later document has the same fact.

``coherence(action, case)`` returns a list of finding dicts.  ``case`` is the
causal context for one action, normally built with :func:`case_for_step` or
:func:`case_from_view`.  The check never reads labels or ``meta``; callers may
use those for scoring, but the check itself does not.

The check is written for the reference world's two surface forms.  It uses the
world's own entity map (tickers when unshifted, company names when shifted) and
the world's fact phrases (including the shifted word map), never a ticker
substring search over shifted text.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterable

from .world import COMPANY_NAMES, FACT_PHRASES, SECTORS, _shift_text

# Rationale direction cues.  The patterns are deliberately narrow: a phrase
# must name the agent's own action, not merely contain a trading word.
_BUY_CUES = (
    r"\bwe add\b",
    r"\badd(?:ing)? to (?:the )?(?:position|exposure|holding)\b",
    r"\badding (?:some )?[A-Za-z0-9&'.\- ]{1,40} to the position\b",
    r"\bbuy(?:ing)?\b",
    r"\baccumulat(?:e|ing)\b",
    r"\bgo(?:ing)? long\b",
    r"\binitiat(?:e|ing)\b",
    r"\bbuild(?:ing)? (?:the )?(?:[A-Za-z0-9&'.\-]+ ){0,2}position\b",
    r"\brebalanc(?:e|ing) into\b",
    r"\bincreas(?:e|ing) (?:the )?(?:[A-Za-z0-9&'.\-]+ ){0,2}position\b",
    r"\bwe (?:build|increase)\b",
)
_SELL_CUES = (
    r"\btak(?:e|ing) .{0,50} off the table\b",
    r"\btrim(?:ming)?\b",
    r"\breduc(?:e|ing) (?:the )?(?:[A-Za-z0-9&'.\-]+ ){0,2}(?:position|exposure|holding)\b",
    r"\bsell(?:ing)?\b",
    r"\bcut(?:ting)? (?:the )?(?:[A-Za-z0-9&'.\-]+ ){0,2}(?:position|exposure|holding)\b",
    r"\bexit(?:ing)? (?:the )?position\b",
    r"\blighten(?:ing)?\b",
    r"\boffload(?:ing)?\b",
    r"\btake profits?\b",
    r"\brebalanc(?:e|ing) out\b",
    r"\blower(?:ing)? the position\b",
)
_BUY_RE = tuple(re.compile(p, re.IGNORECASE) for p in _BUY_CUES)
_SELL_RE = tuple(re.compile(p, re.IGNORECASE) for p in _SELL_CUES)

_NEGATION_RE = re.compile(
    r"\b(?:not|no longer|never|without|rather than|instead of)\s*$", re.IGNORECASE
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_COMPARISON_RE = re.compile(
    r"\b(?:versus|vs\.?|compared (?:with|to)|relative to|against|"
    r"outperform(?:s|ed|ing)?|underperform(?:s|ed|ing)?|"
    r"cheaper than|more expensive than|richer than|pricier than|"
    r"better than|worse than|peer|sibling|spread|whereas)\b",
    re.IGNORECASE,
)

_FINDING_RATIONALE_DIRECTION = "rationale_direction"
_FINDING_RATIONALE_FOREIGN = "rationale_foreign_instrument"
_FINDING_CLAIMS_NOT_ABOUT_TRADE = "claim_not_about_trade"
_FINDING_CLAIM_FOREIGN = "claim_foreign_instrument"
_FINDING_CLAIM_SOURCE_ENTITY = "claim_source_entity_mismatch"
_FINDING_CLAIM_STALE_PERIOD = "claim_stale_period"

FINDING_KINDS = (
    _FINDING_RATIONALE_DIRECTION,
    _FINDING_RATIONALE_FOREIGN,
    _FINDING_CLAIMS_NOT_ABOUT_TRADE,
    _FINDING_CLAIM_FOREIGN,
    _FINDING_CLAIM_SOURCE_ENTITY,
    _FINDING_CLAIM_STALE_PERIOD,
)


def _as_dict(obj: Any) -> dict:
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


def _episode_dict(episode: Any) -> dict:
    return episode.to_dict() if hasattr(episode, "to_dict") else episode


def _aliases(instrument: str, shifted: bool) -> list[str]:
    if shifted:
        return [COMPANY_NAMES.get(instrument, instrument)]
    return [instrument]


def default_entity_names(instrument_sectors: dict[str, str], shifted: bool) -> dict[str, list[str]]:
    return {inst: _aliases(inst, shifted) for inst in instrument_sectors}


def _infer_shifted(d: dict) -> bool:
    """Infer the surface form from the text, never from ``meta`` or labels.

    Every reference document names exactly one instrument, as either its
    ticker or its company name, so the first decisive mention settles the
    form.  The shared ticker/name ``AMD`` is skipped because it says nothing.
    """
    texts = [str(doc.get("text") or "") for doc in d.get("documents") or []]
    texts.extend(str(note.get("text") or "") for note in d.get("initial_notes") or [])
    for text in texts:
        if not text:
            continue
        for ticker, company in COMPANY_NAMES.items():
            if not isinstance(company, str) or company == ticker:
                continue
            if company and _name_pattern(company).search(text):
                return True
            if ticker and _name_pattern(ticker).search(text):
                return False
    return False


def build_context(episode: Any, entity_names: dict[str, list[str]] | None = None) -> dict:
    """Precompute the episode-level tables the per-action check reuses.

    ``doc_subjects`` and ``facts_by_instrument_name`` are built once, not once
    per action.  Causal filtering still happens when the case is built: only
    documents with ``t <= action.t`` enter the case, and the period check only
    looks at facts whose document time is strictly later than the claim's.
    """
    d = _episode_dict(episode)
    shifted = _infer_shifted(d)
    isec = d.get("instrument_sectors") or {}
    names = entity_names or default_entity_names(isec, shifted)
    name_to_instrument: dict[str, str] = {}
    for instrument, aliases in names.items():
        for name in aliases:
            if name:
                name_to_instrument[name] = instrument
    ordered = sorted(name_to_instrument, key=len, reverse=True)
    mention_re = (
        re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(n) for n in ordered) + r")(?![A-Za-z0-9])")
        if ordered else None
    )
    doc_subjects: dict[str, frozenset[str]] = {}
    facts_by_instrument_name: dict[str, dict[str, list[tuple]]] = {}
    for doc in d.get("documents") or []:
        doc_id = str(doc.get("id"))
        subjects = frozenset(
            name_to_instrument[m.group(0)]
            for m in (mention_re.finditer(str(doc.get("text", ""))) if mention_re else ())
        )
        doc_subjects[doc_id] = subjects
        if len(subjects) != 1:
            continue
        subject = next(iter(subjects))
        try:
            ordinal = int(doc_id[1:])
        except (TypeError, ValueError):
            ordinal = 0
        for fact in doc.get("facts") or []:
            facts_by_instrument_name.setdefault(subject, {}).setdefault(
                str(fact.get("name")), []
            ).append((int(doc.get("t", 0)), ordinal, doc_id, fact.get("value"), fact.get("unit")))
    for by_name in facts_by_instrument_name.values():
        for rows in by_name.values():
            rows.sort(key=lambda r: (r[0], r[1]))
    return {
        "shifted": shifted,
        "instrument_sectors": isec,
        "entity_names": names,
        "name_to_instrument": name_to_instrument,
        "mention_re": mention_re,
        "doc_subjects": doc_subjects,
        "facts_by_instrument_name": facts_by_instrument_name,
        "fact_phrases": {
            name: (_shift_text(phrase, shifted) if shifted else phrase)
            for name, phrase in FACT_PHRASES.items()
        },
        "sectors": tuple(SECTORS),
    }


def case_for_step(
    episode: Any,
    step_index: int,
    entity_names: dict[str, list[str]] | None = None,
    context: dict | None = None,
) -> dict:
    """Build the causal context for one action without exposing labels."""
    d = _episode_dict(episode)
    ctx = context or build_context(d, entity_names=entity_names)
    action = d["steps"][step_index]["action"]
    t = action["t"]
    view = {
        "instrument_sectors": d.get("instrument_sectors") or {},
        "documents": [doc for doc in d.get("documents") or [] if doc.get("t", 0) <= t],
        "theses": [th for th in d.get("theses") or [] if th.get("opened_t", 0) <= t],
        "action": action,
    }
    return case_from_view(view, shifted=ctx["shifted"], context=ctx)


def case_from_view(
    view: dict,
    shifted: bool = False,
    entity_names: dict[str, list[str]] | None = None,
    context: dict | None = None,
) -> dict:
    """Build a case from an already-causal view or a :func:`build_context` table."""
    docs = view.get("documents") or []
    ctx = context
    if ctx is None:
        isec = view.get("instrument_sectors") or {}
        names = entity_names or default_entity_names(isec, shifted)
        ctx = {
            "shifted": bool(shifted),
            "instrument_sectors": isec,
            "entity_names": names,
            "name_to_instrument": {
                n: inst for inst, aliases in names.items() for n in aliases if n
            },
            "mention_re": None,
            "doc_subjects": {
                str(d.get("id")): frozenset(_scan_mentions(str(d.get("text", "")), names))
                for d in docs
            },
            "facts_by_instrument_name": {},
            "fact_phrases": {
                name: (_shift_text(phrase, shifted) if shifted else phrase)
                for name, phrase in FACT_PHRASES.items()
            },
            "sectors": tuple(SECTORS),
        }
    case = dict(ctx)
    case.update({
        "documents": docs,
        "doc_by_id": {str(d.get("id")): d for d in docs},
        "doc_index": {str(d.get("id")): i for i, d in enumerate(docs)},
        "theses": {str(t.get("id")): t for t in (view.get("theses") or [])},
        "action": view.get("action") or {},
    })
    return case


@lru_cache(maxsize=256)
def _name_pattern(name: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])")


def _scan_mentions(text: str, entity_names: dict[str, list[str]]) -> list[str]:
    found = []
    for instrument, names in entity_names.items():
        for name in names:
            if name and _name_pattern(name).search(text):
                found.append(instrument)
                break
    return found


def _mentions(text: str, case: dict) -> list[str]:
    mention_re = case.get("mention_re")
    if mention_re is not None:
        mapping = case.get("name_to_instrument") or {}
        out = []
        seen = set()
        for match in mention_re.finditer(text):
            instrument = mapping.get(match.group(0))
            if instrument is not None and instrument not in seen:
                seen.add(instrument)
                out.append(instrument)
        return out
    return _scan_mentions(text, case.get("entity_names") or {})


def _mentioned_sectors(text: str, sectors: Iterable[str]) -> list[str]:
    low = text.lower()
    return [s for s in sectors if _name_pattern(s).search(low)]


def _cue_hit(pattern: re.Pattern, text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 30):match.start()]
        if _NEGATION_RE.search(prefix):
            continue
        return True
    return False


def _direction(text: str) -> tuple[bool, bool]:
    return (
        any(_cue_hit(p, text) for p in _BUY_RE),
        any(_cue_hit(p, text) for p in _SELL_RE),
    )


def _foreign_instruments(text: str, traded: str, case: dict) -> list[str]:
    """Instruments named as if they were the traded one.

    A peer named in the same sentence as the traded name and an explicit
    comparison word is a legitimate relative-value statement; a peer named on
    its own is the binding error.
    """
    foreign: set[str] = set()
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        mentioned = _mentions(sentence, case)
        peers = [i for i in mentioned if i != traded]
        if not peers:
            continue
        if _COMPARISON_RE.search(sentence) and traded in mentioned:
            continue
        foreign.update(peers)
    return sorted(foreign)


def _doc_subjects(doc: dict, case: dict) -> set[str]:
    key = str(doc.get("id"))
    cached = (case.get("doc_subjects") or {}).get(key)
    if cached is not None:
        return set(cached)
    return set(_mentions(str(doc.get("text", "")), case))


def _claim_subject(text: str, traded: str, case: dict) -> str | None:
    mentioned = _mentions(text, case)
    if traded in mentioned:
        return traded
    if mentioned:
        return mentioned[0]
    return None


def _rendered_in_text(fact: dict, doc_text: str) -> str | None:
    """Return an exact rendered occurrence of a fact value in ``doc_text``."""
    value = fact.get("value")
    if not isinstance(value, (int, float)):
        return None
    for dec in (3, 2, 4, 1, 0):
        rendered = f"{float(value):.{dec}f}"
        for candidate in (rendered, f"${rendered}", f"{rendered}%"):
            if candidate in doc_text:
                return candidate
    return None


def _claim_source_fact(claim: dict, doc: dict, fact_phrases: dict[str, str]) -> dict | None:
    text = str(claim.get("text") or "")
    span = claim.get("quoted_span")
    unit = claim.get("unit")
    if span is None and claim.get("value") is None:
        return None
    best = None
    doc_text = str(doc.get("text") or "")
    for fact in doc.get("facts") or []:
        if unit is not None and str(fact.get("unit")) != str(unit):
            continue
        rendered = _rendered_in_text(fact, doc_text)
        name = str(fact.get("name"))
        phrase = fact_phrases.get(name, name.replace("_", " "))
        if span is not None and rendered is not None and str(span) == rendered:
            return fact
        if rendered and rendered in text and phrase.lower() in text.lower():
            best = fact
    return best


def _stale_period_finding(
    claim: dict,
    doc: dict,
    case: dict,
    subject: str | None,
    fact_phrases: dict[str, str],
    action_t: int,
) -> dict | None:
    fact = _claim_source_fact(claim, doc, fact_phrases)
    if fact is None or subject is None:
        return None
    src_key = str(doc.get("id"))
    src_t = int(doc.get("t", 0))
    name = str(fact.get("name"))
    old_value = fact.get("value")
    rows = ((case.get("facts_by_instrument_name") or {}).get(subject) or {}).get(name, [])
    for t, _ordinal, doc_id, value, _unit in rows:
        # Same-time documents are the same period; only a strictly later
        # document makes the old figure stale.
        if t <= src_t or t > action_t or doc_id == src_key:
            continue
        if value == old_value:
            continue
        return {
            "kind": _FINDING_CLAIM_STALE_PERIOD,
            "message": (
                f"claim uses {name}={old_value} from {src_key}, but {doc_id} "
                f"reports {name}={value} for the same instrument"
            ),
            "refs": [src_key, doc_id],
            "claim_index": None,
        }
    return None


def coherence(action: Any, case: dict) -> list[dict]:
    """Return the binding-coherence findings for one action.

    Empty list means coherent.  Each finding has ``kind``, ``message``,
    ``refs`` (document ids the finding points at) and ``claim_index``.
    """
    action = _as_dict(action)
    traded = str(action.get("instrument") or "")
    side = str(action.get("side") or "")
    fact_phrases = case.get("fact_phrases") or FACT_PHRASES
    findings: list[dict] = []

    rationale = str(action.get("rationale") or "")
    if rationale:
        buy, sell = _direction(rationale)
        if side == "sell" and buy and not sell:
            findings.append({
                "kind": _FINDING_RATIONALE_DIRECTION,
                "message": "sell rationale uses buying language",
                "refs": [],
                "claim_index": None,
            })
        elif side == "buy" and sell and not buy:
            findings.append({
                "kind": _FINDING_RATIONALE_DIRECTION,
                "message": "buy rationale uses selling language",
                "refs": [],
                "claim_index": None,
            })
        foreign = _foreign_instruments(rationale, traded, case)
        if foreign:
            findings.append({
                "kind": _FINDING_RATIONALE_FOREIGN,
                "message": f"rationale names {', '.join(sorted(foreign))} but trades {traded}",
                "refs": [],
                "claim_index": None,
            })

    claims = action.get("claims") or []
    thesis = (case.get("theses") or {}).get(str(action.get("thesis_id")))
    thesis_sector = str(thesis.get("sector")) if thesis else None
    thesis_evidence = set(str(x) for x in (thesis.get("evidence_docs") or [])) if thesis else set()
    sectors = case.get("sectors") or SECTORS

    relevant = False
    for j, claim in enumerate(claims):
        text = str(claim.get("text") or "")
        mentioned = _mentions(text, case)
        foreign = _foreign_instruments(text, traded, case)
        if foreign:
            findings.append({
                "kind": _FINDING_CLAIM_FOREIGN,
                "message": (
                    f"claim {j} names {', '.join(sorted(foreign))} without an "
                    f"explicit comparison to {traded}"
                ),
                "refs": [str(claim.get("source_doc"))] if claim.get("source_doc") else [],
                "claim_index": j,
            })
        source = str(claim.get("source_doc")) if claim.get("source_doc") is not None else None
        subject = _claim_subject(text, traded, case)
        if traded in mentioned:
            relevant = True
        elif not mentioned:
            sector_mentions = _mentioned_sectors(text, sectors)
            if any(s == thesis_sector for s in sector_mentions):
                relevant = True
        if source is not None and source in (case.get("doc_by_id") or {}):
            doc = case["doc_by_id"][source]
            if source in thesis_evidence and thesis_sector == str(action.get("sector")):
                relevant = True
            if subject is not None and _COMPARISON_RE.search(text) and traded in mentioned:
                subject = traded
            doc_subjects = _doc_subjects(doc, case)
            if subject is not None and doc_subjects and subject not in doc_subjects:
                findings.append({
                    "kind": _FINDING_CLAIM_SOURCE_ENTITY,
                    "message": (
                        f"claim {j} is about {subject} but its source {source} "
                        f"is about {', '.join(sorted(doc_subjects))}"
                    ),
                    "refs": [source],
                    "claim_index": j,
                })
            stale = _stale_period_finding(
                claim, doc, case, subject, fact_phrases, int(action.get("t", 0)))
            if stale is not None:
                stale["claim_index"] = j
                findings.append(stale)

    if not relevant:
        findings.append({
            "kind": _FINDING_CLAIMS_NOT_ABOUT_TRADE,
            "message": f"no claim is about {traded}, its sector thesis, or its sector",
            "refs": [],
            "claim_index": None,
        })

    # Attach the claim source documents to rationale findings too: when a
    # caller writes ``cause_refs`` for a rationale plant it names the document
    # the rationale's figure came from, and the finding should point at it.
    source_refs = sorted({
        str(c.get("source_doc"))
        for c in claims
        if c.get("source_doc") is not None
    })
    for finding in findings:
        if finding["kind"] in (_FINDING_RATIONALE_DIRECTION, _FINDING_RATIONALE_FOREIGN):
            finding["refs"] = source_refs

    return findings


def finding_kinds(findings: list[dict]) -> list[str]:
    return [str(f.get("kind")) for f in findings]


def is_coherent(action: Any, case: dict) -> bool:
    return not coherence(action, case)
