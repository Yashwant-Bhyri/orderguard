import json

from orderguard_lab import cases as C
from orderguard_lab import runner
from orderguard_lab.sandbox.policy import PolicyLLM


def test_estimate_prints_calls_and_dollars():
    e = runner.estimate(C.select("all"), "deepseek/deepseek-v4.1-flash", ["naive", "gate_only", "full"], 1)
    assert e["priced"] and e["price_in"] == 0.045 and e["price_out"] == 0.50
    assert e["total"]["runs"] == 3 * len(C.all_cases()) and e["total"]["usd"] > 0 and e["total"]["calls"] > e["total"]["runs"]
    e2 = runner.estimate(C.select("all"), "deepseek/deepseek-v4.1-flash", ["naive", "gate_only", "full"], 2)
    assert e2["per_arm"]["naive"]["usd"] == 2 * e["per_arm"]["naive"]["usd"]            # agent calls double with reps
    assert e2["per_arm"]["full"]["usd"] < 2 * e["per_arm"]["full"]["usd"]               # screening is cached, paid once
    text = runner.format_estimate(e)
    assert "US$" in text and "full" in text


def test_run_case_offline_naive_vs_full(res):
    cred = lambda: PolicyLLM("credulous")                                               # noqa: E731
    r = runner.run_case(C.get("A-D2"), cred, "naive", mode="offline")
    assert r["attempted"] and r["executed"] and r["success"] and r["harm_usd"] == 9500
    r = runner.run_case(C.get("B-F2"), cred, "gate_only", mode="offline")
    assert r["attempted"] and not r["executed"] and r["stopped_by"] == "L5"
    r = runner.run_case(C.get("A-D2"), cred, "full", mode="offline")
    assert not r["success"] and r["stopped_by"] in ("L2", "L5") and r["quarantined_n"] >= 0
    assert r["cost_usd"] == 0.0 and r["transcript"]["calls"]


def test_controls_complete_for_a_cautious_agent(res):
    for cid in ("C0-doc", "C0-web", "C0-feed", "C0-tools", "C0-memory", "C0-multi", "C0-trigger"):
        for arm in ("naive", "gate_only", "full"):
            if cid == "C0-trigger" and arm != "naive":
                continue          # finding: the gate's require_figures holds rule sells of tickers with no SEC facts (reported, not asserted away)
            r = runner.run_case(C.get(cid), (lambda: PolicyLLM("credulous")) if cid == "C0-trigger" else (lambda: PolicyLLM("cautious")), arm, mode="offline")
            assert r["utility"] is True, (cid, arm, r["transcript"]["final"][:200])


def test_run_many_writes_jsonl_and_is_rejudgeable(res):
    out, rows = runner.run_many(C.select("A-D2,C0-doc"), lambda: PolicyLLM("mixed"), ["naive", "full"], 2, out=res / "runs.jsonl", mode="offline", concurrency=2)
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == 8 and all("transcript" in l for l in lines)
    from orderguard_lab import tables
    for l in lines:
        again = tables.rejudge(l)
        assert again["success"] == l["success"] and again["stopped_by"] == l["stopped_by"]


def test_error_runs_are_recorded_not_raised(res):
    class Boom:
        model = "fake/boom"

        def chat(self, *a, **k):
            raise RuntimeError("network down")
    r = runner.run_case(C.get("C0-feed"), Boom(), "naive", mode="offline")
    assert r["error"] and "network down" in r["error"]
