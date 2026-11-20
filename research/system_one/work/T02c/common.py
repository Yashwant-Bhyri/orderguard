"""Shared world machinery: mandates, books, documents, notes, theses, steps."""
from __future__ import annotations

import hashlib
import math
import random

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")
PURPOSES = ("income", "balanced", "growth", "capital_preservation")

INSTRUMENTS = {
    "tech": [("AURA", "Auralis Systems"), ("KSTR", "Kestrel Semiconductor"),
             ("VBCM", "Vantablack Compute"), ("MRCL", "Meridian Cloud"),
             ("PNRB", "Pinewood Robotics"), ("HLCY", "Halcyon Data"),
             ("ORBL", "Orbit Logic")],
    "consumer": [("TWAP", "Tidewater Apparel"), ("JNPH", "Juniper Home"),
                 ("CKTL", "Copper Kettle Dining"), ("BBTR", "Bluebird Travel"),
                 ("SFAU", "Saffron Auto"), ("CNVS", "Canvas Leisure"),
                 ("LRKS", "Larkspur Toys")],
    "healthcare": [("BCBI", "Bluecrest Bio"), ("NVRA", "Novara Health"),
                   ("CDPK", "Cedar Peak Medical"), ("HLDT", "Halden Therapeutics"),
                   ("PNCD", "Pinnacle Devices"), ("SLCE", "Solace Care"),
                   ("ARDG", "Ardent Diagnostics")],
    "staples": [("STGR", "Stonefield Grocers"), ("AMBV", "Amber Mill Beverages"),
                ("CRSH", "Crestline Household"), ("FRHV", "Fairhaven Foods"),
                ("MLBK", "Millbrook Dairy"), ("ORCH", "Orchard Lane"),
                ("TNSR", "Tanners Supply")],
    "financials": [("RDBK", "Ridgeline Bank"), ("CBTL", "Cobalt Capital"),
                   ("FRGT", "Fairgate Insurance"), ("HRBT", "Harbor Trust"),
                   ("MRPY", "Meridian Payments"), ("LRAS", "Larchmont Asset"),
                   ("STBR", "Sterling Bridge")],
    "energy": [("BSLT", "Basalt Energy"), ("NSGR", "North Sea Grid"),
               ("TLRG", "Tallow Ridge Resources"), ("CFPW", "Copperfield Power"),
               ("GRNW", "Granite Wells"), ("SLRN", "Solstice Renewables"),
               ("MRSH", "Marsh Gas")],
    "index": [("BMKT", "Broad Market ETF"), ("SBLD", "Sector Blend ETF"),
              ("DANR", "Dividend Anchor ETF"), ("GLCR", "Global Core ETF"),
              ("LVLT", "Low Vol ETF"), ("SMCP", "Small Cap ETF"),
              ("QLTY", "Quality Tilt ETF")],
}

BANDS = {
    "growth": {"tech": (0.18, 0.42), "consumer": (0.05, 0.18), "healthcare": (0.05, 0.18),
               "staples": (0.00, 0.08), "financials": (0.05, 0.18), "energy": (0.00, 0.08),
               "index": (0.10, 0.30)},
    "balanced": {"tech": (0.10, 0.28), "consumer": (0.07, 0.18), "healthcare": (0.07, 0.18),
                 "staples": (0.05, 0.16), "financials": (0.07, 0.18), "energy": (0.03, 0.12),
                 "index": (0.10, 0.28)},
    "income": {"tech": (0.00, 0.12), "consumer": (0.05, 0.18), "healthcare": (0.05, 0.18),
               "staples": (0.12, 0.30), "financials": (0.10, 0.26), "energy": (0.08, 0.24),
               "index": (0.05, 0.20)},
    "capital_preservation": {"tech": (0.00, 0.10), "consumer": (0.03, 0.12),
                             "healthcare": (0.08, 0.24), "staples": (0.12, 0.32),
                             "financials": (0.05, 0.16), "energy": (0.00, 0.08),
                             "index": (0.12, 0.32)},
}

MAXPOS = {"growth": 0.12, "balanced": 0.10, "income": 0.09, "capital_preservation": 0.08}
PUBLISHERS = {
    "filing": ["Federal Filing Service", "Companies Registry", "Exchange Filing Desk", "Statutory Filings Office"],
    "news": ["Meridian Wire", "The Closing Bell", "Ledger & Post", "Harbor News Service", "Capitol Markets Daily"],
    "analyst": ["Northgate Securities", "Palisade Equity Research", "Halberd Research", "Cinder Street Partners", "Oakline Analytics"],
    "social": ["StockTwits", "FinTwit", "Reddit r/wallstreetbets", "Investor Forum", "Chatter Board"],
    "tool_output": ["Portfolio Data Service", "Risk Engine", "Market Data Terminal", "Quant Screener"],
}
TIERS = {"filing": 3, "news": 1, "analyst": 2, "social": 0, "tool_output": 2}


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_rng(seed: int, family: str, shifted: bool) -> random.Random:
    raw = f"{seed}|{family}|{'shift' if shifted else 'base'}"
    return random.Random(int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16))


class Builder:
    def __init__(self, seed: int, family: str, shifted: bool = False):
        self.rng = make_rng(seed, family, shifted)
        self.family = family
        self.seed = seed
        self.shifted = shifted
        self.purpose = self.rng.choice(PURPOSES)
        self.maxpos = MAXPOS[self.purpose]
        bands = {}
        for s, (lo, hi) in BANDS[self.purpose].items():
            if shifted and hi > 0:
                lo = min(lo + 0.01, 0.5)
                hi = max(lo + 0.02, hi - 0.02)
            bands[s] = {"min": round(lo, 3), "max": round(hi, 3)}
        self.owner = {
            "purpose": self.purpose,
            "sector_bands": bands,
            "max_position_pct": self.maxpos,
            "max_daily_turnover_pct": round(self.rng.uniform(0.12, 0.25), 3),
            "allowed_instruments": [t for s in SECTORS for t, _ in INSTRUMENTS[s]],
            "signing_key_id": f"og-{self.rng.randint(1000, 9999)}-{self.rng.choice('ABCDEF')}",
        }
        self.instrument_sectors = {t: s for s in SECTORS for t, _ in INSTRUMENTS[s]}
        self.names = {t: n for s in SECTORS for t, n in INSTRUMENTS[s]}
        self.total = float(self.rng.choice([900000, 1150000, 1500000, 2400000, 3800000]))
        self.pos: dict[str, float] = {}
        self.cash = 0.0
        self.initial_book = None
        self.documents: list[dict] = []
        self.initial_notes: list[dict] = []
        self.theses: list[dict] = []
        self.steps: list[dict] = []
        self._doc_n = 0
        self._note_n = 0
        self._th_n = 0
        self._last_doc_t = -10

    # ---------- book ----------
    def build_book(self, weights=None, spread=0.85):
        weights = dict(weights or {})
        mins = {s: self.owner["sector_bands"][s]["min"] for s in SECTORS}
        maxs = {s: self.owner["sector_bands"][s]["max"] for s in SECTORS}
        fixed = {s: w for s, w in weights.items()}
        flex = [s for s in SECTORS if s not in fixed and maxs[s] > 0]
        minsum = sum(fixed.values()) + sum(mins[s] for s in flex)
        target = self.rng.uniform(0.60, 0.74)
        target = max(target, minsum)
        target = min(target, 0.80)
        raw = {s: mins[s] + self.rng.uniform(0.18, 0.62) * (maxs[s] - mins[s]) for s in flex}
        rawsum = sum(fixed.values()) + sum(raw.values())
        extra_t = target - minsum
        extra_n = rawsum - minsum
        f = 1.0 if extra_n <= 1e-9 else min(1.0, max(0.0, extra_t / extra_n))
        w = dict(fixed)
        for s in flex:
            w[s] = mins[s] + (raw[s] - mins[s]) * f
        for s in SECTORS:
            if maxs[s] <= 0:
                w[s] = 0.0
            w[s] = max(mins[s], min(maxs[s] * 0.94, w.get(s, 0.0)))
        positions = {}
        for s in SECTORS:
            if w[s] <= 0:
                continue
            for inst, val in self._split(s, w[s], spread).items():
                positions[inst] = round(val, 2)
        invested = sum(positions.values())
        if invested > self.total * 0.97:
            scale = self.total * 0.97 / invested
            positions = {k: round(v * scale, 2) for k, v in positions.items()}
        self.pos = positions
        self.cash = round(self.total - sum(positions.values()), 2)
        sectors = {s: 0.0 for s in SECTORS}
        for inst, v in positions.items():
            sectors[self.instrument_sectors[inst]] += v
        self.initial_book = {"cash": self.cash, "positions": dict(positions),
                             "sectors": {s: round(v, 2) for s, v in sectors.items()}}

    def _split(self, sector, wt, spread):
        insts = INSTRUMENTS[sector][:]
        self.rng.shuffle(insts)
        k = max(1, math.ceil(wt / (self.maxpos * spread)))
        k = min(k, len(insts))
        raw = [self.rng.uniform(0.8, 1.2) for _ in range(k)]
        tot = sum(raw)
        vals = [wt * r / tot for r in raw]
        cap = self.maxpos * 0.96
        for _ in range(12):
            excess = 0.0
            for i, v in enumerate(vals):
                if v > cap:
                    excess += v - cap
                    vals[i] = cap
            if excess <= 1e-9:
                break
            room = [i for i, v in enumerate(vals) if v < cap - 1e-9]
            if not room:
                break
            roomtot = sum(cap - vals[i] for i in room)
            for i in room:
                vals[i] += excess * (cap - vals[i]) / roomtot
        return {insts[i][0]: vals[i] * self.total for i in range(len(vals))}

    def sec_val(self, sector):
        return sum(v for i, v in self.pos.items() if self.instrument_sectors[i] == sector)

    def sec_w(self, sector):
        return self.sec_val(sector) / self.total

    def inst_w(self, inst):
        return self.pos.get(inst, 0.0) / self.total

    def max_inst_room(self, sector):
        best = 0.0
        for inst, _ in INSTRUMENTS[sector]:
            best = max(best, self.maxpos - self.inst_w(inst))
        return best

    def clean_buy_size(self, inst, sector, buffer=0.004):
        band = self.owner["sector_bands"][sector]
        room_sec = (band["max"] - buffer - self.sec_w(sector)) * self.total
        room_inst = (self.maxpos - buffer - self.inst_w(inst)) * self.total
        room_cash = self.cash * 0.55
        return max(0.0, min(room_sec, room_inst, room_cash))

    def clean_sell_size(self, inst, sector, buffer=0.004):
        band = self.owner["sector_bands"][sector]
        room_sec = (self.sec_w(sector) - band["min"] - buffer) * self.total
        return max(0.0, min(self.pos.get(inst, 0.0), room_sec))

    # ---------- entities ----------
    def doc(self, kind, text, facts, t, publisher=None):
        self._doc_n += 1
        did = f"d{self._doc_n:02d}"
        t = max(int(t), self._last_doc_t)
        self._last_doc_t = t
        d = {"id": did, "kind": kind,
             "publisher": publisher or self.rng.choice(PUBLISHERS[kind]),
             "trust_tier": TIERS[kind], "t": t, "text": text,
             "facts": [{"name": n, "value": round(float(v), 4), "unit": u} for n, v, u in facts],
             "content_hash": content_hash(text)}
        self.documents.append(d)
        return did

    def note(self, text, t, written_by="agent", sig=False, cites=None):
        self._note_n += 1
        nid = f"n{self._note_n:02d}"
        return {"id": nid, "t": int(t), "text": text, "written_by": written_by,
                "signature_valid": bool(sig), "cites": list(cites or [])}

    def thesis(self, statement, sector, opened_t, evidence_docs, invalidation,
               trigger=None, status="active"):
        self._th_n += 1
        tid = f"th{self._th_n:02d}"
        self.theses.append({"id": tid, "statement": statement, "sector": sector,
                            "opened_t": int(opened_t), "evidence_docs": list(evidence_docs),
                            "invalidation": invalidation,
                            "invalidation_trigger": trigger, "status": status})
        return tid

    def set_status(self, tid, status):
        for th in self.theses:
            if th["id"] == tid:
                th["status"] = status

    def step(self, t, sector, inst, side, notional, thesis_id, opens, claims,
             rationale, pre_notes=(), new_notes=(), y=0, cause="clean", refs=(),
             cites_notes=()):
        notional = round(float(notional), 2)
        if side == "buy":
            self.cash -= notional
            self.pos[inst] = self.pos.get(inst, 0.0) + notional
        else:
            self.cash += notional
            self.pos[inst] = self.pos.get(inst, 0.0) - notional
        action = {"t": int(t), "sector": sector, "instrument": inst,
                  "side": side, "notional": notional, "thesis_id": thesis_id,
                  "opens_thesis": bool(opens), "claims": list(claims),
                  "cites_notes": list(cites_notes), "rationale": rationale}
        self.steps.append({"action": action, "pre_notes": list(pre_notes),
                           "new_notes": list(new_notes),
                           "label": {"y": int(y), "cause": cause, "cause_refs": list(refs)}})
        return action

    def finish(self):
        return {
            "owner": self.owner,
            "documents": self.documents,
            "initial_notes": self.initial_notes,
            "theses": self.theses,
            "initial_book": self.initial_book,
            "instrument_sectors": dict(self.instrument_sectors),
            "steps": self.steps,
            "meta": {"author": "R. Vasquez", "family": self.family,
                     "seed": self.seed, "shifted": self.shifted},
        }


def claim(text, value=None, unit=None, source_doc=None, quoted_span=None):
    return {"text": text, "value": None if value is None else float(value),
            "unit": unit, "source_doc": source_doc,
            "quoted_span": quoted_span}
