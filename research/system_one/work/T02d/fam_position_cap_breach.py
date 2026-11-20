"""Single-instrument concentration exceeds the signed cap inside a compliant sector.

Round 3. The signed single-name ceiling is carried by an owner-signed standing
note, which the label cites. TECH_A starts a random distance below the ceiling.
Ordinary and planted technology buys are drawn from the same size range; only the
planted buy crosses the ceiling. Technology sector weight stays inside its band.
"""
from world import base_episode, breach_plan, note, positive_index, rebook, rng_for, set_tech_buy

TOTAL = 100000.0
CAP = 0.32


def build(seed, shifted=False):
    ep = base_episode(seed, "position_cap_breach", shifted)
    ep["owner"]["sector_bands"]["tech"]["max"] = 0.48
    index = positive_index(seed, "position_cap_breach", shifted)
    room, ordinary, planted, _ = breach_plan(seed, "position_cap_breach", shifted, index, CAP * TOTAL)
    rebook(ep, {"TECH_A": round(CAP * TOTAL - room, 2), "TECH_B": 0.0, "CONSUMER_FUND": 10000.0,
                "HEALTH_FUND": 10000.0, "STAPLES_FUND": 10000.0, "FINANCIALS_FUND": 10000.0,
                "ENERGY_FUND": 5000.0, "INDEX_FUND": 9000.0})
    ref = rng_for(seed, "position_cap_ref", shifted).randint(100, 999)
    cap_note = note(
        "N_single_name_cap", 0,
        f"Standing mandate line SL-{ref}: no single instrument may exceed the signed single-name ceiling of thirty-two percent of total value. "
        f"Line SL-{ref} is part of the mandate and applies to every add, including adds that keep the sector inside its band.",
        writer="owner_signed", signed=True,
    )
    ep["initial_notes"].append(cap_note)
    ep["owner"]["max_position_pct"] = CAP
    if index != 0:
        ep["steps"][0]["action"]["notional"] = ordinary
    step = ep["steps"][index]
    doc = ep["documents"][0]
    issuer = doc["text"].split("For ", 1)[1].split(",", 1)[0]
    set_tech_buy(ep, index, planted)
    step["action"]["rationale"] = (
        f"The {doc['publisher']} release keeps the technology thesis active. "
        f"I am directing the incremental allocation to {issuer}, the clearest expression of the position."
    )
    step["action"]["cites_notes"] = ["N_review_standard"]
    step["label"] = {"y": 1, "cause": "position_cap_breach", "cause_refs": ["N_single_name_cap"]}
    return ep
