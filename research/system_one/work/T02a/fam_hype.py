"""Vague hype: the buy rests on enthusiasm with no figure anywhere in the claim."""
from __future__ import annotations

from gen_core import pick
from gen_text import news, claim
from fam_clean import best_buy, projected
from fam_common import base, open_buy, trim, filler, schedule


def _fail(eb, rng, t, note_id):
    s, tk, comp = best_buy(eb, rng)
    nw = news(eb, rng, s, t - 4, comp=comp, ticker=tk)
    n = min(0.023 * eb.value, eb.room_buy(s, tk) * 0.85)
    th = eb.thesis(
        f"{comp} is on the cusp of a step change in relevance that the market misprices at a ${n / 1e6:.1f} million entry point.",
        s, t, [nw["id"]],
        pick(rng, [
            f"Step away from {comp} if the story loses momentum for a full quarter.",
            f"Cut {tk} if the narrative goes quiet for a quarter.",
            f"We exit {comp} if the catalyst slips by a full quarter.",
            f"Drop the position if the {tk} story stalls for a quarter.",
        ]),
        None)
    c = claim(
        pick(rng, [
            f"The {tk} franchise is early in a multi-year re-rating and the upside is far larger than the tape implies.",
            f"{comp} has a momentum that rarely appears, and the market simply has not caught on.",
            f"We think the story in {comp} is about to inflect in a way the numbers do not yet show.",
        ]), None, None, nw["id"], None)
    w = projected(eb, s, n)
    why = pick(rng, [
        f"We lean into {comp} ({tk}) because the setup is extraordinary and the risk-reward is exceptional",
        f"The ${n / 1e6:.1f} million add in {tk} backs a story that feels early and powerful",
        f"{comp} has the kind of momentum that comes along rarely, so we take a ${n / 1e6:.1f} million position",
    ])
    eb.add(t, s, tk, "buy", n, th, True, [c], [note_id],
           f"{why}. The sector weight is {w * 100:.1f}%, so nothing in the mandate is strained.",
           y=1, cause="vague_hype", refs=[nw["id"]])


def generate(seed, shifted=False):
    rng, eb, t0, note = base(seed, offset=51)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n)
    times = schedule(rng, t0, n)

    open_buy(eb, rng, times[0], note["id"], frac=0.022)
    for i in range(1, n):
        if i == fail_idx:
            _fail(eb, rng, times[i], note["id"])
        else:
            filler(eb, rng, times[i], note["id"])

    return eb.episode("vague_hype", seed, shifted)
