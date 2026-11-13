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
from pathlib import Path

from . import features as F
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
    def __init__(self, model: dict):
        if model.get("format") != "orderguard-order-risk/1":
            raise ValueError(f"unsupported order-risk model format {model.get('format')!r}")
        self.model = model
        self.ens = TreeEnsemble.from_json(model["trees"])
        self.cols = list(model["cols"])
        self.t_hold, self.t_refuse = float(model["thresholds"]["hold"]), float(model["thresholds"]["refuse"])
        self.engine = F.FeatureEngine()
        self.protos: list[tuple[list[float], float]] = []   # one-shot analyst labels: (standardised vector, its own bandwidth)
        self.notes: list[str] = []
        self.recent: list[list[float]] = []                  # embeddings of recent unflagged orders: the reference for new labels
        self.recent_max, self.capture_budget = 5000, 0.005
        p = model.get("prototype") or {}
        self._mu, self._sd, self._h, self._tau = p.get("mu"), p.get("sd"), float(p.get("h", 1.0)), float(p.get("tau", 0.5))

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RiskScorer":
        return cls(json.loads(Path(path or MODEL_PATH).read_text()))

    def set_envelopes(self, envelopes: dict, steps_per_day: int = 500) -> None:
        self.engine.set_envelopes(envelopes, steps_per_day)
        self.engine.reset()

    # ---- one-shot memory ------------------------------------------------------------------------------------------
    def _embed(self, x: list[float]) -> list[float] | None:
        if not self._mu:
            return None
        out = []
        for c, (m, s) in zip(self.cols, zip(self._mu, self._sd)):
            v = x[c]
            v = math.copysign(math.log1p(abs(v)), v)
            out.append(max(-6.0, min(6.0, (v - m) / (s or 1.0))))
        return out

    def label_attack(self, event: dict, note: str = "") -> float | None:
        """An analyst marks one event as an attack: similar orders are held from now on, with no retraining.
        The prototype's bandwidth is set so it would have captured at most `capture_budget` of the recent orders the model did not flag
        (mostly honest flow). Returns that bandwidth, or None when the model has no prototype parameters."""
        e = self._embed(self.engine.featurize(event))
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
        p = self.ens.prob(self.ens.raw(xs))
        action = "refuse" if p >= self.t_refuse else "hold" if p >= self.t_hold else "none"
        reasons = []
        if action != "none":
            for v, k in self.ens.contributions(xs)[:3]:
                if v > 0:
                    name = self.ens.names[k]
                    reasons.append(F.explain(name, xs[k]))
        sim, note = self._proto_sim(x)
        if action == "none" and self._mu:
            self.recent.append(self._embed(x))
            if len(self.recent) > self.recent_max:
                del self.recent[: len(self.recent) - self.recent_max]
        if sim >= self._tau and action == "none":
            action = "hold"
            reasons.insert(0, "Closely resembles an order an analyst labelled as an attack" + (f" ({note})" if note else "") + ".")
        return {"risk": round(p, 6), "action": action, "reasons": reasons, "prototype_similarity": round(sim, 4),
                "latency_us": round((time.perf_counter_ns() - t0) / 1000, 2)}

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
