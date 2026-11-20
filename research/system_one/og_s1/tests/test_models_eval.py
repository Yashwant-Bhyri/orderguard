from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import logit
from sklearn.metrics import brier_score_loss, roc_auc_score

from og_s1.evaluate import (
    PREVIOUS_SPLIT_SEED,
    SPLIT_SEED,
    auroc,
    brier,
    bootstrap_episode_values,
    bootstrap_metrics,
    bootstrap_metrics_fast,
    bootstrap_multiplicities,
    ece_adaptive,
    ece_equal_width,
    episode_bootstrap_indices,
    percentile_ci,
    split_records,
    threshold_for_hold_rate,
)
from og_s1.models import (
    BoostedTreesModel,
    EBMModel,
    LogisticModel,
    NoisyAndModel,
    check_ebm_certificate,
    check_ebm_monotonicity,
    monotonise_ebm,
)


def test_auroc_toy_and_sklearn():
    y = np.array([0, 0, 1, 1])
    scores = np.array([0.1, 0.4, 0.35, 0.8])
    assert auroc(y, scores) == pytest.approx(0.75)
    rng = np.random.default_rng(7)
    yy = rng.integers(0, 2, size=200)
    ss = rng.random(200)
    assert auroc(yy, ss) == pytest.approx(roc_auc_score(yy, ss))
    assert np.isnan(auroc(np.zeros(5), np.arange(5.0)))


def test_brier_toy_and_sklearn():
    y = np.array([0, 1, 1, 0], dtype=float)
    p = np.array([0.1, 0.9, 0.8, 0.2])
    assert brier(y, p) == pytest.approx(0.025)
    rng = np.random.default_rng(9)
    yy = rng.integers(0, 2, size=300).astype(float)
    pp = rng.random(300)
    assert brier(yy, pp) == pytest.approx(brier_score_loss(yy, pp))


def test_ece_equal_width_hand_computed():
    y = np.array([0, 1, 1, 0], dtype=float)
    p = np.array([0.1, 0.9, 0.8, 0.2])
    assert ece_equal_width(y, p, n_bins=2) == pytest.approx(0.15)


def test_ece_adaptive_hand_computed():
    y = np.array([0, 0, 0, 1], dtype=float)
    p = np.array([0.1, 0.2, 0.3, 0.9])
    assert ece_equal_width(y, p, n_bins=2) == pytest.approx(0.175)
    assert ece_adaptive(y, p, n_bins=2) == pytest.approx(0.125)


def test_threshold_for_hold_rate():
    scores = np.arange(100, dtype=float)
    tau = threshold_for_hold_rate(scores, target=0.02)
    assert tau == 97.0
    assert int(np.sum(scores > tau)) == 2


def test_episode_bootstrap_resamples_whole_episodes():
    ids = np.array(["a"] * 5 + ["b"] * 3, dtype=object)
    blocks = {"a": set(range(5)), "b": set(range(5, 8))}
    for idx in episode_bootstrap_indices(ids, n_boot=50, seed=3):
        selected = set(int(i) for i in idx.tolist())
        for block in blocks.values():
            assert selected.isdisjoint(block) or block.issubset(selected)
        assert len(idx) in (6, 8, 10)


def test_bootstrap_metrics_delegates_to_episode_grouping(monkeypatch):
    import og_s1.evaluate as evaluate

    seen = {}

    def fake_episode_indices(episode_ids, n_boot=1, seed=0):
        seen["ids"] = [str(value) for value in episode_ids]
        seen["n_boot"] = n_boot
        seen["seed"] = seed
        yield np.array([0, 1, 2, 3])

    monkeypatch.setattr(evaluate, "episode_bootstrap_indices", fake_episode_indices)
    y = np.array([0.0, 0.0, 1.0, 1.0])
    probs = np.array([0.1, 0.2, 0.9, 0.8])
    clean = np.array([True, True, False, False])
    out = bootstrap_metrics(
        y,
        probs,
        np.array(["a", "a", "b", "b"], dtype=object),
        clean,
        tau=0.5,
        n_boot=1,
        seed=0,
    )
    assert seen == {"ids": ["a", "a", "b", "b"], "n_boot": 1, "seed": 0}
    assert out["auroc"] == (1.0, 1.0)
    assert out["brier"] == (pytest.approx(0.025), pytest.approx(0.025))
    assert out["ece_15"] == (pytest.approx(0.15), pytest.approx(0.15))
    assert out["ece_adaptive"] == (pytest.approx(0.15), pytest.approx(0.15))
    assert out["hold_rate_clean"] == (0.0, 0.0)
    assert out["recall"] == (1.0, 1.0)


def test_bootstrap_episode_values_percentile():
    (lo_mean, hi_mean), (lo_med, hi_med) = bootstrap_episode_values(
        np.array([0.0, 10.0]), n_boot=2000, seed=0
    )
    assert lo_mean == pytest.approx(0.0)
    assert hi_mean == pytest.approx(10.0)
    assert lo_med == pytest.approx(0.0)
    assert hi_med == pytest.approx(10.0)
    empty = percentile_ci([np.nan, np.nan])
    assert np.isnan(empty[0]) and np.isnan(empty[1])


def _toy_data(n=400, d=4, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, d))
    y = (X[:, 0] + 0.7 * X[:, 1] + rng.normal(scale=0.3, size=n) > 0).astype(float)
    return X, y


def test_logistic_interface_and_explain_is_exact():
    X, y = _toy_data()
    model = LogisticModel(C=1.0, random_state=0).fit(
        X, y, calibration=(X, y), feature_names=[f"f{i}" for i in range(X.shape[1])]
    )
    p = model.predict_proba(X)
    assert p.shape == (len(y),)
    assert np.all((p >= 0.0) & (p <= 1.0))
    contributions = model.explain(X)
    assert contributions.shape == X.shape
    reconstructed = contributions.sum(axis=1) + model.base_
    raw = model.platt_a_ * model._decision(X) + model.platt_b_
    assert np.allclose(reconstructed, raw, atol=1e-6)


def test_score_with_and_without_text_feature():
    X, y = _toy_data()
    model = LogisticModel(C=1.0, random_state=0).fit(X, y, calibration=(X, y))
    with_text, without_text = model.score_with_and_without(X, [0, 1], baseline=0.0)
    assert with_text.shape == without_text.shape == (len(y),)
    assert not np.allclose(with_text, without_text)


def test_noisy_and_interface_and_factor_contributions():
    X, y = _toy_data(d=6)
    groups = {
        "f0": "drift",
        "f1": "drift",
        "f2": "unsupported_claim",
        "f3": "misquote",
        "f4": "poisoned_note",
        "f5": "evidence_quality",
    }
    model = NoisyAndModel(l2=1e-2, random_state=0).fit(
        X, y, groups, calibration=(X, y), feature_names=[f"f{i}" for i in range(6)]
    )
    p = model.predict_proba(X)
    assert p.shape == (len(y),)
    contributions = model.explain(X)
    assert contributions.shape == X.shape
    assert np.all(contributions >= -1e-12)
    factor = model.factor_contributions(X)
    assert factor.shape == (len(y), len(model.factors_))
    base = model.platt_a_ * model._base_raw(X) + model.platt_b_
    raw_final = model.platt_a_ * model._raw_risk_logit(X) + model.platt_b_
    assert np.allclose(contributions.sum(axis=1) + base, raw_final, atol=1e-6)


def test_ebm_monotonicity_enumeration_and_repair():
    X, y = _toy_data(n=500, d=3, seed=1)
    model = EBMModel(
        interactions=0,
        max_bins=16,
        outer_bags=1,
        learning_rate=0.05,
        max_rounds=100,
        early_stopping_rounds=20,
        random_state=0,
    ).fit(X, y, calibration=(X, y), feature_names=["a", "b", "c"])
    ok, details = model.monotonicity_report()
    assert ok, details
    assert len(details) == 3
    assert all(entry["monotone"] for entry in details)

    term = next(i for i, features in enumerate(model.clf_.term_features_) if len(features) == 1)
    scores = np.asarray(model.clf_.term_scores_[term], dtype=float).copy()
    if len(scores) > 3:
        scores[2] = scores[1] - 100.0
        model.clf_.term_scores_[term] = scores
        corrupt_ok, _ = check_ebm_monotonicity(model.clf_)
        assert not corrupt_ok
        monotonise_ebm(model.clf_)
        repaired_ok, _ = check_ebm_monotonicity(model.clf_)
        assert repaired_ok


def test_ebm_explain_sums_to_logit():
    X, y = _toy_data(n=300, d=3, seed=2)
    model = EBMModel(
        interactions=0,
        max_bins=16,
        outer_bags=1,
        learning_rate=0.05,
        max_rounds=80,
        early_stopping_rounds=20,
        random_state=0,
    ).fit(X, y, calibration=(X, y), feature_names=["a", "b", "c"])
    p = model.predict_proba(X)
    contributions = model.explain(X)
    assert contributions.shape == X.shape
    reconstructed = contributions.sum(axis=1) + model.base_
    raw = model.platt_a_ * (
        np.asarray(model.clf_.eval_terms(X)).sum(axis=1) + float(model.clf_.intercept_[0])
    ) + model.platt_b_
    assert np.allclose(reconstructed, raw, atol=1e-6)


def test_boosted_trees_explain_sums_to_logit():
    X, y = _toy_data(n=300, d=3, seed=3)
    model = BoostedTreesModel(monotone=True, max_iter=30, random_state=0).fit(
        X, y, calibration=(X, y), feature_names=["a", "b", "c"]
    )
    p = model.predict_proba(X)
    contributions = model.explain(X)
    assert contributions.shape == X.shape
    base = model.platt_a_ * float(np.asarray(model._explainer.expected_value).ravel()[0]) + model.platt_b_
    reconstructed = contributions.sum(axis=1) + base
    raw = model.platt_a_ * model.clf_.decision_function(X) + model.platt_b_
    assert np.allclose(reconstructed, raw, atol=1e-6)


def test_fast_bootstrap_matches_naive_on_continuous_scores():
    rng = np.random.default_rng(11)
    episode = np.repeat(np.arange(9), [4, 6, 5, 7, 3, 8, 4, 5, 6])
    ids = np.array([f"e{k}" for k in episode], dtype=object)
    y = rng.integers(0, 2, episode.size).astype(float)
    probs = rng.random(episode.size)
    clean = np.isin(episode, [0, 2, 4, 6])
    naive = bootstrap_metrics(y, probs, ids, clean, tau=0.5, n_boot=200, seed=5)
    fast = bootstrap_metrics_fast(y, probs, ids, clean, tau=0.5, n_boot=200, seed=5)
    for name in naive:
        if name == "ece_adaptive":
            assert abs(naive[name][0] - fast[name][0]) < 1e-9
            assert abs(naive[name][1] - fast[name][1]) < 1e-9
        else:
            assert naive[name] == pytest.approx(fast[name], abs=1e-12)


def test_fast_bootstrap_handles_ties_within_tolerance():
    rng = np.random.default_rng(12)
    episode = np.repeat(np.arange(7), [5, 4, 6, 3, 5, 4, 6])
    ids = np.array([f"e{k}" for k in episode], dtype=object)
    y = rng.integers(0, 2, episode.size).astype(float)
    probs = np.round(rng.random(episode.size), 2)
    clean = np.isin(episode, [0, 3, 5])
    naive = bootstrap_metrics(y, probs, ids, clean, tau=0.5, n_boot=300, seed=6)
    fast = bootstrap_metrics_fast(y, probs, ids, clean, tau=0.5, n_boot=300, seed=6)
    for name in ("auroc", "brier", "ece_15", "hold_rate_clean", "recall"):
        assert naive[name] == pytest.approx(fast[name], abs=1e-12)
    assert naive["ece_adaptive"][0] == pytest.approx(fast["ece_adaptive"][0], abs=0.02)
    assert naive["ece_adaptive"][1] == pytest.approx(fast["ece_adaptive"][1], abs=0.02)


def test_bootstrap_multiplicities_match_episode_draws():
    ids = np.array(["a"] * 3 + ["b"] * 2 + ["c"] * 4, dtype=object)
    mult = bootstrap_multiplicities(3, n_boot=40, seed=4)
    assert mult.shape == (40, 3)
    assert np.all(mult.sum(axis=1) == 3)


def test_split_avoids_previously_inspected_test_episodes():
    from types import SimpleNamespace

    items = [
        SimpleNamespace(key=f"f{i}", family=f"fam{i % 2}")
        for i in range(40)
    ]
    previous = split_records(items, seed=PREVIOUS_SPLIT_SEED)["test"]
    avoid = {item.key for item in previous}
    fresh = split_records(items, seed=SPLIT_SEED, avoid_test_keys=avoid)
    assert not ({item.key for item in fresh["test"]} & avoid)
    assert len(fresh["test"]) == len(previous)
    assert len(fresh["train"]) + len(fresh["cal"]) + len(fresh["test"]) == len(items)


def test_ebm_certificate_checks_additivity_and_all_bins():
    X, y = _toy_data(n=400, d=3, seed=4)
    model = EBMModel(
        interactions=2,
        max_bins=16,
        outer_bags=1,
        learning_rate=0.05,
        max_rounds=100,
        early_stopping_rounds=20,
        random_state=0,
    ).fit(X, y, calibration=(X, y), feature_names=["a", "b", "c"])
    ok, details = model.monotonicity_report()
    assert ok, (details, model.certificate_)
    cert = model.certificate_
    assert cert["univariate"] is True
    assert cert["bins_aligned"] is True
    assert cert["additivity_max_error"] is not None
    assert cert["additivity_max_error"] <= 1e-8
    assert cert["features_checked"] == 3
    assert all(len(features) == 1 for features in model.clf_.term_features_)


def test_ebm_is_deterministic_with_one_thread():
    X, y = _toy_data(n=300, d=3, seed=5)
    kw = dict(
        interactions=0,
        max_bins=16,
        outer_bags=2,
        learning_rate=0.05,
        max_rounds=60,
        early_stopping_rounds=15,
        random_state=0,
        n_jobs=1,
    )
    first = EBMModel(**kw).fit(X, y, calibration=(X, y), feature_names=["a", "b", "c"])
    second = EBMModel(**kw).fit(X, y, calibration=(X, y), feature_names=["a", "b", "c"])
    assert np.array_equal(first.predict_proba(X), second.predict_proba(X))
    assert np.array_equal(first.explain(X), second.explain(X))
