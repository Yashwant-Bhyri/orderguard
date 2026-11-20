"""Stale thesis: two later filings trip the invalidation trigger and the agent adds."""
from __future__ import annotations

from gen_text import filing, claim
from fam_common import base, open_buy, trim, filler, schedule


def _fail(eb, rng, t, note_id, info0):
    s = info0["sector"]
    tk = info0["ticker"]
    soft1 = round(rng.uniform(-6.0, 2.2), 1)
    soft2 = round(rng.uniform(-6.5, 2.4), 1)
    f1 = filing(eb, rng, s, t - 4, comp=info0["comp"], ticker=tk,
                growth=soft1, guide=round(soft1 + rng.uniform(-0.8, 0.8), 1))
    f2 = filing(eb, rng, s, t - 1, comp=info0["comp"], ticker=tk,
                growth=soft2, guide=round(soft2 + rng.uniform(-0.8, 0.8), 1))
    room = eb.room_buy(s, tk)
    n = min(0.022 * eb.value, room * 0.85)
    if n < 0.006 * eb.value:
        n = min(room * 0.95, 0.010 * eb.value)
    c = claim(f"The {tk} filing shows growth of {soft2}% year over year.",
              soft2, "%", f2["id"], f2["spans"]["growth"])
    w = (eb.sec_val(s) + n) / eb.value
    why = rng.choice([
        f"We add ${n / 1e6:.1f} million to {info0['comp']} because two soft prints are a timing issue, not a broken thesis",
        f"The {soft2}% quarter follows a {soft1}% one, and we keep buying {tk} on the same long view",
        f"{info0['comp']} remains a core holding despite {soft2}% growth, and the ${n / 1e6:.1f} million add reflects that",
    ])
    eb.add(t, s, tk, "buy", n, info0["thesis"], False, [c], [note_id],
           f"{why}. We read the two quarters as timing and hold {s} at {w * 100:.1f}%.",
           y=1, cause="stale_thesis", refs=[f1["id"], f2["id"]])
    for th in eb.theses:
        if th["id"] == info0["thesis"]:
            th["status"] = "weakened"
    return f1, f2


def generate(seed, shifted=False):
    rng, eb, t0, note = base(seed, offset=81)
    n = rng.choice([3, 4, 4, 5, 5, 6])
    fail_idx = rng.randrange(2, n)
    times = schedule(rng, t0, n)

    info0 = open_buy(eb, rng, times[0], note["id"], frac=0.010)
    exclude = {info0["sector"]}
    for i in range(1, n):
        if i == fail_idx:
            _fail(eb, rng, times[i], note["id"], info0)
        else:
            filler(eb, rng, times[i], note["id"], exclude=exclude)

    return eb.episode("stale_thesis", seed, shifted)
