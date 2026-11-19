"""Tests for taint propagation, the taint features, the gate and the root cap."""

from __future__ import annotations

import copy
import inspect
import random

import numpy as np
import pytest

from og_s1.schema import model_view_at
from og_s1.taint import (
    DEFAULT_CONFIG,
    TAINT_FEATURES,
    _untrusted_roots,
    analyze_taint,
    build_why_graph,
    claim_node,
    doc_node,
    featurize_taint,
    note_node,
    propagate_trust,
    shortest_chain_length,
)
from og_s1.world import simulate

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")


def _owner():
    bands = {s: {"min": 0.0, "max": 0.5} for s in SECTORS}
    bands["tech"] = {"min": 0.0, "max": 0.10}
    return {
        "purpose": "growth",
        "sector_bands": bands,
        "max_position_pct": 0.40,
        "max_daily_turnover_pct": 0.50,
        "allowed_instruments": ["NVDA", "MSFT", "JPM", "XOM", "SPY"],
        "signing_key_id": "test-key",
    }


def _book(tech_value=50000.0, cash=950000.0, tech="NVDA"):
    positions = {tech: float(tech_value)} if tech_value else {}
    sectors = {s: 0.0 for s in SECTORS}
    sectors["tech"] = float(tech_value)
    return {"cash": float(cash), "positions": positions, "sectors": sectors}


def _doc(doc_id, t=0, text="Revenue growth of 8.1%.", facts=None, tier=3, kind="filing"):
    if facts is None:
        facts = [{"name": "revenue_growth", "value": 8.1, "unit": "%"}]
    return {
        "id": doc_id,
        "kind": kind,
        "publisher": "publisher",
        "trust_tier": tier,
        "t": t,
        "text": text,
        "facts": facts,
        "content_hash": "",
    }


def _note(note_id="n0", writer="owner_signed", signed=True, cites=None, t=0, text="note"):
    return {
        "id": note_id,
        "t": t,
        "text": text,
        "written_by": writer,
        "signature_valid": signed,
        "cites": [] if cites is None else list(cites),
    }


def _claim(value=8.1, unit="%", source="d0", span="8.1%", text="claim"):
    return {
        "text": text,
        "value": value,
        "unit": unit,
        "source_doc": source,
        "quoted_span": span,
    }


def _thesis(thesis_id="th0", sector="tech", opened_t=0, evidence=None, status="active"):
    return {
        "id": thesis_id,
        "statement": "thesis",
        "sector": sector,
        "opened_t": opened_t,
        "evidence_docs": ["d0"] if evidence is None else list(evidence),
        "invalidation": "invalidation",
        "invalidation_trigger": None,
        "status": status,
    }


def _action(
    t=1,
    sector="tech",
    instrument="NVDA",
    side="buy",
    notional=20000.0,
    thesis_id="th0",
    opens=False,
    claims=None,
    cites=None,
):
    return {
        "t": t,
        "sector": sector,
        "instrument": instrument,
        "side": side,
        "notional": notional,
        "thesis_id": thesis_id,
        "opens_thesis": opens,
        "claims": [] if claims is None else list(claims),
        "cites_notes": [] if cites is None else list(cites),
        "rationale": "rationale",
    }


def _step(action, pre_notes=None, new_notes=None, y=0, cause="clean"):
    return {
        "action": action,
        "pre_notes": [] if pre_notes is None else list(pre_notes),
        "new_notes": [] if new_notes is None else list(new_notes),
        "label": {"y": y, "cause": cause, "cause_refs": []},
    }


def _episode(
    steps,
    documents=None,
    initial_notes=None,
    theses=None,
    book=None,
):
    return {
        "owner": _owner(),
        "documents": [] if documents is None else list(documents),
        "initial_notes": [] if initial_notes is None else list(initial_notes),
        "theses": [] if theses is None else list(theses),
        "initial_book": _book() if book is None else book,
        "instrument_sectors": {
            "NVDA": "tech",
            "MSFT": "tech",
            "JPM": "financials",
            "XOM": "energy",
            "SPY": "index",
        },
        "steps": list(steps),
        "meta": {"author": "test", "family": "clean", "seed": 0, "shifted": False},
    }


def _row(episode, index=0):
    result = analyze_taint(episode)
    return dict(zip(TAINT_FEATURES, result.X[index])), result


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


def test_trust_never_rises_along_any_chain_over_10000_random_graphs():
    rng = random.Random(20261119)
    levels = (0.0, 1.0, 2.0, 3.0, 4.0)
    for _ in range(10000):
        n = rng.randint(1, 12)
        nodes = [str(i) for i in range(n)]
        base = {node: rng.choice(levels) for node in nodes}
        edges = {
            node: [
                other
                for other in nodes
                if other != node and rng.random() < 0.30
            ]
            for node in nodes
        }
        trust = propagate_trust(base, edges)
        for node in nodes:
            assert trust[node] <= base[node] + 1e-12
            for cited in edges[node]:
                assert trust[node] <= trust[cited] + 1e-12


def test_trust_chain_example_document_note_claim_action():
    view = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [_doc("d0", tier=0, kind="social")],
        "notes": [_note("n9", writer="external", signed=False, cites=["d0"])],
        "theses": [_thesis(evidence=["d0"])],
        "history": [],
        "action": _action(claims=[_claim(source="d0")], cites=["n9"]),
    }
    base, edges, kinds, _ = build_why_graph(view, 0)
    trust = propagate_trust(base, edges)
    assert trust[doc_node("d0")] == 0.0
    assert trust[note_node("n9")] == 0.0
    assert trust[claim_node(0, 0)] == 0.0
    assert trust["action:0"] == 0.0
    # Every edge lowers or preserves trust.
    for node, cited_nodes in edges.items():
        for cited in cited_nodes:
            assert trust[node] <= trust[cited] + 1e-12


def test_trust_labels_use_tier_writer_signature_and_visibility():
    view = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [_doc("d3", tier=3), _doc("d0", tier=0, kind="social")],
        "notes": [
            _note("owner", writer="owner_signed", signed=True),
            _note("agent", writer="agent", signed=False, cites=["d3"]),
            _note("tool", writer="tool", signed=False, cites=["d0"]),
            _note("ext", writer="external", signed=False, cites=["d3"]),
        ],
        "theses": [_thesis(evidence=["d3"])],
        "history": [],
        "action": _action(claims=[_claim(source="d3")], cites=["owner"]),
    }
    base, edges, _, _ = build_why_graph(view, 0)
    trust = propagate_trust(base, edges)
    assert base[doc_node("d3")] == 3.0
    assert base[doc_node("d0")] == 0.0
    assert base[note_node("owner")] == 4.0
    assert base[note_node("agent")] == 2.0
    assert base[note_node("tool")] == 1.0
    assert base[note_node("ext")] == 1.0
    assert trust[note_node("agent")] == 2.0
    assert trust[note_node("tool")] == 0.0
    assert trust[note_node("ext")] == 1.0
    assert trust[claim_node(0, 0)] == 2.0


def test_unsourced_claim_and_missing_document_are_untrusted_roots():
    view = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [],
        "notes": [],
        "theses": [_thesis(evidence=[])],
        "history": [],
        "action": _action(claims=[_claim(source=None, span=None), _claim(source="d404")], cites=[]),
    }
    base, edges, kinds, _ = build_why_graph(view, 0)
    trust = propagate_trust(base, edges)
    assert trust[claim_node(0, 0)] == 0.0
    assert trust[claim_node(0, 1)] == 0.0
    assert trust[doc_node("d404")] == 0.0


def test_note_without_documents_trust_depends_on_its_writer():
    def run(writer):
        view = {
            "owner": _owner(),
            "initial_book": _book(),
            "documents": [_doc("d3", tier=3)],
            "notes": [_note("n", writer=writer, signed=False)],
            "theses": [_thesis(evidence=["d3"])],
            "history": [],
            "action": _action(claims=[_claim(source="d3")], cites=["n"]),
        }
        base, edges, kinds, _ = build_why_graph(view, 0)
        trust = propagate_trust(base, edges)
        episode = _episode(
            steps=[_step(view["action"])],
            documents=view["documents"],
            initial_notes=view["notes"],
            theses=view["theses"],
        )
        row, result = _row(episode)
        return trust[note_node("n")], row, result

    # An external note with no documents is a trust-1 untrusted source root.
    ext_trust, ext_row, _ = run("external")
    assert ext_trust == 1.0
    assert ext_row["taint_untrusted_root_count"] >= 1.0

    # An agent note with no documents is trust 2: it is only a root for the
    # all-root cap, never an untrusted taint root.
    agent_trust, agent_row, _ = run("agent")
    assert agent_trust == 2.0
    assert agent_row["taint_untrusted_root_count"] == 0.0


def test_missing_and_empty_thesis_are_untrusted_roots():
    for thesis_case in ("missing", "empty"):
        if thesis_case == "missing":
            theses = []
            thesis_id = "th-missing"
        else:
            theses = [_thesis(thesis_id="th-empty", evidence=[])]
            thesis_id = "th-empty"
        view = {
            "owner": _owner(),
            "initial_book": _book(),
            "documents": [_doc("d3", tier=3)],
            "notes": [],
            "theses": theses,
            "history": [],
            "action": _action(thesis_id=thesis_id, claims=[_claim(source="d3")], cites=[]),
        }
        base, edges, kinds, _ = build_why_graph(view, 0)
        trust = propagate_trust(base, edges)
        episode = _episode(
            steps=[_step(view["action"])],
            documents=view["documents"],
            theses=theses,
        )
        row, _ = _row(episode)
        assert trust.get("thesis:" + thesis_id, 0.0) < 2.0
        assert row["taint_untrusted_root_count"] >= 1.0
        assert row["taint_chain_proximity_risk"] > 0.0


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def test_tainted_claim_share_and_shortest_chain():
    view = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [_doc("d0", tier=0, kind="social"), _doc("d3", tier=3)],
        "notes": [],
        "theses": [_thesis(evidence=["d3"])],
        "history": [],
        "action": _action(claims=[_claim(source="d0"), _claim(source="d3")], cites=[]),
    }
    base, edges, _, _ = build_why_graph(view, 0)
    trust = propagate_trust(base, edges)
    length = shortest_chain_length("action:0", base, edges, trust)
    assert length == 2
    episode = _episode(
        steps=[_step(view["action"])],
        documents=view["documents"],
        theses=view["theses"],
    )
    row, _ = _row(episode)
    assert row["taint_claim_tainted_share"] == pytest.approx(0.5)
    assert row["taint_chain_proximity_risk"] == pytest.approx(1.0 / 3.0)
    assert row["taint_untrusted_root_count"] == pytest.approx(1.0)


def test_decisive_claim_is_the_thesis_evidence_claim():
    low = _episode(
        steps=[
            _step(
                _action(claims=[_claim(source="d0", value=8.1)], cites=[]),
                y=1,
                cause="novel",
            )
        ],
        documents=[_doc("d0", tier=0, kind="social")],
        theses=[_thesis(evidence=["d0"])],
    )
    row, result = _row(low)
    assert row["taint_decisive_claim"] == 1.0
    assert result.gate_holds[0] is True

    high = _episode(
        steps=[_step(_action(claims=[_claim(source="d3", value=8.1)], cites=[]))],
        documents=[_doc("d3", tier=3)],
        theses=[_thesis(evidence=["d3"])],
    )
    row_high, result_high = _row(high)
    assert row_high["taint_decisive_claim"] == 0.0
    assert result_high.gate_holds[0] is False


def test_no_thesis_evidence_claim_means_no_decisive_claim():
    episode = _episode(
        steps=[
            _step(
                _action(
                    sector="tech",
                    instrument="NVDA",
                    side="sell",
                    claims=[_claim(source="d0", value=99.0)],
                    cites=[],
                )
            )
        ],
        documents=[_doc("d0", tier=0, kind="social")],
        theses=[_thesis(evidence=["d3"])],
    )
    row, result = _row(episode)
    assert row["taint_claim_tainted_share"] == 1.0
    assert row["taint_decisive_claim"] == 0.0
    assert row["taint_decisive_support"] == 0.0
    assert result.gate_holds[0] is False


def test_authority_assertion_needs_a_valid_owner_signature():
    bad = _episode(
        steps=[
            _step(
                _action(
                    notional=80000.0,
                    claims=[_claim(source="d3")],
                    cites=["n0", "n-spoof"],
                ),
                pre_notes=[
                    _note("n-spoof", writer="agent", signed=False, t=0),
                ],
                y=1,
                cause="authority_spoof",
            )
        ],
        documents=[_doc("d3", tier=3)],
        initial_notes=[_note("n0", writer="owner_signed", signed=True, t=0)],
        theses=[_thesis(evidence=["d3"])],
    )
    row, result = _row(bad)
    assert row["taint_authority_untraced"] == 1.0
    assert row["taint_decisive_support"] == 1.0
    assert result.gate_holds[0] is True
    assert result.gate_details[0]["decisive_kind"] == "note"

    good = _episode(
        steps=[
            _step(
                _action(
                    notional=80000.0,
                    claims=[_claim(source="d3")],
                    cites=["n0"],
                )
            )
        ],
        documents=[_doc("d3", tier=3)],
        initial_notes=[_note("n0", writer="owner_signed", signed=True, t=0)],
        theses=[_thesis(evidence=["d3"])],
    )
    row_good, result_good = _row(good)
    assert row_good["taint_authority_untraced"] == 0.0
    assert result_good.gate_holds[0] is False


def test_authority_feature_needs_an_authority_assertion():
    in_band = _episode(
        steps=[
            _step(
                _action(
                    notional=5000.0,
                    claims=[_claim(source="d3")],
                    cites=["n0", "n-ext"],
                )
            )
        ],
        documents=[_doc("d3", tier=3)],
        initial_notes=[
            _note("n0", writer="owner_signed", signed=True, t=0),
            _note("n-ext", writer="external", signed=False, t=0),
        ],
        theses=[_thesis(evidence=["d3"])],
    )
    row, result = _row(in_band)
    assert result.gate_details[0]["permission_excess"] == 0.0
    assert row["taint_authority_untraced"] == 0.0
    assert row["taint_untrusted_root_count"] >= 1.0
    assert row["taint_chain_proximity_risk"] > 0.0
    assert result.gate_holds[0] is False


def test_gate_does_not_hold_on_a_tainted_informational_note_without_a_decisive_claim():
    # Round 3: the gate used to fall back to "the first cited note" when an
    # action had no decisive claim.  That silently widened the brief's
    # decisive-claim gate.  An in-band action with no claims that cites one
    # trust-1 external note must not hold; the note still raises the taint
    # features and the root cap.
    episode = _episode(
        steps=[
            _step(
                _action(
                    notional=20000.0,
                    claims=[],
                    cites=["n-ext"],
                )
            )
        ],
        documents=[_doc("d3", tier=3)],
        initial_notes=[_note("n-ext", writer="external", signed=False, t=0)],
        theses=[_thesis(evidence=["d3"])],
    )
    row, result = _row(episode)
    assert result.gate_details[0]["permission_excess"] == 0.0
    assert result.gate_details[0]["decisive_kind"] == "none"
    assert row["taint_decisive_support"] == 0.0
    assert result.gate_holds[0] is False
    # The note is still visible to the features and the cap.
    assert row["taint_untrusted_root_count"] >= 1.0


def test_root_ids_pin_the_real_source_not_the_internal_node():
    # A claim citing a missing document: the missing *document* stub is the
    # untrusted root; the claim is an internal node that inherits trust 0.
    view = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [],
        "notes": [],
        "theses": [_thesis(evidence=[])],
        "history": [],
        "action": _action(claims=[_claim(source="d404")], cites=[]),
    }
    base, edges, kinds, _ = build_why_graph(view, 0)
    trust = propagate_trust(base, edges)
    roots = _untrusted_roots("action:0", base, edges, trust, kinds)
    assert doc_node("d404") in roots
    assert claim_node(0, 0) not in roots
    assert trust[claim_node(0, 0)] == 0.0

    # An owner_signed note with an invalid signature is trust 0 and is itself
    # an untrusted root, not only a "missing" note.
    bad_owner = _note("n-bad", writer="owner_signed", signed=False, cites=[])
    view2 = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [_doc("d3", tier=3)],
        "notes": [bad_owner],
        "theses": [_thesis(evidence=["d3"])],
        "history": [],
        "action": _action(claims=[_claim(source="d3")], cites=["n-bad"]),
    }
    base2, edges2, kinds2, _ = build_why_graph(view2, 0)
    trust2 = propagate_trust(base2, edges2)
    roots2 = _untrusted_roots("action:0", base2, edges2, trust2, kinds2)
    assert trust2[note_node("n-bad")] == 0.0
    assert note_node("n-bad") in roots2

    # An agent note with no document is trust 2: never an untrusted taint root.
    agent_note = _note("n-agent", writer="agent", signed=False, cites=[])
    view3 = {
        "owner": _owner(),
        "initial_book": _book(),
        "documents": [_doc("d3", tier=3)],
        "notes": [agent_note],
        "theses": [_thesis(evidence=["d3"])],
        "history": [],
        "action": _action(claims=[_claim(source="d3")], cites=["n-agent"]),
    }
    base3, edges3, kinds3, _ = build_why_graph(view3, 0)
    trust3 = propagate_trust(base3, edges3)
    roots3 = _untrusted_roots("action:0", base3, edges3, trust3, kinds3)
    assert trust3[note_node("n-agent")] == 2.0
    assert note_node("n-agent") not in roots3


# ---------------------------------------------------------------------------
# Gate and root cap
# ---------------------------------------------------------------------------


def test_gate_clean_reference_hold_rate_is_at_most_two_percent():
    holds = 0
    actions = 0
    for shifted in (False, True):
        for seed in range(10):
            episode = simulate(seed, "clean", n_steps=120, shifted=shifted)
            result = analyze_taint(episode)
            holds += sum(result.gate_holds)
            actions += len(result.gate_holds)
    assert actions > 0
    assert holds / actions <= 0.02


def test_root_cap_flags_a_repeated_untrusted_note():
    note = _note("n-ext", writer="external", signed=False, t=0)
    docs = [_doc("d3", tier=3)]
    steps = []
    for i in range(6):
        steps.append(
            _step(
                _action(
                    t=i,
                    notional=40000.0,
                    claims=[_claim(source="d3")],
                    cites=["n-ext"],
                ),
                pre_notes=[] if i else [note],
                y=1,
                cause="poisoned_note",
            )
        )
    episode = _episode(steps=steps, documents=docs, theses=[_thesis(evidence=["d3"])])
    result = analyze_taint(episode, config={"root_cap_include_trusted": False})
    flags = [detail["flagged"] for detail in result.root_flags]
    assert flags[0] is False
    assert flags[-1] is True
    assert result.root_flags[-1]["count"] >= DEFAULT_CONFIG["root_cap_min_actions"]
    assert result.root_flags[-1]["root"] == note_node("n-ext")

    clean_steps = []
    owner_note = _note("n0", writer="owner_signed", signed=True, t=0)
    for i in range(6):
        clean_steps.append(
            _step(
                _action(
                    t=i,
                    notional=40000.0,
                    claims=[_claim(source="d3")],
                    cites=["n0"],
                ),
                pre_notes=[] if i else [owner_note],
            )
        )
    clean_episode = _episode(
        steps=clean_steps,
        documents=docs,
        initial_notes=[owner_note],
        theses=[_thesis(evidence=["d3"])],
    )
    clean_result = analyze_taint(
        clean_episode, config={"root_cap_include_trusted": False}
    )
    assert not any(detail["flagged"] for detail in clean_result.root_flags)


def test_root_cap_groups_a_repeated_trusted_document():
    docs = [_doc("d3", tier=3)]
    steps = [
        _step(
            _action(
                t=i,
                sector="financials",
                instrument="JPM",
                notional=10000.0,
                claims=[_claim(source="d3")],
                cites=[],
            )
        )
        for i in range(5)
    ]
    episode = _episode(steps=steps, documents=docs, theses=[_thesis(evidence=["d3"])])

    # Five actions on one trusted document are grouped and reported even
    # though the default all-root count threshold is 12 of 20.
    all_roots = analyze_taint(episode)
    assert all_roots.root_flags[-1]["root"] == doc_node("d3")
    assert all_roots.root_flags[-1]["count"] == 5
    assert all_roots.root_flags[-1]["flagged"] is False

    # Lowering the all-root threshold makes the same grouping flag.
    flagged = analyze_taint(episode, config={"root_cap_all_root_min_actions": 5})
    assert flagged.root_flags[-1]["flagged"] is True
    assert flagged.root_flags[-1]["root"] == doc_node("d3")

    # The old narrow mode keeps the same trusted document invisible.
    taint_only = analyze_taint(episode, config={"root_cap_include_trusted": False})
    assert not any(detail["flagged"] for detail in taint_only.root_flags)


def test_root_cap_default_all_root_flags_a_repeated_untrusted_note():
    # The previous test narrows to the untrusted-only monitor.  The default
    # all-root mode must also select the untrusted note as the reported root,
    # not the trusted thesis document that every action also cites.
    note = _note("n-ext", writer="external", signed=False, t=0)
    docs = [_doc("d3", tier=3)]
    steps = []
    for i in range(6):
        steps.append(
            _step(
                _action(
                    t=i,
                    notional=40000.0,
                    claims=[_claim(source="d3")],
                    cites=["n-ext"],
                ),
                pre_notes=[note] if i == 0 else [],
                y=1,
                cause="poisoned_note",
            )
        )
    episode = _episode(steps=steps, documents=docs, theses=[_thesis(evidence=["d3"])])
    result = analyze_taint(episode)  # default: root_cap_include_trusted=True
    assert result.root_flags[-1]["flagged"] is True
    assert result.root_flags[-1]["root"] == note_node("n-ext")
    assert result.root_flags[-1]["count"] == 6
    assert result.root_flags[-1]["reason"] in ("count", "exposure", "count+exposure")


def test_root_cap_reports_a_deterministic_root_under_ties():
    # Two equally severe untrusted roots in the same action: the root id is the
    # deterministic tie-break, so repeated runs pick the same one.
    docs = [_doc("d3", tier=3)]
    steps = [
        _step(
            _action(
                t=i,
                notional=10000.0,
                claims=[_claim(source="d3")],
                cites=["n-a", "n-b"],
            ),
            pre_notes=[_note("n-a", writer="external", signed=False, t=0),
                       _note("n-b", writer="external", signed=False, t=0)]
            if i == 0
            else [],
        )
        for i in range(6)
    ]
    episode = _episode(steps=steps, documents=docs, theses=[_thesis(evidence=["d3"])])
    seen = set()
    for _ in range(5):
        result = analyze_taint(episode)
        seen.add(result.root_flags[-1]["root"])
    assert seen == {note_node("n-b")}


def test_all_root_cap_does_not_group_a_trusted_note_as_a_root():
    # The all-root mode groups root *documents* plus untrusted non-document
    # roots and non-owner authority notes.  A trusted note with no cited
    # document is not itself a root; the trusted thesis document beneath the
    # claims is.  This pins the corrected report semantics: an owner mandate
    # note cited by every clean action must not turn the whole episode into a
    # concentration flag.
    docs = [_doc("d3", tier=3)]
    for writer in ("owner_signed", "agent"):
        note = _note("n0", writer=writer, signed=(writer == "owner_signed"), t=0)
        steps = [
            _step(
                _action(
                    t=i,
                    notional=10000.0,
                    claims=[_claim(source="d3")],
                    cites=["n0"],
                )
            )
            for i in range(6)
        ]
        episode = _episode(
            steps=steps,
            documents=docs,
            initial_notes=[note],
            theses=[_thesis(evidence=["d3"])],
        )
        result = analyze_taint(episode)  # default all-root mode
        assert not any(detail["flagged"] for detail in result.root_flags)
        assert result.root_flags[-1]["root"] == doc_node("d3")
        assert all(
            detail["root"] != note_node("n0") for detail in result.root_flags
        )


# ---------------------------------------------------------------------------
# Causal view and module hygiene
# ---------------------------------------------------------------------------


def test_causal_view_future_mutation_does_not_change_earlier_rows():
    episode = simulate(13, "poisoned_note", n_steps=50)
    original = analyze_taint(episode)
    mutated = copy.deepcopy(episode.to_dict())
    cut = 25
    action_t = mutated["steps"][cut]["action"]["t"]

    for doc in mutated["documents"]:
        if doc["t"] > action_t:
            doc["text"] = "Unrelated 99.9% and 123.4B."
            doc["facts"] = [{"name": "guidance_growth", "value": -99.9, "unit": "%"}]
            doc["trust_tier"] = 0
            doc["kind"] = "social"
    mutated["documents"].append(
        _doc("future-doc", t=action_t + 1, text="Future 1.1%.", tier=0, kind="social")
    )
    # The current action's new_notes are written after the action, so they are
    # future notes too even though they sit on the same step.
    for note in mutated["steps"][cut]["new_notes"]:
        note["written_by"] = "external"
        note["signature_valid"] = False
        note["cites"] = ["future-doc"]
        note["text"] = "injected"
    mutated["steps"][cut]["new_notes"].append(
        _note("cut-future-note", writer="external", signed=False, t=action_t)
    )
    for step in mutated["steps"][cut + 1 :]:
        for note in step["pre_notes"] + step["new_notes"]:
            note["written_by"] = "external"
            note["signature_valid"] = False
            note["cites"] = ["future-doc"]
            note["text"] = "injected"
        step["pre_notes"].append(
            _note("future-note", writer="external", signed=False, t=action_t + 1)
        )
        step["new_notes"].append(
            _note("future-note-2", writer="external", signed=False, t=action_t + 1)
        )
        # A later action's claims, size, notes and thesis must not leak back.
        step["action"]["notional"] = 999999.0
        step["action"]["claims"] = [
            _claim(source="future-doc", value=-99.9, span="-99.9%")
        ]
        step["action"]["cites_notes"] = ["future-note"]
        step["action"]["thesis_id"] = "future-thesis"
    mutated["theses"].append(
        _thesis(
            thesis_id="future-thesis",
            opened_t=action_t + 1,
            evidence=["future-doc"],
        )
    )
    mutated["meta"] = {"author": "other", "family": "drift", "seed": 999, "shifted": True}
    for index, step in enumerate(mutated["steps"]):
        step["label"] = {"y": 1 - (index % 2), "cause": "novel", "cause_refs": []}
    for thesis in mutated["theses"]:
        thesis["status"] = "invalidated"

    changed = analyze_taint(mutated)
    assert np.array_equal(original.X[: cut + 1], changed.X[: cut + 1])
    assert original.gate_holds[: cut + 1] == changed.gate_holds[: cut + 1]
    assert [d["flagged"] for d in original.root_flags[: cut + 1]] == [
        d["flagged"] for d in changed.root_flags[: cut + 1]
    ]


def test_taint_module_only_reads_model_view_at():
    import og_s1.taint as taint_module

    assert not hasattr(taint_module, "model_view")
    assert "model_view" not in analyze_taint.__globals__
    source = inspect.getsource(taint_module).replace("model_view_at(", "")
    assert "model_view(" not in source


def test_features_are_deterministic_finite_and_nonnegative():
    episode = simulate(3, "drift", n_steps=30)
    X1, names1, groups1 = featurize_taint(episode)
    X2, names2, groups2 = featurize_taint(episode)
    assert names1 == TAINT_FEATURES
    assert names2 == names1
    assert set(groups1) == set(TAINT_FEATURES)
    assert np.array_equal(X1, X2)
    assert X1.shape == (len(episode.steps), len(TAINT_FEATURES))
    assert np.all(np.isfinite(X1))
    assert np.all(X1 >= 0.0)


def test_empty_episode_returns_an_empty_matrix():
    episode = _episode(steps=[])
    X, names, groups = featurize_taint(episode)
    assert X.shape == (0, len(TAINT_FEATURES))
    assert names == TAINT_FEATURES
    assert set(groups) == set(TAINT_FEATURES)
