"""unsupported_claim: the reasoning asserts a figure no cited source contains."""
from __future__ import annotations

from common import SECTORS, Builder, claim
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "unsupported_claim", shifted)
    rng = b.rng
    b.build_book()
    base_th, _, _ = sc.seed_episode(b)
    pick = sc.pick_buy(b, rng, sectors=[x for x in SECTORS if x != "index"])
    if not pick:
        return b.finish()
    s, inst, size = pick
    t = sc.warmup(b, rng.choice([1, 2]), avoid={s})
    co = b.names[inst]
    f = sc.fact_for(s, rng)
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, "Palisade Equity Research", per, [f], extra=1)
    d = b.doc("analyst", txt, dfacts, t=t - 5, publisher="Palisade Equity Research")
    claimed = rng.choice(["forward guidance growth", "market share gain",
                          "pricing power", "order book expansion"])
    val = round(rng.uniform(22.0, 58.0), 1)
    use_source = rng.random() < 0.55
    if use_source:
        c = claim(f"{claimed} of {val:.1f}% is the reason to own {co}.",
                  value=val, unit="%", source_doc=d)
        refs = [d]
    else:
        c = claim(f"{claimed} of {val:.1f}% is the reason to own {co}.",
                  value=val, unit="%")
        refs = []
    tid = b.thesis(
        f"{co} can compound with {claimed} of {val:.1f}% underpinning the {s} call.",
        s, t, [d], prose.invalidation(rng, f[0], f[1], s, 0.0),
        {"name": "forward_guidance_growth", "op": "<", "value": 0.0}, "active")
    notional = round(size * rng.uniform(0.35, 0.7), 2)
    b.step(t, s, inst, "buy", notional, tid, True, [c],
           prose.rat_unsupported(rng, co, f"{claimed} of {val:.1f}%"),
           y=1, cause="unsupported_claim", refs=refs)
    t += 10
    sc.closeout(b, rng, t, base_th, s, inst)
    return b.finish()
