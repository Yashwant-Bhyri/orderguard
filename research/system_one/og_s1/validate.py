"""Validator for OrderGuard System One episodes.

``validate(episode_dict) -> list[str]`` returns the list of errors (empty when
valid). CLI: ``python -m og_s1.validate <dir-or-jsonl>`` validates every episode
found and exits non-zero if any error is found.

Besides the structural contract the validator:

- enforces the intra-step event order (``pre_notes`` are available to the
  action, ``new_notes`` are not; neither later-step notes nor later documents
  may be cited);
- enforces the label convention (``y = 0`` iff ``cause = "clean"``);
- replays the book from ``initial_book`` and the actions, and checks that every
  endorsed (``y = 0``) action leaves the book compliant with the sector bands and
  the instrument cap (whatever cause string it carries), and that every
  ``drift`` label really is a buy that leaves a sector above its ``max``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .schema import (
    DOC_KINDS,
    NOTE_WRITERS,
    OPS,
    PURPOSES,
    SECTORS,
    SIDES,
    THESIS_STATUSES,
    content_hash,
)

TOL = 1e-6


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sentence_count(text):
    parts = [p for p in text.split(". ") if p.strip()]
    return len(parts)


def validate(ep) -> list[str]:
    errors: list[str] = []
    if not isinstance(ep, dict):
        return ["episode is not a dict"]
    for key in ("owner", "documents", "initial_notes", "theses", "initial_book",
                "instrument_sectors", "steps", "meta"):
        if key not in ep:
            errors.append(f"missing top-level key: {key}")
    if errors:
        return errors

    errors += _check_owner(ep.get("owner"))
    errors += _check_documents(ep.get("documents"))
    errors += _check_notes(ep.get("initial_notes"), "initial_notes")
    errors += _check_theses(ep.get("theses"))
    errors += _check_book(ep.get("initial_book"), ep.get("instrument_sectors"))
    errors += _check_steps(ep.get("steps"))
    errors += _check_meta(ep.get("meta"))

    if errors:
        return errors

    doc_ids = {d["id"] for d in ep["documents"]}
    doc_t = {d["id"]: d["t"] for d in ep["documents"]}
    note_ids = {n["id"] for n in ep["initial_notes"]}
    for s in ep["steps"]:
        for n in s["pre_notes"]:
            note_ids.add(n["id"])
        for n in s["new_notes"]:
            note_ids.add(n["id"])
    thesis_ids = {th["id"] for th in ep["theses"]}
    thesis_t = {th["id"]: th["opened_t"] for th in ep["theses"]}

    errors += _check_id_refs(ep, doc_ids, doc_t, note_ids, thesis_ids, thesis_t)
    errors += _check_instruments(ep)
    errors += _check_spans(ep, doc_ids)
    errors += _check_labels(ep)
    errors += _check_times(ep)
    # Replay runs even when the label convention above failed, so a relabelling
    # that hides a mandate breach is reported as both a label error and a replay
    # error rather than being masked by the early return.
    errors += _check_replay(ep)
    return errors


def _check_owner(owner):
    errors = []
    if not isinstance(owner, dict):
        return ["owner is not a dict"]
    if owner.get("purpose") not in PURPOSES:
        errors.append(f"owner.purpose invalid: {owner.get('purpose')!r}")
    bands = owner.get("sector_bands")
    if not isinstance(bands, dict) or not bands:
        errors.append("owner.sector_bands missing or empty")
    else:
        missing = [s for s in SECTORS if s not in bands]
        if missing:
            errors.append(f"owner.sector_bands missing sectors: {', '.join(missing)}")
        for s, b in bands.items():
            if s not in SECTORS:
                errors.append(f"owner.sector_bands has unknown sector {s!r}")
            if not isinstance(b, dict) or "min" not in b or "max" not in b:
                errors.append(f"owner.sector_bands[{s}] must be {{min,max}}")
            else:
                if not _is_num(b["min"]) or not _is_num(b["max"]):
                    errors.append(f"owner.sector_bands[{s}] min/max not numeric")
                elif b["min"] > b["max"]:
                    errors.append(f"owner.sector_bands[{s}] min > max")
                elif not (0.0 <= b["min"] <= 1.0 and 0.0 <= b["max"] <= 1.0):
                    errors.append(f"owner.sector_bands[{s}] must lie within [0, 1]")
    for f in ("max_position_pct", "max_daily_turnover_pct"):
        if not _is_num(owner.get(f)):
            errors.append(f"owner.{f} not numeric")
    if not isinstance(owner.get("allowed_instruments"), list):
        errors.append("owner.allowed_instruments must be a list")
    if not isinstance(owner.get("signing_key_id"), str) or not owner["signing_key_id"]:
        errors.append("owner.signing_key_id must be a non-empty string")
    return errors


def _check_documents(docs):
    errors = []
    if not isinstance(docs, list):
        return ["documents is not a list"]
    for i, d in enumerate(docs):
        p = f"documents[{i}]"
        if not isinstance(d, dict):
            errors.append(f"{p} is not a dict")
            continue
        if not isinstance(d.get("id"), str) or not d["id"]:
            errors.append(f"{p}.id missing")
        if d.get("kind") not in DOC_KINDS:
            errors.append(f"{p}.kind invalid: {d.get('kind')!r}")
        if not isinstance(d.get("publisher"), str) or not d["publisher"]:
            errors.append(f"{p}.publisher missing")
        if not isinstance(d.get("trust_tier"), int) or not (0 <= d.get("trust_tier", -1) <= 3):
            errors.append(f"{p}.trust_tier must be int in 0..3")
        if not isinstance(d.get("t"), int):
            errors.append(f"{p}.t must be an int")
        text = d.get("text", "")
        if not isinstance(text, str):
            errors.append(f"{p}.text must be a string")
        else:
            n = _sentence_count(text)
            if n < 2 or n > 6:
                errors.append(f"{p}.text must have 2-6 sentences, got {n}")
        if not isinstance(d.get("facts"), list):
            errors.append(f"{p}.facts must be a list")
        else:
            for j, f in enumerate(d["facts"]):
                if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not f["name"]:
                    errors.append(f"{p}.facts[{j}] must have a name")
                if not _is_num(f.get("value")):
                    errors.append(f"{p}.facts[{j}].value not numeric")
                if not isinstance(f.get("unit"), str) or not f["unit"]:
                    errors.append(f"{p}.facts[{j}].unit missing")
        if not isinstance(d.get("content_hash"), str):
            errors.append(f"{p}.content_hash missing")
        elif isinstance(text, str) and d["content_hash"] != content_hash(text):
            errors.append(f"{p}.content_hash does not match text")
    return errors


def _check_notes(notes, where):
    errors = []
    if not isinstance(notes, list):
        return [f"{where} is not a list"]
    for i, n in enumerate(notes):
        p = f"{where}[{i}]"
        if not isinstance(n, dict):
            errors.append(f"{p} is not a dict")
            continue
        if not isinstance(n.get("id"), str) or not n["id"]:
            errors.append(f"{p}.id missing")
        if not isinstance(n.get("t"), int):
            errors.append(f"{p}.t must be an int")
        if not isinstance(n.get("text"), str) or not n["text"]:
            errors.append(f"{p}.text missing")
        if n.get("written_by") not in NOTE_WRITERS:
            errors.append(f"{p}.written_by invalid: {n.get('written_by')!r}")
        if not isinstance(n.get("signature_valid"), bool):
            errors.append(f"{p}.signature_valid must be bool")
        if n.get("written_by") == "owner_signed" and n.get("signature_valid") is not True:
            errors.append(f"{p} is owner_signed but signature_valid is not true")
        if not isinstance(n.get("cites"), list):
            errors.append(f"{p}.cites must be a list")
    return errors


def _check_theses(theses):
    errors = []
    if not isinstance(theses, list):
        return ["theses is not a list"]
    for i, th in enumerate(theses):
        p = f"theses[{i}]"
        if not isinstance(th, dict):
            errors.append(f"{p} is not a dict")
            continue
        if not isinstance(th.get("id"), str) or not th["id"]:
            errors.append(f"{p}.id missing")
        if not isinstance(th.get("statement"), str) or not th["statement"]:
            errors.append(f"{p}.statement missing")
        if th.get("sector") not in SECTORS:
            errors.append(f"{p}.sector invalid: {th.get('sector')!r}")
        if not isinstance(th.get("opened_t"), int):
            errors.append(f"{p}.opened_t must be an int")
        if not isinstance(th.get("evidence_docs"), list):
            errors.append(f"{p}.evidence_docs must be a list")
        if not isinstance(th.get("invalidation"), str):
            errors.append(f"{p}.invalidation must be a string")
        trig = th.get("invalidation_trigger")
        if trig is not None:
            if not isinstance(trig, dict) or not isinstance(trig.get("name"), str) or trig.get("op") not in OPS or not _is_num(trig.get("value")):
                errors.append(f"{p}.invalidation_trigger must be {{name, op, value}}")
        if th.get("status") not in THESIS_STATUSES:
            errors.append(f"{p}.status invalid: {th.get('status')!r}")
    return errors


def _check_book(book, instrument_sectors):
    errors = []
    if not isinstance(book, dict):
        return ["initial_book is not a dict"]
    for key in ("cash", "positions", "sectors"):
        if key not in book:
            errors.append(f"initial_book missing {key}")
    if errors:
        return errors
    if not _is_num(book["cash"]) or book["cash"] < 0:
        errors.append("initial_book.cash must be a non-negative number")
    if not isinstance(book["positions"], dict):
        errors.append("initial_book.positions must be a dict")
    else:
        for inst, v in book["positions"].items():
            if not isinstance(inst, str) or not inst:
                errors.append("initial_book.positions has an empty instrument key")
            if not _is_num(v) or v < 0:
                errors.append(f"initial_book.positions[{inst}] must be a non-negative number")
    if not isinstance(book["sectors"], dict):
        errors.append("initial_book.sectors must be a dict")
    else:
        missing_s = [s for s in SECTORS if s not in book["sectors"]]
        if missing_s:
            errors.append(f"initial_book.sectors missing sectors (give 0 explicitly): {', '.join(missing_s)}")
        for s, v in book["sectors"].items():
            if s not in SECTORS:
                errors.append(f"initial_book.sectors has unknown sector {s!r}")
            if not _is_num(v) or v < 0:
                errors.append(f"initial_book.sectors[{s}] must be a non-negative number")

    if not isinstance(instrument_sectors, dict):
        errors.append("instrument_sectors must be a dict")
        return errors
    for inst, sec in instrument_sectors.items():
        if not isinstance(inst, str) or not inst:
            errors.append("instrument_sectors has an empty instrument key")
        if sec not in SECTORS:
            errors.append(f"instrument_sectors[{inst!r}] has unknown sector {sec!r}")

    if isinstance(book.get("positions"), dict) and isinstance(book.get("sectors"), dict):
        for inst in book["positions"]:
            if inst not in instrument_sectors:
                errors.append(f"initial_book position {inst!r} has no instrument_sectors entry")
        if all(inst in instrument_sectors for inst in book["positions"]):
            derived = {s: 0.0 for s in SECTORS}
            for inst, v in book["positions"].items():
                if _is_num(v):
                    derived[instrument_sectors[inst]] += v
            for s in SECTORS:
                stated = book["sectors"].get(s, 0.0)
                if _is_num(stated) and abs(stated - derived[s]) > 0.011:
                    errors.append(
                        f"initial_book.sectors[{s}]={stated} does not equal the sum "
                        f"of its instrument positions {round(derived[s], 2)}")
    return errors


def _check_steps(steps):
    errors = []
    if not isinstance(steps, list):
        return ["steps is not a list"]
    for i, s in enumerate(steps):
        p = f"steps[{i}]"
        if not isinstance(s, dict):
            errors.append(f"{p} is not a dict")
            continue
        if "action" not in s or "pre_notes" not in s or "new_notes" not in s or "label" not in s:
            errors.append(f"{p} must have action, pre_notes, new_notes, label")
            continue
        errors += _check_action(s["action"], f"{p}.action")
        errors += _check_notes(s["pre_notes"], f"{p}.pre_notes")
        errors += _check_notes(s["new_notes"], f"{p}.new_notes")
        errors += _check_label(s["label"], f"{p}.label")
    return errors


def _check_action(a, p):
    errors = []
    if not isinstance(a, dict):
        return [f"{p} is not a dict"]
    if not isinstance(a.get("t"), int):
        errors.append(f"{p}.t must be an int")
    if a.get("sector") not in SECTORS:
        errors.append(f"{p}.sector invalid: {a.get('sector')!r}")
    if not isinstance(a.get("instrument"), str) or not a["instrument"]:
        errors.append(f"{p}.instrument missing")
    if a.get("side") not in SIDES:
        errors.append(f"{p}.side invalid: {a.get('side')!r}")
    if not _is_num(a.get("notional")) or a.get("notional", 0) <= 0:
        errors.append(f"{p}.notional must be positive")
    if not isinstance(a.get("thesis_id"), str) or not a["thesis_id"]:
        errors.append(f"{p}.thesis_id missing")
    if not isinstance(a.get("opens_thesis"), bool):
        errors.append(f"{p}.opens_thesis must be bool")
    if not isinstance(a.get("claims"), list):
        errors.append(f"{p}.claims must be a list")
    else:
        for j, c in enumerate(a["claims"]):
            errors += _check_claim(c, f"{p}.claims[{j}]")
    if not isinstance(a.get("cites_notes"), list):
        errors.append(f"{p}.cites_notes must be a list")
    rationale = a.get("rationale")
    if not isinstance(rationale, str) or not rationale:
        errors.append(f"{p}.rationale missing")
    else:
        n = _sentence_count(rationale)
        if n < 1 or n > 3:
            errors.append(f"{p}.rationale must have 1-3 sentences, got {n}")
    return errors


def _check_claim(c, p):
    errors = []
    if not isinstance(c, dict):
        return [f"{p} is not a dict"]
    if not isinstance(c.get("text"), str) or not c["text"]:
        errors.append(f"{p}.text missing")
    if c.get("value") is not None and not _is_num(c.get("value")):
        errors.append(f"{p}.value must be numeric or null")
    if c.get("unit") is not None and (not isinstance(c.get("unit"), str) or not c["unit"]):
        errors.append(f"{p}.unit must be a string or null")
    if c.get("source_doc") is not None and (not isinstance(c.get("source_doc"), str) or not c["source_doc"]):
        errors.append(f"{p}.source_doc must be a string or null")
    if c.get("quoted_span") is not None:
        if not isinstance(c.get("quoted_span"), str) or not c["quoted_span"]:
            errors.append(f"{p}.quoted_span must be a string or null")
        elif c.get("source_doc") is None:
            errors.append(f"{p}.quoted_span has no source_doc")
    return errors


def _check_label(lb, p):
    errors = []
    if not isinstance(lb, dict):
        return [f"{p} is not a dict"]
    if lb.get("y") not in (0, 1):
        errors.append(f"{p}.y must be 0 or 1")
    if not isinstance(lb.get("cause"), str) or not lb["cause"]:
        errors.append(f"{p}.cause missing")
    if not isinstance(lb.get("cause_refs"), list):
        errors.append(f"{p}.cause_refs must be a list")
    return errors


def _check_meta(meta):
    errors = []
    if not isinstance(meta, dict):
        return ["meta is not a dict"]
    for k in ("author", "family", "seed", "shifted"):
        if k not in meta:
            errors.append(f"meta.{k} missing")
    if not isinstance(meta.get("seed"), int):
        errors.append("meta.seed must be an int")
    if not isinstance(meta.get("shifted"), bool):
        errors.append("meta.shifted must be bool")
    return errors


def _available_notes(ep, step_index, t):
    """Note ids available to the action at ``step_index`` (time ``t``).

    Order inside a step: the step's ``pre_notes`` are written first and are
    available to the action; ``new_notes`` are written after the action and are
    *not* available to it. Notes from later steps are never available.
    """
    available = set()
    for n in ep["initial_notes"]:
        if n["t"] <= t:
            available.add(n["id"])
    for j in range(step_index + 1):
        for n in ep["steps"][j]["pre_notes"]:
            if n["t"] <= t:
                available.add(n["id"])
    for j in range(step_index):
        for n in ep["steps"][j]["new_notes"]:
            if n["t"] <= t:
                available.add(n["id"])
    return available


def _check_id_refs(ep, doc_ids, doc_t, note_ids, thesis_ids, thesis_t):
    errors = []
    doc_seen = set()
    for i, d in enumerate(ep["documents"]):
        if d["id"] in doc_seen:
            errors.append(f"duplicate document id {d['id']!r}")
        doc_seen.add(d["id"])
    all_ids = set()
    for n in ep["initial_notes"]:
        if n["id"] in all_ids:
            errors.append(f"duplicate note id {n['id']!r}")
        all_ids.add(n["id"])
    for s in ep["steps"]:
        for n in s["pre_notes"] + s["new_notes"]:
            if n["id"] in all_ids:
                errors.append(f"duplicate note id {n['id']!r}")
            all_ids.add(n["id"])
    for n in ep["initial_notes"] + [n for s in ep["steps"] for n in s["pre_notes"] + s["new_notes"]]:
        for c in n["cites"]:
            if c not in doc_ids:
                errors.append(f"note {n['id']} cites unknown document {c!r}")
            elif doc_t[c] > n["t"]:
                errors.append(f"note {n['id']} cites document {c!r} not yet available")
    th_ids = set()
    for th in ep["theses"]:
        if th["id"] in th_ids:
            errors.append(f"duplicate thesis id {th['id']!r}")
        th_ids.add(th["id"])
        for ev in th["evidence_docs"]:
            if ev not in doc_ids:
                errors.append(f"thesis {th['id']} evidence_doc {ev!r} does not resolve")
            elif doc_t[ev] > th["opened_t"]:
                errors.append(f"thesis {th['id']} evidence_doc {ev!r} not yet available at open")
    for i, s in enumerate(ep["steps"]):
        a = s["action"]
        if a["thesis_id"] not in thesis_ids:
            errors.append(f"steps[{i}] thesis_id {a['thesis_id']!r} does not resolve")
        elif thesis_t[a["thesis_id"]] > a["t"]:
            errors.append(f"steps[{i}] thesis_id {a['thesis_id']!r} opened after action")
        available = _available_notes(ep, i, a["t"])
        for cn in a["cites_notes"]:
            if cn not in note_ids:
                errors.append(f"steps[{i}] cites_notes {cn!r} does not resolve")
            elif cn not in available:
                errors.append(f"steps[{i}] cites_notes {cn!r} not yet available (same-step new note or later)")
        for j, c in enumerate(a["claims"]):
            if c.get("source_doc") is not None:
                if c["source_doc"] not in doc_ids:
                    errors.append(f"steps[{i}].claims[{j}] source_doc {c['source_doc']!r} does not resolve")
                elif doc_t[c["source_doc"]] > a["t"]:
                    errors.append(f"steps[{i}].claims[{j}] source_doc {c['source_doc']!r} not yet available")
        for r in s["label"]["cause_refs"]:
            if r in doc_ids:
                if doc_t[r] > a["t"]:
                    errors.append(f"steps[{i}].label.cause_refs {r!r} not yet available")
            elif r in note_ids:
                if r not in available:
                    errors.append(f"steps[{i}].label.cause_refs {r!r} not yet available (same-step new note or later)")
            else:
                errors.append(f"steps[{i}].label.cause_refs {r!r} does not resolve")
    return errors


def _check_instruments(ep):
    errors = []
    isec = ep["instrument_sectors"]
    allowed = set(ep["owner"]["allowed_instruments"])
    for i, s in enumerate(ep["steps"]):
        a = s["action"]
        inst = a["instrument"]
        sec = a["sector"]
        if inst not in isec:
            errors.append(f"steps[{i}] instrument {inst!r} has no instrument_sectors entry")
        elif isec[inst] != sec:
            errors.append(
                f"steps[{i}] instrument {inst!r} is in {isec[inst]!r} but action.sector is {sec!r}")
        if inst not in allowed:
            errors.append(f"steps[{i}] instrument {inst!r} is not in owner.allowed_instruments")
    return errors


def _check_spans(ep, doc_ids):
    errors = []
    text_by_id = {d["id"]: d["text"] for d in ep["documents"]}
    for i, s in enumerate(ep["steps"]):
        for j, c in enumerate(s["action"]["claims"]):
            span = c.get("quoted_span")
            src = c.get("source_doc")
            if span is None:
                continue
            if src is None or src not in text_by_id:
                continue
            if span not in text_by_id[src]:
                errors.append(f"steps[{i}].claims[{j}] quoted_span is not a substring of source text")
    return errors


def _check_labels(ep):
    """Enforce the documented cause/y convention.

    ``y = 0`` means the owner endorses the action and therefore must use
    ``cause = "clean"``; ``y = 1`` must name a real (or novel) failure cause.
    This makes a relabelled positive (for example changing a drift positive's
    ``y`` to 0 while leaving its cause) a validation error instead of a silent
    pass.
    """
    errors = []
    for i, s in enumerate(ep["steps"]):
        lb = s["label"]
        if lb["y"] == 0 and lb["cause"] != "clean":
            errors.append(
                f"steps[{i}] y=0 must have cause clean, got {lb['cause']!r}")
        if lb["y"] == 1 and lb["cause"] == "clean":
            errors.append(f"steps[{i}] y=1 with cause clean")
        if lb["cause"] == "binding_error" and not lb["cause_refs"]:
            errors.append(
                f"steps[{i}] binding_error must point at the claim or rationale "
                f"via at least one cause_ref")
    return errors


def _check_times(ep):
    errors = []
    prev = None
    for i, s in enumerate(ep["steps"]):
        t = s["action"]["t"]
        if prev is not None and t <= prev:
            errors.append(f"steps[{i}] action.t not strictly increasing")
        prev = t
        for n in s["pre_notes"]:
            if n["t"] > t:
                errors.append(f"steps[{i}] pre_note t after action t")
        for n in s["new_notes"]:
            if n["t"] < t:
                errors.append(f"steps[{i}] new_note t before action t")
    prev_d = None
    for d in ep["documents"]:
        if prev_d is not None and d["t"] < prev_d:
            errors.append(f"documents not monotone: {d['id']!r}")
        prev_d = d["t"]
    return errors


def _check_replay(ep):
    """Replay the book and check labels against the mandate.

    The book value is constant (no price moves); a buy moves cash into the
    instrument, a sell moves it back. Clean actions must leave the book inside
    every limit they touch; a drift label must be a buy that leaves its sector
    above ``max``.
    """
    errors = []
    book = ep["initial_book"]
    isec = ep["instrument_sectors"]
    owner = ep["owner"]
    bands = owner["sector_bands"]
    maxpos = owner["max_position_pct"]

    positions = {k: float(v) for k, v in book["positions"].items()}
    cash = float(book["cash"])
    value = cash + sum(positions.values())
    if value <= 0:
        return ["initial_book has non-positive total value"]

    def weight_of(sector, pos):
        return sum(v for i, v in pos.items() if isec.get(i) == sector) / value

    for s in SECTORS:
        b = bands[s]
        w = weight_of(s, positions)
        if b["max"] <= 0:
            if w > TOL:
                errors.append(f"initial_book holds a disallowed sector {s}")
            continue
        if w > b["max"] + TOL or w < b["min"] - TOL:
            errors.append(
                f"initial_book sector {s} weight {w:.6f} outside band "
                f"[{b['min']}, {b['max']}]")
    for inst, v in positions.items():
        if v / value > maxpos + TOL:
            errors.append(f"initial_book instrument {inst} weight {v / value:.6f} exceeds max_position_pct")

    for i, s in enumerate(ep["steps"]):
        a = s["action"]
        inst = a["instrument"]
        sec = a["sector"]
        n = float(a["notional"])
        if a["side"] == "buy":
            cash -= n
            positions[inst] = positions.get(inst, 0.0) + n
        else:
            cash += n
            positions[inst] = positions.get(inst, 0.0) - n
        if cash < -1e-6:
            errors.append(f"steps[{i}] replay drives cash negative")
        if positions[inst] < -1e-6:
            errors.append(f"steps[{i}] replay drives {inst} position negative")
        sec_w = weight_of(sec, positions)
        inst_w = positions.get(inst, 0.0) / value
        b = bands[sec]
        lb = s["label"]
        # Every negative action must leave the book inside the mandate,
        # whatever cause string it carries. This is gated on the label, not on
        # the cause, so substituting a novel cause cannot bypass the check.
        if lb["y"] == 0:
            if inst_w > maxpos + TOL:
                errors.append(
                    f"steps[{i}] y=0 but instrument weight {inst_w:.6f} "
                    f"exceeds max_position_pct")
            if a["side"] == "buy" and sec_w > b["max"] + TOL:
                errors.append(
                    f"steps[{i}] y=0 buy leaves {sec} weight {sec_w:.6f} "
                    f"above max {b['max']}")
            if a["side"] == "sell" and sec_w < b["min"] - TOL:
                errors.append(
                    f"steps[{i}] y=0 sell leaves {sec} weight {sec_w:.6f} "
                    f"below min {b['min']}")
        if lb["cause"] == "drift":
            if a["side"] != "buy":
                errors.append(f"steps[{i}] drift label on a non-buy")
            elif sec_w <= b["max"] + TOL:
                errors.append(
                    f"steps[{i}] drift label but {sec} weight {sec_w:.6f} is not above max {b['max']}")
    return errors


def _iter_jsonl(path):
    with open(path, "r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError as e:
                yield line_no, {"__json_error__": str(e)}


def validate_path(path):
    path = Path(path)
    total_errors = 0
    n_files = 0
    n_episodes = 0
    if path.is_dir():
        files = sorted(path.glob("*.jsonl"))
    else:
        files = [path]
    if not files:
        print(f"no jsonl files found under {path}")
        return 1
    for f in files:
        n_files += 1
        for line_no, ep in _iter_jsonl(f):
            n_episodes += 1
            if "__json_error__" in ep:
                print(f"{f}:{line_no}: JSON error: {ep['__json_error__']}")
                total_errors += 1
                continue
            errs = validate(ep)
            if errs:
                total_errors += len(errs)
                for e in errs:
                    print(f"{f}:{line_no}: {e}")
    print(f"validated {n_episodes} episodes across {n_files} file(s): {total_errors} error(s)")
    return 0 if total_errors == 0 else 1


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m og_s1.validate <dir-or-jsonl>")
        return 2
    return validate_path(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
