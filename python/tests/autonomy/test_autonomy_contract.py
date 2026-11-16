"""The signed specification: intent -> proposal -> signature, the diff, attenuated delegation (unit, property, adversarial)."""
import random
from dataclasses import replace

import pytest

from autonomy_helpers import OWNER, SECTORS, base_limits, make_contract
from orderguard_autonomy import contract as C
from orderguard_autonomy._crypto import key_from_label, public_b64
from orderguard_autonomy.risk import Scenario

TRUSTED = {public_b64(OWNER)}


def test_intent_proposal_and_signature_are_three_objects():
    intent = C.Intent("Grow $250k, diversified, not too aggressive, no crypto", "owner")
    prop = C.RuleProposer(tuple(SECTORS) + ("BTC-USD",), {**SECTORS, "BTC-USD": "crypto"}).propose(intent)
    assert prop.limits["portfolio.capital_usd"] == 250_000
    assert "BTC-USD" not in prop.limits["trading.symbols"]
    assert prop.limits["portfolio.max_sector_weight"] == 0.35
    assert set(prop.consequences) >= {"market_down_20", "tech_down_30"}
    # the owner tightens one limit and loosens another before signing; both are recorded
    signed_limits = {**prop.limits, "portfolio.max_issuer_weight": 0.05, "trading.max_order_usd": prop.limits["trading.max_order_usd"] * 2}
    c = C.sign_contract(C.contract_from_limits(signed_limits, contract_id="c", principal="owner", agents=("a",)), OWNER)
    d = C.signed_diff(prop, c)
    assert d["changed"]["portfolio.max_issuer_weight"]["direction"] == "tighter"
    assert d["changed"]["trading.max_order_usd"]["direction"] == "looser"
    assert d["consequences_shown"] == prop.consequences
    assert not C.verify_contract(c, TRUSTED)


def test_unsigned_tampered_or_untrusted_contracts_fail():
    c = make_contract()
    assert not C.verify_contract(c, TRUSTED)
    assert C.verify_contract(replace(c, signature=""), TRUSTED)
    tampered = replace(c, portfolio={**c.portfolio, "max_issuer_weight": 0.9})
    assert "signature does not verify" in C.verify_contract(tampered, TRUSTED)
    assert "signature does not verify" in C.verify_contract(replace(c, authorized_agents=c.authorized_agents + ("mallory",)), TRUSTED)
    other = C.sign_contract(C.contract_from_limits(base_limits(), contract_id="c1", principal="owner", agents=("a1",)), key_from_label("x"))
    assert "signer is not a trusted key" in C.verify_contract(other, TRUSTED)


def test_malformed_contract_cannot_be_signed():
    lim = base_limits()
    lim["portfolio.max_issuer_weight"] = 1.5
    with pytest.raises(C.ContractInvalid):
        C.sign_contract(C.contract_from_limits(lim, contract_id="c", principal="o", agents=("a",)), OWNER)
    lim = base_limits()
    del lim["autonomy.lease_seconds"]
    with pytest.raises(C.ContractInvalid, match="missing autonomy.lease_seconds"):
        C.sign_contract(C.contract_from_limits(lim, contract_id="c", principal="o", agents=("a",)), OWNER)
    lim = base_limits()
    lim["portfolio.sectors"] = {k: v for k, v in lim["portfolio.sectors"].items() if k != "AAPL"}
    with pytest.raises(C.ContractInvalid, match="no sector for AAPL"):
        C.sign_contract(C.contract_from_limits(lim, contract_id="c", principal="o", agents=("a",)), OWNER)
    lim = base_limits()
    lim["trading.max_order_usd"] = float("nan")
    with pytest.raises((C.ContractInvalid, ValueError)):
        C.sign_contract(C.contract_from_limits(lim, contract_id="c", principal="o", agents=("a",)), OWNER)


def _child(parent, **over):
    flat = parent.flat()
    flat.update(over)
    return C.contract_from_limits(flat, contract_id="child", principal=parent.principal, agents=("sub",), parent_id=parent.contract_id)


def _narrow(rng, key, v):
    rule = C.SCHEMA[key]
    if rule == "subset":
        return v[: max(1, rng.randint(1, len(v)))]
    if rule == "le":
        return v * rng.uniform(0.0, 1.0)
    if rule == "ge":
        return v if key == "portfolio.es_alpha" and v >= 0.99 else (min(0.99, v + rng.uniform(0, 0.02)) if key == "portfolio.es_alpha" else v + rng.randint(0, 3))
    if rule == "implies":
        return False
    return v


def _widen(rng, key, v):
    rule = C.SCHEMA[key]
    if rule == "subset":
        return list(v) + ["EVIL"]
    if rule == "le":
        return v * rng.uniform(1.01, 3.0) + 1
    if rule == "ge":
        return v - 0.01 if key == "portfolio.es_alpha" else v - 1
    if rule == "implies":
        return True
    if rule == "sectors":
        return {**v, "NVDA": "staples"}                      # reclassify to dodge a sector cap
    if rule == "scenarios":
        return v[1:]                                          # drop a declared scenario
    if rule == "equal":
        return {**v, "id": "another-objective"}
    raise AssertionError(rule)


def test_property_any_narrowing_is_an_attenuation():
    rng = random.Random(1)
    parent = make_contract()
    for _ in range(300):
        flat = parent.flat()
        for key in rng.sample(sorted(C.SCHEMA), rng.randint(1, len(C.SCHEMA))):
            flat[key] = _narrow(rng, key, flat[key])
        child = C.contract_from_limits(flat, contract_id="child", principal="owner", agents=("sub",), parent_id="c1")
        assert C.is_attenuation(parent, child), C.attenuation_problems(parent, child)


def test_property_widening_any_single_limit_is_refused():
    rng = random.Random(2)
    parent = make_contract(**{"trading.allow_short": False})
    for key in sorted(C.SCHEMA):
        if C.SCHEMA[key] == "implies" and parent.flat()[key]:
            continue
        for _ in range(5):
            child = _child(parent, **{key: _widen(rng, key, parent.flat()[key])})
            assert not C.is_attenuation(parent, child), key


def test_adversarial_delegation_tricks_are_refused():
    parent = make_contract()
    flat = parent.flat()
    del flat["autonomy.review_above_usd"]                       # dropping a limit means unbounded
    child = C.contract_from_limits(flat, contract_id="x", principal="owner", agents=("s",), parent_id="c1")
    assert any("missing" in p for p in C.attenuation_problems(parent, child))
    flat = parent.flat()
    flat["portfolio.unknown_override"] = 1                      # an unknown key cannot be reasoned about
    child = C.contract_from_limits(flat, contract_id="x", principal="owner", agents=("s",), parent_id="c1")
    assert not C.is_attenuation(parent, child)
    assert not C.is_attenuation(parent, replace(_child(parent), principal="mallory"))
    assert not C.is_attenuation(parent, replace(_child(parent), parent_id="someone-else"))
    scn = [dict(s) for s in parent.portfolio["scenarios"]]
    scn[0] = {"name": scn[0]["name"], "shocks": {"*": -0.01}}    # soften a declared scenario but keep its name
    assert not C.is_attenuation(parent, _child(parent, **{"portfolio.scenarios": scn}))


def test_delegation_chain_signed_by_delegating_agent():
    parent = make_contract()
    agent_key = key_from_label("agent-a1")
    child = C.sign_contract(_child(parent, **{"trading.max_order_usd": 1000.0}), agent_key)
    grand = C.sign_contract(C.contract_from_limits({**child.flat(), "trading.symbols": ["AAPL"]}, contract_id="g", principal="owner",
                                                   agents=("subsub",), parent_id="child"), key_from_label("sub"))
    assert C.verify_chain([parent, child, grand], TRUSTED) == []
    wide = C.sign_contract(C.contract_from_limits({**child.flat(), "trading.max_order_usd": 5000.0}, contract_id="g", principal="owner",
                                                  agents=("subsub",), parent_id="child"), key_from_label("sub"))
    assert any("wider" in p for p in C.verify_chain([parent, child, wide], TRUSTED))
    assert C.verify_chain([child, grand], TRUSTED)               # a chain must start at an owner-signed root


def test_worst_fill_loss_is_optimal_against_a_linear_program():
    scipy = pytest.importorskip("scipy.optimize")
    rng = random.Random(3)
    syms = list(SECTORS)
    for _ in range(40):
        lim = base_limits(**{"portfolio.max_issuer_weight": rng.uniform(0.05, 0.5), "portfolio.max_sector_weight": rng.uniform(0.1, 0.8),
                             "portfolio.max_gross_usd": rng.uniform(20_000, 100_000)})
        scn = Scenario("s", {s: -rng.uniform(0, 0.5) for s in syms if rng.random() < 0.7})
        greedy = C.worst_fill_loss(lim, scn, SECTORS)
        cap = lim["portfolio.capital_usd"]
        c = [scn.shock_for(s, SECTORS) for s in syms]            # minimise -loss
        A, b = [[1.0] * len(syms)], [min(lim["portfolio.max_gross_usd"], cap * lim["trading.max_leverage"])]
        for sec in set(SECTORS.values()):
            A.append([1.0 if SECTORS[s] == sec else 0.0 for s in syms])
            b.append(lim["portfolio.max_sector_weight"] * cap)
        res = scipy.linprog(c, A_ub=A, b_ub=b, bounds=[(0, lim["portfolio.max_issuer_weight"] * cap)] * len(syms))
        assert abs(greedy - (-res.fun)) < 1e-4 * max(1.0, greedy)


def test_compiled_predicates_cover_every_hard_limit():
    names = {p.name for p in C.compile_predicates(make_contract())}
    assert {"issuer_cap", "sector_cap", "declared_scenario_loss", "gross_exposure", "no_short", "lease_valid", "price_band",
            "max_order_usd", "order_rate", "state_fresh", "review_above"} <= names
    model = [p for p in C.compile_predicates(make_contract()) if not p.hard]
    assert {p.name for p in model} == {"risk_budget", "portfolio_es"}
    assert all(p.on_fail == "hold" for p in model)            # model-dependent checks can only hold
