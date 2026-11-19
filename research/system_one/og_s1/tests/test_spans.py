from og_s1.world import FACT_SPECS, _render, simulate


def _facts_by_doc(ep):
    return {d.id: d.facts for d in ep.documents}


def _fact_at_span(facts_by_doc, source_doc, span):
    for f in facts_by_doc.get(source_doc, []):
        if _render(FACT_SPECS[f["name"]], f["value"]) == span:
            return f
    return None


def test_quoted_spans_are_substrings():
    for fam in ("clean", "misquote", "unsupported_claim", "stale_thesis"):
        ep = simulate(11, fam, 100, False)
        text_by_id = {d.id: d.text for d in ep.documents}
        for st in ep.steps:
            for c in st.action.claims:
                if c.quoted_span is not None and c.source_doc is not None:
                    assert c.quoted_span in text_by_id[c.source_doc], c


def test_clean_claims_quote_exactly():
    ep = simulate(13, "clean", 100, False)
    facts_by_doc = _facts_by_doc(ep)
    checked = 0
    for st in ep.steps:
        for c in st.action.claims:
            if c.quoted_span is None or c.source_doc is None:
                continue
            fact = _fact_at_span(facts_by_doc, c.source_doc, c.quoted_span)
            if fact is not None:
                assert abs(c.value - fact["value"]) < 1e-9
                checked += 1
    assert checked > 0


def test_misquote_value_differs_from_fact():
    ep = simulate(12, "misquote", 100, False)
    facts_by_doc = _facts_by_doc(ep)
    any_mismatch = False
    for st in ep.steps:
        if st.label.cause != "misquote":
            continue
        for c in st.action.claims:
            if c.quoted_span is None or c.source_doc is None:
                continue
            fact = _fact_at_span(facts_by_doc, c.source_doc, c.quoted_span)
            if fact is not None and abs(c.value - fact["value"]) > 1e-9:
                any_mismatch = True
    assert any_mismatch
