"""Novel family: withdrawn target.

The agent quotes a sell-side price target exactly and ignores the sentence in
the same note saying the target and rating are under review and not current.
"""
from __future__ import annotations

from gen_text import analyst, claim
from fam_clean import best_buy, projected
from fam_common import base, open_buy, trim, filler, schedule


def _fail(eb, rng, t, note_id):
    s, tk, comp = best_buy(eb, rng)
    pt = round(eb.value / 1e6 * rng.uniform(0.04, 0.16), 2)
    up = round(rng.uniform(16.0, 44.0), 1)
    a = analyst(eb, rng, s, t - 4, comp=comp, ticker=tk, suspended=True,
                upside=up, pt=pt)
    n = min(0.030 * eb.value, eb.room_buy(s, tk) * 0.88)
    th = eb.thesis(
        f"{comp} offers {up}% upside to the price target and a re-rating catalyst.",
        s, t, [a["id"]],
        rng.choice([
            f"Reassess {comp} once the delayed filing is published and coverage is reinstated.",
            f"Revisit {tk} when the suspended rating is reinstated after the delayed filing.",
            f"We wait for {comp} coverage to resume once the delayed filing appears.",
            f"Re-examine {comp} when the target is reinstated after the delayed report.",
        ]),
        None)
    c = claim(f"The note implies upside of {up}% to its price target.",
              up, "%", a["id"], a["spans"]["upside"])
    w = projected(eb, s, n)
    why = rng.choice([
        f"We act on the {up}% upside to the ${pt:.2f} target in the {tk} note",
        f"The ${pt:.2f} target on {comp} ({tk}) leaves {up}% on the table, so we buy",
        f"With {up}% implied upside, {comp} ({tk}) deserves a ${n / 1e6:.1f} million position",
    ])
    eb.add(t, s, tk, "buy", n, th, True, [c], [note_id],
           f"{why}. The resulting {s} weight is {w * 100:.1f}%, inside the signed band.",
           y=1, cause="withdrawn_target", refs=[a["id"]])


def generate(seed, shifted=False):
    rng, eb, t0, note = base(seed, offset=95)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(1, n)
    times = schedule(rng, t0, n)

    open_buy(eb, rng, times[0], note["id"], frac=0.022)
    for i in range(1, n):
        if i == fail_idx:
            _fail(eb, rng, times[i], note["id"])
        else:
            filler(eb, rng, times[i], note["id"])

    return eb.episode("withdrawn_target", seed, shifted)
