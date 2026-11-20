"""Drift: a sector already at its ceiling is pushed further out by a buy."""
from __future__ import annotations

import random

from gen_core import UNIVERSE, pick, TICKER_NAME
from gen_text import filing, news, claim, REVIEW_MONTHS
from fam_common import base, open_buy, trim, filler, schedule


def _onset(eb, rng, t, drift, note_id):
    names = list(UNIVERSE[drift])
    rng.shuffle(names)
    comp, tk = min(names, key=lambda x: eb.positions.get(x[1], 0.0))
    posmax = max(eb.positions.get(x[1], 0.0) for x in UNIVERSE[drift])
    f = filing(eb, rng, drift, t - 4, comp=comp, ticker=tk,
               growth=round(rng.uniform(6.0, 24.0), 1))
    gap = eb.bands[drift]["max"] * eb.value - eb.sec_val(drift)
    extra = min(rng.uniform(0.012, 0.026) * eb.value,
                0.86 * posmax - 0.006 * eb.value)
    extra = max(extra, 0.004 * eb.value)
    n = min(gap + extra, eb.cash * 0.92)
    th = eb.thesis(
        f"{comp} is gaining share in the {drift} sleeve after {f['growth']}% growth and should carry a larger allocation.",
        drift, t, [f["id"]],
        # The trigger sits well above the largest planted overshoot (2.6
        # points) so the opening buy cannot invalidate its own thesis.
        pick(rng, [
            f"Trim {comp} if the {drift} weight is more than 5 points above the signed cap",
            f"Cut {tk} if the {drift} sleeve runs more than 5 points over its ceiling",
            f"Reduce {comp} if the {drift} band is breached by more than 5 points",
            f"Exit {tk} if the {drift} allocation overshoots the cap by more than 5 points",
            f"We trim {comp} if the {drift} sleeve sits more than 5 points above the signed maximum",
        ]) + f", with the line next due at the {pick(rng, REVIEW_MONTHS)} committee (item {rng.randrange(10, 99)}).",
        None)
    c = claim(f"The {tk} filing shows growth of {f['growth']}% year over year.",
              f["growth"], "%", f["id"], f["spans"]["growth"])
    w = (eb.sec_val(drift) + n) / eb.value
    why = pick(rng, [
        f"We add {comp} ({tk}) because the ${n / 1e6:.1f} million order only nudges {drift} to {w * 100:.1f}% of the book",
        f"The {tk} upgrade is worth acting on and the ${n / 1e6:.1f} million add takes {drift} to {w * 100:.1f}%",
        f"Adding ${n / 1e6:.1f} million of {tk} expresses the {drift} view and leaves the sector at {w * 100:.1f}%",
    ])
    tail = pick(rng, [
        f"At {w * 100:.1f}% the {drift} position size is comfortable for a sector growing {f['growth']:.1f}%",
        f"We are happy carrying {drift} at {w * 100:.1f}% while {tk} grows revenue at {f['growth']:.1f}%",
        f"The {drift} sleeve at {w * 100:.1f}% is proportionate to {f['growth']:.1f}% growth",
    ])
    eb.add(t, drift, tk, "buy", n, th, True, [c], [note_id],
           f"{why}. {tail[0].upper() + tail[1:]}.",
           y=1, cause="drift", refs=[f["id"]])
    return th


def _correct(eb, rng, t, drift, note_id, th):
    pos_tk = max(eb.holdings(drift), key=lambda x: eb.positions[x])
    nw = news(eb, rng, drift, t - 2, comp=TICKER_NAME[pos_tk], ticker=pos_tk)
    target = (eb.bands[drift]["max"] - 0.010) * eb.value
    n2 = min(eb.sec_val(drift) - target, eb.positions[pos_tk] * 0.94)
    n2 = max(n2, 0.0)
    w2 = (eb.sec_val(drift) - n2) / eb.value
    c2 = claim(f"The {pos_tk} tape shows a {nw['move']}% move in the shares.",
               nw["move"], "%", nw["id"], nw["spans"]["move"])
    why2 = pick(rng, [
        f"We sell ${n2 / 1e6:.1f} million of {pos_tk} to take the {drift} sleeve back to {w2 * 100:.1f}%",
        f"The ${n2 / 1e6:.1f} million trim in {pos_tk} restores the {drift} sleeve to {w2 * 100:.1f}% of the book",
        f"After the ${n2 / 1e6:.1f} million sale of {pos_tk}, the {drift} sleeve sits at {w2 * 100:.1f}%",
    ])
    tail = (" inside the signed range." if w2 <= eb.bands[drift]["max"]
            else " and we will finish the rebalance next session.")
    eb.add(t, drift, pos_tk, "sell", n2, th, False, [c2], [note_id],
           f"{why2}{tail}")


def generate(seed, shifted=False):
    purpose = pick(random.Random(seed), ["growth", "balanced", "income",
                                          "capital_preservation"])
    drift = pick(random.Random(seed + 3), ["tech", "index"])
    rng, eb, t0, note = base(seed, purpose=purpose, near_max=drift, offset=21)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n - 1)
    times = schedule(rng, t0, n)

    open_buy(eb, rng, times[0], note["id"], exclude={drift}, frac=0.020)
    th = None
    for i in range(1, n):
        if i == fail_idx:
            th = _onset(eb, rng, times[i], drift, note["id"])
        elif i == fail_idx + 1:
            _correct(eb, rng, times[i], drift, note["id"], th)
        elif i < fail_idx:
            filler(eb, rng, times[i], note["id"], exclude={drift}, mode="trim")
        else:
            filler(eb, rng, times[i], note["id"], exclude={drift})

    return eb.episode("drift", seed, shifted)
