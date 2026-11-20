"""superseded_source: the cited figure was later withdrawn and restated."""
from __future__ import annotations

from common import SECTORS, INSTRUMENTS, Builder, claim
import prose
import scenario as sc


def generate(seed, shifted=False):
    b = Builder(seed, "superseded_source", shifted)
    rng = b.rng
    b.build_book()
    base_th, _, _ = sc.seed_episode(b)
    pick = sc.pick_buy(b, rng, sectors=[x for x in SECTORS if x != "index"])
    if not pick:
        return b.finish()
    s, inst, size = pick
    co = b.names[inst]
    per = rng.choice(prose.PERIODS)
    old = round(rng.uniform(1.4, 4.8), 2)
    new = round(old * rng.uniform(0.6, 0.82), 2)
    os_ = prose.fmt("revenue", old, "$B")
    ns = prose.fmt("revenue", new, "$B")
    span = f"preliminary revenue of {os_}"
    t1 = 20
    tail1 = rng.choice([
        f"The {os_} figure is preliminary and subject to the full audit, management said.",
        f"{co} cautioned that the {os_} number could be restated once the audit closes.",
        f"Executives said the {os_} preliminary figure may change in the final filing.",
        f"The preliminary {os_} has not yet been signed off by the auditors of {co}.",
        f"Management flagged that the {os_} print for {per} is unaudited.",
        f"Auditors have not signed off on the {os_} figure, {co} said.",
        f"The company described the {os_} number as an early estimate, not final.",
        f"{co} said the {os_} release is subject to revision after the audit.",
    ])
    tail2 = rng.choice([
        f"Volume trends at {co} were described as strong in the release.",
        f"Management called out better unit volume for {co} in the period.",
        f"The sales team at {co} pointed to firm demand over {per}.",
        f"{co} said order flow held up through the quarter.",
        f"The release noted healthy order flow at {co} for {per}.",
        f"{co} added that channel inventories stayed lean in the period.",
    ])
    text1 = f"{co} released preliminary revenue of {os_} for {per}. {tail1} {tail2}"
    d1 = b.doc("news", text1, [("revenue", old, "$B")], t=14, publisher="Meridian Wire")
    tid = b.thesis(
        f"{co} is scaling into {per} with revenue tracking {os_}.",
        s, t1, [d1], prose.invalidation(rng, "revenue", new, s, round(new * 0.9, 2)),
        {"name": "revenue", "op": "<", "value": round(new * 0.9, 2)}, "active")
    b.step(t1, s, inst, "buy", round(size * rng.uniform(0.35, 0.6), 2), tid, True,
           [claim(f"preliminary revenue of {os_} at {co} supports the add.",
                  value=old, unit="$B", source_doc=d1, quoted_span=span)],
           prose.rat_open(rng, co, "revenue", os_, s))
    t = 30
    # A newer, still-valid document appears; a clean add still cites the older
    # (and still current) preliminary release, so recency is not diagnostic.
    sc.neutral_doc(b, t - 6, s, co)
    if sc.cite_older_clean_buy(b, t, d1, ["revenue", old, "$B"], {"revenue": span},
                               s, inst, tid, co):
        t += 10
    for _ in range(rng.choice([1, 2, 3])):
        if sc.clean_buy(b, t, avoid={s}):
            t += 10
        else:
            break
    tail3 = rng.choice([
        f"The company said the earlier {os_} figure should not be relied upon.",
        f"Management asked investors to use only the restated {ns} number.",
        f"The filing states that the preliminary {os_} release is superseded.",
        f"{co} told holders to disregard the earlier {os_} preliminary figure.",
        f"The regulator required {co} to withdraw the {os_} print.",
        f"Auditors found the {os_} figure overstated and published {ns} instead.",
        f"The amended report replaces the {os_} release in full.",
        f"{co} removed the preliminary {os_} figure from its guidance page.",
    ])
    text2 = (f"{co} filed an amended report that withdraws the {os_} preliminary revenue figure. "
             f"The restated revenue is {ns} for {per}. {tail3}")
    bad = b.doc("filing", text2, [("revenue", new, "$B")], t=t - 5, publisher="Exchange Filing Desk")
    f_inst = inst
    room = b.clean_buy_size(f_inst, s)
    if room <= 0.002 * b.total:
        return b.finish()
    b.step(t, s, f_inst, "buy", round(room * rng.uniform(0.3, 0.6), 2), tid, False,
           [claim(f"preliminary revenue of {os_} at {co} is the number behind this add.",
                  value=old, unit="$B", source_doc=d1, quoted_span=span)],
           prose.rat_superseded(rng, co, os_),
           y=1, cause="superseded_source", refs=[d1, bad])
    t += 8
    if rng.random() < 0.2:
        room2 = b.clean_buy_size(f_inst, s)
        extra = round(min(room2 * rng.uniform(0.25, 0.5), b.cash * 0.4), 2)
        if room2 > 0 and extra > 0.002 * b.total:
            b.step(t, s, f_inst, "buy", extra, tid, False,
                   [claim(f"preliminary revenue of {os_} at {co} is the number behind this add.",
                          value=old, unit="$B", source_doc=d1, quoted_span=span)],
                   prose.rat_superseded(rng, co, os_),
                   y=1, cause="superseded_source", refs=[d1, bad])
            t += 8
    sc.closeout(b, rng, t, base_th, s, f_inst)
    return b.finish()
