"""Offline replays never fall back to a live call; damaged raw results are refused; every family has matched controls; twins match for every technique."""
import json
from collections import defaultdict

import pytest

from orderguard_lab import cases as C, runner, tables
from orderguard_lab.llm_shared import ReplayIncomplete
from orderguard_lab.sandbox import compiler, sweep
from orderguard_guard.llm import ReplayMiss


class _MissingRecording:
    model = "recorded/none"

    def chat(self, *a, **k):
        raise ReplayMiss("OG_LLM=replay and no recorded response for request deadbeef")


def test_replay_miss_is_loud_in_strict_mode_and_a_labelled_error_otherwise(monkeypatch):
    case = C.select("C0-web")[0]
    monkeypatch.delenv("OG_REPLAY_STRICT", raising=False)
    rec = runner.run_case(case, _MissingRecording(), "naive", mode="live")
    assert str(rec["error"]).startswith("ReplayMiss")                 # the dashboard shows this to its user
    monkeypatch.setenv("OG_REPLAY_STRICT", "1")
    with pytest.raises(ReplayIncomplete, match="must not fall back to a live call"):
        runner.run_case(case, _MissingRecording(), "naive", mode="live")


def test_offline_sweeps_and_corpus_never_reach_a_model(monkeypatch):
    from orderguard_guard import llm
    monkeypatch.setenv("OG_REPLAY_STRICT", "1")

    def boom(self, *a, **k):
        raise AssertionError("an offline run called LLM.chat")

    monkeypatch.setattr(llm.LLM, "chat", boom)
    names = sweep.technique_names()
    for arm in sweep.ARMS:
        for policy in ("cautious", "credulous", "mixed"):
            for name in names:
                r = sweep.run_job(1, name, arm, policy=policy)
                assert not r["attack"]["error"] and not r["twin"]["error"], (name, arm, policy)
    for case in C.all_cases():
        from orderguard_lab.sandbox.policy import PolicyLLM
        rec = runner.run_case(case, PolicyLLM("mixed"), "full", mode="offline")
        assert not rec["error"], case.id


def test_tables_check_refuses_damaged_or_replaymiss_results(res):
    (res / "runs").mkdir()
    good = {"case": "C0-web", "family": "control", "arm": "naive", "model": "m", "rep": 0, "mode": "live", "error": None, "utility": True, "success": False, "attempted": False, "executed": False, "belief": False, "stopped_by": None}
    (res / "runs" / "a.jsonl").write_text(json.dumps(good) + "\n")
    assert tables.integrity_problems() == []
    (res / "runs" / "a.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(good)[:40])           # a run killed mid-write
    assert tables.integrity_problems() == ["unparsable line runs/a.jsonl:2"]
    tables.write()
    assert not tables.check()
    miss = dict(good, error="ReplayMiss: OG_LLM=replay and no recorded response")
    (res / "runs" / "a.jsonl").write_text(json.dumps(miss) + "\n")
    assert tables.integrity_problems() == ["ReplayMiss error recorded at runs/a.jsonl:1"]


def test_committed_results_are_intact():
    assert tables.integrity_problems() == []


def test_every_family_surface_has_a_matched_benign_control():
    controls = C.select("control")
    ctl_surfaces = {c.surface for c in controls if "trigger" not in c.tags and c.goal != "trigger_fire"}
    trigger_ctl = any(c.goal == "trigger_fire" for c in controls)
    for fam in ("A", "B", "C", "D", "E", "F"):
        for c in C.select(fam):
            if c.goal == "trigger_fire":
                assert trigger_ctl, (fam, c.id)
            else:
                assert c.surface in ctl_surfaces, (fam, c.id, c.surface)
    # and in the sandbox every technique compiles to an attack world plus a twin (the matched control), checked below
    assert {t for t in compiler.TECHNIQUES} >= {"directive", "fake_split", "false_figure", "venue_lie", "dos_notice", "natural_error", "clean"}


def test_sandbox_registry_has_23_attack_and_error_techniques_plus_controls():
    t = compiler.TECHNIQUES
    controls = [n for n, x in t.items() if x.control]
    assert sorted(controls) == ["clean", "real_crash"]
    assert len(t) - len(controls) == 23 and "natural_error" in t           # 22 attack techniques + natural_error


def test_twin_parity_holds_for_every_technique_over_many_seeds_and_grid_corners():
    for name, tech in compiler.TECHNIQUES.items():
        for seed in range(40):
            par = compiler.compile_case(seed, name).parity()
            assert par["ok"], (name, seed, par)
        # every pinned value of every parameter (one at a time) keeps parity too
        for key, values in tech.params.items():
            for v in values:
                sc = compiler.compile_case(7, name, fixed={key: str(v)})
                assert sc.parity()["ok"], (name, key, v)


def test_different_seeds_give_different_worlds_per_technique_family():
    digests = defaultdict(set)
    for seed in range(12):
        digests["w"].add(compiler.compile_case(seed, "clean").world.digest())
    assert len(digests["w"]) >= 6
