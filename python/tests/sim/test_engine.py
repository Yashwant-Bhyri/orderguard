from orderguard_sim.engine import SimConfig, audit_order_log, run_scenario


def test_seeded_runs_are_deterministic_and_guarded_arms_audit_clean():
    cfg = SimConfig(agents=200, steps=16, seed=23, replicates=1, activity=0.01, attack_activity=0.12)
    first = run_scenario(cfg, "fake_headline")
    second = run_scenario(cfg, "fake_headline")
    for arm in first["arms"]:
        assert first["runs"][0]["arms"][arm]["digest"] == second["runs"][0]["arms"][arm]["digest"]
        assert first["arms"][arm]["auditor_valid"]
        assert first["arms"][arm]["auditor_breaches"] == 0
    assert first["runs"][0]["arms"]["unguarded"]["bad_dollars_executed"] > 0


def test_independent_auditor_catches_a_seeded_cap_breach():
    specs = {"e1": {"per_order": 100.0, "daily": 1000.0, "max_symbol_daily": 500.0, "max_position": 500.0}}
    events = [{"i": 1, "step": 0, "steps_per_day": 10, "envelope": "e1", "authority_decision": "allow",
               "authority_layer": "L5", "decision": "allow", "replay": False,
               "order": {"ticker": "AAPL", "side": "buy", "quantity": 2, "limit_price": 100.0}, "tp": 100.0}]
    audited = audit_order_log(events, specs)
    assert not audited["valid"]
    assert audited["cap_breaches"] >= 1
    assert any("per-order" in b["reason"] for b in audited["breaches"])


def test_stale_venue_orders_are_checked_against_the_current_median():
    from orderguard_sim.engine import run_arm
    from orderguard_sim.scenarios import build_scenario

    cfg = SimConfig(agents=1_000, steps=40, seed=5, replicates=1, activity=0.002, attack_activity=0.2)
    scenario = build_scenario("stale_feed", cfg.steps, attack_activity=cfg.attack_activity, seed=cfg.seed)
    unguarded = run_arm(cfg, scenario, "unguarded")
    guarded = run_arm(cfg, scenario, "gate_only")
    assert unguarded["by_label"]["stale_price"]["fills"] > 0
    assert guarded["authority_refusals_by_code"].get("band", 0) > 0
    assert guarded["audit"]["valid"]


def test_scale_smoke_uses_compact_population_for_100k_agents():
    from orderguard_sim.engine import run_arm
    from orderguard_sim.scenarios import build_scenario

    cfg = SimConfig(agents=100_000, steps=8, seed=31, replicates=1, activity=0.00001, attack_activity=0.001, envelopes=100)
    result = run_arm(cfg, build_scenario("crowded_momentum", cfg.steps, attack_activity=cfg.attack_activity, seed=cfg.seed), "unguarded")
    assert result["agents"] == 100_000
    assert result["audit"]["valid"]
    assert result["agents_per_s"] > 0

