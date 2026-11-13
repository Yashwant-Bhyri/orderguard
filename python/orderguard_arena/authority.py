"""High-throughput pre-trade authorization for a swarm of agents.

    authority.authorize(order, key=..., envelope=..., trigger=..., step=...)  -> Decision(allow | hold | refuse, reasons, envelope, ...)
    authority.authorize_batch(items)                                          -> list[Decision], same semantics, one pass

What one decision does, in order:
  L1  ticker normalisation (NFKC, upper-case, non-Latin look-alikes refused), money movement is not an order
  L7  an order that claims to carry out a rule ("news says sell X") is held unless >= 2 independent origins confirm the event
  L5  the envelope rules at the TRUSTED price (median across venues; the agent's own limit price is never used for sizing): allow-list,
      side, whole positive quantity, per-order cap, the envelope's shared daily budget, price band, step-up hold
  idempotency: a repeated key returns the first decision and consumes nothing; a key reused for a different order is refused
  budget: an allow reserves its notional atomically (DailyBudget.reserve), so concurrent agents can never together exceed the cap

`strict=True` runs the real `OrderGate` per order instead of the inlined checks (slower; used for parity tests and the bench).
Optional L8 pass-through: with `receiver` set (ORDERGUARD_RECEIVER_URL) a deterministic sample of decisions is also sent to the
TypeScript receiver and the agreement is counted. The receiver stays the final authority; this only measures that it agrees.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from orderguard_guard.gate import OrderGate, _parse_time, normalise_ticker
from orderguard_guard.graph import Rule, TriggerGraph, graph_events
from orderguard_guard.market import UnknownTicker

from .envelopes import Envelope, EnvelopeBook, _f
from .feeds import BASE_DATE, Snapshot

CODES = (("money", "Moving money"), ("revoked", "revoked"), ("expired", "expired"), ("idempotency", "idempotency key"),
         ("ticker", "ticker"), ("side", "side"), ("quantity", "quantity must"), ("limit", "limit price must"),
         ("no_price", "no trusted price"), ("per_order", "per-order cap"), ("daily", "daily cap"), ("band", "the mandate allows at most"),
         ("fair_share", "fair share"), ("l7", "standing rule"), ("stepup", "step-up"), ("no_envelope", "no envelope"))


def reason_code(text: str) -> str:
    for code, needle in CODES:
        if needle in text:
            return code
    return "other"


@dataclass(slots=True)
class Decision:
    decision: str                       # allow | hold | refuse
    reasons: list
    envelope: str | None = None         # name of the envelope that authorized (or would have held) the order
    notional: float | None = None       # at the trusted price
    trusted: float | None = None
    replay: bool = False
    layer: str | None = None            # L1 | L5 | L7 | idempotency | money
    latency_ns: int = 0

    @property
    def code(self) -> str:
        return reason_code(self.reasons[0]) if self.reasons else ""


class SnapshotMarket:
    """TrustedMarket over a {symbol: price} dict, for the real OrderGate (strict mode and parity tests)."""

    def __init__(self, prices: dict):
        self.prices = prices

    def quote(self, ticker: str) -> dict:
        p = self.prices.get(ticker.upper())
        if p is None:
            raise UnknownTicker(ticker)
        return {"price": p, "as_of": "arena", "source": "arena-median"}

    def status(self, ticker: str) -> dict:
        return {"halted": False, "lot_size": 1, "band_pct": None, "as_of": "arena", "source": "arena-median"}


class Authority:
    def __init__(self, book: EnvelopeBook, *, steps_per_day: int = 500, routing: str = "pinned", strict: bool = False, min_sources: int = 2,
                 agent_share: float | None = None, receiver=None, receiver_sample: float = 0.0):
        if routing not in ("pinned", "tightest_fit"):
            raise ValueError("routing is 'pinned' or 'tightest_fit'")
        self.book, self.steps_per_day, self.routing, self.strict, self.min_sources = book, int(steps_per_day), routing, strict, min_sources
        self.agent_share = agent_share        # optional OPERATOR policy (not part of the signed mandate): one agent may use at most this share of an envelope's daily cap
        self.prices: dict[str, float] = {}
        self.news: dict[str, list] = {}
        self._l7: dict = {}
        self._seen: dict = {}
        self._ilock = threading.Lock()
        self._asof: dict[int, dt.datetime] = {}
        self._market = SnapshotMarket(self.prices)
        self._gates: dict[str, OrderGate] = {}
        self._norm: dict = {}
        self._lat: list[int] = []
        self.counts = {"allow": 0, "hold": 0, "refuse": 0}
        self.codes: dict[str, int] = {}
        self.pending: dict[str, dict] = {}
        self.receiver, self.receiver_sample = receiver, float(receiver_sample)
        self.l8 = {"sampled": 0, "agree": 0, "disagree": 0, "unreachable": 0, "examples": []}
        self._stat_lock = threading.Lock()

    @classmethod
    def from_env(cls, book: EnvelopeBook, **kw) -> "Authority":
        """Attach the L8 receiver when ORDERGUARD_RECEIVER_URL is set (sampled at ORDERGUARD_RECEIVER_SAMPLE, default 0.01)."""
        url = os.getenv("ORDERGUARD_RECEIVER_URL")
        if url:
            from orderguard_guard.receiver_client import Receiver
            kw.setdefault("receiver", Receiver(url))
            kw.setdefault("receiver_sample", float(os.getenv("ORDERGUARD_RECEIVER_SAMPLE", "0.01")))
        return cls(book, **kw)

    # ---- trusted data ---------------------------------------------------------------------------------------------
    def on_snapshot(self, snap: Snapshot) -> None:
        """Trusted prices (median across venues) and the feed's own news evidence. Agents cannot write either."""
        self.prices.clear()
        self.prices.update(snap.trusted())
        for e in snap.news:
            self.news.setdefault(e["news_id"], []).append(e)

    def set_prices(self, prices: dict) -> None:
        self.prices.clear()
        self.prices.update(prices)

    def revoke(self, envelope: str) -> None:
        e = self.book.get(envelope)
        if e is None:
            raise KeyError(envelope)
        e.revoked = True

    def _as_of(self, day: int) -> dt.datetime:
        a = self._asof.get(day)
        if a is None:
            a = self._asof[day] = _parse_time(BASE_DATE + dt.timedelta(days=day))
        return a

    def _norm_ticker(self, raw):
        r = self._norm.get(raw)
        if r is None:
            r = normalise_ticker(raw)
            if len(self._norm) < 50_000:
                self._norm[raw] = r
        return r

    # ---- L7 -----------------------------------------------------------------------------------------------------------
    def confirm_trigger(self, trigger: dict, ticker: str, side: str) -> tuple[bool, str]:
        """A rule-triggered order is confirmed only if the feed's own events for that news id have >= min_sources independent origins."""
        if "confirmed" in trigger:                      # replayed stream: the verdict was recorded when the stream was made
            return bool(trigger["confirmed"]), trigger.get("why", "")
        nid = str(trigger.get("news_id"))
        memo = self._l7.get((nid, side))
        if memo is not None:
            return memo
        ev = self.news.get(nid)
        if not ev:
            res = (False, "no event with that id is on the trusted feed")
        else:
            nm = f"{ticker}_news"
            rule = Rule(f"L7-{nid}", f"{side} {ticker} when the news is confirmed", [nm], lambda v, nm=nm: v[nm] > 0, 0.0, side,
                        matchers={nm: lambda e, nid=nid: e.get("news_id") == nid}, tickers=[ticker])
            r = TriggerGraph([rule], min_sources=self.min_sources, baseline=[]).evaluate(graph_events(ev))[0]
            res = (bool(r["fires"]), r["held_reason"] or f"the event is not confirmed by at least {self.min_sources} independent sources")
        self._l7[(nid, side)] = res
        return res

    # ---- decide -------------------------------------------------------------------------------------------------------
    def _candidates(self, ticker: str, envelope, owner) -> list[Envelope]:
        if envelope is not None:
            e = envelope if isinstance(envelope, Envelope) else self.book.get(envelope)
            return [e] if e is not None else []
        if self.routing == "tightest_fit":
            return self.book.envelopes(owner)
        h = self.book.home_for(ticker, owner)
        return [h] if h is not None else []

    def _gate_for(self, e: Envelope) -> OrderGate:
        g = self._gates.get(e.id)
        if g is None:
            g = self._gates[e.id] = OrderGate(e.m, self._market)
        return g

    def _evaluate_one(self, e: Envelope, ticker, problem, side, qty, limit, trusted, day, order, as_of):
        """-> (reasons, holds, notional) for one envelope, from the inlined rules or, in strict mode, the real OrderGate."""
        dead = e.live(as_of)
        if dead:
            return [dead], [], None
        used = e.budget.used(day)
        if not self.strict:
            return e.check(ticker, problem, side, qty, limit, trusted, used)
        res = self._gate_for(e).evaluate({**order, "ticker": order.get("ticker")}, {"daily_total_usd": used, "as_of": as_of})
        n = res["checks"].get("notional_usd")
        if res["decision"] == "allow":
            return [], [], n
        return (res["reasons"], [], n) if res["decision"] == "refuse" else ([], res["reasons"], n)

    def _decide(self, order: dict, key: str, envelope, owner, trigger, step: int, agent=None) -> Decision:
        kind = str(order.get("type") or order.get("action") or "order").lower()
        if kind in ("transfer", "withdraw", "withdrawal", "wire", "transfer_funds") or "destination_account" in order:
            return Decision("refuse", ["Moving money out of the account is not something the mandate allows."], layer="money")
        ticker, problem = self._norm_ticker(order.get("ticker"))
        side = str(order.get("side", "")).strip().lower()
        qty, limit = _f(order.get("quantity")), _f(order.get("limit_price"))
        day = step // self.steps_per_day
        as_of = self._as_of(day)
        trusted = self.prices.get(ticker) if not problem else None
        # L7: a rule-triggered order must be confirmed by independent sources before it may rely on the rule
        if trigger is not None:
            ok, why = self.confirm_trigger(trigger, ticker, side)
            if not ok:
                return Decision("hold", [f"The standing rule {trigger.get('rule', 'news')} does not fire on the confirmed events: "
                                         f"{why.rstrip('.')}. A human must approve this order."], layer="L7", trusted=trusted)
        cands = self._candidates(ticker, envelope, owner)
        if not cands:
            why = (problem[0].upper() + problem[1:] + ".") if problem else f"The ticker {ticker or order.get('ticker')!r} is not on the allow-list of any envelope; nothing is authorized."
            return Decision("refuse", [why], layer="L1" if problem else "L5", trusted=trusted)
        evals = [(e, *self._evaluate_one(e, ticker, problem, side, qty, limit, trusted, day, order, as_of)) for e in cands]
        notional = next((n for _, _, _, n in evals if n is not None), None)
        allows = [(e, n) for e, r, h, n in evals if not r and not h]
        holds = [(e, h, n) for e, r, h, n in evals if not r and h]
        if allows:
            allows.sort(key=lambda t: (t[0].headroom(t[1], day), t[0].name))      # tightest fit first
            for e, n in allows:
                cap_a = e.budget.cap * self.agent_share if (self.agent_share is not None and agent is not None) else None
                if e.budget.reserve(day, n, agent, cap_a):                        # atomic: concurrent agents share one budget
                    return Decision("allow", [], e.name, n, trusted, layer="L5")
            e0 = allows[0][0]
            used = e0.budget.used(day)
            if self.agent_share is not None and agent is not None and used + allows[0][1] <= e0.budget.cap:
                return Decision("refuse", [f"This agent has used its fair share of the envelope's daily cap ({self.agent_share:.1%}), so the order is refused."],
                                e0.name, allows[0][1], trusted, layer="L5")
            return Decision("refuse", [f"With ${used:,.0f} already placed today this order would bring the day's total to "
                                       f"${used + allows[0][1]:,.0f}, above the daily cap of ${e0.m.maxDailyNotionalUsd:,.0f}."],
                            e0.name, allows[0][1], trusted, layer="L5")
        if holds:
            holds.sort(key=lambda t: (t[0].headroom(t[2], day), t[0].name))
            e, h, n = holds[0]
            # Like the receiver, a held order counts against the day's budget from the moment it is held (approval reserves nothing more).
            cap_a = e.budget.cap * self.agent_share if (self.agent_share is not None and agent is not None) else None
            if not e.budget.reserve(day, n, agent, cap_a):
                used = e.budget.used(day)
                return Decision("refuse", [f"With ${used:,.0f} already placed today this order would bring the day's total to "
                                           f"${used + n:,.0f}, above the daily cap of ${e.m.maxDailyNotionalUsd:,.0f}."], e.name, n, trusted, layer="L5")
            return Decision("hold", h, e.name, n, trusted, layer="L5")
        e, r, _, n = min(evals, key=lambda t: len(t[1]))
        if len(evals) > 1:
            r = r + ["No envelope of the owner authorizes this order."]
        return Decision("refuse", r, e.name, n, trusted, layer="L5")

    def authorize(self, order: dict, *, key: str, envelope=None, owner: str | None = None, trigger: dict | None = None, step: int = 0,
                  agent=None) -> Decision:
        t0 = time.perf_counter_ns()
        fp = (order.get("ticker"), order.get("side"), order.get("quantity"), order.get("limit_price"), order.get("type"))
        with self._ilock:
            prior = self._seen.get(key)
            if prior is None:
                self._seen[key] = (fp, None)                    # claim the key: a concurrent duplicate waits for our answer
        if prior is not None:
            fp0, d = prior
            while d is None:
                time.sleep(0.00005)
                d = self._seen[key][1]
            if fp0 != fp:
                d = Decision("refuse", ["The idempotency key was reused with a different order."], layer="idempotency")
            else:
                d = Decision(d.decision, d.reasons, d.envelope, d.notional, d.trusted, True, d.layer)
            d.latency_ns = time.perf_counter_ns() - t0
            self._record(d, replay=True)
            return d
        try:
            d = self._decide(order, key, envelope, owner, trigger, step, agent)
        except Exception as e:                                   # fail closed
            d = Decision("refuse", [f"The order could not be evaluated ({type(e).__name__}), so it is refused."], layer="L5")
        self._seen[key] = (fp, d)
        if d.decision == "hold":
            self.pending[key] = {"order": order, "envelope": d.envelope, "notional": d.notional, "step": step, "layer": d.layer}
        d.latency_ns = time.perf_counter_ns() - t0
        self._record(d)
        if self.receiver is not None and self._sampled(key):
            self._l8(order, key, d)
        return d

    def authorize_batch(self, items: list) -> list[Decision]:
        """items: (order, key, envelope, owner, trigger, step, agent) tuples (missing trailing fields default to None/0). One pass, input order kept."""
        out = []
        for it in items:
            order, key, *rest = it
            rest = list(rest) + [None] * (5 - len(rest))
            envelope, owner, trigger, step, agent = rest[0], rest[1], rest[2], (rest[3] or 0), rest[4]
            out.append(self.authorize(order, key=key, envelope=envelope, owner=owner, trigger=trigger, step=step, agent=agent))
        return out

    def approve(self, key: str, *, step: int = 0) -> Decision:
        """The human approves a held order. A step-up hold already reserved its budget (as in the receiver); an L7 hold reserves it now, if it still fits. Agents cannot call this."""
        p = self.pending.pop(key, None)
        if p is None:
            return Decision("refuse", ["No held order has that key."], layer="L5")
        e = self.book.get(p["envelope"]) if p["envelope"] else None
        if e is None or e.revoked:
            return Decision("refuse", ["The envelope is gone or revoked; the held order cannot be approved."], layer="L5")
        if p["layer"] != "L5":                       # an L7 hold reserved nothing: approving it now must fit the budget
            day = step // self.steps_per_day
            if p["notional"] is None or not e.budget.reserve(day, p["notional"]):
                return Decision("refuse", ["Approving this order would exceed the envelope's daily cap."], e.name, p["notional"], layer="L5")
        return Decision("allow", [], e.name, p["notional"], layer="L5")           # an L5 hold already reserved its notional

    # ---- statistics ---------------------------------------------------------------------------------------------------
    def _record(self, d: Decision, replay: bool = False) -> None:
        with self._stat_lock:
            self.counts[d.decision] += 1
            self._lat.append(d.latency_ns)
            if d.reasons:
                self.codes[d.code] = self.codes.get(d.code, 0) + 1

    def latency_us(self) -> dict:
        if not self._lat:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
        a = np.asarray(self._lat, dtype=np.float64) / 1000.0
        return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "p99": float(np.percentile(a, 99)), "mean": float(a.mean())}

    def reset_stats(self) -> None:
        self._lat.clear()
        self.counts.update(allow=0, hold=0, refuse=0)
        self.codes.clear()

    # ---- L8 pass-through ----------------------------------------------------------------------------------------------
    def _sampled(self, key: str) -> bool:
        h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 10_000
        return h < self.receiver_sample * 10_000

    def _l8(self, order: dict, key: str, d: Decision) -> None:
        try:
            q = _f(order.get("quantity"))
            lim = _f(order.get("limit_price"))
            if q is None or lim is None or not order.get("ticker") or "destination_account" in order:
                return
            r = self.receiver.propose(str(order["ticker"]), str(order.get("side")), int(q), float(lim), client_order_id=key)
            theirs = {"filled": "allow", "held": "hold", "denied": "refuse"}.get(r.get("decision"), "refuse")
        except Exception:
            with self._stat_lock:
                self.l8["unreachable"] += 1
            return
        with self._stat_lock:
            self.l8["sampled"] += 1
            if theirs == d.decision:
                self.l8["agree"] += 1
            else:
                self.l8["disagree"] += 1
                if len(self.l8["examples"]) < 5:
                    self.l8["examples"].append({"ours": d.decision, "receiver": theirs, "reason": str(r.get("reason"))[:160]})
