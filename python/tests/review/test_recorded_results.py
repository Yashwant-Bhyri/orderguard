"""The committed results reproduce from the recordings, offline: replaying data/replay/decisions through the same code gives the same numbers,
so no figure in docs/REVIEW.md depends on a live call."""
import json
from pathlib import Path

import pytest

from orderguard_guard.decisions import Decisions
from orderguard_review import advice as A
from orderguard_review import evaluate, study

ROOT = Path(__file__).resolve().parents[3]
RES = ROOT / "results" / "review"


def _strip(d):
    d = json.loads(json.dumps(d))
    d.get("jev_calls", {}).pop("live_latency_ms", None)
    return d


@pytest.mark.slow
def test_triage_study_reproduces_from_recordings():
    got = study.run_study(decisions=Decisions(A.model_name(), mode="replay"))
    want = json.loads((RES / "triage.json").read_text())
    assert got["jev_calls"]["no_advice"] == 0 and got["jev_calls"]["calls"] == 1266
    assert _strip(got) == _strip(want)


def test_triage_study_without_recordings_degrades_to_the_model_alone(tmp_path):
    """No recording, no key: every call is 'no advice', so the model-only and the merged orderings are the same ordering."""
    res = study.run_study(decisions=Decisions(A.model_name(), mode="replay", replay_dir=tmp_path), limit=4000)
    assert res["jev_calls"]["no_advice"] == res["jev_calls"]["calls"] > 0
    for q in res["queues"].values():
        for k, v in q["caught_by_k"]["model"].items():
            assert q["caught_by_k"]["jev+model"][k] == v


def test_copilot_and_scope_results_reproduce_from_recordings():
    got = evaluate.evaluate_drafts(Decisions(A.model_name(), mode="replay"))
    want = json.loads((RES / "copilot.json").read_text())
    assert got == want and got["no_advice"] == 0 and got["all_contained"] is True
    got = evaluate.evaluate_scope(Decisions(A.model_name(), mode="replay"))
    assert got == json.loads((RES / "scope.json").read_text()) and got["no_advice"] == 0


def test_the_labels_never_reach_the_model():
    meta, events = study.load_stream(study.STREAM)
    cases, _ = study.build_cases(events[:3000], meta)
    from orderguard_review.triage import build_state
    blob = json.dumps([build_state(c["held"], c["context"]) for c in cases]).lower()
    for word in ("collusion", "fake_news", "runaway_dup", "fat_finger", "compromised_", "\"label\"", "legit"):
        assert word not in blob
