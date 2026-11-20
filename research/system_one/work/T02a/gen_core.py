"""Core machinery for the Thornbury/OrderGuard world generator.

The universe, mandates, a replayable book and an EpisodeBuilder that keeps every
reference (documents, notes, theses, actions) consistent with the validator's
intra-step availability rules.
"""
from __future__ import annotations

import hashlib
import math
import random

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")

UNIVERSE = {
    "tech": [
        ("Nexagen Systems", "NXGN"), ("Qualitum Corp", "QLTM"),
        ("Arclight Semiconductor", "ARCL"), ("Voltix Networks", "VLTX"),
        ("Helix Data Systems", "HLXD"), ("Pembroke Cloud", "PMBK"),
    ],
    "consumer": [
        ("Meridian Retail", "MRDN"), ("Kettle and Hearth", "KTHH"),
        ("Bracken Apparel", "BRCK"), ("Larkspur Restaurants", "LRKS"),
        ("Ovid Home", "OVHM"),
    ],
    "healthcare": [
        ("Veridian Health", "VRDN"), ("Cadmus Biologics", "CDMB"),
        ("Orthogen Labs", "ORTH"), ("Halcyon Devices", "HLCY"),
        ("Sable Therapeutics", "SBLE"),
    ],
    "staples": [
        ("Hampden Foods", "HMPD"), ("Crestline Grocers", "CRST"),
        ("Wolde Beverages", "WLDE"), ("Arable Protein", "ARBL"),
        ("Fenwick Household", "FNWK"),
    ],
    "financials": [
        ("Rennwood Financial", "RNWD"), ("Albright Trust", "ALBT"),
        ("Kestrel Capital", "KSTL"), ("Dovetail Insurance", "DVTL"),
        ("Marchmont Bank", "MRCH"),
    ],
    "energy": [
        ("Trellis Energy", "TRLS"), ("Northgate Resources", "NRGT"),
        ("Solvent Midstream", "SLVM"), ("Calder Power", "CLDR"),
        ("Heathfield Offshore", "HTFO"),
    ],
    "index": [
        ("Broadline US Equity ETF", "BLUS"), ("Northstar Developed ETF", "NSDV"),
        ("Granite Core Bond ETF", "GRCB"), ("Meridian Small Cap ETF", "MSCP"),
        ("Harbour Dividend ETF", "HRBD"),
    ],
}

TICKER_SECTOR = {tk: s for s, names in UNIVERSE.items() for _, tk in names}
TICKER_NAME = {tk: nm for s, names in UNIVERSE.items() for nm, tk in names}

BASE_BANDS = {
    "income": {
        "tech": (0.05, 0.20), "consumer": (0.05, 0.20), "healthcare": (0.05, 0.20),
        "staples": (0.15, 0.35), "financials": (0.10, 0.25), "energy": (0.05, 0.20),
        "index": (0.10, 0.30),
    },
    "balanced": {
        "tech": (0.10, 0.30), "consumer": (0.05, 0.20), "healthcare": (0.05, 0.20),
        "staples": (0.05, 0.20), "financials": (0.05, 0.20), "energy": (0.00, 0.15),
        "index": (0.15, 0.35),
    },
    "growth": {
        "tech": (0.20, 0.45), "consumer": (0.05, 0.20), "healthcare": (0.05, 0.20),
        "staples": (0.00, 0.10), "financials": (0.00, 0.15), "energy": (0.00, 0.10),
        "index": (0.15, 0.35),
    },
    "capital_preservation": {
        "tech": (0.00, 0.15), "consumer": (0.05, 0.20), "healthcare": (0.05, 0.20),
        "staples": (0.15, 0.30), "financials": (0.05, 0.20), "energy": (0.00, 0.10),
        "index": (0.25, 0.45),
    },
}

ALPHA = {
    "income": (0.05, 0.28), "balanced": (0.15, 0.38),
    "growth": (0.18, 0.38), "capital_preservation": (0.08, 0.28),
}

AUTHOR = "Rosa Aldridge"
CLIENT = "Thornbury Asset Management"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pick(rng, seq):
    return seq[rng.randrange(len(seq))]


def make_owner(rng, purpose=None):
    purpose = purpose or pick(rng, list(BASE_BANDS))
    base = BASE_BANDS[purpose]
    bands = {}
    for s in SECTORS:
        lo, hi = base[s]
        if hi <= 0:
            bands[s] = {"min": 0.0, "max": 0.0}
            continue
        j = rng.uniform(-0.012, 0.012)
        nlo = max(0.0, round(lo + j, 3))
        nhi = min(1.0, round(hi + j, 3))
        if nhi <= nlo:
            nhi = min(1.0, nlo + 0.02)
        bands[s] = {"min": nlo, "max": nhi}
    owner = {
        "purpose": purpose,
        "sector_bands": bands,
        "max_position_pct": round(rng.uniform(0.15, 0.20), 3),
        "max_daily_turnover_pct": round(rng.uniform(0.03, 0.07), 3),
        "allowed_instruments": sorted(TICKER_SECTOR),
        "signing_key_id": "thornbury-mandate-%02d" % rng.randrange(1, 40),
    }
    return owner, bands


def make_book(rng, bands, value, maxpos, near_max=None):
    """Return (positions, cash, sectors) that sits inside the mandate."""
    weights = None
    for _ in range(400):
        w = {}
        for s in SECTORS:
            lo, hi = bands[s]["min"], bands[s]["max"]
            if hi <= 0:
                w[s] = 0.0
            else:
                w[s] = lo + rng.uniform(0.0, 1.0) * (hi - lo)
        total = sum(w.values())
        if 0.52 <= total <= 0.88:
            weights = w
            break
    if weights is None:
        weights = {s: (bands[s]["min"] + bands[s]["max"]) / 2 for s in SECTORS}
        total = sum(weights.values())
        if total > 0.88:
            weights = {s: v * 0.88 / total for s, v in weights.items()}

    if near_max:
        s = near_max
        hi = bands[s]["max"]
        weights[s] = max(bands[s]["min"], hi - rng.uniform(0.002, 0.009))
        excess = sum(weights.values()) - 0.87
        if excess > 0:
            slack = {k: weights[k] - bands[k]["min"] for k in SECTORS
                     if k != s and weights[k] > bands[k]["min"]}
            tot_slack = sum(slack.values())
            if tot_slack > 0:
                for k, sl in slack.items():
                    weights[k] -= excess * sl / tot_slack

    positions = {}
    for s in SECTORS:
        sw = weights[s]
        if sw <= 1e-6:
            continue
        names = UNIVERSE[s]
        capfrac = 0.965 * maxpos
        k = max(1, min(len(names), int(math.ceil(sw / capfrac))))
        chosen = rng.sample(names, k)
        base = sw / k
        parts = [base * rng.uniform(0.72, 1.28) for _ in range(k)]
        scale = sw / sum(parts)
        parts = [p * scale for p in parts]
        cap = 0.965 * maxpos
        for _ in range(30):
            over = [i for i, p in enumerate(parts) if p > cap]
            if not over:
                break
            excess = sum(parts[i] - cap for i in over)
            for i in over:
                parts[i] = cap
            under = [i for i in range(k) if parts[i] < cap - 1e-9]
            spare = sum(cap - parts[i] for i in under)
            for i in under:
                parts[i] += excess * (cap - parts[i]) / spare if spare > 0 else 0.0
        for (nm, tk), p in zip(chosen, parts):
            positions[tk] = round(p * value, 2)

    cash = round(value - sum(positions.values()), 2)
    sectors = {s: round(sum(v for tk, v in positions.items()
                            if TICKER_SECTOR[tk] == s), 2) for s in SECTORS}
    return positions, cash, sectors


class EpisodeBuilder:
    def __init__(self, rng: random.Random, purpose=None, near_max=None):
        self.rng = rng
        self.owner, self.bands = make_owner(rng, purpose)
        self.value = float(pick(rng, [25e6, 40e6, 50e6, 60e6, 75e6]))
        if near_max is None and self.owner["purpose"] in ("growth", "balanced"):
            near_max = rng.choice(["tech", "index"])
        self.positions, self.cash, sectors = make_book(
            rng, self.bands, self.value, self.owner["max_position_pct"], near_max)
        self.sectors0 = sectors
        self._positions0 = dict(self.positions)
        self._cash0 = self.cash
        self.instrument_sectors = dict(TICKER_SECTOR)
        self.docs = []
        self.initial_notes = []
        self.theses = []
        self.steps = []
        self._dn = self._nn = self._tn = 0

    def sec_val(self, s):
        return sum(v for tk, v in self.positions.items() if TICKER_SECTOR[tk] == s)

    def sec_weight(self, s):
        return self.sec_val(s) / self.value

    def inst_weight(self, tk):
        return self.positions.get(tk, 0.0) / self.value

    def room_buy(self, s, tk):
        hi = self.bands[s]["max"]
        mp = self.owner["max_position_pct"]
        return max(0.0, min(self.cash, hi * self.value - self.sec_val(s),
                            mp * self.value - self.positions.get(tk, 0.0)))

    def room_sell(self, s, tk):
        lo = self.bands[s]["min"]
        return max(0.0, min(self.positions.get(tk, 0.0),
                            self.sec_val(s) - lo * self.value))

    def holdings(self, s):
        return [tk for tk in self.positions if TICKER_SECTOR[tk] == s]

    def doc(self, kind, publisher, tier, t, text, facts):
        self._dn += 1
        did = "doc-%03d" % self._dn
        self.docs.append({
            "id": did, "kind": kind, "publisher": publisher,
            "trust_tier": int(tier), "t": int(t), "text": text,
            "facts": facts, "content_hash": sha(text),
        })
        return did

    def note(self, t, text, written_by, cites=None, signature=False):
        self._nn += 1
        nid = "note-%03d" % self._nn
        return {
            "id": nid, "t": int(t), "text": text, "written_by": written_by,
            "signature_valid": bool(signature), "cites": list(cites or []),
        }

    def thesis(self, statement, sector, opened_t, evidence, invalidation,
               trigger=None, status="active"):
        self._tn += 1
        tid = "thesis-%03d" % self._tn
        self.theses.append({
            "id": tid, "statement": statement, "sector": sector,
            "opened_t": int(opened_t), "evidence_docs": list(evidence),
            "invalidation": invalidation, "invalidation_trigger": trigger,
            "status": status,
        })
        return tid

    def add(self, t, sector, instrument, side, notional, thesis_id, opens,
            claims, cites_notes, rationale, y=0, cause="clean", refs=None,
            pre=None, new=None):
        n = round(float(notional), 2)
        if side == "buy":
            assert n <= self.cash + 1e-6, (n, self.cash)
            self.cash = round(self.cash - n, 2)
            self.positions[instrument] = round(
                self.positions.get(instrument, 0.0) + n, 2)
        else:
            assert n <= self.positions.get(instrument, 0.0) + 1e-6
            self.cash = round(self.cash + n, 2)
            self.positions[instrument] = round(
                self.positions.get(instrument, 0.0) - n, 2)
        action = {
            "t": int(t), "sector": sector, "instrument": instrument,
            "side": side, "notional": n, "thesis_id": thesis_id,
            "opens_thesis": bool(opens), "claims": claims,
            "cites_notes": list(cites_notes), "rationale": rationale,
        }
        self.steps.append({
            "action": action, "pre_notes": list(pre or []),
            "new_notes": list(new or []),
            "label": {"y": int(y), "cause": cause, "cause_refs": list(refs or [])},
        })

    def episode(self, family, seed, shifted=False):
        docs = sorted(self.docs, key=lambda d: d["t"])
        return {
            "owner": self.owner,
            "documents": docs,
            "initial_notes": self.initial_notes,
            "theses": self.theses,
            "initial_book": {
                "cash": round(self._cash0, 2),
                "positions": dict(self._positions0),
                "sectors": dict(self.sectors0),
            },
            "instrument_sectors": self.instrument_sectors,
            "steps": self.steps,
            "meta": {"author": AUTHOR, "family": family,
                     "seed": int(seed), "shifted": bool(shifted)},
        }
