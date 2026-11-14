"""Inline order-risk scoring: the trained model, a streaming feature engine, and the tighten-only rule.

    scorer = RiskScorer.load()                      # data/models/order_risk.json, pure Python, no sklearn
    scorer.set_envelopes({"core": {"per_order": 25_000, "daily": 8e6, "step_up": 20_000, "band_pct": 1.0}}, steps_per_day=500)
    r = scorer.score(event)                         # before the event is folded in: point-in-time
    decision = tighten(gate_decision, r)            # can only move allow -> hold -> refuse
    scorer.observe(event)                           # fold the event into the rolling state

`event` keys: step, agent, env, ticker, side, qty, limit, tp (trusted price or None), notional (at the trusted price), key, trig (None/True/False).

The model can only tighten a decision the code gate already made. It never turns a refusal into anything else, so a wrong or
attacked model can cost legitimate flow (a human reviews the hold) but cannot authorize an order the signed mandate forbids.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path

from . import features as F
from . import program as G
from .models import TreeEnsemble

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "data" / "models" / "order_risk.json"
ORDER = {"allow": 0, "hold": 1, "refuse": 2}


def tighten(decision: str, risk: dict | None) -> str:
    """The stricter of the gate's decision and the risk model's action. Pure; never loosens."""
    if decision not in ORDER:
        return "refuse"                          # unknown decisions fail closed
    act = (risk or {}).get("action", "none")
    want = {"none": "allow", "hold": "hold", "refuse": "refuse"}.get(act, "refuse")
    return decision if ORDER[decision] >= ORDER[want] else want


class RiskScorer:
    """Loads either model format. /2 = programmed units + learned trees combined by noisy-OR, with one-shot weight edits; /1 = the first
    shipped model (trees + nearest-neighbour prototypes), kept loadable for comparison."""

    def __init__(self, model: dict):
        fmt = model.get("format")
        if fmt not in ("orderguard-order-risk/1", "orderguard-order-risk/2"):
            raise ValueError(f"unsupported order-risk model format {fmt!r}")
        self.model, self.v2 = model, fmt.endswith("/2")
        self.ens = TreeEnsemble.from_json(model["trees"])
        self.cols = list(model["cols"])
        self.t_hold, self.t_refuse = float(model["thresholds"]["hold"]), float(model["thresholds"]["refuse"])
        self.engine = F.FeatureEngine()
        self.units = G.compile_units([{**u, "terms": [tuple(t) for t in u["terms"]]} for u in model.get("units", [])]) if self.v2 else []
        self.edits: list[dict] = []                          # one-shot weight edits written by label_attack (v2)
        self.protos: list[tuple[list[float], float]] = []   # fallback / v1: (standardised vector, its own bandwidth)
        self.notes: list[str] = []
        self.recent: list[list[float]] = []                  # embeddings of recent unflagged orders (prototype reference)
        self.recent_x: deque = deque(maxlen=5000)            # raw feature rows of recent unflagged orders (edit reference)
        self.recent_max, self.capture_budget = 5000, 0.005
        self.edit_budget = float((model.get("edit") or {}).get("budget", 0.001))
        p = model.get("prototype") or {}
        self._mu, self._sd, self._h, self._tau = p.get("mu"), p.get("sd"), float(p.get("h", 1.0)), float(p.get("tau", 0.5))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RiskScorer":
        return cls(json.loads(Path(path or MODEL_PATH).read_text()))

    def set_envelopes(self, envelopes: dict, steps_per_day: int = 500) -> None:
        self.engine.set_envelopes(envelopes, steps_per_day)
        self.engine.reset()

    # ---- one-shot ---------------------------------------------------------------------------------------------------
    def _embed(self, x: list[float]) -> list[float] | None:
        if not self._mu:
            return None
        out = []
        for c, (m, s) in zip(self.cols, zip(self._mu, self._sd)):
            v = x[c]
            v = math.copysign(math.log1p(abs(v)), v)
            out.append(max(-6.0, min(6.0, (v - m) / (s or 1.0))))
        return out

    def label_attack(self, event: dict, note: str = "", hint: list[str] | None = None, budget: float | None = None) -> float | None:
        """An analyst marks ONE event as an attack: the pattern is held from now on, with no retraining.

        v2 writes a weight edit (program.edit_from_example): a new unit over the coordinates on which the example is far outside the
        honest statistics stored in the model, thresholded so that it would have captured at most `budget` (default 0.1%) of the recent
        orders the model did not flag (other agents' orders only). `hint` optionally names the feature coordinates the analyst believes define the attack. When the example is not outside
        honest flow on any coordinate (or for a v1 model) it falls back to a nearest-neighbour prototype with a calibrated radius.
        Returns a positive number (the edit's kappa, or the prototype bandwidth), or None when nothing could be written."""
        x = self.engine.featurize(event)
        if self.v2:
            ag = event.get("agent")
            ref = [r for a, r in self.recent_x if a != ag]   # the labelled agent's own orders are not honest reference
            if len(ref) >= 200:
                e = G.edit_from_example(x, ref, stats=self.model.get("edit"), budget=self.edit_budget if budget is None else budget, hint=hint, note=note)
            else:                                            # too little live flow: training-set honest statistics and a strict conjunction
                e = G.edit_from_example(x, [], stats=self.model.get("edit"), hint=hint, note=note, min_terms=3, kappas=(0.8,)) if self.model.get("edit") else None
            if e is not None:
                self.edits.append(e)
                return float(e["kappa"])
        e = self._embed(x)
        if e is None:
            return None
        ds = sorted(math.sqrt(sum((a - b) ** 2 for a, b in zip(e, r))) for r in self.recent)
        q = ds[int(self.capture_budget * (len(ds) - 1))] if len(ds) >= 50 else self._h * math.sqrt(2 * math.log(1 / self._tau))
        h = max(q, 1e-6) / math.sqrt(2 * math.log(1 / self._tau))
        self.protos.append((e, h))
        self.notes.append(note)
        return h

    def _proto_sim(self, x: list[float]) -> tuple[float, str]:
        if not self.protos:
            return 0.0, ""
        e = self._embed(x)
        best, note = 0.0, ""
        for (p, h), n in zip(self.protos, self.notes):
            d2 = sum((a - b) ** 2 for a, b in zip(e, p))
            s = math.exp(-d2 / (2 * h ** 2))
            if s > best:
                best, note = s, n
        return best, note

    # ---- scoring ---------------------------------------------------------------------------------------------------
    def score(self, event: dict) -> dict:
        t0 = time.perf_counter_ns()
        x = self.engine.featurize(event)
        xs = [x[c] for c in self.cols]
        pl = self.ens.prob(self.ens.raw(xs))
        p, fired = pl, []
        if self.units:
            q = 1.0 - pl
            for u in self.units:
                a = G.unit_value(u["terms"], x)
                if a > 0.0:
                    q *= 1.0 - u["pi"] * a
                    fired.append((u["pi"] * a, a, u))
            p = 1.0 - q
        action = "refuse" if p >= self.t_refuse else "hold" if p >= self.t_hold else "none"
        reasons = []
        if action != "none":
            fired.sort(key=lambda t: -t[0])
            for w, a, u in fired[:2]:
                if w >= self.t_hold:
                    reasons.append(u["why"][0].upper() + u["why"][1:] + ": " + "; ".join(F.explain(f, x[F.IX[f]]) for f, _lo, _hi in u["spec"] if f != "trig"))
            if pl >= self.t_hold or not reasons:
                for v, k in self.ens.contributions(xs)[:3]:
                    if v > 0:
                        reasons.append(F.explain(self.ens.names[k], xs[k]))
        sim, note = self._proto_sim(x)
        for e in self.edits:
            if G.edit_fires(e, x):
                sim = 1.0
                if action == "none":
                    action = "hold"
                reasons.insert(0, "Matches a pattern an analyst labelled as an attack" + (f" ({e['note']})" if e.get("note") else "") + ": " + "; ".join(G.edit_reasons(e, x)) + ".")
                break
        if action == "none":
            if self.v2:
                self.recent_x.append((event.get("agent"), x))
            if self._mu and not self.v2 or (self._mu and self.protos):
                self.recent.append(self._embed(x))
                if len(self.recent) > self.recent_max:
                    del self.recent[: len(self.recent) - self.recent_max]
        if sim >= self._tau and action == "none":
            action = "hold"
            reasons.insert(0, "Closely resembles an order an analyst labelled as an attack" + (f" ({note})" if note else "") + ".")
        out = {"risk": round(p, 6), "action": action, "reasons": reasons, "prototype_similarity": round(sim, 4)}
        if self.v2:
            out["learned_risk"] = round(pl, 6)
            out["units"] = [{"name": u["name"], "family": u["family"], "activation": round(a, 3)} for _w, a, u in fired]
        out["latency_us"] = round((time.perf_counter_ns() - t0) / 1000, 2)
        return out

    def observe(self, event: dict) -> None:
        self.engine.update(event)


def arena_event(e: dict) -> dict:
    """Map an arena event-log row to the scorer's event format (no rationale text: the shipped model is behavioural)."""
    o = e.get("order") or {}
    tp = e.get("tp")
    trig = e.get("trigger")
    side = o.get("side") or ""
    if o.get("type") == "transfer" or "destination_account" in o:
        side = ""
    return {"step": int(e.get("step", 0)), "agent": int(e.get("agent", 0)), "env": e.get("sleeve") or e.get("env"), "ticker": str(o.get("ticker") or ""),
            "side": side, "qty": float(o.get("quantity") or 0), "limit": float(o.get("limit_price") or 0.0), "tp": tp, "notional": float(e.get("risk") or 0.0),
            "key": e.get("key"), "trig": None if trig is None else bool(trig.get("confirmed")), "listed": tp is not None}
