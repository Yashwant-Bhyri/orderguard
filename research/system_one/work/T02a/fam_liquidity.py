"""Novel family: liquidity breach.

The agent sizes a position beyond what the name's average daily volume can
absorb inside the owner-signed exit policy. Every quoted number is true; the
failure is the arithmetic the agent never does.
"""
from __future__ import annotations

from gen_core import SECTORS, UNIVERSE, pick
from gen_text import liquidity, news, claim
from fam_common import base, open_buy, trim, filler, schedule


def _plan(eb, rng, days, part):
    """Choose a fresh (unheld) name whose new order both breaches the exit
    policy and sits above the policy's own screening threshold.

    The family reasons about the new order alone, so the ticker must start
    unheld: that makes the stated days equal the post-trade position days and
    keeps the corrective sale below the screening threshold.
    """
    value = eb.value
    cands = []
    for s in SECTORS:
        if eb.bands[s]["max"] <= 0:
            continue
        for comp, tk in UNIVERSE[s]:
            pos0 = eb.positions.get(tk, 0.0)
            if pos0 > 1e-6:
                continue
            room = eb.room_buy(s, tk)
            if room < 0.052 * value:
                continue
            desired = min(0.050 * value, room * 0.82)
            if desired < 0.042 * value:
                continue
            slack = eb.sec_val(s) - pos0 - eb.bands[s]["min"] * value
            cands.append((slack, s, tk, comp, desired, pos0))
    rng.shuffle(cands)
    cands.sort(key=lambda c: -c[0])
    for slack, s, tk, comp, desired, pos0 in cands:
        lo = eb.bands[s]["min"] * value
        other = eb.sec_val(s) - pos0
        for _ in range(12):
            u = rng.uniform(1.22, 1.75)
            adv = round(max(0.25, min(25.0, desired / (part * days * u * 1e6))), 1)
            actual = desired / (part * adv * 1e6)
            cap = part * days * adv * 1e6
            # The corrective sale (desired - cap) stays under the screening
            # threshold T = 0.026 * value, and the new order itself is above it.
            if (actual > days * 1.04 and cap >= 0.020 * value
                    and 0.006 * value <= desired - cap <= 0.023 * value
                    and cap >= lo - other + 0.0005 * value):
                return {"sector": s, "ticker": tk, "comp": comp,
                        "desired": desired, "pos0": pos0, "adv": adv,
                        "actual": actual, "cap": cap}
    return None


def _fail(eb, rng, t, note_id, policy, plan, days, part):
    s = plan["sector"]
    tk = plan["ticker"]
    comp = plan["comp"]
    adv = plan["adv"]
    desired = plan["desired"]
    tool = liquidity(eb, rng, tk, t - 4, adv=adv)
    th = eb.thesis(
        f"{comp} can absorb a ${desired / 1e6:.1f} million position without disturbing the price.",
        s, t, [tool["id"]],
        pick(rng, [
            f"Reduce {comp} if the position is still above the {days}-day limit after the corrective sale.",
            f"Cut {tk} if the rebalance fails to bring the exit back under {days} trading days.",
            f"We trim {comp} again if the {days}-day limit is still breached once the sale settles.",
            f"Exit {tk} if the correction does not restore the {days}-day exit by the next session.",
            f"Reduce {comp} if a follow-up check finds the {days}-day limit still breached.",
        ]),
        None)
    c = claim(f"Average daily volume was ${adv:.1f} million for {tk}.",
              adv, "$M", tool["id"], tool["spans"]["adv"])
    w = (eb.sec_val(s) + desired) / eb.value
    why = pick(rng, [
        f"We build a ${desired / 1e6:.1f} million position in {comp} ({tk}) on the liquidity screen",
        f"The ${desired / 1e6:.1f} million order in {tk} reflects the depth the desk reported",
        f"{comp} turns over ${adv:.1f} million a day, so a ${desired / 1e6:.1f} million stake is worth holding",
    ])
    eb.add(t, s, tk, "buy", desired, th, True, [c], [policy["id"], note_id],
           f"{why}. At {part * 100:.0f}% participation the exit would take about "
           f"{plan['actual']:.1f} days to exit at {part * 100:.0f}% of ADV, and {s} sits at {w * 100:.1f}% inside its band.",
           y=1, cause="liquidity_breach", refs=[tool["id"], policy["id"]])
    return th


def _correct(eb, rng, t, note_id, policy, plan, days, part):
    s = plan["sector"]
    tk = plan["ticker"]
    comp = plan["comp"]
    n2 = plan["desired"] + plan["pos0"] - plan["cap"]
    n2 = min(n2, eb.positions[tk] * 0.99)
    if n2 <= 0:
        return
    nw = news(eb, rng, s, t - 2, comp=comp, ticker=tk)
    c2 = claim(f"The {tk} tape shows a {nw['move']}% move in the shares.",
               nw["move"], "%", nw["id"], nw["spans"]["move"])
    w2 = (eb.sec_val(s) - n2) / eb.value
    why2 = pick(rng, [
        f"We cut {tk} by ${n2 / 1e6:.1f} million so the line is inside the signed liquidity envelope",
        f"The ${n2 / 1e6:.1f} million sale brings {comp} down to a size the market can absorb",
        f"To respect the exit policy we reduce {tk} by ${n2 / 1e6:.1f} million",
    ])
    eb.add(t, s, tk, "sell", n2, plan["thesis"], False, [c2], [note_id, policy["id"]],
           f"{why2}; at {part * 100:.0f}% participation it is a {days:.0f}-day exit, "
           f"leaving {s} at {w2 * 100:.1f}% of the book.")


def generate(seed, shifted=False):
    days = pick(__import__("random").Random(seed + 2), [2, 2, 3])
    part = pick(__import__("random").Random(seed + 3), [0.20, 0.25, 0.30])
    purpose = pick(__import__("random").Random(seed), ["balanced", "income",
                                                       "capital_preservation", "growth"])
    rng, eb, t0, note = base(seed, offset=91, purpose=purpose,
                             pol_days=days, pol_part=int(round(part * 100)))
    # The same 4.0%-of-book policy as every other family.  Every padding order
    # in this family is at most 2.2% and the corrective sale is at most 2.3%,
    # while the planted buy is at least 4.2%, so scope is clean.
    policy = eb.prelude["policy"]["note"]

    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n - 1)
    times = schedule(rng, t0, n)

    open_buy(eb, rng, times[0], note["id"], frac=0.022)
    plan = None
    for i in range(1, n):
        if i == fail_idx:
            plan = _plan(eb, rng, days, part)
            if plan is None:
                filler(eb, rng, times[i], note["id"])
                continue
            plan["thesis"] = _fail(eb, rng, times[i], note["id"], policy,
                                   plan, days, part)
        elif i == fail_idx + 1 and plan is not None:
            _correct(eb, rng, times[i], note["id"], policy, plan, days, part)
        elif i < fail_idx:
            filler(eb, rng, times[i], note["id"], mode="trim")
        else:
            skip = {plan["ticker"]} if plan else set()
            filler(eb, rng, times[i], note["id"], skip_ticker=skip)

    return eb.episode("liquidity_breach", seed, shifted)
