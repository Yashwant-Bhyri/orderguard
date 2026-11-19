"""Deterministic structural and provenance features for the System One world.

Each action is featurised from ``og_s1.schema.model_view_at(episode, i)`` only:
documents published by then, notes written before the action, theses opened by
then (without their final status), the earlier actions and the current action.
No label, ``meta`` value, rationale, claim prose, note prose or document prose is
inspected, except for the exact substring test that the schema requires for a
quoted span.

Every feature is oriented so that a larger value means more risk.
"""

from __future__ import annotations

import gc
import math
import time
from typing import Any

import numpy as np

from og_s1.schema import model_view_at

DRIFT = "drift"
UNSUPPORTED_CLAIM = "unsupported_claim"
MISQUOTE = "misquote"
POISONED_NOTE = "poisoned_note"
AUTHORITY_SPOOF = "authority_spoof"
STALE_THESIS = "stale_thesis"
EVIDENCE_QUALITY = "evidence_quality"

_UNITS: dict[str, tuple[str, float, str]] = {
    "%": ("percent", 1.0, "%"),
    "pct": ("percent", 1.0, "%"),
    "percent": ("percent", 1.0, "%"),
    "percentage": ("percent", 1.0, "%"),
    "bp": ("percent", 0.01, "bp"),
    "bps": ("percent", 0.01, "bp"),
    "basis_point": ("percent", 0.01, "bp"),
    "basis_points": ("percent", 0.01, "bp"),
    "$b": ("money", 1e9, "$B"),
    "$bn": ("money", 1e9, "$B"),
    "billion": ("money", 1e9, "$B"),
    "$m": ("money", 1e6, "$M"),
    "$mn": ("money", 1e6, "$M"),
    "million": ("money", 1e6, "$M"),
    "$k": ("money", 1e3, "$K"),
    "thousand": ("money", 1e3, "$K"),
    "$t": ("money", 1e12, "$T"),
    "trillion": ("money", 1e12, "$T"),
    "ratio": ("ratio", 1.0, "ratio"),
    "x": ("multiple", 1.0, "x"),
    "times": ("multiple", 1.0, "x"),
}


def _unit_info(unit: Any) -> tuple[str | None, float, str | None]:
    if unit is None:
        return (None, 1.0, None)
    key = str(unit).strip().lower()
    if key in _UNITS:
        return _UNITS[key]
    return ("unit:" + key, 1.0, key)


def _unit_dim(unit: Any) -> str | None:
    return _unit_info(unit)[0]


def _unit_scale(unit: Any) -> float:
    return _unit_info(unit)[1]


def _unit_key(unit: Any) -> str | None:
    return _unit_info(unit)[2]


def _to_base(value: float, unit: Any) -> float:
    return float(value) * _unit_scale(unit)


def _is_num(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def _rel_err(a: float, b: float) -> float:
    scale = max(abs(float(a)), abs(float(b)), 1e-12)
    return abs(float(a) - float(b)) / scale


def _finite(value: float) -> float:
    value = float(value)
    if math.isnan(value) or value < 0.0:
        return 0.0
    if math.isinf(value):
        return 1e6
    return value


def _op_holds(op: Any, value: float, threshold: float) -> bool:
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


def _band_excess(owner: dict[str, Any], sectors: dict[str, float], capital: float) -> tuple[float, int]:
    bands = owner.get("sector_bands") or {}
    worst = 0.0
    count = 0
    keys = set(sectors) | set(bands)
    for sector in keys:
        value = float(sectors.get(sector, 0.0))
        weight = value / capital if capital > 0 else 0.0
        band = bands.get(sector)
        if band is None:
            excess = max(0.0, weight)
        else:
            top = float(band.get("max", 0.0))
            bottom = float(band.get("min", 0.0))
            excess = max(0.0, weight - top) + max(0.0, bottom - weight)
        if excess > 1e-12:
            count += 1
        worst = max(worst, excess)
    return worst, count


def _out_of_band_total(owner: dict[str, Any], sectors: dict[str, float], capital: float) -> float:
    bands = owner.get("sector_bands") or {}
    total = 0.0
    keys = set(sectors) | set(bands)
    for sector in keys:
        weight = float(sectors.get(sector, 0.0)) / capital if capital > 0 else 0.0
        band = bands.get(sector)
        if band is None:
            total += max(0.0, weight)
        else:
            top = float(band.get("max", 0.0))
            bottom = float(band.get("min", 0.0))
            total += max(0.0, weight - top) + max(0.0, bottom - weight)
    return total


class _BookState:
    def __init__(self, view: dict[str, Any]) -> None:
        book = view.get("initial_book") or {}
        self.positions = {str(k): float(v) for k, v in (book.get("positions") or {}).items()}
        self.sector_values = {str(k): float(v) for k, v in (book.get("sectors") or {}).items()}
        self.cash = float(book.get("cash", 0.0) or 0.0)
        self.capital = self.cash + sum(self.positions.values())
        if self.capital <= 0.0:
            self.capital = 1.0
        self.turnover: dict[Any, float] = {}
        self.cusum = 0.0

    def apply(self, action: dict[str, Any]) -> None:
        notional = float(action.get("notional", 0.0) or 0.0)
        sign = 1.0 if action.get("side") == "buy" else -1.0
        instrument = action.get("instrument")
        sector = action.get("sector")
        if instrument is not None:
            self.positions[str(instrument)] = self.positions.get(str(instrument), 0.0) + sign * notional
        if sector is not None:
            self.sector_values[str(sector)] = self.sector_values.get(str(sector), 0.0) + sign * notional
        self.cash -= sign * notional
        t = action.get("t")
        self.turnover[t] = self.turnover.get(t, 0.0) + notional


def _book_features(
    owner: dict[str, Any],
    action: dict[str, Any],
    state: _BookState,
) -> dict[str, float]:
    capital = state.capital
    before_sectors = state.sector_values
    after_sectors = dict(before_sectors)
    sector = str(action.get("sector"))
    notional = float(action.get("notional", 0.0) or 0.0)
    sign = 1.0 if action.get("side") == "buy" else -1.0
    after_sectors[sector] = after_sectors.get(sector, 0.0) + sign * notional

    oob_before = _out_of_band_total(owner, before_sectors, capital)
    oob_after = _out_of_band_total(owner, after_sectors, capital)
    oob_increase = max(0.0, oob_after - oob_before)
    worst_after, sectors_out = _band_excess(owner, after_sectors, capital)

    band = (owner.get("sector_bands") or {}).get(sector) or {}
    top = float(band.get("max", 0.0))
    traded_weight = float(after_sectors.get(sector, 0.0)) / capital
    traded_excess = max(0.0, traded_weight - top)

    instrument = str(action.get("instrument"))
    position_after = state.positions.get(instrument, 0.0) + sign * notional
    max_pos = float(owner.get("max_position_pct", 0.0) or 0.0)
    if max_pos > 0.0:
        position_ratio = position_after / (max_pos * capital)
    else:
        position_ratio = 1e6 if position_after > 0.0 else 0.0
    position_excess = max(0.0, position_ratio - 1.0)

    max_turnover = float(owner.get("max_daily_turnover_pct", 0.0) or 0.0)
    t = action.get("t")
    day_turnover = state.turnover.get(t, 0.0) + notional
    if max_turnover > 0.0:
        turnover_ratio = (day_turnover / capital) / max_turnover
    else:
        turnover_ratio = 1e6 if day_turnover > 0.0 else 0.0

    out_of_band_buy = (
        action.get("side") == "buy" and traded_weight > top + 1e-12
    )
    cusum = max(0.0, state.cusum + (1.0 if out_of_band_buy else 0.0) - 0.5)

    return {
        "drift_out_of_band_weight": _finite(oob_after),
        "drift_out_of_band_increase": _finite(oob_increase),
        "drift_cusum_out_of_band_buys": _finite(cusum),
        "drift_daily_turnover_ratio": _finite(turnover_ratio),
        "drift_position_ratio": _finite(position_ratio),
        "drift_position_excess": _finite(position_excess),
        "drift_sector_excess_after": _finite(traded_excess),
        "drift_sectors_out_of_band": _finite(sectors_out),
        "drift_worst_sector_excess": _finite(worst_after),
        "_cusum_next": _finite(cusum),
    }


def _claim_features(action: dict[str, Any], docs_by_id: dict[str, dict[str, Any]]) -> dict[str, float]:
    claims = action.get("claims") or []
    n = len(claims)
    unsourced = 0
    source_missing = 0
    span_bad = 0
    unit_absent = 0
    value_absent = 0
    rel_errors: list[float] = []
    scale_errors: list[float] = []
    unit_swap = 0.0

    for claim in claims:
        source = claim.get("source_doc")
        span = claim.get("quoted_span")
        raw_value = claim.get("value")
        unit = claim.get("unit")
        numeric = _is_num(raw_value)

        if source is None:
            unsourced += 1
            continue
        doc = docs_by_id.get(source)
        if doc is None:
            source_missing += 1
            continue

        text = doc.get("text") or ""
        facts = doc.get("facts") or []
        span_missing = span is None
        span_blank = (not span_missing) and not (
            isinstance(span, str) and span.strip() != ""
        )
        span_valid = (
            (not span_missing) and (not span_blank) and span in text
        )
        if not span_valid:
            span_bad += 1

        claim_dim = None
        claim_key = None
        same_unit: list[dict[str, Any]] = []
        same_dim: list[dict[str, Any]] = []
        if numeric or unit is not None:
            claim_dim = _unit_dim(unit)
            claim_key = _unit_key(unit)
            same_unit = [
                f for f in facts
                if _unit_key(f.get("unit")) == claim_key and _is_num(f.get("value"))
            ]
            same_dim = [
                f for f in facts
                if claim_dim is not None
                and _unit_dim(f.get("unit")) == claim_dim
                and _is_num(f.get("value"))
            ]
            if not same_unit:
                unit_absent += 1

        if not numeric:
            continue
        value = float(raw_value)
        if span_valid:
            candidates = same_unit if same_unit else same_dim
            if candidates:
                claim_base = _to_base(value, unit)
                scored = [
                    (abs(_to_base(float(f["value"]), f.get("unit")) - claim_base), f)
                    for f in candidates
                ]
                _, nearest = min(scored, key=lambda pair: pair[0])
                rel = _rel_err(claim_base, _to_base(float(nearest["value"]), nearest.get("unit")))
                rel_errors.append(rel)
                if claim_key != _unit_key(nearest.get("unit")):
                    scale_errors.append(rel)
                    raw_rel = _rel_err(value, float(nearest["value"]))
                    if raw_rel <= 1e-6:
                        unit_swap = 1.0
        elif span_missing:
            if same_unit:
                nearest = min(
                    same_unit,
                    key=lambda f: abs(float(f["value"]) - value),
                )
                if _rel_err(value, float(nearest["value"])) > 1e-9:
                    value_absent += 1
            else:
                value_absent += 1

    if n == 0:
        return {
            "claim_unsourced_share": 0.0,
            "claim_source_unavailable_share": 0.0,
            "claim_span_not_in_source_share": 0.0,
            "claim_unit_absent_share": 0.0,
            "claim_value_absent_share": 0.0,
            "claim_support_failure_share": 0.0,
            "value_relative_error": 0.0,
            "value_unit_scale_error": 0.0,
            "value_unit_swap": 0.0,
            "value_fidelity_score": 0.0,
        }

    unsourced_share = unsourced / n
    source_missing_share = source_missing / n
    span_bad_share = span_bad / n
    unit_absent_share = unit_absent / n
    value_absent_share = value_absent / n
    support = max(
        unsourced_share,
        source_missing_share,
        span_bad_share,
        unit_absent_share,
        value_absent_share,
    )
    rel_error = max(rel_errors) if rel_errors else 0.0
    scale_error = max(scale_errors) if scale_errors else 0.0
    fidelity = max(rel_error, scale_error, unit_swap)
    return {
        "claim_unsourced_share": _finite(unsourced_share),
        "claim_source_unavailable_share": _finite(source_missing_share),
        "claim_span_not_in_source_share": _finite(span_bad_share),
        "claim_unit_absent_share": _finite(unit_absent_share),
        "claim_value_absent_share": _finite(value_absent_share),
        "claim_support_failure_share": _finite(support),
        "value_relative_error": _finite(rel_error),
        "value_unit_scale_error": _finite(scale_error),
        "value_unit_swap": _finite(unit_swap),
        "value_fidelity_score": _finite(fidelity),
    }


def _note_features(
    action: dict[str, Any],
    notes_by_id: dict[str, dict[str, Any]],
    docs_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    cited = [str(x) for x in (action.get("cites_notes") or [])]
    n = len(cited)
    if n == 0:
        return {
            "note_external_tool_unsourced_share": 0.0,
            "note_unsigned_nonagent_share": 0.0,
            "note_missing_from_view_share": 0.0,
            "note_low_trust_citation_share": 0.0,
            "note_provenance_score": 0.0,
        }

    external_tool_unsourced = 0
    unsigned_nonagent = 0
    missing = 0
    low_trust_citation = 0
    for note_id in cited:
        note = notes_by_id.get(note_id)
        if note is None:
            missing += 1
            continue
        writer = note.get("written_by")
        signed = bool(note.get("signature_valid"))
        note_cites = [str(x) for x in (note.get("cites") or [])]
        tiers = []
        for doc_id in note_cites:
            doc = docs_by_id.get(doc_id)
            tiers.append(int(doc.get("trust_tier", 0)) if doc is not None else 0)
        if writer in ("external", "tool") and (not note_cites or any(t == 0 for t in tiers)):
            external_tool_unsourced += 1
        if not signed and writer != "agent":
            unsigned_nonagent += 1
        if note_cites and any(t == 0 for t in tiers):
            low_trust_citation += 1

    ext_share = external_tool_unsourced / n
    unsigned_share = unsigned_nonagent / n
    missing_share = missing / n
    low_share = low_trust_citation / n
    return {
        "note_external_tool_unsourced_share": _finite(ext_share),
        "note_unsigned_nonagent_share": _finite(unsigned_share),
        "note_missing_from_view_share": _finite(missing_share),
        "note_low_trust_citation_share": _finite(low_share),
        "note_provenance_score": _finite(max(ext_share, unsigned_share, missing_share)),
    }


def _authority_features(
    owner: dict[str, Any],
    action: dict[str, Any],
    after_positions: dict[str, float],
    after_sectors: dict[str, float],
    capital: float,
    notes_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    sector = str(action.get("sector"))
    side = action.get("side")
    weight = float(after_sectors.get(sector, 0.0)) / capital if capital > 0 else 0.0
    band = (owner.get("sector_bands") or {}).get(sector)
    if band is None:
        action_band_excess = max(0.0, weight)
    else:
        top = float(band.get("max", 0.0))
        bottom = float(band.get("min", 0.0))
        if side == "buy":
            action_band_excess = max(0.0, weight - top)
        else:
            action_band_excess = max(0.0, bottom - weight)

    instrument = str(action.get("instrument"))
    position_after = float(after_positions.get(instrument, 0.0))
    max_pos = float(owner.get("max_position_pct", 0.0) or 0.0)
    if side != "buy":
        position_excess = 0.0
    elif max_pos > 0.0:
        position_excess = max(0.0, position_after / (max_pos * capital) - 1.0)
    else:
        position_excess = 1e6 if position_after > 0.0 else 0.0

    allowed = owner.get("allowed_instruments")
    if allowed is None:
        instrument_not_allowed = 0.0
    else:
        instrument_not_allowed = 0.0 if instrument in set(map(str, allowed)) else 1.0

    permission_excess = max(action_band_excess, position_excess, instrument_not_allowed)
    unsigned_note = 0.0
    for note_id in action.get("cites_notes") or []:
        note = notes_by_id.get(str(note_id))
        if note is None:
            unsigned_note = 1.0
            break
        if not bool(note.get("signature_valid")):
            unsigned_note = 1.0
            break

    breach = 1.0 if permission_excess > 1e-12 else 0.0
    band_breach = 1.0 if action_band_excess > 1e-12 else 0.0
    return {
        "auth_unsigned_and_excess": _finite(unsigned_note * breach),
        "auth_unsigned_and_band_breach": _finite(unsigned_note * band_breach),
        "auth_permission_excess": _finite(permission_excess),
        "auth_unsigned_note": _finite(unsigned_note),
        "auth_instrument_not_allowed": _finite(instrument_not_allowed),
        "auth_band_breach_after": _finite(band_breach),
    }


def _thesis_features(
    view: dict[str, Any],
    action: dict[str, Any],
    docs_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    thesis_id = action.get("thesis_id")
    thesis = None
    for candidate in view.get("theses") or []:
        if candidate.get("id") == thesis_id:
            thesis = candidate
            break
    action_t = float(action.get("t", 0) or 0)
    if thesis is None:
        return {
            "stale_days_since_newest_evidence": 0.0,
            "stale_days_since_opened": 0.0,
            "stale_invalidation_fired": 0.0,
            "stale_invalidation_fired_high_trust": 0.0,
            "stale_invalidated_buy": 0.0,
            "stale_trigger_age": 0.0,
            "stale_evidence_trust_risk": 0.0,
        }

    opened_t = float(thesis.get("opened_t", action_t) or 0.0)
    evidence_ids = [str(x) for x in (thesis.get("evidence_docs") or [])]
    evidence_docs = [docs_by_id[i] for i in evidence_ids if i in docs_by_id]
    evidence_times = [float(d.get("t", opened_t) or 0.0) for d in evidence_docs]
    newest_evidence_t = max(evidence_times) if evidence_times else opened_t
    days_since_newest = max(0.0, action_t - newest_evidence_t)
    days_since_opened = max(0.0, action_t - opened_t)

    trigger = thesis.get("invalidation_trigger")
    fired = False
    fired_high_trust = False
    fire_times: list[float] = []
    if isinstance(trigger, dict):
        name = trigger.get("name")
        op = trigger.get("op")
        threshold = trigger.get("value")
        if name is not None and _is_num(threshold):
            for doc in docs_by_id.values():
                doc_t = float(doc.get("t", 0) or 0.0)
                if doc_t <= opened_t or doc_t > action_t:
                    continue
                for fact in doc.get("facts") or []:
                    if fact.get("name") == name and _is_num(fact.get("value")):
                        fact_value, limit = float(fact.get("value")), float(threshold)
                        t_unit = trigger.get("unit")              # optional; the schema's trigger has no unit (lead fix)
                        if t_unit is not None and fact.get("unit") is not None:
                            if _unit_dim(t_unit) != _unit_dim(fact.get("unit")):
                                continue                          # same name, different dimension: never fire
                            fact_value, limit = _to_base(fact_value, fact.get("unit")), _to_base(limit, t_unit)
                        if _op_holds(op, fact_value, limit):
                            fired = True
                            fire_times.append(doc_t)
                            if int(doc.get("trust_tier", 0) or 0) >= 2:
                                fired_high_trust = True
                            break

    trigger_age = action_t - max(fire_times) if fire_times else 0.0
    if evidence_docs:
        mean_trust = sum(float(d.get("trust_tier", 0) or 0.0) for d in evidence_docs) / len(evidence_docs)
        trust_risk = max(0.0, 3.0 - mean_trust)
    else:
        trust_risk = 0.0

    return {
        "stale_days_since_newest_evidence": _finite(days_since_newest),
        "stale_days_since_opened": _finite(days_since_opened),
        "stale_invalidation_fired": 1.0 if fired else 0.0,
        "stale_invalidation_fired_high_trust": 1.0 if fired_high_trust else 0.0,
        "stale_invalidated_buy": 1.0 if fired and action.get("side") == "buy" else 0.0,
        "stale_trigger_age": _finite(trigger_age),
        "stale_evidence_trust_risk": _finite(trust_risk),
    }


def _evidence_features(
    action: dict[str, Any],
    view: dict[str, Any],
    docs_by_id: dict[str, dict[str, Any]],
    notes_by_id: dict[str, dict[str, Any]],
) -> dict[str, float]:
    cited_ids: set[str] = set()
    for claim in action.get("claims") or []:
        source = claim.get("source_doc")
        if source is not None:
            cited_ids.add(str(source))
    for note_id in action.get("cites_notes") or []:
        note = notes_by_id.get(str(note_id))
        if note is not None:
            for doc_id in note.get("cites") or []:
                cited_ids.add(str(doc_id))
    for thesis in view.get("theses") or []:
        if thesis.get("id") == action.get("thesis_id"):
            for doc_id in thesis.get("evidence_docs") or []:
                cited_ids.add(str(doc_id))
            break

    docs = [docs_by_id[i] for i in cited_ids if i in docs_by_id]
    if not docs:
        return {
            "evidence_mean_trust_risk": 0.0,
            "evidence_social_share": 0.0,
            "evidence_tool_output_share": 0.0,
            "evidence_low_trust_share": 0.0,
        }
    n = len(docs)
    mean_trust = sum(float(d.get("trust_tier", 0) or 0.0) for d in docs) / n
    social = sum(1 for d in docs if d.get("kind") == "social") / n
    tool = sum(1 for d in docs if d.get("kind") == "tool_output") / n
    low = sum(1 for d in docs if int(d.get("trust_tier", 0) or 0) <= 1) / n
    return {
        "evidence_mean_trust_risk": _finite(3.0 - mean_trust),
        "evidence_social_share": _finite(social),
        "evidence_tool_output_share": _finite(tool),
        "evidence_low_trust_share": _finite(low),
    }


FEATURE_NAMES: list[str] = [
    "drift_out_of_band_weight",
    "drift_out_of_band_increase",
    "drift_cusum_out_of_band_buys",
    "drift_daily_turnover_ratio",
    "drift_position_ratio",
    "drift_position_excess",
    "drift_sector_excess_after",
    "drift_sectors_out_of_band",
    "drift_worst_sector_excess",
    "claim_unsourced_share",
    "claim_source_unavailable_share",
    "claim_span_not_in_source_share",
    "claim_unit_absent_share",
    "claim_value_absent_share",
    "claim_support_failure_share",
    "value_relative_error",
    "value_unit_scale_error",
    "value_unit_swap",
    "value_fidelity_score",
    "note_external_tool_unsourced_share",
    "note_unsigned_nonagent_share",
    "note_missing_from_view_share",
    "note_low_trust_citation_share",
    "note_provenance_score",
    "auth_unsigned_and_excess",
    "auth_unsigned_and_band_breach",
    "auth_permission_excess",
    "auth_unsigned_note",
    "auth_instrument_not_allowed",
    "auth_band_breach_after",
    "stale_days_since_newest_evidence",
    "stale_days_since_opened",
    "stale_invalidation_fired",
    "stale_invalidation_fired_high_trust",
    "stale_invalidated_buy",
    "stale_trigger_age",
    "stale_evidence_trust_risk",
    "evidence_mean_trust_risk",
    "evidence_social_share",
    "evidence_tool_output_share",
    "evidence_low_trust_share",
]

GROUPS: dict[str, str] = {}
for _name in FEATURE_NAMES:
    if _name.startswith("drift_"):
        GROUPS[_name] = DRIFT
    elif _name.startswith("claim_"):
        GROUPS[_name] = UNSUPPORTED_CLAIM
    elif _name.startswith("value_"):
        GROUPS[_name] = MISQUOTE
    elif _name.startswith("note_"):
        GROUPS[_name] = POISONED_NOTE
    elif _name.startswith("auth_"):
        GROUPS[_name] = AUTHORITY_SPOOF
    elif _name.startswith("stale_"):
        GROUPS[_name] = STALE_THESIS
    elif _name.startswith("evidence_"):
        GROUPS[_name] = EVIDENCE_QUALITY
    else:
        raise RuntimeError("unmapped feature " + _name)


def _row_features(
    view: dict[str, Any],
    state: _BookState,
) -> list[float]:
    owner = view.get("owner") or {}
    action = view.get("action") or {}
    docs_by_id = {str(d.get("id")): d for d in view.get("documents") or []}
    notes_by_id = {str(n.get("id")): n for n in view.get("notes") or []}

    book = _book_features(owner, action, state)
    next_cusum = book.pop("_cusum_next")

    after_positions = dict(state.positions)
    after_sectors = dict(state.sector_values)
    notional = float(action.get("notional", 0.0) or 0.0)
    sign = 1.0 if action.get("side") == "buy" else -1.0
    instrument = str(action.get("instrument"))
    sector = str(action.get("sector"))
    after_positions[instrument] = after_positions.get(instrument, 0.0) + sign * notional
    after_sectors[sector] = after_sectors.get(sector, 0.0) + sign * notional

    claims = _claim_features(action, docs_by_id)
    notes = _note_features(action, notes_by_id, docs_by_id)
    authority = _authority_features(
        owner, action, after_positions, after_sectors, state.capital, notes_by_id
    )
    thesis = _thesis_features(view, action, docs_by_id)
    evidence = _evidence_features(action, view, docs_by_id, notes_by_id)

    combined: dict[str, float] = {}
    combined.update(book)
    combined.update(claims)
    combined.update(notes)
    combined.update(authority)
    combined.update(thesis)
    combined.update(evidence)

    state.cusum = next_cusum
    state.apply(action)
    return [float(combined[name]) for name in FEATURE_NAMES]


def featurize(
    episode: Any,
    *,
    timings: list[float] | None = None,
) -> tuple[np.ndarray, list[str], dict[str, str]]:
    """Return ``(X, names, groups)`` for every action in the episode.

    ``episode`` may be an ``Episode`` or its dict form.  Each row is computed
    from ``model_view_at(episode, i)``; no future document, note, thesis status,
    label or ``meta`` value is read.  When ``timings`` is supplied, the wall
    clock for each action's feature computation is appended to it.
    """
    if hasattr(episode, "steps"):
        n_actions = len(episode.steps)  # type: ignore[union-attr]
    else:
        n_actions = len(episode.get("steps") or [])
    rows: list[list[float]] = []
    state: _BookState | None = None

    gc_was_enabled = gc.isenabled()
    if gc_was_enabled and n_actions > 100:
        gc.disable()
    try:
        for i in range(n_actions):
            started = time.perf_counter() if timings is not None else 0.0
            view = model_view_at(episode, i)
            if state is None:
                state = _BookState(view)
            rows.append(_row_features(view, state))
            if timings is not None:
                timings.append(time.perf_counter() - started)
    finally:
        if gc_was_enabled:
            gc.enable()

    if not rows:
        X = np.zeros((0, len(FEATURE_NAMES)), dtype=float)
    else:
        X = np.asarray(rows, dtype=float)
        if not np.all(np.isfinite(X)):
            X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=0.0)
    return X, list(FEATURE_NAMES), dict(GROUPS)


def auroc(y: Any, scores: Any) -> float:
    """Rank-based AUROC with tie-averaged ranks, higher score means class 1."""
    y_arr = np.asarray(y, dtype=float).ravel()
    s_arr = np.asarray(scores, dtype=float).ravel()
    if y_arr.size == 0 or y_arr.size != s_arr.size:
        return float("nan")
    pos = y_arr == 1.0
    neg = y_arr == 0.0
    n_pos = int(pos.sum())
    n_neg = int(neg.sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    order = np.argsort(s_arr, kind="mergesort")
    sorted_scores = s_arr[order]
    ranks = np.empty(s_arr.size, dtype=float)
    i = 0
    while i < sorted_scores.size:
        j = i + 1
        while j < sorted_scores.size and sorted_scores[j] == sorted_scores[i]:
            j += 1
        average_rank = 0.5 * ((i + 1) + j)
        ranks[order[i:j]] = average_rank
        i = j

    rank_sum = float(ranks[pos].sum())
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
