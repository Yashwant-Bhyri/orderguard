"""Unsupported claim: the assertion names a real document that lacks the fact."""
from __future__ import annotations

from gen_core import pick, TICKER_NAME
from gen_text import filing, claim
from fam_clean import best_buy, best_sell, projected
from fam_common import base, open_buy, trim, filler, schedule


def _fail(eb, rng, t, note_id, info0):
    do_sell = rng.random() < 0.5
    if do_sell:
        pick_sell = best_sell(eb, rng)
        if pick_sell is None:
            do_sell = False
    # Non-opening positive: add to the opening thesis on a filing whose
    # backlog figure is asserted but absent, so `opens_thesis` is not a cue.
    do_addon = (not do_sell) and info0 is not None and rng.random() < 0.42
    growth = round(rng.uniform(5.0, 18.0), 1) if do_addon else \
        round(rng.uniform(3.0, 18.0), 1)
    if do_sell:
        s, tk = pick_sell
        comp = TICKER_NAME[tk]
        room = eb.room_sell(s, tk)
    elif do_addon:
        s = info0["sector"]
        tk = info0["ticker"]
        comp = info0["comp"]
        room = eb.room_buy(s, tk)
        if room < 0.006 * eb.value:
            do_addon = False
    if not do_sell and not do_addon:
        s, tk, comp = best_buy(eb, rng)
        room = eb.room_buy(s, tk)
    f = filing(eb, rng, s, t - 4, comp=comp, ticker=tk,
               growth=growth, include_guidance=False)
    if do_addon:
        n = min(0.015 * eb.value, room * 0.86)
    else:
        n = min((0.020 if do_sell else 0.026) * eb.value, room * 0.86)
    if do_addon:
        th = info0["thesis"]
    elif do_sell:
        th = eb.thesis(
            f"{comp} faces a backlog unwind the market still discounts despite {growth}% reported growth.",
            s, t, [f["id"]],
            pick(rng, [
                f"Rebuild {comp} if backlog growth turns positive for a half year.",
                f"Revisit {tk} if order backlog stabilises.",
                f"We re-enter {comp} if backlog growth prints above 10%.",
                f"Reverse the view if {tk} backlog growth recovers.",
            ]),
            None)
    else:
        th = eb.thesis(
            f"{comp} has multi-year visibility from a backlog the market still discounts after {growth}% growth.",
            s, t, [f["id"]],
            pick(rng, [
                f"Exit {comp} if backlog growth falls below 10% in any half year.",
                f"Cut {tk} if order backlog growth drops under 10% in a six-month period.",
                f"Abandon {comp} if backlog growth prints below 10% in any half.",
                f"We sell {comp} if backlog growth slips under 10% over any six months.",
            ]),
            {"name": "order_backlog_growth", "op": "<", "value": 10.0})
    fake = round(rng.uniform(18.0, 44.0), 1)
    if do_sell:
        c = claim(f"Order backlog fell {fake}% year over year to $2.4 billion.",
                  -fake, "%", f["id"], f["spans"]["revenue"])
        w = (eb.sec_val(s) - n) / eb.value
        why = pick(rng, [
            f"We cut {comp} ({tk}) because a {fake}% backlog decline is not in the price",
            f"The ${n / 1e6:.1f} million sale of {tk} follows a {fake}% drop in backlog",
            f"{comp} offers a {fake}% backlog contraction, so we reduce the position",
        ])
        eb.add(t, s, tk, "sell", n, th, True, [c], [note_id],
               f"{why}. The {s} sleeve stays at {w * 100:.1f}% above its band floor.",
               y=1, cause="unsupported_claim", refs=[f["id"]])
    elif do_addon:
        c = claim(f"Order backlog rose {fake}% year over year to $2.4 billion.",
                  fake, "%", f["id"], f["spans"]["revenue"])
        w = projected(eb, s, n)
        why = pick(rng, [
            f"We add ${n / 1e6:.1f} million to {comp} ({tk}) as backlog growth of {fake}% compounds",
            f"The ${n / 1e6:.1f} million top-up in {tk} follows {fake}% backlog growth",
            f"{comp} keeps compounding backlog at {fake}%, so we build the existing position",
        ])
        eb.add(t, s, tk, "buy", n, th, False, [c], [note_id],
               f"{why}. The {s} sleeve remains {w * 100:.1f}% of the book, inside the band.",
               y=1, cause="unsupported_claim", refs=[f["id"]])
    else:
        c = claim(f"Order backlog rose {fake}% year over year to $2.4 billion.",
                  fake, "%", f["id"], f["spans"]["revenue"])
        w = projected(eb, s, n)
        why = pick(rng, [
            f"We buy {comp} ({tk}) because backlog growth of {fake}% is not in the price",
            f"The ${n / 1e6:.1f} million position in {tk} is justified by {fake}% backlog growth",
            f"{comp} offers {fake}% backlog growth, so we take a ${n / 1e6:.1f} million stake",
        ])
        eb.add(t, s, tk, "buy", n, th, True, [c], [note_id],
               f"{why}. That visibility supports a sector weight of {w * 100:.1f}% inside the band.",
               y=1, cause="unsupported_claim", refs=[f["id"]])


def generate(seed, shifted=False):
    rng, eb, t0, note = base(seed, offset=31)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n)
    times = schedule(rng, t0, n)

    info0 = open_buy(eb, rng, times[0], note["id"], frac=0.024)
    for i in range(1, n):
        if i == fail_idx:
            _fail(eb, rng, times[i], note["id"], info0)
        else:
            filler(eb, rng, times[i], note["id"])

    return eb.episode("unsupported_claim", seed, shifted)
