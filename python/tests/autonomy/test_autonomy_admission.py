"""The admission controller: hard predicates decide, models only tighten, admission is linearizable (unit, property, adversarial)."""
import random
import threading
from dataclasses import replace

import pytest

from autonomy_helpers import OWNER, SECTORS, Clock, make_contract, make_controller, req
from orderguard_autonomy import contract as C
from orderguard_autonomy._crypto import key_from_label
from orderguard_autonomy.admission import Decision, SupervisionConfig, combine
from orderguard_autonomy.state import L

D = Decision


def test_ten_thousand_held_three_agents_add_five_thousand_each():
    ctl = make_controller(make_contract(**{"portfolio.max_issuer_weight": 0.20, "autonomy.review_above_usd": 20_000.0}))  # $20,000 per issuer
    first = ctl.admit(req(ctl, "a1", "NVDA", "buy", 100))                          # $10,000 held
    ctl.on_terminal(first.order_id, L.FILLED, 100)
    out = [ctl.admit(req(ctl, f"a{i}", "NVDA", "buy", 50)).decision for i in (1, 2, 3)]
    assert out == [D.ALLOW, D.ALLOW, D.REFUSE]                                   # the third would make $25,000 if all fill


def test_risk_reducing_order_passes_even_when_the_book_is_over_a_cap():
    ctl = make_controller()
    a = ctl.admit(req(ctl, "a1", "AAPL", "buy", 90))
    ctl.on_terminal(a.order_id, L.FILLED, 90)
    ctl.set_marks({**{s: 100.0 for s in SECTORS}, "AAPL": 300.0}, ctl.test_clock())     # price tripled: $27,000 > $20,000 cap
    assert ctl.admit(req(ctl, "a1", "AAPL", "buy", 1)).decision == D.REFUSE
    assert ctl.admit(req(ctl, "a1", "AAPL", "sell", 10, limit=300.0)).decision == D.ALLOW


def test_sector_and_declared_scenario_caps_refuse_with_reasons():
    ctl = make_controller(make_contract(**{"portfolio.max_sector_weight": 0.20}))   # $20,000 per sector
    for sym in ("AAPL", "MSFT"):
        r = ctl.admit(req(ctl, "a1", sym, "buy", 80))
        assert r.decision == D.ALLOW
    r = ctl.admit(req(ctl, "a2", "NVDA", "buy", 80))                               # tech would be $16,000 + $8,000
    assert r.decision == D.REFUSE and any("sector" in x for x in r.hard_reasons)
    ctl2 = make_controller(make_contract(**{"portfolio.max_scenario_loss_usd": 2_000.0}))
    ok = ctl2.admit(req(ctl2, "a1", "SPY", "buy", 80))                              # market -20%: $1,600
    bad = ctl2.admit(req(ctl2, "a2", "KO", "buy", 30))                              # +$600 -> $2,200
    assert ok.decision == D.ALLOW and bad.decision == D.REFUSE
    assert any("declared scenario" in x for x in bad.hard_reasons)


def test_idempotency_key_never_creates_a_second_order():
    ctl = make_controller()
    r1 = ctl.admit(req(ctl, "a1", "KO", "buy", 10, key="same"))
    r2 = ctl.admit(req(ctl, "a1", "KO", "buy", 10, key="same"))
    assert r1.decision == D.ALLOW and r2.decision == D.REFUSE and r2.order_id == r1.order_id
    assert len(ctl.ledger.state.working) == 1


def test_stale_state_and_review_threshold_hold_rather_than_refuse():
    ctl = make_controller()
    ctl.test_clock.t += 60                                                         # marks are now a minute old
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10))
    assert r.decision == D.HOLD and any("old" in x for x in r.hard_reasons)
    ctl.set_marks({s: 100.0 for s in SECTORS}, ctl.test_clock())
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 95))                                 # $9,500 > $9,000 review threshold
    assert r.decision == D.HOLD and r.reservation_id is None                       # a held order reserves nothing
    approved = ctl.resolve_hold(r.order_id, approve=True)                          # a person approves: admitted afresh
    assert approved.decision == D.ALLOW and approved.certificate is not None and approved.reservation_id
    r2 = ctl.admit(req(ctl, "a2", "KO", "buy", 95))
    assert ctl.resolve_hold(r2.order_id, approve=False) is None and r2.order_id not in ctl.held
    # an approval cannot override a hard limit that has since been reached
    ctl3 = make_controller(make_contract(**{"portfolio.max_issuer_weight": 0.15}))
    h = ctl3.admit(req(ctl3, "a1", "KO", "buy", 95))
    assert h.decision == D.HOLD
    assert ctl3.admit(req(ctl3, "a2", "KO", "buy", 80)).decision == D.ALLOW          # $8,000 of the $15,000 cap
    assert ctl3.resolve_hold(h.order_id, approve=True).decision == D.REFUSE


def test_contract_tampering_version_and_untrusted_signer_refuse():
    ctl = make_controller()
    loose = replace(ctl.contract, portfolio={**ctl.contract.portfolio, "max_issuer_weight": 1.0})
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10), contract=loose)
    assert r.decision == D.REFUSE and any("signature" in x for x in r.hard_reasons)
    v2 = C.sign_contract(replace(ctl.contract, version=2, signature=""), OWNER)
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10), contract=v2)
    assert r.decision == D.REFUSE and any("version" in x for x in r.hard_reasons)
    forged = C.sign_contract(replace(ctl.contract, signature=""), key_from_label("mallory"))
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10), contract=forged)
    assert r.decision == D.REFUSE and any("trusted" in x for x in r.hard_reasons)


def test_unauthorized_agent_borrowed_lease_and_expired_lease_refuse():
    ctl = make_controller()
    stranger = req(ctl, "a1", "KO", "buy", 1)
    r = ctl.admit(replace(stranger, agent="mallory", intent=replace(stranger.intent, agent="mallory")))
    assert r.decision == D.REFUSE and any("not authorized" in x for x in r.hard_reasons)
    borrowed = replace(req(ctl, "a2", "KO", "buy", 1), lease=ctl.test_leases["a1"])
    assert ctl.admit(borrowed).decision == D.REFUSE
    ctl.test_clock.t += 301
    ctl.set_marks({s: 100.0 for s in SECTORS}, ctl.test_clock())
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 1))
    assert r.decision == D.REFUSE and any("expired" in x for x in r.hard_reasons)


def test_compromised_tool_order_mismatch_refuses_and_quarantines_the_lineage():
    ctl = make_controller()
    child = ctl.leases.grant("a1", "c1", parent=ctl.test_leases["a1"])            # a spawned helper under a1
    good = req(ctl, "a1", "KO", "buy", 10)
    tampered = replace(good, quantity=100)                                        # the tool inflated the size after the decision
    r = ctl.admit(tampered)
    assert r.decision == D.REFUSE and any("exceeds the intended" in x for x in r.hard_reasons)
    assert ctl.leases.check(ctl.test_leases["a1"]) and ctl.leases.check(child)      # both leases are dead now
    assert ctl.leases.check(ctl.test_leases["a2"]) is None                         # a sibling is untouched
    assert ctl.admit(req(ctl, "a1", "KO", "buy", 1)).decision == D.REFUSE


def test_missing_or_foreign_intent_record_refuses():
    ctl = make_controller()
    assert ctl.admit(req(ctl, "a1", "KO", "buy", 1, intent=False)).decision == D.REFUSE
    r = req(ctl, "a2", "KO", "buy", 1)
    assert ctl.admit(replace(r, intent=replace(r.intent, agent="a3"))).decision == D.REFUSE


def test_supervision_only_holds_never_refuses_a_clean_risk_reducing_order():
    ctl = make_controller()
    a = ctl.admit(req(ctl, "a1", "KO", "buy", 50))
    ctl.on_terminal(a.order_id, L.FILLED, 50)
    fake = "0" * 64
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10, evidence=(fake,)))              # cites evidence that does not exist
    assert r.decision == D.HOLD and any("not on record" in x for x in r.model_reasons)
    r = ctl.admit(req(ctl, "a1", "KO", "sell", 10, evidence=(fake,)))
    assert r.decision == D.ALLOW


def test_news_trades_need_independent_origins_and_reposts_do_not_count():
    ctl = make_controller()
    t = ctl.test_clock()
    root = ctl.evidence.register("rumourmill", "Exclusive: KO to be acquired at a 40% premium, sources say", t - 5)
    reposts = [ctl.evidence.register(f"outlet{i}", "Exclusive: KO to be acquired at a 40% premium, sources say", t - 4, origin=f"outlet{i}",
                                     derived_from=(root.sha256,)) for i in range(3)]
    copies = [ctl.evidence.register(f"blog{i}", "EXCLUSIVE - KO to be acquired at a 40% premium, sources say!!", t - 3, origin=f"blog{i}")
              for i in range(3)]
    ev = tuple(x.sha256 for x in reposts + copies)
    r = ctl.admit(req(ctl, "a1", "KO", "buy", 10, kind="news", evidence=ev))
    assert r.decision == D.HOLD and any("independent origin" in x for x in r.model_reasons)
    a = ctl.evidence.register("wireA", "KO confirms agreement to be acquired by a beverage group", t - 2)
    b = ctl.evidence.register("filingB", "Form 8-K: definitive merger agreement filed by the company", t - 2)
    r = ctl.admit(req(ctl, "a2", "KO", "buy", 10, kind="news", evidence=(a.sha256, b.sha256)))
    assert r.decision == D.ALLOW


class _Model:
    def __init__(self, p):
        self.p = p

    def score_request(self, *a):
        if self.p is None:
            raise RuntimeError("model down")
        return self.p, "test"


@pytest.mark.parametrize("seed", range(5))
def test_property_a_model_can_never_loosen_a_hard_decision(seed):
    """Random orders through two controllers that differ only in the judgement model: the model's version is never less strict."""
    rng = random.Random(seed)
    for p in (0.0, 0.9, None):
        base, judged = make_controller(), make_controller(judgement=_Model(p))
        rank = {D.ALLOW: 0, D.HOLD: 1, D.REFUSE: 2}
        for i in range(60):
            sym, side, qty = rng.choice(list(SECTORS)), rng.choice(["buy", "sell"]), rng.choice([1, 20, 60, 120])
            lim = 100.0 * rng.choice([1.0, 1.01, 1.05])
            kw = dict(key=f"s{seed}-{i}", limit=lim)
            d0 = base.admit(req(base, "a1", sym, side, qty, **kw)).decision
            d1 = judged.admit(req(judged, "a1", sym, side, qty, **kw)).decision
            assert rank[d1] >= rank[d0]
            if p is None:
                assert d1 == d0                                                    # a failing model is no advice
    assert combine(D.REFUSE, D.ALLOW) is D.REFUSE


def test_linearizable_under_concurrent_agents():
    """Twelve threads hammer one issuer. Whatever the interleaving, the conservative projection never exceeds the cap."""
    ctl = make_controller(make_contract(agents=tuple(f"a{i}" for i in range(12)), **{"portfolio.max_issuer_weight": 0.2}),
                          supervision=SupervisionConfig(drift=False, herding=False, pacing=False, loops=False))
    allowed = []

    def worker(i):
        for j in range(15):
            r = ctl.admit(req(ctl, f"a{i}", "MSFT", "buy", 7, key=f"t{i}-{j}"))
            if r.decision in (D.ALLOW, D.HOLD):
                allowed.append(7)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) * 100 <= 20_000
    assert sum(allowed) * 100 > 20_000 - 700                                       # and it is not over-conservative
    assert ctl.root.check_invariants() == []


def test_risk_budget_holds_when_the_agent_escrow_is_exhausted():
    ctl = make_controller(risk_agent=600.0, risk_firm=600.0)
    decisions = [ctl.admit(req(ctl, "a1", s, "buy", 50)).decision for s in ("KO", "JNJ", "XOM", "SPY", "AAPL")]
    assert decisions[0] == D.ALLOW and D.HOLD in decisions
    held = [ctl.admit(req(ctl, "a2", "KO", "buy", 50))]
    assert held[0].decision == D.HOLD and any("risk budget" in x for x in held[0].model_reasons)


def test_reconcile_settles_escrow_and_returns_diversification():
    ctl = make_controller()
    ids = [ctl.admit(req(ctl, "a1", s, "buy", 40)).order_id for s in ("KO", "JNJ", "XOM")]
    node = ctl.nodes["a1"]
    reserved = node.used_risk
    ctl.reconcile([{"order_id": i, "status": "filled", "filled": 40} for i in ids], {"KO": 40, "JNJ": 40, "XOM": 40})
    assert node.used_risk < reserved                                               # Euler share < sum of standalone reservations
    assert not ctl.ledger.state.reservations
    assert ctl.root.check_invariants() == []


def test_a_retry_under_a_new_key_cannot_spend_the_same_decision_twice():
    ctl = make_controller()
    first = req(ctl, "a1", "KO", "buy", 10, key="try-1")
    r1 = ctl.admit(first)
    retry = replace(first, idempotency_key="try-2")                                # naive retry: new key, same decision
    r2 = ctl.admit(retry)
    assert r1.decision == D.ALLOW and r2.decision == D.REFUSE
    assert any("already working or filled" in x for x in r2.hard_reasons)
    ctl.on_status(r1.order_id, L.SUBMITTED)
    ctl.on_status(r1.order_id, L.UNCERTAIN)                                       # sent, no acknowledgement
    assert ctl.admit(replace(first, idempotency_key="try-2b")).decision == D.REFUSE
    ctl.reconcile([], None, complete=True)                                       # the broker proves the first never arrived
    assert ctl.ledger.state.working[r1.order_id].state == L.REJECTED
    assert ctl.admit(replace(first, idempotency_key="try-3")).decision == D.ALLOW # now the retry is legitimate
