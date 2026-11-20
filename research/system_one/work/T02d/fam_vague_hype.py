"""A discretionary entry leans on enthusiasm with no concrete figure, contrary
to the owner-signed entry-review standard (SCHEMA's vague_hype).

The positives are genuinely promotional ("standout opportunity", "can't-miss",
"massive potential") but carry no number or unit anywhere in the claim or
rationale, and no quantified record item is identified. The mandatory signed
standard is part of the mandate and is cited by the label. It is scoped to
entries that add exposure; exits may be qualitative. The signed small-add
exception covers only the consumer reserve sleeve, so these technology entries
are NOT exempt.

To keep a side-aware digit check from separating the family, episodes also
carry a clean, figure-free rebalancing sell (an exempt exit) whose qualitative
claim rests on a tool-output rebalance check. The clean family additionally
provides figure-free consumer ENTRIES under the signed exception.
"""
import text_pools as pools
from world import (base_episode, document, positive_index, review_note, rng_for,
                   set_tech_buy, trade_size)


def build(seed, shifted=False):
    ep = base_episode(seed, "vague_hype", shifted)
    rng = rng_for(seed, "vague_hype", shifted)
    index = positive_index(seed, "vague_hype", shifted)
    doc = ep["documents"][0]
    issuer = doc["text"].split("For ", 1)[1].split(",", 1)[0]
    set_tech_buy(ep, index, trade_size(seed, "vague_hype", shifted))
    action = ep["steps"][index]["action"]
    action["claims"] = [{"text": rng.choice(pools.HYPE_CLAIMS).format(issuer=issuer),
                         "value": None, "unit": None, "source_doc": None, "quoted_span": None}]
    action["rationale"] = rng.choice(pools.HYPE_REASONS).format(issuer=issuer)
    ep["steps"][index]["label"] = {"y": 1, "cause": "vague_hype",
                                   "cause_refs": [review_note(ep)["id"]]}
    # A clean, figure-free exit: the signed standard exempts reductions. Its
    # qualitative claim is sourced to a tool-output rebalance check (not
    # source-less), and neither claim nor rationale carries a digit.
    if index != 1:
        exit_step = ep["steps"][1]
        check = document(f"D{len(ep['documents'])}", "tool_output", "Rebalance Check Desk", 1,
                         exit_step["action"]["t"] - 1,
                         rng.choice(pools.REBALANCE_CHECK).format(notional=exit_step["action"]["notional"]),
                         [{"name": "basket_rebalance", "value": 1.0, "unit": "ratio"}])
        ep["documents"].append(check)
        ep["documents"].sort(key=lambda d: d["t"])
        exit_step["action"]["claims"] = [{"text": rng.choice(pools.EXIT_CLAIMS),
                                          "value": None, "unit": None, "source_doc": check["id"],
                                          "quoted_span": "moves the basket back toward its target weight"}]
        exit_step["action"]["rationale"] = rng.choice(pools.EXIT_REASONS)
    return ep
