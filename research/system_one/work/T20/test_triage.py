"""Offline tests for og_s1.triage: recorded response, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1 import triage  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "recorded_response.json"


def _fixture(name: str | None = None) -> dict:
    path = FIXTURE if name is None else FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def _run_recorded(fixture: dict, tmp_path, monkeypatch) -> dict:
    key, row = _cache_row(fixture)
    cache = tmp_path / "cache.jsonl"
    cache.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(triage, "_post", _offline_post)
    out = triage.triage(
        [{"id": "x", "state": fixture["state"], "questions": fixture["questions"]}],
        model=fixture["model"],
        cache_path=cache,
        allow_network=False,
    )
    return out[0], key


def _cache_row(fixture: dict) -> tuple[str, dict]:
    spec = triage.resolve_questions(fixture["questions"])
    body = triage.request_body(fixture["model"], fixture["state"], spec)
    key = triage.request_key(body)
    return key, {
        "key": key,
        "model": fixture["model"],
        "status": 200,
        "latency_s": fixture["latency_s"],
        "response": fixture["response"],
    }


def _offline_post(*_args, **_kwargs):
    raise AssertionError("the test attempted a network request")


def test_recorded_response_parses_offline(tmp_path, monkeypatch):
    fixture = _fixture()
    key, row = _cache_row(fixture)
    cache = tmp_path / "cache.jsonl"
    cache.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(triage, "_post", _offline_post)

    out = triage.triage(
        [{"id": "review:001", "state": fixture["state"], "questions": fixture["questions"]}],
        model=fixture["model"],
        cache_path=cache,
        allow_network=False,
    )
    assert out[0]["id"] == "review:001"
    assert out[0]["answers"]["finding_kind"]["label"] == "leakage"
    assert out[0]["answers"]["finding_kind"]["type"] == "choice"
    assert out[0]["usage"]["cost"] >= 0.0
    assert len(key) == 64


def test_missing_cache_raises_without_network(tmp_path, monkeypatch):
    fixture = _fixture()
    monkeypatch.setattr(triage, "_post", _offline_post)
    with pytest.raises(RuntimeError, match="not cached"):
        triage.triage(
            [{"id": "x", "state": fixture["state"], "questions": fixture["questions"]}],
            model=fixture["model"],
            cache_path=tmp_path / "empty.jsonl",
            allow_network=False,
        )


def test_refusal_is_not_a_negative_answer(tmp_path, monkeypatch):
    fixture = _fixture()
    key, row = _cache_row(fixture)
    row["response"] = {"answers": {"finding_kind": {"type": "refusal"}}}
    cache = tmp_path / "cache.jsonl"
    cache.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setattr(triage, "_post", _offline_post)

    out = triage.triage(
        [{"id": "x", "state": fixture["state"], "questions": fixture["questions"]}],
        model=fixture["model"],
        cache_path=cache,
        allow_network=False,
    )
    answer = out[0]["answers"]["finding_kind"]
    assert answer["type"] == "refusal"
    assert answer["label"] is None


def test_every_item_kind_has_questions():
    expected = {
        "ref_action": {"label_ok", "finverify", "difficulty"},
        "label_noise_probe": {"label_ok"},
        "review_finding": {"finding_kind"},
        "failed_case": {"failure_kind"},
    }
    for kind, names in expected.items():
        assert set(triage.questions_for(kind)) == names


def test_noul_recorded_above_threshold(tmp_path, monkeypatch):
    fixture = _fixture("recorded_noul.json")
    out, _ = _run_recorded(fixture, tmp_path, monkeypatch)
    answer = out["answers"]["label_ok"]
    assert answer["type"] == "noul"
    assert answer["value"] == 0.68
    assert answer["label"] is True


def test_noul_recorded_below_threshold(tmp_path, monkeypatch):
    fixture = _fixture("recorded_noul_below.json")
    out, _ = _run_recorded(fixture, tmp_path, monkeypatch)
    answer = out["answers"]["label_ok"]
    assert answer["type"] == "noul"
    assert answer["value"] == 0.12
    assert answer["label"] is False


def test_score_recorded_rounds_to_category(tmp_path, monkeypatch):
    high = _fixture("recorded_score.json")
    out, _ = _run_recorded(high, tmp_path, monkeypatch)
    answer = out["answers"]["difficulty"]
    assert answer["type"] == "score"
    assert answer["value"] == 1.63
    assert answer["label"] == 2


def test_score_recorded_low_rounds_to_one(tmp_path, monkeypatch):
    low = _fixture("recorded_score_low.json")
    out, _ = _run_recorded(low, tmp_path, monkeypatch)
    answer = out["answers"]["difficulty"]
    assert answer["value"] == 1.29
    assert answer["label"] == 1


def test_spend_cap_stops_before_a_request(tmp_path):
    fixture = _fixture()
    calls = []

    def poster(body):
        calls.append(body)
        return {"answers": {}, "usage": {"cost": 0.0}}, 0.0

    with pytest.raises(RuntimeError, match="spend cap"):
        triage.triage(
            [{"id": "x", "state": fixture["state"], "questions": fixture["questions"]}],
            model=fixture["model"],
            cache_path=tmp_path / "empty.jsonl",
            allow_network=True,
            post=poster,
            max_spend=0.0,
        )
    assert calls == []
