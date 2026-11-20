"""drift: a buy that leaves a sector above its signed maximum."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, Builder, claim
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "drift", shifted)
    rng = b.rng
    cands = []
    for s in SECTORS:
        lo = b.owner["sector_bands"][s]["min"]
        hi = b.owner["sector_bands"][s]["max"]
        if hi >= 0.12 and hi - lo >= 0.04:
            cands.append(s)
    ds = rng.choice(cands)
    hi = b.owner["sector_bands"][ds]["max"]
    b.build_book(weights={ds: hi - rng.uniform(0.012, 0.03)}, spread=0.6)
    base_th, _, _ = sc.seed_episode(b)

    pre = rng.choice([1, 2])
    t = sc.warmup(b, pre, avoid={ds})

    band = b.owner["sector_bands"][ds]
    cur = b.sec_w(ds)
    gap = max(0.002, band["max"] - cur)
    overshoot = rng.uniform(0.004, 0.012)
    need = (gap + overshoot) * b.total
    inst = max((i for i, _ in INSTRUMENTS[ds]), key=lambda i: b.maxpos - b.inst_w(i))
    room = (b.maxpos - b.inst_w(inst) - 0.001) * b.total
    need = min(need, room, b.cash * 0.7)
    if need <= gap * b.total:
        return b.finish()
    co = b.names[inst]
    f = sc.fact_for(ds, rng)
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, "Meridian Wire", per, [f], extra=1)
    d = b.doc("news", txt, dfacts, t=t - 5, publisher="Meridian Wire")
    tid = b.thesis(
        f"{co} can carry a larger {ds} weight after {prose.label(f[0])} of {prose.fmt(*f)}.",
        ds, t, [d], prose.invalidation(rng, f[0], f[1], ds, round(f[1] * 0.5, 2)),
        {"name": f[0], "op": "<", "value": round(f[1] * 0.5, 2)}, "active")
    c = sc.quote_claim(d, [f], spans, co=co)
    post = (b.sec_val(ds) + need) / b.total * 100.0
    b.step(t, ds, inst, "buy", need, tid, True, [c],
           prose.rat_drift(rng, co, ds, post), y=1, cause="drift", refs=[])
    t += 6
    if rng.random() < 0.2:
        room2 = (b.maxpos - b.inst_w(inst) - 0.001) * b.total
        extra = round(min(room2 * rng.uniform(0.2, 0.5), b.cash * 0.5), 2)
        if room2 > 0 and extra > 0.002 * b.total:
            post2 = (b.sec_val(ds) + extra) / b.total * 100.0
            b.step(t, ds, inst, "buy", extra, tid, False, [c],
                   prose.rat_drift(rng, co, ds, post2), y=1, cause="drift", refs=[])
            t += 8
    t += 2
    sc.closeout(b, rng, t, base_th, ds, inst)
    return b.finish()
