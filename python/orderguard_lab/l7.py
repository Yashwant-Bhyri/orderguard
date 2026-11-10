"""L7 in the lab: a thin shim. The trigger graph now runs inside the guard's agent loop (orderguard_guard.agent, arm `full`), before an
order reaches L5/L8, so a held order never touches the ledger. This module only summarises the transcript's L7 gate records for the
result's `l7` field (the layer attribution "L7" itself comes from the gate record's `layer`)."""
from __future__ import annotations


def l7_info(tr: dict, arm: str, rules_active: bool = True) -> dict:
    if arm != "full" or not rules_active:
        return {"applied": False}
    held, fired = [], []
    for c in tr.get("calls", []):
        g = c.get("gate") if c.get("name") == "place_order" else None
        if not isinstance(g, dict):
            continue
        rid = (g.get("checks") or {}).get("rule")
        if g.get("layer") == "L7" and g.get("decision") == "hold":
            held.append(rid)
        elif g.get("decision") == "allow" and (g.get("checks") or {}).get("l7_rule"):
            fired.append(g["checks"]["l7_rule"])
    return {"applied": True, "fires": sorted(set(fired)), "held": held}
