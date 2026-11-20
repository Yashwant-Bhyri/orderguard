"""Core mechanical world: mandate, book, documents, notes, theses, steps."""
from __future__ import annotations

import hashlib
import math
import random

from textlib import (COMPANY, INSTRUMENTS, SECTORS, UNITS, fmt, kind_meta,
                     make_doc)

BANDS = {
    "growth": {
        "tech": {"min": 0.12, "max": 0.42},
        "consumer": {"min": 0.05, "max": 0.17},
        "healthcare": {"min": 0.05, "max": 0.17},
        "staples": {"min": 0.02, "max": 0.09},
        "financials": {"min": 0.05, "max": 0.15},
        "energy": {"min": 0.02, "max": 0.09},
        "index": {"min": 0.10, "max": 0.30},
    },
    "balanced": {
        "tech": {"min": 0.08, "max": 0.26},
        "consumer": {"min": 0.07, "max": 0.19},
        "healthcare": {"min": 0.07, "max": 0.19},
        "staples": {"min": 0.04, "max": 0.13},
        "financials": {"min": 0.07, "max": 0.19},
        "energy": {"min": 0.03, "max": 0.11},
        "index": {"min": 0.12, "max": 0.32},
    },
    "income": {
        "tech": {"min": 0.04, "max": 0.16},
        "consumer": {"min": 0.06, "max": 0.18},
        "healthcare": {"min": 0.06, "max": 0.18},
        "staples": {"min": 0.10, "max": 0.24},
        "financials": {"min": 0.10, "max": 0.24},
        "energy": {"min": 0.05, "max": 0.14},
        "index": {"min": 0.12, "max": 0.32},
    },
    "capital_preservation": {
        "tech": {"min": 0.02, "max": 0.10},
        "consumer": {"min": 0.04, "max": 0.14},
        "healthcare": {"min": 0.05, "max": 0.14},
        "staples": {"min": 0.08, "max": 0.22},
        "financials": {"min": 0.06, "max": 0.18},
        "energy": {"min": 0.02, "max": 0.09},
        "index": {"min": 0.22, "max": 0.44},
    },
}

PURPOSES = tuple(BANDS)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def allocate(rng, bands, total, pin=None, pin_value=None):
    """Weights inside every band summing to ``total``, optionally pinning one."""
    w = {s: bands[s]["min"] for s in SECTORS}
    if pin is not None and pin_value is not None:
        w[pin] = min(max(pin_value, bands[pin]["min"]), bands[pin]["max"])
    remaining = total - sum(w.values())
    if remaining < 0:
        raise ValueError("bands cannot reach target total")
    caps = {s: bands[s]["max"] - w[s] for s in SECTORS}
    guard = 0
    while remaining > 1e-9 and guard < 80:
        guard += 1
        avail = [s for s in SECTORS if caps[s] > 1e-9]
        if not avail:
            break
        rng.shuffle(avail)
        moved = False
        for s in avail:
            if remaining <= 1e-9:
                break
            take = min(remaining, caps[s] * rng.uniform(0.25, 0.95))
            if take <= 1e-9:
                continue
            w[s] += take
            caps[s] -= take
            remaining -= take
            moved = True
        if not moved:
            s = max(avail, key=lambda x: caps[x])
            take = min(remaining, caps[s])
            w[s] += take
            caps[s] -= take
            remaining -= take
    return w


def split_sector(rng, sector, amount, value, maxpos):
    insts = INSTRUMENTS[sector]
    n = min(len(insts), max(2, int(math.ceil(amount / (0.072 * value)))))
    chosen = rng.sample(insts, n)
    parts = [amount / n * rng.uniform(0.72, 1.28) for _ in range(n)]
    scale = amount / sum(parts)
    parts = [p * scale for p in parts]
    cap = maxpos * value * 0.92
    for _ in range(12):
        excess = sum(max(0.0, p - cap) for p in parts)
        if excess < 1e-6:
            break
        parts = [min(p, cap) for p in parts]
        room = [i for i, p in enumerate(parts) if p < cap - 1e-9]
        if not room:
            break
        for i in room:
            parts[i] += excess / len(room)
    out = {}
    for inst, p in zip(chosen, parts):
        out[inst] = round(p, 2)
    return out


class World:
    def __init__(self, rng, purpose=None, pin=None, pin_value=None,
                 total_w=None, maxpos=None, family="clean", shifted=False):
        self.rng = rng
        self.family = family
        self.shifted = shifted
        self.purpose = purpose or rng.choice(PURPOSES)
        self.value = rng.choice([420e6, 510e6, 660e6, 780e6, 915e6, 1040e6])
        if shifted:
            self.value *= rng.uniform(1.1, 1.4)
        self.maxpos = maxpos or round(rng.uniform(0.085, 0.105), 3)
        self.bands = BANDS[self.purpose]
        if total_w is None:
            total_w = rng.uniform(0.905, 0.965)
        if pin is not None:
            total_w = max(total_w, pin_value + sum(
                self.bands[s]["min"] for s in SECTORS if s != pin) + 0.01)
        w = allocate(rng, self.bands, total_w, pin, pin_value)
        self.positions = {}
        for sector in SECTORS:
            if w[sector] <= 1e-9:
                continue
            self.positions.update(split_sector(
                rng, sector, w[sector] * self.value, self.value, self.maxpos))
        self.cash = self.value - sum(self.positions.values())
        self.instrument_sectors = {}
        for sector in SECTORS:
            for inst in INSTRUMENTS[sector]:
                self.instrument_sectors[inst] = sector
        self.documents = []
        self.initial_notes = []
        self.theses = []
        self.steps = []
        self.spans = {}
        self.factmap = {}
        self._d = 0
        self._n = 0
        self._th = 0
        key = "mandate-key-" + "".join(rng.choice("0123456789abcdef") for _ in range(8))
        self.owner = {
            "purpose": self.purpose,
            "sector_bands": {s: dict(self.bands[s]) for s in SECTORS},
            "max_position_pct": self.maxpos,
            "max_daily_turnover_pct": round(rng.uniform(0.22, 0.45), 3),
            "allowed_instruments": [i for s in SECTORS for i in INSTRUMENTS[s]],
            "signing_key_id": key,
        }
        self.initial_book = self.book()

    # -- book -------------------------------------------------------------
    def book(self):
        positions = {k: round(v, 2) for k, v in self.positions.items() if v > 1e-9}
        sectors = {s: 0.0 for s in SECTORS}
        for inst, v in positions.items():
            sectors[self.instrument_sectors[inst]] += v
        sectors = {s: round(v, 2) for s, v in sectors.items()}
        return {"cash": round(self.cash, 2), "positions": positions, "sectors": sectors}

    def sector_weight(self, sector):
        return sum(v for i, v in self.positions.items()
                   if self.instrument_sectors.get(i) == sector) / self.value

    def inst_weight(self, inst):
        return self.positions.get(inst, 0.0) / self.value

    def apply(self, inst, side, notional):
        n = float(notional)
        if side == "buy":
            if n > self.cash + 1e-6:
                raise ValueError("buy exceeds cash")
            self.cash -= n
            self.positions[inst] = self.positions.get(inst, 0.0) + n
        else:
            if n > self.positions.get(inst, 0.0) + 1e-6:
                raise ValueError("sell exceeds position")
            self.cash += n
            self.positions[inst] = self.positions.get(inst, 0.0) - n

    # -- entities ---------------------------------------------------------
    def add_doc(self, kind, sector, instrument, t, metrics=None):
        self._d += 1
        doc_id = f"D{self._d}"
        company = COMPANY[instrument]
        publisher, tier, text, facts, spans = make_doc(
            self.rng, kind, sector, company, metrics)
        self.documents.append({
            "id": doc_id, "kind": kind, "publisher": publisher,
            "trust_tier": tier, "t": int(t), "text": text,
            "facts": facts, "content_hash": sha(text),
        })
        self.spans[doc_id] = spans
        self.factmap[doc_id] = {f["name"]: (f["value"], f["unit"]) for f in facts}
        return doc_id

    def add_custom_doc(self, kind, t, text, facts, spans):
        self._d += 1
        doc_id = f"D{self._d}"
        publisher, tier = kind_meta(self.rng, kind)
        self.documents.append({
            "id": doc_id, "kind": kind, "publisher": publisher,
            "trust_tier": tier, "t": int(t), "text": text,
            "facts": facts, "content_hash": sha(text),
        })
        self.spans[doc_id] = spans
        self.factmap[doc_id] = {f["name"]: (f["value"], f["unit"]) for f in facts}
        return doc_id

    def fact(self, doc_id, name):
        return self.factmap[doc_id][name]

    def span(self, doc_id, name):
        return self.spans[doc_id][name]

    def note(self, t, text, written_by="agent", signature_valid=False, cites=None):
        self._n += 1
        return {"id": f"N{self._n}", "t": int(t), "text": text,
                "written_by": written_by,
                "signature_valid": bool(signature_valid),
                "cites": list(cites or [])}

    def thesis(self, statement, sector, opened_t, evidence_docs, invalidation,
               trigger=None, status="active"):
        self._th += 1
        th = {"id": f"T{self._th}", "statement": statement, "sector": sector,
              "opened_t": int(opened_t), "evidence_docs": list(evidence_docs),
              "invalidation": invalidation, "invalidation_trigger": trigger,
              "status": status}
        self.theses.append(th)
        return th["id"]

    def claim(self, text, value=None, unit=None, source=None, span=None):
        return {"text": text, "value": value, "unit": unit,
                "source_doc": source, "quoted_span": span}

    def exact(self, doc_id, metric, text=None):
        v, u = self.fact(doc_id, metric)
        sp = self.span(doc_id, metric)
        if text is None:
            text = f"{metric.replace('_', ' ')} of {fmt(v)}{u} is the figure we are underwriting."
        return self.claim(text, v, u, doc_id, sp)

    def add_step(self, t, inst, side, notional, thesis_id, opens_thesis,
                 claims, cites_notes, rationale, y=0, cause="clean",
                 cause_refs=None, pre_notes=None, new_notes=None):
        sector = self.instrument_sectors[inst]
        self.apply(inst, side, notional)
        action = {
            "t": int(t), "sector": sector, "instrument": inst, "side": side,
            "notional": round(float(notional), 2), "thesis_id": thesis_id,
            "opens_thesis": bool(opens_thesis),
            "claims": list(claims), "cites_notes": list(cites_notes),
            "rationale": rationale,
        }
        self.steps.append({
            "action": action,
            "pre_notes": list(pre_notes or []),
            "new_notes": list(new_notes or []),
            "label": {"y": int(y), "cause": cause,
                      "cause_refs": list(cause_refs or [])},
        })
        return action

    def episode(self, author):
        return {
            "owner": self.owner,
            "documents": self.documents,
            "initial_notes": self.initial_notes,
            "theses": self.theses,
            "initial_book": self.initial_book,
            "instrument_sectors": self.instrument_sectors,
            "steps": self.steps,
            "meta": {"author": author, "family": self.family,
                     "seed": getattr(self, "seed", 0),
                     "shifted": self.shifted},
        }
