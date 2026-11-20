"""Endorsable trades built to look like failures. EVERY clean episode carries
all five SCHEMA hard negatives, plus a figure-free entry and a figure-free exit:

  step 0  tech buy opening a thesis on a fresh filing  -> legitimate adaptation,
          an exact quote, and enthusiastic-but-factual language;
  step 1  index rebalancing sell, qualitative          -> a correct sell and a
          figure-free exit (the entry standard exempts reductions);
  step 2  tech trim after a new adverse guidance filing -> a correct sell on
          fresh evidence, with an exact quote of the adverse figure;
  step 3  small consumer add on a qualitative case      -> a figure-free ENTRY
          endorsable under the owner-signed small-add exception (a hard negative
          for vague_hype: a buy with no figure that is still fine);
  step 4  staples buy on an explicit peer comparison    -> a relative-value
          comparison naming both peers, an exact quote, factual enthusiasm.

Every claim rests on a real source (a filing, or a tool-output pre-trade /
rebalance check for the qualitative claims). Every sentence carries a
per-episode variable so none is stamped across the corpus. The replayed book
stays inside every signed limit, and every label is clean.
"""
from world import (base_episode, document, exception_note, rebook, review_note,
                   rng_for, trade_size)
import text_pools as pools

TOTAL = 100000.0


def _issuer(doc, prefix, sep):
    return doc["text"].split(prefix, 1)[1].split(sep, 1)[0]


def build(seed, shifted=False):
    ep = base_episode(seed, "clean", shifted)
    rng = rng_for(seed, "clean", shifted)
    d0, d1, d2, d3 = ep["documents"]
    tech_issuer = _issuer(d0, "For ", ",")
    consumer_issuer = _issuer(d2, " at ", " increased")
    staples_issuer = _issuer(d3, " at ", " covered")
    publisher = d0["publisher"]

    n0 = trade_size(seed, "clean_open", shifted)
    n1 = trade_size(seed, "clean_rebalance", shifted)
    n2 = trade_size(seed, "clean_trim", shifted)
    n3 = trade_size(seed, "clean_consumer", shifted)   # <= 2400 < 2600 exception
    n4 = trade_size(seed, "clean_staples", shifted)

    # Adverse tech guidance filing (fresh evidence for the trim), available t=22.
    guidance = round(-(3.0 + rng_for(seed, "clean_guidance", shifted).uniform(0.0, 4.0)), 1)
    adverse = document("D4", "filing", publisher, 3, 22,
                       f"{tech_issuer} lowered forward shipment guidance growth to {guidance:.1f}% after a customer moved an acceptance date. "
                       f"Management at {tech_issuer} said contract terms are unchanged and the backlog is still being converted.",
                       [{"name": "guidance_growth", "value": guidance, "unit": "%"}])

    # Relative-value analyst doc: name a peer explicitly with "versus".
    coverage = d3["facts"][0]["value"]
    leverage = d3["facts"][1]["value"]
    peer_cover = round(coverage + rng.choice((-1.0, -0.6, 0.5, 0.9)), 1)
    rv_text = (f"Cash at {staples_issuer} covered its quarterly distribution {coverage:.1f}x, versus {peer_cover:.1f}x at {tech_issuer}, "
               f"with net leverage at {leverage:.1f}x. " + d3["text"].split(". ", 1)[1])
    rv_doc = document("D3", d3["kind"], d3["publisher"], d3["trust_tier"], d3["t"], rv_text,
                      [d3["facts"][0], {"name": "peer_distribution_coverage", "value": peer_cover, "unit": "x"}, d3["facts"][1]])

    # Tool-output checks that source the two qualitative (figure-free) claims.
    rebalance_check = document("D5", "tool_output", "Rebalance Check Desk", 1, 24,
                               rng.choice(pools.REBALANCE_CHECK).format(notional=n1),
                               [{"name": "index_weight", "value": 28.0, "unit": "%"}, {"name": "index_target", "value": 25.0, "unit": "%"}])
    reserve_check = document("D6", "tool_output", "Reserve Release Check", 1, 44,
                             rng.choice(pools.RESERVE_CHECK).format(notional=n3, issuer=consumer_issuer),
                             [{"name": "consumer_weight", "value": 10.0, "unit": "%"}, {"name": "consumer_ceiling", "value": 25.0, "unit": "%"}])

    ep["documents"] = sorted([d0, d1, d2, rv_doc, adverse, rebalance_check, reserve_check], key=lambda d: d["t"])

    # Opening book: index near its ceiling so the sell is a genuine rebalance.
    rebook(ep, {"TECH_A": 12000.0, "TECH_B": 7000.0, "CONSUMER_FUND": 10000.0,
                "HEALTH_FUND": 10000.0, "STAPLES_FUND": 10000.0, "FINANCIALS_FUND": 10000.0,
                "ENERGY_FUND": 5000.0, "INDEX_FUND": 28000.0}, TOTAL)

    v0 = d0["facts"][0]["value"]
    review_id = review_note(ep)["id"]
    exception_id = exception_note(ep)["id"]

    steps = []
    # Step 0: adaptation + exact quote + enthusiasm.
    steps.append({"action": {"t": 15, "sector": "tech", "instrument": "TECH_A", "side": "buy",
                             "notional": n0, "thesis_id": "T0", "opens_thesis": True,
                             "claims": [{"text": f"The {v0:.1f}% net sales growth at {tech_issuer} is a genuinely encouraging reading.",
                                         "value": v0, "unit": "%", "source_doc": "D0", "quoted_span": f"{v0:.1f}%"}],
                             "cites_notes": [review_id],
                             "rationale": f"The filing's {v0:.1f}% growth reading at {tech_issuer} is an encouraging, measured basis for the line. "
                                          f"I am opening a small {tech_issuer} technology position on that fresh disclosure."},
                  "pre_notes": [], "new_notes": [], "label": {"y": 0, "cause": "clean", "cause_refs": []}})
    # Step 1: figure-free rebalancing sell (exempt exit), sourced qualitative claim.
    steps.append({"action": {"t": 25, "sector": "index", "instrument": "INDEX_FUND", "side": "sell",
                             "notional": n1, "thesis_id": "T1", "opens_thesis": True,
                             "claims": [{"text": rng.choice(pools.EXIT_CLAIMS),
                                         "value": None, "unit": None, "source_doc": "D5",
                                         "quoted_span": "moves the basket back toward its target weight"}],
                             "cites_notes": [review_id],
                             "rationale": rng.choice(pools.EXIT_REASONS)},
                  "pre_notes": [], "new_notes": [], "label": {"y": 0, "cause": "clean", "cause_refs": []}})
    # Step 2: trim after adverse filing, exact quote of the adverse figure.
    steps.append({"action": {"t": 35, "sector": "tech", "instrument": "TECH_A", "side": "sell",
                             "notional": n2, "thesis_id": "T0", "opens_thesis": False,
                             "claims": [{"text": f"Forward shipment guidance growth at {tech_issuer} was {guidance:.1f}% in the latest filing.",
                                         "value": guidance, "unit": "%", "source_doc": "D4", "quoted_span": f"{guidance:.1f}%"}],
                             "cites_notes": [review_id],
                             "rationale": f"The new filing lowers forward shipment guidance to {guidance:.1f}%, which weakens the conversion case behind the technology line. "
                                          f"I am trimming part of the {tech_issuer} position rather than adding to it."},
                  "pre_notes": [], "new_notes": [], "label": {"y": 0, "cause": "clean", "cause_refs": []}})
    # Step 3: figure-free consumer ENTRY under the signed small-add exception.
    steps.append({"action": {"t": 45, "sector": "consumer", "instrument": "CONSUMER_FUND", "side": "buy",
                             "notional": n3, "thesis_id": "T2", "opens_thesis": True,
                             "claims": [{"text": rng.choice(pools.RESERVE_CLAIMS).format(issuer=consumer_issuer),
                                         "value": None, "unit": None, "source_doc": "D6",
                                         "quoted_span": "inside its signed band"}],
                             "cites_notes": [review_id, exception_id],
                             "rationale": rng.choice(pools.RESERVE_REASONS).format(issuer=consumer_issuer)},
                  "pre_notes": [], "new_notes": [], "label": {"y": 0, "cause": "clean", "cause_refs": []}})
    # Step 4: relative-value comparison + exact quote + enthusiasm.
    span = f"{coverage:.1f}x, versus {peer_cover:.1f}x at {tech_issuer}"
    steps.append({"action": {"t": 55, "sector": "staples", "instrument": "STAPLES_FUND", "side": "buy",
                             "notional": n4, "thesis_id": "T3", "opens_thesis": True,
                             "claims": [{"text": f"Distribution cover at {staples_issuer} is {coverage:.1f}x versus {peer_cover:.1f}x at {tech_issuer}.",
                                         "value": coverage, "unit": "x", "source_doc": "D3", "quoted_span": span}],
                             "cites_notes": [review_id],
                             "rationale": f"The {coverage:.1f}x cover at {staples_issuer} compares well versus {tech_issuer} on the same measure, a genuinely reassuring cushion. "
                                          f"I am adding a modest amount to {staples_issuer} on the stronger disclosed figure."},
                  "pre_notes": [], "new_notes": [], "label": {"y": 0, "cause": "clean", "cause_refs": []}})
    ep["steps"] = steps

    # Theses anchored to the fresh evidence; each opened by exactly one action.
    rows = [("T0", "tech", "revenue_growth", "D0", 15), ("T1", "index", "turnover_pct", "D1", 25),
            ("T2", "consumer", "comparable_sales_growth", "D2", 45), ("T3", "staples", "distribution_coverage", "D3", 55)]
    issuers = {"T0": tech_issuer, "T1": "the broad basket", "T2": consumer_issuer, "T3": staples_issuer}
    theses = []
    for tid, sector, metric, ev, opened in rows:
        val = next(d["facts"][0]["value"] for d in ep["documents"] if d["id"] == ev)
        statement = rng.choice(pools.THESIS_STATEMENTS[sector]).format(issuer=issuers[tid], publisher=publisher, value=val)
        invalidation = rng.choice(pools.THESIS_INVALIDATIONS).format(metric=metric.replace("_", " "), issuer=issuers[tid])
        theses.append({"id": tid, "statement": statement, "sector": sector, "opened_t": opened,
                       "evidence_docs": [ev], "invalidation": invalidation,
                       "invalidation_trigger": {"name": metric, "op": "<", "value": 0.0}, "status": "active"})
    ep["theses"] = theses
    ep["meta"]["family"] = "clean"
    return ep
