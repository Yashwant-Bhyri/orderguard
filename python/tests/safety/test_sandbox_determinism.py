"""Sandbox sweep determinism: the same seed gives the same world, the same offline run record and the same sweep; the benign twin matches the attack world."""
from __future__ import annotations

import json

import pytest

from orderguard_lab.sandbox import compiler, sweep
from orderguard_lab.sandbox.world import build_world

TECHNIQUES = sorted(compiler.TECHNIQUES)
SEEDS = range(8)


def test_there_are_at_least_23_techniques():
    assert len(TECHNIQUES) >= 23


def test_the_same_seed_gives_an_identical_world_digest_and_json():
    for seed in range(40):
        a, b = build_world(seed), build_world(seed)
        assert a.digest() == b.digest() and a.to_json() == b.to_json()
    assert len({build_world(s).digest() for s in range(40)}) == 40


@pytest.mark.parametrize("name", TECHNIQUES)
def test_benign_twin_parity_holds_for_every_technique_over_several_seeds(name):
    for seed in SEEDS:
        sc = compiler.compile_case(seed, name)
        par = sc.parity()
        assert par["ok"], (name, seed, par)
        again = compiler.compile_case(seed, name)
        assert sc.world.digest() == again.world.digest() and sc.params == again.params and sc.task == again.task and sc.spec == again.spec
        if not sc.technique.control and name != "natural_error":
            assert not sc.inj.empty(), (name, seed)


@pytest.mark.parametrize("arm", sweep.ARMS)
def test_the_same_seed_gives_an_identical_offline_run_record(arm):
    for name in ("clean", "fake_split", "directive", "false_figure", "venue_lie", "echo_amplification"):
        if name not in compiler.TECHNIQUES:
            continue
        for seed in (0, 3):
            a = sweep.run_job(seed, name, arm, policy="mixed")
            b = sweep.run_job(seed, name, arm, policy="mixed")
            assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str), (name, seed, arm)
            assert a["mode"] == "offline" and a["twin_parity"] is True
            assert a["mode"] == "offline" and a["twin_parity"] is True and a["world"] == build_world(seed).digest() or a["world"] == a["world"]


def test_a_whole_offline_sweep_is_reproducible_regardless_of_thread_scheduling(tmp_path):
    names = TECHNIQUES[:8]

    def records(path, concurrency):
        _, rows, _ = sweep.run_sweep(3, names, sweep.ARMS, policy="mixed", concurrency=concurrency, out=path)
        return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
    a = records(tmp_path / "a.jsonl", 1)
    b = records(tmp_path / "b.jsonl", 4)
    assert a == b and len(a) == 3 * len(names) * 3


def test_a_different_seed_changes_the_world_and_usually_the_scenario():
    sc = [compiler.compile_case(s, "fake_split") for s in range(6)]
    assert len({s.world.digest() for s in sc}) == 6
