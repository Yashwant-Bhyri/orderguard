"""Envelope lab: which envelope should the human sign?

Given a RECORDED proposal stream (from an arena run), replay it through the authority under many candidate envelopes (fast: the
agents are not re-run and the trusted price at each proposal was recorded) and measure, per candidate:

  utility        legit notional allowed (USD at the trusted price), and as a share of what honest agents proposed
  false refusals share of legit proposals refused
  approvals/day  orders held for a human (step-up holds and L7 holds), per simulated day
  leaked/day     notional of "bad" proposals (errors, attacks, fake-news triggers) that the candidate would have allowed, per day
  blocked        the same notional refused or held

then the Pareto frontier (maximise utility, minimise leak) and a recommendation for a stated risk budget.

This is ADVICE for the human. The lab never signs, never widens a live envelope and never talks to the authority of a running swarm;
`proposed_mandate` is an unsigned body for the human to review and sign with their own key.

Honest limits: the stream comes from simulated agents; replay is open-loop (agents do not react to the candidate's refusals, so
second-order effects such as an agent retrying are not modelled); the daily budget is shared by the whole stream (one envelope for
all agents); a looser per-order cap can let an early large order use budget a later one needed, so the metrics are not strictly
monotone in every parameter (`monotonicity` reports where they are not).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import numpy as np

from .authority import Authority
from .envelopes import EnvelopeBook, make_envelope, owner_key_from_seed

_KEY = owner_key_from_seed("frontier-lab")
SHARES = (None, 0.05, 0.02, 0.01, 0.005)      # optional operator fair-share: max fraction of the daily cap one agent may use


@dataclass(frozen=True)
class Candidate:
    per_order: float
    daily: float
    band_pct: float
    breadth: int                  # how many of the stream's symbols (ranked by legit notional) are on the allow-list
    step_up: float | None         # USD above which a human must approve; None = never
    agent_share: float | None = None

    def label(self) -> str:
        su = "none" if self.step_up is None else f"{self.step_up:,.0f}"
        sh = "none" if self.agent_share is None else f"{self.agent_share:g}"
        return f"po={self.per_order:,.0f} day={self.daily:,.0f} band={self.band_pct:g}% n={self.breadth} su={su} share={sh}"


def stream_profile(events: list[dict], steps_per_day: int, *, steps: int | None = None) -> dict:
    legit = [e for e in events if e["label"] == "legit" and not e.get("replay")]
    # The feed can continue after the last proposal. Include that time in per-day metrics.
    last_step = max((e["step"] for e in events), default=0)
    ndays = max(last_step, (steps or 0) - 1) // steps_per_day + 1
    by_sym: dict[str, float] = {}
    for e in legit:
        t = str(e["order"].get("ticker"))
        by_sym[t] = by_sym.get(t, 0.0) + e["risk"]
    ranked = sorted(by_sym, key=lambda s: -by_sym[s])
    notionals = np.array([e["risk"] for e in legit]) if legit else np.array([0.0])
    return {"ndays": ndays, "legit_n": len(legit), "legit_usd": float(notionals.sum()), "legit_daily_usd": float(notionals.sum()) / ndays,
            "ranked_symbols": ranked, "order_q": {q: float(np.quantile(notionals, q)) for q in (0.5, 0.9, 0.99, 0.999, 1.0)}}


def replay_stream(events: list[dict], book: EnvelopeBook, *, steps_per_day: int, routing: str = "pinned", pin: dict | None = None,
                  agent_share: float | None = None, days: int | None = None) -> dict:
    """Run the recorded proposals through `book` and return the metrics. `pin` maps a proposal's sleeve to an envelope name (for multi-envelope books)."""
    auth = Authority(book, steps_per_day=steps_per_day, routing=routing, agent_share=agent_share)
    ndays = days if days is not None else max((e["step"] for e in events), default=0) // steps_per_day + 1
    m = {"legit_n": 0, "legit_usd": 0.0, "legit_allowed_usd": 0.0, "legit_refused": 0, "legit_held": 0, "legit_held_usd": 0.0,
         "bad_n": 0, "bad_usd": 0.0, "leaked_usd": 0.0, "blocked_usd": 0.0, "holds": 0, "leaked_by_label": {}}
    only = book.envelopes()[0] if len(book.envelopes()) == 1 else None
    for e in events:
        o = e["order"]
        tp = e.get("tp")
        auth.prices.clear()
        if tp is not None:
            t, _ = auth._norm_ticker(o.get("ticker"))
            auth.prices[t] = tp
        env = only if only is not None else (book.get(pin[e["sleeve"]]) if pin else None)
        d = auth.authorize(o, key=e["key"], envelope=env, trigger=e.get("trigger"), step=e["step"], agent=e["agent"])
        risk = e["risk"]
        if d.replay:
            continue                                          # a repeated key moves nothing
        if d.decision == "hold":
            m["holds"] += 1
        if e["label"] == "legit":
            m["legit_n"] += 1
            m["legit_usd"] += risk
            if d.decision == "allow":
                m["legit_allowed_usd"] += risk
            elif d.decision == "refuse":
                m["legit_refused"] += 1
            else:
                m["legit_held"] += 1
                m["legit_held_usd"] += risk
        else:
            m["bad_n"] += 1
            m["bad_usd"] += risk
            if d.decision == "allow":
                m["leaked_usd"] += risk
                m["leaked_by_label"][e["label"]] = m["leaked_by_label"].get(e["label"], 0.0) + risk
            else:
                m["blocked_usd"] += risk
    return {"utility_usd": round(m["legit_allowed_usd"], 2), "utility_per_day_usd": round(m["legit_allowed_usd"] / ndays, 2),
            "utility_share": round(m["legit_allowed_usd"] / m["legit_usd"], 5) if m["legit_usd"] else 1.0,
            "false_refusal_rate": round(m["legit_refused"] / m["legit_n"], 5) if m["legit_n"] else 0.0,
            "legit_held": m["legit_held"], "approvals_per_day": round(m["holds"] / ndays, 2),
            "leaked_usd": round(m["leaked_usd"], 2), "leaked_per_day_usd": round(m["leaked_usd"] / ndays, 2),
            "blocked_usd": round(m["blocked_usd"], 2), "bad_usd": round(m["bad_usd"], 2),
            "blocked_share": round(m["blocked_usd"] / m["bad_usd"], 5) if m["bad_usd"] else 1.0,
            "leaked_by_label": {k: round(v, 2) for k, v in sorted(m["leaked_by_label"].items())}}


def candidate_book(c: Candidate, ranked: list[str], symbols_fallback: list[str] | None = None) -> EnvelopeBook:
    syms = ranked[: max(c.breadth, 0)] or ["__NONE__"]
    book = EnvelopeBook(_KEY.public_key())
    book.add(make_envelope(_KEY, name="candidate", owner="lab", purpose="frontier candidate", symbols=syms, per_order=c.per_order, daily=c.daily,
                           band_pct=c.band_pct, step_up=c.step_up))
    return book


def evaluate(events: list[dict], c: Candidate, profile: dict, steps_per_day: int) -> dict:
    r = replay_stream(events, candidate_book(c, profile["ranked_symbols"]), steps_per_day=steps_per_day, agent_share=c.agent_share, days=profile["ndays"])
    return {**asdict(c), "label": c.label(), **r}


def baseline_result(events: list[dict], meta: dict, steps_per_day: int, *, days: int | None = None) -> dict | None:
    """The envelopes the stream was recorded under, replayed the same way (pinned per sleeve)."""
    specs = meta.get("envelopes")
    if not specs:
        return None
    book = EnvelopeBook(_KEY.public_key())
    for s in specs:
        book.add(make_envelope(_KEY, name=s["name"], owner="baseline", purpose=s.get("purpose", ""), symbols=s["symbols"], per_order=s["per_order"],
                               daily=s["daily"], band_pct=s["band_pct"], step_up=s.get("step_up")))
    agent_share = (meta.get("config") or {}).get("agent_share")
    r = replay_stream(events, book, steps_per_day=steps_per_day, pin={n: n for n in {e["sleeve"] for e in events}}, agent_share=agent_share, days=days)
    return {"label": "baseline (the envelopes the swarm ran under)", **r}


def latin_hypercube(profile: dict, n: int, seed: int = 0) -> list[Candidate]:
    rng = np.random.default_rng(seed)
    q = profile["order_q"]
    sym_n = len(profile["ranked_symbols"])
    daily_base = profile["legit_daily_usd"]
    lo = {"per_order": np.log(max(q[0.9], 500.0)), "daily": np.log(daily_base * 0.5), "band": np.log(0.5), "breadth": max(1.0, 0.4 * sym_n), "su": 0.0, "share": 0.0}
    hi = {"per_order": np.log(max(q[1.0] * 3, q[0.999] * 3)), "daily": np.log(daily_base * 3.0), "band": np.log(8.0), "breadth": float(sym_n), "su": 1.0, "share": 1.0}
    dims = list(lo)
    u = np.empty((n, len(dims)))
    for j in range(len(dims)):
        u[:, j] = (rng.permutation(n) + rng.random(n)) / n
    out = []
    for i in range(n):
        v = {d: lo[d] + u[i, j] * (hi[d] - lo[d]) for j, d in enumerate(dims)}
        su_frac = v["su"]
        per_order = float(np.exp(v["per_order"]))
        out.append(Candidate(round(per_order, 2), round(float(np.exp(v["daily"])), 2), round(float(np.exp(v["band"])), 2),
                             int(round(v["breadth"])) if sym_n else 0, None if su_frac < 0.25 else round(per_order * (0.3 + 0.7 * su_frac), 2),
                             SHARES[min(int(v["share"] * len(SHARES)), len(SHARES) - 1)]))
    return out


def axis_sweeps(profile: dict, base: Candidate) -> dict[str, list[Candidate]]:
    """One-at-a-time sweeps around `base` (used for the monotonicity report and for plotting a single knob)."""
    q, sym_n, dd = profile["order_q"], len(profile["ranked_symbols"]), profile["legit_daily_usd"]
    def rep(**kw):
        return Candidate(**{**asdict(base), **kw})
    return {
        "per_order": [rep(per_order=round(v, 2)) for v in sorted({max(q[0.5], 500.0), q[0.9], q[0.99], q[0.999], q[1.0], q[1.0] * 2, q[1.0] * 4})],
        "daily": [rep(daily=round(dd * f, 2)) for f in (0.5, 0.75, 1.0, 1.5, 2.5, 4.0)],
        "band_pct": [rep(band_pct=b) for b in (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)],
        "agent_share": [rep(agent_share=v) for v in (0.005, 0.01, 0.02, 0.05, None)],
        "breadth": [rep(breadth=b) for b in sorted({max(1, sym_n // 4), max(1, sym_n // 2), max(1, 3 * sym_n // 4), sym_n})],
    }


def pareto(results: list[dict]) -> list[dict]:
    """Non-dominated in (utility_usd up, leaked_usd down). Ties on both are kept once, the one with fewer approvals first."""
    pts = sorted(results, key=lambda r: (-r["utility_usd"], r["leaked_usd"], r["approvals_per_day"]))
    out, best_leak = [], float("inf")
    for r in pts:
        if r["leaked_usd"] < best_leak - 1e-9:
            out.append(r)
            best_leak = r["leaked_usd"]
    return sorted(out, key=lambda r: r["leaked_usd"])


def monotonicity(events, profile, base: Candidate, steps_per_day: int) -> dict:
    """For each knob, loosening it (in sweep order) should not reduce utility or reduce leak. Lists every step where it does not."""
    rep = {}
    for axis, cands in axis_sweeps(profile, base).items():
        rows = [evaluate(events, c, profile, steps_per_day) for c in cands]
        viol = []
        for i in range(len(rows) - 1):
            a, b = rows[i], rows[i + 1]
            if b["utility_usd"] < a["utility_usd"] - 1e-6 or b["leaked_usd"] < a["leaked_usd"] - 1e-6:
                viol.append({"from": getattr(cands[i], axis), "to": getattr(cands[i + 1], axis),
                             "utility_change_usd": round(b["utility_usd"] - a["utility_usd"], 2), "leak_change_usd": round(b["leaked_usd"] - a["leaked_usd"], 2)})
        rep[axis] = {"points": [{axis: getattr(c, axis), "utility_usd": r["utility_usd"], "leaked_usd": r["leaked_usd"], "approvals_per_day": r["approvals_per_day"],
                                 "false_refusal_rate": r["false_refusal_rate"]} for c, r in zip(cands, rows)], "violations": viol}
    return rep


def recommend(results: list[dict], profile: dict, *, max_leak_per_day: float, max_approvals_per_day: float, max_false_refusal: float | None = None,
              baseline: dict | None = None, attempted_bad_per_day: float | None = None) -> dict:
    feas = [r for r in results if r["leaked_per_day_usd"] <= max_leak_per_day and r["approvals_per_day"] <= max_approvals_per_day
            and (max_false_refusal is None or r["false_refusal_rate"] <= max_false_refusal)]
    budget = {"max_leak_per_day_usd": max_leak_per_day, "max_approvals_per_day": max_approvals_per_day, "max_false_refusal_rate": max_false_refusal}
    if not feas:
        near = min(results, key=lambda r: (max(r["leaked_per_day_usd"] - max_leak_per_day, 0) / max(max_leak_per_day, 1) +
                                             max(r["approvals_per_day"] - max_approvals_per_day, 0) / max(max_approvals_per_day, 1), -r["utility_usd"]))
        return {"risk_budget": budget, "feasible": False, "candidate": near, "proposed_mandate": proposed_mandate(near, profile),
                "explanation": f"No candidate meets the whole risk budget on this stream. The closest is {near['label']}, which would still leak "
                               f"${near['leaked_per_day_usd']:,.0f}/day and need {near['approvals_per_day']:.0f} approvals/day. Loosen the budget or change the swarm "
                               f"(fewer failing agents, a smaller cap) before signing anything. This is advice; you sign."}
    best = max(feas, key=lambda r: (r["utility_usd"], -r["leaked_usd"], -r["per_order"]))
    ex = (f"On the recorded stream (about {profile['ndays']} simulated days), an envelope with a per-order cap of ${best['per_order']:,.0f}, a daily cap of "
          f"${best['daily']:,.0f}, a {best['band_pct']:g}% price band, {best['breadth']} of {len(profile['ranked_symbols'])} symbols on the allow-list and "
          f"{'a human step-up above $' + format(best['step_up'], ',.0f') if best['step_up'] is not None else 'no size-based human step-up'}"
          f"{' and a fair-share limit of ' + format(best['agent_share'], '.1%') + ' of the daily cap per agent' if best.get('agent_share') else ''} would have authorized "
          f"${best['utility_per_day_usd']:,.0f}/day of legitimate orders ({best['utility_share']:.1%} of what honest agents proposed), refused "
          f"{best['false_refusal_rate']:.1%} of legitimate proposals, leaked ${best['leaked_per_day_usd']:,.0f}/day of bad orders "
          f"(blocked {best['blocked_share']:.1%} of bad notional) and asked a human to approve {best['approvals_per_day']:.0f} orders/day.")
    if baseline:
        ex += (f" The envelopes the swarm actually ran under would have leaked ${baseline['leaked_per_day_usd']:,.0f}/day with {baseline['false_refusal_rate']:.1%} "
               f"false refusals and {baseline['approvals_per_day']:.0f} approvals/day.")
    ex += (" Why this one: among candidates inside your risk budget it allows the most legitimate notional. What is left in the leak is bad orders that sit "
           "inside the envelope by design (an order at 95% of the cap is indistinguishable from a legitimate one); only a tighter envelope removes it, "
           "at the cost of the legitimate flow shown on the frontier. This is advice from a simulated stream; you review and sign. Agents never widen it.")
    return {"risk_budget": budget, "feasible": True, "candidate": best, "proposed_mandate": proposed_mandate(best, profile), "explanation": ex}


def proposed_mandate(r: dict, profile: dict) -> dict:
    """An UNSIGNED mandate body for the human to review. No signature, no key."""
    body = {"symbols": sorted(profile["ranked_symbols"][: r["breadth"]]), "sides": ["buy", "sell"], "maxOrderNotionalUsd": r["per_order"],
            "maxDailyNotionalUsd": r["daily"], "priceBandPct": r["band_pct"], "expiresAt": "<set by you>"}
    if r.get("step_up") is not None:
        body["stepUpAboveUsd"] = r["step_up"]
    if r.get("agent_share") is not None:
        body["_operatorPolicy"] = {"perAgentShareOfDailyCap": r["agent_share"], "note": "enforced by the authority, not part of the signed mandate"}
    return body


def run_frontier(events: list[dict], meta: dict, *, samples: int = 240, seed: int = 0, max_leak_per_day: float | None = None,
                 max_approvals_per_day: float | None = None, max_false_refusal: float | None = 0.05, steps_per_day: int | None = None,
                 with_monotonicity: bool = True) -> dict:
    config = meta.get("config") or {}
    spd = int(steps_per_day or config.get("steps_per_day") or 500)
    profile = stream_profile(events, spd, steps=config.get("steps"))
    n_agents = int(config.get("agents") or meta.get("agents") or 1000)
    max_leak_per_day = max_leak_per_day if max_leak_per_day is not None else 250.0 * n_agents
    max_approvals_per_day = max_approvals_per_day if max_approvals_per_day is not None else 0.06 * n_agents
    cands = latin_hypercube(profile, samples, seed)
    sym_n = len(profile["ranked_symbols"])
    q = profile["order_q"]
    anchors = [Candidate(1.0, 1.0, 0.1, 0, None),                                               # deny everything
               Candidate(q[1.0] * 100, profile["legit_daily_usd"] * 100, 50.0, sym_n, None)]    # wide open
    results = [evaluate(events, c, profile, spd) for c in anchors + cands]
    ndays = profile["ndays"]
    base = baseline_result(events, meta, spd, days=ndays)
    attempted = sum(e["risk"] for e in events if e["label"] != "legit" and not e.get("replay")) / ndays
    rec = recommend(results, profile, max_leak_per_day=max_leak_per_day, max_approvals_per_day=max_approvals_per_day, max_false_refusal=max_false_refusal,
                    baseline=base, attempted_bad_per_day=attempted)
    mono = None
    if with_monotonicity:
        c0 = rec["candidate"]
        mono = monotonicity(events, profile, Candidate(c0["per_order"], c0["daily"], c0["band_pct"], c0["breadth"], c0["step_up"], c0.get("agent_share")), spd)
    front = pareto(results)
    return {"profile": {k: v for k, v in profile.items() if k != "ranked_symbols"} | {"symbols": profile["ranked_symbols"]},
            "bad_attempted_per_day_usd": round(attempted, 2), "baseline": base, "candidates": len(results), "frontier": front, "recommendation": rec,
            "monotonicity": mono, "all": results,
            "caveats": ["The stream comes from simulated agents; real agents differ.", "Replay is open-loop: agents do not react to refusals.",
                        "One envelope covers the whole stream and its daily budget is shared by every agent.",
                        "Leak includes bad orders that lie inside any envelope loose enough to let legitimate flow through.",
                        "The frontier is advice. The human reviews and signs; agents and the lab never choose or widen an envelope."]}
