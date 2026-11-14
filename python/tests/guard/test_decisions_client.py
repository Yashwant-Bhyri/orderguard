"""Typed decision client: replay is exact, a missing recording raises, malformed answers are refused. Offline."""
import json

import pytest

from orderguard_guard import decisions as D
from orderguard_guard.llm import LLMError, ReplayMiss, request_hash

Q = {"hold": {"type": "noul", "instructions": "Hold this order?"}}


def _record(tmp_path, state, answers):
    body = {"model": "typesafe/jev-1.14", "state": state, "questions": Q}
    (tmp_path / f"{request_hash(body)}.json").write_text(json.dumps({"request": body, "response": {"answers": answers}}))


def test_replay_returns_recorded_answer(tmp_path):
    _record(tmp_path, {"o": 1}, {"hold": {"type": "noul", "noul": 0.82}})
    assert D.Decisions(mode="replay", replay_dir=tmp_path).ask({"o": 1}, Q)["hold"]["noul"] == 0.82


def test_missing_recording_raises_in_replay(tmp_path):
    with pytest.raises(ReplayMiss):
        D.Decisions(mode="replay", replay_dir=tmp_path).ask({"o": 2}, Q)


@pytest.mark.parametrize("bad", [{"hold": {"noul": 1.5}}, {"hold": {}}, {"other": {"noul": 0.1}}, {}])
def test_malformed_answers_are_refused(tmp_path, bad):
    _record(tmp_path, {"o": 3}, bad)
    with pytest.raises(LLMError):
        D.Decisions(mode="replay", replay_dir=tmp_path).ask({"o": 3}, Q)


@pytest.mark.parametrize("q", [{}, {"x": {"type": "free", "instructions": "?"}}, {"x": {"type": "choice", "instructions": "?"}},
                               {"x": {"type": "score", "instructions": "?", "criteria": ["only one"]}}])
def test_invalid_questions_rejected_before_any_call(q):
    with pytest.raises(ValueError):
        D.validate_questions(q)
