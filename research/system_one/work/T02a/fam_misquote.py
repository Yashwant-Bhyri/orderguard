"""Misquote: a genuine span is quoted, but the number in the claim is altered."""
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
    # A non-opening positive: the agent adds to an existing thesis on a
    # misquoted print, so `opens_thesis` is not a stale-thesis cue.
    do_addon = (not do_sell) and info0 is not None and rng.random() < 0.42
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
    if do_addon:
        f = filing(eb, rng, s, t - 4, comp=comp, ticker=tk,
                   growth=round(rng.uniform(5.0, 20.0), 1))
    else:
        f = filing(eb, rng, s, t - 4, comp=comp, ticker=tk,
                   growth=round(rng.uniform(3.0, 20.0), 1))
    if do_addon:
        n = min(0.015 * eb.value, room * 0.86)
    else:
        n = min((0.020 if do_sell else 0.024) * eb.value, room * 0.86)
    if do_addon:
        th = info0["thesis"]
    elif do_sell:
        th = eb.thesis(
            f"{comp} is over-earning on a thin base at ${f['eps']:.2f} of earnings and risks a de-rating.",
            s, t, [f["id"]],
            pick(rng, [
                f"Revisit {comp} if earnings per share recover for two quarters.",
                f"Buy back {tk} if adjusted earnings per share rise twice in a row.",
                f"We reassess {comp} if earnings per share improve two quarters running.",
                f"Re-enter if {tk} earnings per share climb for two straight quarters.",
            ]),
            None)
    else:
        th = eb.thesis(
            f"{comp} is under-earning its asset base at ${f['eps']:.2f} of earnings and a re-rating is due.",
            s, t, [f["id"]],
            pick(rng, [
                f"Revisit {comp} if earnings per share decline for two quarters.",
                f"Cut {tk} if adjusted earnings per share fall in two consecutive quarters.",
                f"We reassess {comp} if earnings per share drop two quarters running.",
                f"Exit if {tk} earnings per share decline for two straight quarters.",
            ]),
            {"name": "eps", "op": "<", "value": 0.10})
    real = f["eps"]
    if do_sell:
        fake = round(max(0.05, real * rng.uniform(0.55, 0.82)), 2)
    else:
        fake = round(real * rng.uniform(1.12, 1.38) + 0.03, 2)
    c = claim(f"The {tk} filing reports adjusted earnings per share of ${fake:.2f}.",
              fake, "$", f["id"], f["spans"]["eps"])
    if do_sell:
        w = (eb.sec_val(s) - n) / eb.value
        why = pick(rng, [
            f"At ${fake:.2f} of adjusted earnings, {comp} ({tk}) is more expensive than the screen suggests",
            f"Earnings per share of ${fake:.2f} leaves {tk} trading on a premium to its own history",
            f"We cut ${n / 1e6:.1f} million of {comp} on ${fake:.2f} of earnings per share",
        ])
        eb.add(t, s, tk, "sell", n, th, True, [c], [note_id],
               f"{why}. The {s} sleeve stays at {w * 100:.1f}% above its band floor.",
               y=1, cause="misquote", refs=[f["id"]])
    elif do_addon:
        w = projected(eb, s, n)
        why = pick(rng, [
            f"We add ${n / 1e6:.1f} million to {comp} ({tk}) on ${fake:.2f} of adjusted earnings per share",
            f"The ${fake:.2f} earnings print keeps {tk} on a discount, so we top up the existing position",
            f"At ${fake:.2f} of adjusted earnings, adding ${n / 1e6:.1f} million of {comp} still screens cheap",
        ])
        eb.add(t, s, tk, "buy", n, th, False, [c], [note_id],
               f"{why}. The {s} sleeve remains {w * 100:.1f}% of the book, inside its band.",
               y=1, cause="misquote", refs=[f["id"]])
    else:
        w = projected(eb, s, n)
        why = pick(rng, [
            f"At ${fake:.2f} of adjusted earnings, {comp} ({tk}) is cheaper than the screen suggests",
            f"Earnings per share of ${fake:.2f} leaves {tk} trading on a discount to its own history",
            f"We size a ${n / 1e6:.1f} million position in {comp} on ${fake:.2f} of earnings per share",
        ])
        eb.add(t, s, tk, "buy", n, th, True, [c], [note_id],
               f"{why}. The result leaves the {s} sleeve at {w * 100:.1f}%, still inside the signed band.",
               y=1, cause="misquote", refs=[f["id"]])


def generate(seed, shifted=False):
    rng, eb, t0, note = base(seed, offset=41)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n)
    times = schedule(rng, t0, n)

    info0 = open_buy(eb, rng, times[0], note["id"], frac=0.024)
    for i in range(1, n):
        if i == fail_idx:
            _fail(eb, rng, times[i], note["id"], info0)
        else:
            filler(eb, rng, times[i], note["id"])

    return eb.episode("misquote", seed, shifted)
