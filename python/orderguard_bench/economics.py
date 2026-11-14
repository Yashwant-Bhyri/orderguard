"""Economic outcome at scale, from a run's decision log (the N=1 gate + order-risk run: one global scorer, the shipped model and its
shipped thresholds). Every dollar figure is computed from what the system decided; nothing is modelled on top.

Dollars are notional at the TRUSTED price (quantity x venue median), as in the arena: a homoglyph ticker is valued as the symbol it
imitates, an unlisted ticker at its own limit price, a transfer at its amount. Only first deliveries count: a repeated key that the
authority answered from its idempotency record moved nothing and is reported as absorbed. System traffic (bursts, limit probes, key
conflicts) is excluded from the economics and audited separately.

  stopped by the gate    refused, or held for a human (step-up, unconfirmed news)
  stopped by the risk    the gate allowed it and the order-risk model turned it into a hold or a refusal (tighten-only)
  let through            allowed by both

Caveat (as in docs/RISK.md): the stream is open-loop and the budget a refused colluder would have freed is not re-simulated.
"""
from __future__ import annotations

import json

from orderguard_arena.arena import at_risk

FAMILY = {"legit": "honest", "collusion": "collusion", "collusion_stealth": "collusion_stealth", "collusion_adaptive": "collusion_whitebox",
          "runaway_loop": "runaway", "runaway_dup": "runaway", "fat_finger": "fat_finger", "stale_price": "stale_price", "off_list": "off_list",
          "homoglyph": "off_list", "compromised_oversize": "compromised", "compromised_sell_all": "compromised", "compromised_transfer": "compromised",
          "compromised_unlisted": "compromised", "fake_news": "fake_news"}
SYSTEM = {"burst", "probe", "key_conflict", "ctl"}


class _P:
    __slots__ = ("order",)

    def __init__(self, order):
        self.order = order


def outcome(logs: list[str], prices: list[dict], *, agents: int, days: float) -> dict:
    fam: dict[str, dict] = {}
    honest = {"proposals": 0, "allowed": 0, "held_gate_stepup": 0, "held_gate_l7": 0, "held_risk": 0, "refused_gate": 0, "refused_risk": 0,
              "allowed_usd": 0.0, "proposed_usd": 0.0}
    holds_total = 0
    absorbed = {"deliveries": 0, "bad_usd": 0.0}
    for lp in logs:
        with open(lp, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line.split(" ", 1)[1])
                if rec.get("x") == "ctl" or rec.get("l") in SYSTEM:
                    if rec.get("d") == "hold":
                        holds_total += 1
                    continue
                g, d = rec["g"], rec["d"]
                if d == "hold" and not rec["r"]:
                    holds_total += 1
                usd = at_risk(_P(rec["q"]), rec["p"], prices[rec["t"]])
                f = FAMILY.get(rec["l"], rec["l"])
                if rec["r"] or rec["x"] in ("retry", "dup_now"):
                    absorbed["deliveries"] += 1
                    if f != "honest":
                        absorbed["bad_usd"] += usd
                    continue
                if f == "honest":
                    h = honest
                    h["proposals"] += 1
                    h["proposed_usd"] += usd
                    if d == "allow":
                        h["allowed"] += 1
                        h["allowed_usd"] += usd
                    elif g == "hold":
                        h["held_gate_l7" if rec.get("y") == "L7" else "held_gate_stepup"] += 1
                    elif g == "refuse":
                        h["refused_gate"] += 1
                    elif d == "hold":
                        h["held_risk"] += 1
                    else:
                        h["refused_risk"] += 1
                    continue
                b = fam.setdefault(f, {"proposals": 0, "proposed_usd": 0.0, "gate_refused_usd": 0.0, "gate_held_usd": 0.0, "risk_held_usd": 0.0,
                                       "risk_refused_usd": 0.0, "let_through_usd": 0.0})
                b["proposals"] += 1
                b["proposed_usd"] += usd
                if g == "refuse":
                    b["gate_refused_usd"] += usd
                elif g == "hold":
                    b["gate_held_usd"] += usd
                elif d == "hold":
                    b["risk_held_usd"] += usd
                elif d == "refuse":
                    b["risk_refused_usd"] += usd
                else:
                    b["let_through_usd"] += usd
    tot = {k: round(sum(v[k] for v in fam.values()), 2) for k in ("proposed_usd", "gate_refused_usd", "gate_held_usd", "risk_held_usd", "risk_refused_usd", "let_through_usd")}
    for v in fam.values():
        for k in list(v):
            if k.endswith("_usd"):
                v[k] = round(v[k], 2)
        v["stopped_share"] = round(1 - v["let_through_usd"] / v["proposed_usd"], 5) if v["proposed_usd"] else None
    gate_through = tot["let_through_usd"] + tot["risk_held_usd"] + tot["risk_refused_usd"]
    n = honest["proposals"] or 1
    honest_holds = honest["held_gate_stepup"] + honest["held_gate_l7"] + honest["held_risk"]
    return {
        "bad": {**tot, "stopped_by_gate_usd": round(tot["gate_refused_usd"] + tot["gate_held_usd"], 2),
                "stopped_by_risk_usd": round(tot["risk_held_usd"] + tot["risk_refused_usd"], 2),
                "let_through_if_gate_only_usd": round(gate_through, 2),
                "stopped_share": round(1 - tot["let_through_usd"] / tot["proposed_usd"], 5) if tot["proposed_usd"] else None,
                "stopped_share_gate_only": round(1 - gate_through / tot["proposed_usd"], 5) if tot["proposed_usd"] else None,
                "let_through_per_day_usd": round(tot["let_through_usd"] / days, 2)},
        "by_family": dict(sorted(fam.items())),
        "honest": {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in honest.items()},
                   "allowed_share": round(honest["allowed"] / n, 5), "held_share": round(honest_holds / n, 5),
                   "refused_share": round((honest["refused_gate"] + honest["refused_risk"]) / n, 5),
                   "held_by_risk_share_of_gate_allowed": round(honest["held_risk"] / max(honest["allowed"] + honest["held_risk"] + honest["refused_risk"], 1), 5),
                   "holds_per_day": round(honest_holds / days, 2)},
        "review_load": {"holds_per_day": round(holds_total / days, 2), "holds_per_day_per_1000_agents": round(holds_total / days / agents * 1000, 2),
                        "note": "every hold (gate step-up, unconfirmed news, risk model) is one human decision"},
        "absorbed_duplicates": {"deliveries": absorbed["deliveries"], "bad_usd": round(absorbed["bad_usd"], 2)},
        "days": days, "agents": agents,
    }
