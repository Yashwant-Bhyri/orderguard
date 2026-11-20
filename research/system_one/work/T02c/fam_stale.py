"""stale_thesis: a thesis's kill condition has fired and the agent adds anyway."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, Builder
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "stale_thesis", shifted)
    rng = b.rng
    b.build_book()
    base_th, _, _ = sc.seed_episode(b)
    pick = sc.pick_buy(b, rng, sectors=[x for x in SECTORS if x != "index"])
    if not pick:
        return b.finish()
    s, inst, size = pick
    co = b.names[inst]
    t = 20
    guide = round(rng.uniform(4.0, 14.0), 1)
    f1 = ("forward_guidance_growth", guide, "%")
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, "Exchange Filing Desk", per, [f1], extra=1)
    d1 = b.doc("filing", txt, dfacts, t=14, publisher="Exchange Filing Desk")
    tid = b.thesis(
        f"{co} can grow into its multiple with forward guidance of {guide:.1f}%.",
        s, t, [d1], prose.invalidation(rng, "forward_guidance_growth", guide, s, 0.0),
        {"name": "forward_guidance_growth", "op": "<", "value": 0.0}, "active")
    b.step(t, s, inst, "buy", round(size * rng.uniform(0.35, 0.65), 2), tid, True,
           [sc.quote_claim(d1, [f1], spans, co=co)],
           prose.rat_open(rng, co, "forward guidance growth", prose.fmt(*f1), s))
    t = 30
    for _ in range(rng.choice([1, 2, 3])):
        if sc.clean_buy(b, t, avoid={s}):
            t += 10
        else:
            break
    # A newer, still-valid document exists, yet a clean add legitimately cites
    # the older thesis evidence: recency alone is not a positive tell.
    sc.neutral_doc(b, t - 3, s, co)
    f_inst = inst
    room = b.clean_buy_size(f_inst, s)
    if room <= 0.002 * b.total:
        return b.finish()
    if sc.cite_older_clean_buy(b, t, d1, f1, spans, s, f_inst, tid, co):
        t += 10
    drop = -round(rng.uniform(1.5, 7.5), 1)
    f2 = ("forward_guidance_growth", drop, "%")
    txt2, spans2, dfacts2 = prose.doc_text(rng, co, "Statutory Filings Office", rng.choice(prose.PERIODS), [f2], extra=1)
    bad = b.doc("filing", txt2, dfacts2, t=t - 5, publisher="Statutory Filings Office")
    room = b.clean_buy_size(f_inst, s)
    if room <= 0.002 * b.total:
        return b.finish()
    dsize = round(room * rng.uniform(0.3, 0.6), 2)
    b.set_status(tid, "invalidated")
    b.step(t, s, f_inst, "buy", dsize, tid, False,
           [sc.quote_claim(d1, [f1], spans, co=co)],
           prose.rat_stale(rng, b.names[f_inst], "forward guidance growth", prose.fmt(*f2)),
           y=1, cause="stale_thesis", refs=[bad])
    t += 8
    if rng.random() < 0.2:
        room2 = b.clean_buy_size(f_inst, s)
        extra = round(min(room2 * rng.uniform(0.25, 0.5), b.cash * 0.4), 2)
        if room2 > 0 and extra > 0.002 * b.total:
            b.step(t, s, f_inst, "buy", extra, tid, False,
                   [sc.quote_claim(d1, [f1], spans, co=co)],
                   prose.rat_stale(rng, b.names[f_inst], "forward guidance growth",
                                   prose.fmt(*f2)),
                   y=1, cause="stale_thesis", refs=[bad])
            t += 8
    b.set_status(tid, "invalidated")
    sc.closeout(b, rng, t, base_th, s, f_inst)
    return b.finish()
