import json

import pytest

pytest.importorskip("sklearn")

from orderguard_lab import detect, train_classifier as T


@pytest.fixture(scope="module")
def chunks():
    return T.build_chunks(seeds=2)


def test_dataset_has_labels_groups_and_exact_line_labels(chunks):
    assert {c["label"] for c in chunks} == {0, 1} and {c["source"] for c in chunks} == {"lab", "sandbox"}
    assert all(len(c["lines"]) == len(c["y"]) for c in chunks)
    assert all(sum(c["y"]) == 0 for c in chunks if c["label"] == 0)
    assert any(sum(c["y"]) for c in chunks if c["label"] == 1)
    keys = [(c["label"], c["group"], c["text"]) for c in chunks]
    assert len(keys) == len(set(keys))                  # deduplicated


def test_hash_is_stable_and_folds_keep_groups_whole(chunks):
    assert T.data_hash(chunks) == T.data_hash(list(reversed(chunks)))
    fold = T.assign_folds(chunks, 5)
    assert set(fold.values()) == set(range(5)) and len({c["group"] for c in chunks}) == len(fold)


def test_threshold_respects_target():
    s = [i / 1000 for i in range(1000)]
    t = T.pick_threshold(s, 0.02)
    assert sum(x >= t for x in s) <= 20 and t >= 0.5


def test_training_is_deterministic(chunks, tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for p in (a, b):
        T.export(T.fit(chunks), 0.9, 0.95, {}, "h", p)
    assert a.read_bytes() == b.read_bytes()
    art = json.loads(a.read_text())
    assert art["format"] == "orderguard-injection-clf/1" and art["blocks"]["char"]["terms"]


def test_detect_local_clf_row_is_out_of_fold(res):
    out, rows = detect.run_detect([detect.LOCAL_CLF], out=res / "detect" / "c.jsonl")
    assert {r["screen"] for r in rows} == {detect.LOCAL_CLF_NAME}
    assert any(r["label"] == "attack" for r in rows) and any(r["label"] == "clean" for r in rows)
    assert all("out-of-fold" in r["why"] for r in rows)
