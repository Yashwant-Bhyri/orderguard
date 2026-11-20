"""misquote: quotes a real span but states a different number than the source."""
from __future__ import annotations

from common import Builder, claim
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "misquote", shifted)
    rng = b.rng
    b.build_book()
    base_th, _, _ = sc.seed_episode(b)
    pick = sc.pick_buy(b, rng)
    if not pick:
        return b.finish()
    s, inst, size = pick
    t = sc.warmup(b, rng.choice([1, 2]), avoid={s})
    co = b.names[inst]
    f = sc.fact_for(s, rng)
    name, truth, unit = f
    per = rng.choice(prose.PERIODS)
    txt, spans, dfacts = prose.doc_text(rng, co, "Exchange Filing Desk", per, [f], extra=1)
    d = b.doc("filing", txt, dfacts, t=t - 5, publisher="Exchange Filing Desk")
    if unit == "%":
        wrong = round(truth * rng.uniform(1.18, 1.55), 1)
    elif unit in ("$B", "$M", "$"):
        wrong = round(truth * rng.uniform(1.15, 1.6), 2)
    else:
        wrong = round(truth * rng.uniform(1.15, 1.5), 2)
    if wrong == truth:
        wrong = round(truth + (0.1 if unit == "%" else 0.01), 2)
    met = prose.label(name)
    ws = prose.fmt(name, wrong, unit)
    ts = prose.fmt(name, truth, unit)
    c = claim(f"{met} of {ws} at {co} is the number that justifies the add.",
              value=wrong, unit=unit, source_doc=d, quoted_span=spans[name])
    tid = b.thesis(
        f"{co} re-rates on {met} of {ws}, which keeps the {s} case alive.",
        s, t, [d], prose.invalidation(rng, name, truth, s, round(truth * 0.6, 2)),
        {"name": name, "op": "<", "value": round(truth * 0.6, 2)}, "active")
    notional = round(size * rng.uniform(0.35, 0.7), 2)
    b.step(t, s, inst, "buy", notional, tid, True, [c],
           prose.rat_misquote(rng, co, met, ws, ts),
           y=1, cause="misquote", refs=[d])
    t += 10
    sc.closeout(b, rng, t, base_th, s, inst)
    return b.finish()
