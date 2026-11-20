"""wrong_mandate_scope: a real signed permission that belongs to another account."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, Builder
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "wrong_mandate_scope", shifted)
    rng = b.rng
    cands = []
    for s in SECTORS:
        lo = b.owner["sector_bands"][s]["min"]
        hi = b.owner["sector_bands"][s]["max"]
        if hi >= 0.12 and hi - lo >= 0.04:
            cands.append(s)
    s = rng.choice(cands)
    hi = b.owner["sector_bands"][s]["max"]
    b.build_book(weights={s: hi - rng.uniform(0.015, 0.032)}, spread=0.65)
    base_th, _, _ = sc.seed_episode(b)
    mandate_note = b.initial_notes[0]["id"]
    other_acct = f"sleeve-{rng.choice(['SG', 'AG', 'GR', 'CV'])}-{rng.randint(100, 999)}"
    other_key = f"og-{rng.randint(1000, 9999)}-{rng.choice('CDEF')}"
    claimed_hi = min(0.7, hi + rng.uniform(0.05, 0.12))
    claimed_cap = min(0.35, b.maxpos + rng.uniform(0.02, 0.05))
    b.initial_notes.append(b.note(
        prose.scope_note(rng, other_acct, other_key, s, claimed_hi, claimed_cap),
        7, "owner_signed", True))
    t = sc.warmup(b, rng.choice([1, 2]), avoid={s})

    # A clean buy that legitimately cites this account's own signed mandate note,
    # so "cites any note" is not a positive tell.
    pick = sc.pick_buy(b, rng, avoid={s})
    if pick:
        s2, inst2, size2 = pick
        co2 = b.names[inst2]
        f = sc.fact_for(s2, rng)
        per = rng.choice(prose.PERIODS)
        txt, spans, dfacts = prose.doc_text(rng, co2, "Exchange Filing Desk", per, [f], extra=1)
        d = b.doc("filing", txt, dfacts, t=t - 6, publisher="Exchange Filing Desk")
        notional = round(size2 * rng.uniform(0.35, 0.6), 2)
        art = "an" if s2[0] in "aeiou" else "a"
        tid = b.thesis(
            f"{co2} earns {art} {s2} position on {prose.label(f[0])} of {prose.fmt(*f)}.",
            s2, t, [d], prose.invalidation(rng, f[0], f[1], s2, round(f[1] * 0.5, 2)),
            {"name": f[0], "op": "<", "value": round(f[1] * 0.5, 2)}, "active")
        b.step(t, s2, inst2, "buy", notional, tid, True,
               [sc.quote_claim(d, [f], spans, co=co2)],
               prose.rat_buy_clean(rng, co2, prose.label(f[0]), prose.fmt(*f), s2),
               cites_notes=[mandate_note])
        t += 10

    cur = b.sec_w(s)
    gap = max(0.002, hi - cur)
    need = (gap + rng.uniform(0.004, 0.012)) * b.total
    inst = max((i for i, _ in INSTRUMENTS[s]), key=lambda i: b.maxpos - b.inst_w(i))
    room = (b.maxpos - b.inst_w(inst) - 0.001) * b.total
    need = min(need, room, b.cash * 0.7)
    co = b.names[inst]
    f2 = sc.fact_for(s, rng)
    per2 = rng.choice(prose.PERIODS)
    txt2, spans2, dfacts2 = prose.doc_text(rng, co, "Meridian Wire", per2, [f2], extra=1)
    sup = b.doc("news", txt2, dfacts2, t=t - 6, publisher="Meridian Wire")
    tid = b.thesis(
        f"{co} can take a larger {s} weight under the {other_acct} allowance of {claimed_hi * 100:.1f}%.",
        s, t, [sup], prose.soft_invalidation(rng, s, co, claimed_hi * 100.0),
        None, "active")
    b.step(t, s, inst, "buy", need, tid, True,
           [sc.quote_claim(sup, [f2], spans2, co=co)],
           prose.rat_scope(rng, s, f"{claimed_hi * 100:.0f}%"),
           y=1, cause="wrong_mandate_scope",
           refs=[b.initial_notes[-1]["id"]],
           cites_notes=[b.initial_notes[-1]["id"]])
    t += 10
    sc.closeout(b, rng, t, base_th, s, inst)
    return b.finish()
