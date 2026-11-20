"""vague_hype: an enthusiastic buy with no concrete figure behind it."""
from __future__ import annotations

from common import Builder, claim
import prose
import scenario as sc

HYPE = [
    "{co} has unstoppable momentum and the upside from here is enormous.",
    "{co} is the strongest story on the tape and the crowd is only starting to notice.",
    "The setup in {co} is once-in-a-cycle and I do not want to miss it.",
    "{co} is a must-own name with a narrative that keeps getting stronger.",
    "Sentiment on {co} is electric and the shares look ready to break out.",
    "Everything I am reading says {co} is the next big winner.",
    "The buzz on {co} is impossible to tune out and the upside is huge.",
    "Every feed I follow is talking about {co} and the excitement is real.",
    "{co} has the kind of story that runs for years and I want in early.",
    "The crowd is only beginning to appreciate {co} and the momentum is fierce.",
    "I have rarely seen a setup as compelling as {co} right now.",
    "{co} is the name on everyone's lips and the opportunity is enormous.",
    "The narrative around {co} keeps building and I do not want to be late.",
    "There is a rare energy around {co} and the upside looks unlimited.",
    "{co} is a phenomenon and the market is finally waking up to it.",
    "The excitement on {co} is off the charts and I am adding with confidence.",
    "{co} keeps getting louder on the feeds and the story has legs.",
    "The market is underestimating {co} and the buzz keeps growing.",
    "I cannot find a bear case on {co} that stands up to the excitement.",
    "The whole street is waking up to {co} and the upside is enormous.",
    "The story on {co} only gets better and the crowd knows it.",
    "There is something special happening at {co} and I want to own it.",
    "{co} is the kind of name that defines a cycle and the buzz proves it.",
    "The energy around {co} is unlike anything else I follow right now.",
]


def generate(seed, shifted=False):
    b = Builder(seed, "vague_hype", shifted)
    rng = b.rng
    b.build_book()
    base_th, _, _ = sc.seed_episode(b)
    pick = sc.pick_buy(b, rng)
    if not pick:
        return b.finish()
    s, inst, size = pick
    t = sc.warmup(b, rng.choice([1, 2]), avoid={s})
    co = b.names[inst]
    c = claim(rng.choice(HYPE).format(co=co))
    frames = [
        "{co} is a momentum leader and the {s} sleeve should own more of it.",
        "The {s} sleeve is too light on {co}, which has become the name to own.",
        "{co} is the strongest {s} story I follow and the position should be bigger.",
        "I want a larger {s} weight in {co} while the narrative has this much force.",
        "{co} belongs in the {s} sleeve at a bigger size, on the strength of the story.",
        "The {s} allocation should lean harder into {co} given the momentum.",
    ]
    tid = b.thesis(
        rng.choice(frames).format(co=co, s=s),
        s, t, [b.documents[0]["id"]], prose.soft_invalidation(rng, s, co),
        {"name": "revenue_growth", "op": "<", "value": -5.0}, "weakened")
    notional = round(size * rng.uniform(0.35, 0.7), 2)
    b.step(t, s, inst, "buy", notional, tid, True, [c],
           prose.rat_hype(rng, co, s), y=1, cause="vague_hype", refs=[])
    t += 10
    sc.closeout(b, rng, t, base_th, s, inst)
    return b.finish()
