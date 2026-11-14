"""The campaign is deterministic, runs offline from the recordings under strict replay, records attacker failures, and the report matches the data."""
import json

import pytest

from orderguard_guard.llm import ScriptedLLM
from orderguard_lab.llm_shared import ReplayIncomplete
from orderguard_lab.redteam import attacker, campaign as C, report


def _run(tmp_path, name, cfg=None):
    out = tmp_path / name
    C.run(cfg or C.Config(), out=out)
    return out.read_text()


def test_campaign_replays_offline_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    first = _run(tmp_path, "a.json")
    assert first == _run(tmp_path, "b.json")                                   # deterministic
    assert first == C.CAMPAIGN.read_text()                                      # and equal to the committed result
    camp = json.loads(first)
    assert camp["complete"] and camp["summary"]["units"] == 14


def test_report_matches_campaign_json():
    camp = json.loads(C.CAMPAIGN.read_text())
    assert report.check(camp), "docs/REDTEAM.md is stale: run `og-lab redteam report`"


def test_strict_replay_stops_loudly_on_a_missing_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    cfg = C.Config(seeds={"feed_inject": (97,)}, attackers=("deepseek/deepseek-v4.1-flash-1017",))
    with pytest.raises(ReplayIncomplete):
        C.run(cfg, only=["feed_inject"], out=tmp_path / "x.json")


def test_attacker_refusal_is_a_recorded_failed_round_after_one_retry():
    llm = ScriptedLLM(["I'm sorry, I can't help with that.", "I cannot do that."], model="fake/atk")
    cfg = C.Config(rounds=1, guard_model=ScriptedLLM([], model="fake/guard"))
    u = C.run_unit(llm, "order", 0, cfg)
    assert u["rounds"] == [{"round": 1, "attacker_failed": True, "failure": "refused"}]
    assert len(llm.requests) == 2 and u["attacker_failures"] == 1


def test_attacker_plan_is_validated_and_learns_from_the_outcome():
    plan = json.dumps({"idea": "oversize", "orders": [{"step": 3, "ticker": "AAPL", "side": "buy", "usd": 90000}]})
    llm = ScriptedLLM([plan, plan], model="fake/atk")
    u = C.run_unit(llm, "order", 0, C.Config(rounds=2, guard_model=None))
    assert [r["round"] for r in u["rounds"]] == [1, 2] and all(not r["hard"] for r in u["rounds"])
    assert "REFUSED" in llm.requests[1]["messages"][-2]["content"]               # round 2 saw round 1's public reason
    assert "layer" not in llm.requests[1]["messages"][-2]["content"].lower()      # and nothing internal


def test_parse_obj_handles_chatter_and_braces_in_strings():
    assert attacker.parse_obj('sure {"a": "x } y", "b": {"c": 1}} done') == {"a": "x } y", "b": {"c": 1}}
    assert attacker.parse_obj("no json") is None
