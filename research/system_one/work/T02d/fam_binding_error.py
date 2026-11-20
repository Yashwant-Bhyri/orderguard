"""The action's words are attached to the wrong thing (schema-listed cause).

Three variants, chosen by seed:
(a) wrong entity  - a sibling issuer's exact figure is asserted about the
    traded name (the quoted span is real; the binding is wrong);
(b) wrong period  - an older figure is presented as current while a later
    filing reports a different one for the same measure;
(c) wrong direction - the rationale argues for the opposite side of the trade.
Every quoted span is exact and every source is real; the error is the binding.
"""
from world import base_episode, document, positive_index, rng_for, set_tech_buy, trade_size


def _issuer(ep, i):
    if i == 0:
        return ep["documents"][0]["text"].split("For ", 1)[1].split(",", 1)[0]
    if i == 2:
        return ep["documents"][2]["text"].split(" at ", 1)[1].split(" increased", 1)[0]
    if i == 3:
        return ep["documents"][3]["text"].split(" at ", 1)[1].split(" covered", 1)[0]
    return "the broad basket"


def _wrong_entity(ep, seed, shifted):
    index = positive_index(seed, "binding_error", shifted, choices=(2, 3))
    step = ep["steps"][index]
    tech_issuer = _issuer(ep, 0)
    sibling_doc = ep["documents"][2]
    value = sibling_doc["facts"][0]["value"]
    set_tech_buy(ep, index, trade_size(seed, "binding_error", shifted))
    step["action"]["claims"] = [{
        "text": f"Comparable store sales at {tech_issuer} increased {value:.1f}% across owned locations.",
        "value": value, "unit": "%", "source_doc": sibling_doc["id"], "quoted_span": f"{value:.1f}%",
    }]
    step["action"]["rationale"] = (
        f"The comparable-sales reading at {tech_issuer} supports the demand case. "
        f"I am extending the technology line by a measured amount."
    )
    step["label"] = {"y": 1, "cause": "binding_error", "cause_refs": [sibling_doc["id"]]}
    return ep


def _wrong_period(ep, seed, shifted):
    rng = rng_for(seed, "binding_period", shifted)
    opening = ep["documents"][0]
    issuer = _issuer(ep, 0)
    old = opening["facts"][0]["value"]
    new = round(rng.uniform(4.1, 18.9) if not shifted else rng.uniform(9.5, 32.7), 1)
    if new == old:
        new = round(new + 1.3, 1)
    update = document(
        "D4", "filing", opening["publisher"], 3, 22,
        f"{issuer} updated its net sales growth reading for the current quarter to {new:.1f}%, "
        f"replacing the {old:.1f}% printed in the earlier release. "
        "The update was published through the issuer's standard disclosure channel.",
        [{"name": "revenue_growth", "value": new, "unit": "%"},
         {"name": "prior_revenue_growth", "value": old, "unit": "%"}],
    )
    ep["documents"].append(update)
    ep["documents"].sort(key=lambda d: d["t"])
    index = positive_index(seed, "binding_error", shifted, choices=(2, 3))
    step = ep["steps"][index]
    set_tech_buy(ep, index, trade_size(seed, "binding_error", shifted))
    step["action"]["claims"] = [{
        "text": f"Net sales growth at {issuer} is {old:.1f}% in the current quarter.",
        "value": old, "unit": "%", "source_doc": opening["id"], "quoted_span": f"{old:.1f}%",
    }]
    step["action"]["rationale"] = (
        f"The current quarter's growth reading at {issuer} keeps the operating case intact. "
        f"I am adding a measured amount."
    )
    step["label"] = {"y": 1, "cause": "binding_error", "cause_refs": [opening["id"], update["id"]]}
    return ep


def _wrong_direction(ep, seed, shifted):
    index = positive_index(seed, "binding_error", shifted)
    step = ep["steps"][index]
    action = step["action"]
    quote = action["claims"][0]["quoted_span"]
    issuer = _issuer(ep, index)
    if action["side"] == "buy":
        action["rationale"] = (
            f"The {quote} reading argues for reducing exposure to {issuer}. "
            f"I am trimming the line back toward its starting weight."
        )
    else:
        action["rationale"] = (
            f"The {quote} turnover reading argues for adding to the broad basket. "
            f"I am increasing the line by a measured amount."
        )
    step["label"] = {"y": 1, "cause": "binding_error", "cause_refs": [action["claims"][0]["source_doc"]]}
    return ep


def build(seed, shifted=False):
    ep = base_episode(seed, "binding_error", shifted)
    variant = seed % 3
    if variant == 0:
        return _wrong_entity(ep, seed, shifted)
    if variant == 1:
        return _wrong_period(ep, seed, shifted)
    return _wrong_direction(ep, seed, shifted)
