"""End-to-end T15 bench: two trivial readers through the frozen pipeline.

Reads ``data/ref/`` only.  Pass 1 collects labels, group ids and evaluation
metadata; pass 2 builds the causal Cases, fits the code baseline on the train
split, and scores both readers on the calibration and test splits.  No label or
``meta`` value reaches a Case or a reader.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from og_s1.eval import (
    RENDERINGS,
    SHIFT_AXES,
    TRUTH_TYPES,
    CodeLogisticReader,
    axes_for_meta,
    cases,
    labels,
    tag_shift_axes,
    coverage_at_false_allow,
    ece,
    escalation_rate,
    false_holds_per_1000,
    group_split,
    pointer_accuracy,
    render_lengths,
    risk_from_prob,
    spec_hash,
    split_summary,
    top_cause_accuracy,
    verify_spec,
    auroc,
)
from og_s1.eval.metrics import Metric, cost_summary
from og_s1.eval.splits import assert_episode_disjoint
from og_s1.readers.base import QUESTIONS, ConstantReader, validate_scores
from og_s1.schema import Episode
from og_s1.world import FAMILIES

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPLIT_AXES = ("owner", "episode", "company", "author", "agent")
SPLIT_NOTES = {
    "owner": "whole owner signing keys; episodes are kept together",
    "episode": "whole episodes; an unseen-episode estimate",
    "company": "company-held-out, episode-overlapping; NOT a generalization test",
    "author": "meta.author; unavailable when the corpus has one author",
    "agent": "meta.agent_id; unavailable when absent (never an owner proxy)",
}


def _path(data_dir: str, family: str, shifted: bool) -> Path:
    suffix = ".shifted" if shifted else ""
    return Path(data_dir) / f"{family}{suffix}.jsonl"


def _iter_episodes(data_dir: str, limit: int | None) -> Iterable[tuple[str, int, Episode]]:
    for shifted in (False, True):
        for family in FAMILIES:
            path = _path(data_dir, family, shifted)
            if not path.exists():
                raise FileNotFoundError(path)
            with path.open("r", encoding="utf-8") as handle:
                for episode_index, line in enumerate(handle):
                    if limit is not None and episode_index >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    yield str(path), episode_index, Episode.from_dict(json.loads(line))


def collect_metadata(data_dir: str, limit: int | None) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    rows: dict[str, list[Any]] = {
        "y": [],
        "cause": [],
        "cause_refs": [],
        "truth_type": [],
        "axes": [],
        "owner": [],
        "company": [],
        "author": [],
        "agent": [],
        "family": [],
        "shifted": [],
        "episode": [],
    }
    corpus = {
        "episodes": 0,
        "actions": 0,
        "positives": 0,
        "by_cell": {},
        "agent_id_present": False,
    }
    episode_sizes: list[int] = []
    for file_name, episode_index, ep in _iter_episodes(data_dir, limit):
        meta = ep.meta
        family = str(meta.get("family", "unknown"))
        shifted = bool(meta.get("shifted", False))
        axes = axes_for_meta(meta)
        owner = str(ep.owner.signing_key_id)
        author = str(meta.get("author", "unknown"))
        has_agent_id = "agent_id" in meta and meta.get("agent_id") is not None
        if has_agent_id:
            corpus["agent_id_present"] = True
        agent = str(meta.get("agent_id")) if has_agent_id else ""
        global_episode = corpus["episodes"]
        episode_sizes.append(len(ep.steps))
        key = f"{family}{'.shifted' if shifted else ''}"
        cell = corpus["by_cell"].setdefault(key, {"episodes": 0, "actions": 0, "positives": 0})
        cell["episodes"] += 1
        label_records = labels(ep)
        for step, record in zip(ep.steps, label_records):
            y = int(record.y)
            cause = str(record.cause)
            rows["y"].append(y)
            rows["cause"].append(cause)
            rows["cause_refs"].append(list(record.cause_refs))
            rows["truth_type"].append(str(record.truth_type))
            rows["axes"].append(axes)
            rows["owner"].append(owner)
            rows["company"].append(str(step.action.instrument))
            rows["author"].append(author)
            rows["agent"].append(agent)
            rows["family"].append(family)
            rows["shifted"].append(shifted)
            rows["episode"].append(global_episode)
            corpus["actions"] += 1
            corpus["positives"] += y
            cell["actions"] += 1
            cell["positives"] += y
        corpus["episodes"] += 1
    corpus["episode_sizes"] = episode_sizes
    return rows, corpus


def _split_for_axis(
    rows: dict[str, list[Any]],
    axis: str,
    seed: int,
    *,
    agent_id_present: bool = True,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    groups = [str(g) for g in rows[axis]]
    unique = len(set(groups))
    if axis == "agent" and not agent_id_present:
        return None, {
            "axis": axis,
            "groups": unique,
            "available": False,
            "reason": "no meta.agent_id in the corpus; an owner proxy is not an agent split",
            "note": SPLIT_NOTES[axis],
        }
    if unique < 3:
        return None, {
            "axis": axis,
            "groups": unique,
            "available": False,
            "reason": f"only {unique} group(s)",
            "note": SPLIT_NOTES.get(axis, ""),
        }
    split = group_split(groups, seed=seed)
    summary = split_summary(groups, split)
    summary["axis"] = axis
    summary["available"] = True
    summary["note"] = SPLIT_NOTES.get(axis, "")
    episodes = [str(e) for e in rows["episode"]]
    seen: dict[str, set[int]] = {}
    for episode, label in zip(episodes, split):
        seen.setdefault(episode, set()).add(int(label))
    leaking = sum(1 for labels in seen.values() if len(labels) > 1)
    summary["episodes"] = len(seen)
    summary["episodes_on_both_sides"] = int(leaking)
    summary["episode_disjoint"] = leaking == 0
    if axis in ("owner", "episode"):
        assert_episode_disjoint(episodes, split)
    return split, summary


def materialize(
    data_dir: str,
    limit: int | None,
    split: np.ndarray,
    y: Sequence[int],
    *,
    lengths: bool,
    render_limit: int,
) -> dict[str, Any]:
    train_X: list[Sequence[float]] = []
    train_y: list[int] = []
    cal_cases = []
    cal_idx: list[int] = []
    test_cases = []
    test_idx: list[int] = []
    feature_names: tuple[str, ...] = ()
    lengths_store: dict[str, dict[str, list[int]]] = {
        name: {"chars": [], "tokens": []} for name in RENDERINGS
    }
    flat = 0
    length_count = 0
    for file_name, episode_index, ep in _iter_episodes(data_dir, limit):
        cs = tag_shift_axes(cases(ep), ep.meta)
        if len(cs) != len(ep.steps):
            raise RuntimeError(f"case count mismatch at {file_name}:{episode_index}")
        if cs and not feature_names:
            feature_names = tuple(cs[0].code_feature_names)
        for case in cs:
            if flat >= split.size:
                raise RuntimeError("split is shorter than the materialised cases")
            if lengths and (render_limit == 0 or length_count < render_limit):
                measured = render_lengths(case)
                for name in RENDERINGS:
                    lengths_store[name]["chars"].append(measured[name]["chars"])
                    lengths_store[name]["tokens"].append(measured[name]["tokens"])
                length_count += 1
            label = int(split[flat])
            if label == 0:
                train_X.append(case.code_features)
                train_y.append(int(y[flat]))
            elif label == 1:
                cal_cases.append(case.reader_view())
                cal_idx.append(flat)
            else:
                test_cases.append(case.reader_view())
                test_idx.append(flat)
            flat += 1
    if flat != split.size:
        raise RuntimeError(f"materialised {flat} cases but split has {split.size}")
    return {
        "train_X": np.asarray(train_X, dtype=float) if train_X else np.zeros((0, len(feature_names))),
        "train_y": np.asarray(train_y, dtype=int),
        "cal_cases": cal_cases,
        "cal_idx": cal_idx,
        "test_cases": test_cases,
        "test_idx": test_idx,
        "feature_names": feature_names,
        "lengths": lengths_store,
        "length_count": length_count,
    }


def _risk(values: Sequence[float | None], question: str) -> np.ndarray:
    return np.asarray([risk_from_prob(question, v) for v in values], dtype=float)


def _held(risk: np.ndarray, tau: float) -> np.ndarray:
    if math.isinf(tau) and tau < 0:
        return np.ones(risk.size, dtype=bool)
    return np.where(np.isnan(risk), True, risk > tau)


def _escalated(risk: np.ndarray, lo: float = 0.4, hi: float = 0.6) -> np.ndarray:
    return np.where(np.isnan(risk), True, (risk >= lo) & (risk <= hi))


def _nan_metric(name: str) -> Metric:
    return Metric(name, float("nan"), float("nan"), float("nan"), 0, {})


def compute_bundle(
    y_cal: Sequence[int],
    r_cal: Sequence[float],
    g_cal: Sequence[Any],
    y_test: Sequence[int],
    r_test: Sequence[float],
    g_test: Sequence[Any],
    cause_test: Sequence[str],
    refs_test: Sequence[Sequence[str]],
    pred_cause_test: Sequence[str | None] | None,
    pointers_test: Sequence[Sequence[str] | None] | None,
    *,
    alpha: float = 0.05,
    n_boot: int,
    tau: float | None = None,
) -> dict[str, Any]:
    y_c = np.asarray(y_cal, dtype=int)
    r_c = np.asarray(r_cal, dtype=float)
    g_c = list(g_cal)
    y_t = np.asarray(y_test, dtype=int)
    r_t = np.asarray(r_test, dtype=float)
    g_t = list(g_test)
    if y_t.size == 0:
        out = {
            "coverage": _nan_metric("coverage_at_false_allow"),
            "auroc": _nan_metric("auroc"),
            "ece": _nan_metric("ece"),
            "top_cause": _nan_metric("top_cause_accuracy"),
            "pointer": _nan_metric("pointer_accuracy"),
            "false_holds": _nan_metric("false_holds_per_1000"),
            "escalation": _nan_metric("escalation_rate"),
            "n_test": 0,
            "n_pos": 0,
            "n_clean": 0,
            "tau": float("nan"),
            "tau_source": "none",
        }
        return out

    fixed_tau = tau
    cov = coverage_at_false_allow(
        y_c,
        r_c,
        y_t,
        r_t,
        groups_cal=g_c,
        groups_test=g_t,
        alpha=alpha,
        tau=fixed_tau,
        n_boot=n_boot,
    )
    tau = float(cov.extra.get("tau", float("nan")))
    tau_source = "pooled_fixed" if fixed_tau is not None else "slice_selected"
    held = _held(r_t, tau)
    esc = _escalated(r_t)
    au = auroc(y_t, r_t, groups=g_t, n_boot=n_boot)
    cal = ece(y_t, r_t, groups=g_t, n_boot=n_boot)
    fh = false_holds_per_1000(y_t, held, groups=g_t, n_boot=n_boot)
    er = escalation_rate(esc, groups=g_t, n_boot=n_boot)
    if pred_cause_test is not None:
        tc = top_cause_accuracy(
            y_t,
            cause_test,
            pred_cause_test,
            held,
            groups=g_t,
            n_boot=n_boot,
        )
    else:
        tc = _nan_metric("top_cause_accuracy")
    if pointers_test is not None:
        pa = pointer_accuracy(
            y_t,
            refs_test,
            pointers_test,
            held,
            groups=g_t,
            n_boot=n_boot,
        )
    else:
        pa = _nan_metric("pointer_accuracy")
    return {
        "coverage": cov.to_dict(),
        "auroc": au.to_dict(),
        "ece": cal.to_dict(),
        "top_cause": tc.to_dict(),
        "pointer": pa.to_dict(),
        "false_holds": fh.to_dict(),
        "escalation": er.to_dict(),
        "n_test": int(y_t.size),
        "n_pos": int((y_t == 1).sum()),
        "n_clean": int((y_t == 0).sum()),
        "tau": tau,
        "tau_source": tau_source,
        "hold_all": bool(cov.extra.get("hold_all", False)),
        "held": held,
        "escalated": esc,
    }


def _fmt(value: Any) -> str:
    try:
        v = float(value)
    except Exception:
        return "nan"
    return "nan" if not math.isfinite(v) else f"{v:.4f}"


def _fmt_tau(value: Any, hold_all: bool = False) -> str:
    """Print a threshold; a hold-all policy is ``-inf``, never ``nan``."""
    try:
        v = float(value)
    except Exception:
        return "nan"
    if math.isinf(v) and v < 0:
        return "hold_all"
    if hold_all:
        return "hold_all"
    return "nan" if not math.isfinite(v) else f"{v:.6f}"


def _metric_row(prefix: Sequence[Any], payload: dict[str, Any]) -> str:
    cov = payload["coverage"]
    au = payload["auroc"]
    cal = payload["ece"]
    tc = payload["top_cause"]
    pa = payload["pointer"]
    fh = payload["false_holds"]
    er = payload["escalation"]
    fields = list(prefix) + [
        payload["n_test"],
        payload["n_pos"],
        payload["n_clean"],
        _fmt(cov.get("value")),
        _fmt(cov.get("lo")),
        _fmt(cov.get("hi")),
        _fmt_tau(payload.get("tau"), bool(payload.get("hold_all", False))),
        _fmt(au.get("value")),
        _fmt(au.get("lo")),
        _fmt(au.get("hi")),
        _fmt(cal.get("value")),
        _fmt(cal.get("lo")),
        _fmt(cal.get("hi")),
        _fmt(tc.get("value")),
        _fmt(pa.get("value")),
        _fmt(fh.get("value")),
        _fmt(fh.get("lo")),
        _fmt(fh.get("hi")),
        _fmt(er.get("value")),
    ]
    return ",".join(str(x) for x in fields)


POOLED_HEADER = (
    "reader,question,n_test,n_pos,n_clean,coverage,cov_lo,cov_hi,tau,"
    "auroc,auroc_lo,auroc_hi,ece,ece_lo,ece_hi,top_cause,pointer,"
    "false_holds_per_1000,fh_lo,fh_hi,escalation"
)
SLICE_HEADER = (
    "reader,question,slice,n_test,n_pos,n_clean,coverage,cov_lo,cov_hi,tau,"
    "auroc,auroc_lo,auroc_hi,ece,ece_lo,ece_hi,top_cause,pointer,"
    "false_holds_per_1000,fh_lo,fh_hi,escalation"
)


def measure_latency(reader: Any, test_cases: Sequence[Any], limit: int = 300) -> dict[str, Any]:
    sample = list(test_cases[:limit])
    if not sample:
        return {"n_decisions": 0, "mean_ms": float("nan")}
    times: list[float] = []
    for case in sample:
        started = time.perf_counter()
        reader.score([case], "raw")
        times.append(time.perf_counter() - started)
    groups = [getattr(case, "episode_key", i) for i, case in enumerate(sample)]
    return cost_summary(
        times,
        n_decisions=len(test_cases),
        gpu_seconds=0.0,
        groups=groups,
        n_boot=200,
    )


def print_lengths(lengths: dict[str, dict[str, list[int]]], count: int) -> dict[str, Any]:
    out: dict[str, Any] = {"n_cases": count, "renderings": {}}
    print("== rendering lengths ==")
    print("rendering,n,chars_mean,chars_p50,chars_p95,chars_p99,chars_max,tokens_mean,tokens_p50,tokens_p95,tokens_p99,tokens_max")
    for name in RENDERINGS:
        chars = np.asarray(lengths[name]["chars"], dtype=float)
        tokens = np.asarray(lengths[name]["tokens"], dtype=float)
        if chars.size == 0:
            print(f"{name},0,nan,nan,nan,nan,nan,nan,nan,nan,nan,nan")
            out["renderings"][name] = {"n": 0}
            continue
        row = {
            "n": int(chars.size),
            "chars_mean": float(chars.mean()),
            "chars_p50": float(np.percentile(chars, 50)),
            "chars_p95": float(np.percentile(chars, 95)),
            "chars_p99": float(np.percentile(chars, 99)),
            "chars_max": float(chars.max()),
            "tokens_mean": float(tokens.mean()),
            "tokens_p50": float(np.percentile(tokens, 50)),
            "tokens_p95": float(np.percentile(tokens, 95)),
            "tokens_p99": float(np.percentile(tokens, 99)),
            "tokens_max": float(tokens.max()),
        }
        out["renderings"][name] = row
        print(
            f"{name},{row['n']},{_fmt(chars.mean())},{_fmt(np.percentile(chars, 50))},"
            f"{_fmt(np.percentile(chars, 95))},{_fmt(np.percentile(chars, 99))},{_fmt(chars.max())},"
            f"{_fmt(tokens.mean())},{_fmt(np.percentile(tokens, 50))},{_fmt(np.percentile(tokens, 95))},"
            f"{_fmt(np.percentile(tokens, 99))},{_fmt(tokens.max())}"
        )
    return out


def run_axis(
    axis: str,
    rows: dict[str, list[Any]],
    corpus: dict[str, Any],
    split: np.ndarray,
    *,
    data_dir: str,
    limit: int | None,
    n_boot: int,
    slice_boot: int,
    lengths: bool,
    render_limit: int,
    results: dict[str, Any],
) -> None:
    print(f"== split axis: {axis} ({SPLIT_NOTES.get(axis, '')}) ==")
    summary = split_summary([str(g) for g in rows[axis]], split)
    episodes = [str(e) for e in rows["episode"]]
    seen: dict[str, set[int]] = {}
    for episode, label in zip(episodes, split):
        seen.setdefault(episode, set()).add(int(label))
    leaking = sum(1 for labels in seen.values() if len(labels) > 1)
    summary["episodes"] = len(seen)
    summary["episodes_on_both_sides"] = int(leaking)
    summary["episode_disjoint"] = leaking == 0
    summary["note"] = SPLIT_NOTES.get(axis, "")
    print(
        "split_groups "
        f"train={summary['train']['groups']} cal={summary['cal']['groups']} "
        f"test={summary['test']['groups']} total={summary['groups_total']}"
    )
    print(
        "split_cases "
        f"train={summary['train']['cases']} cal={summary['cal']['cases']} "
        f"test={summary['test']['cases']}"
    )
    print(
        "split_disjointness "
        f"group_key_disjoint=True episode_disjoint={summary.get('episode_disjoint')} "
        f"episodes_on_both_sides={summary.get('episodes_on_both_sides')}"
    )
    materialised = materialize(
        data_dir,
        limit,
        split,
        rows["y"],
        lengths=lengths,
        render_limit=render_limit,
    )
    train_X = materialised["train_X"]
    train_y = materialised["train_y"]
    print(f"train_cases {train_X.shape[0]} features {train_X.shape[1] if train_X.ndim == 2 else 0}")
    code_reader = CodeLogisticReader(seed=20261119)
    code_reader.fit_features(train_X, train_y, materialised["feature_names"])
    readers = {
        "constant": ConstantReader(0.5),
        "code_features_logistic": code_reader,
    }

    cal_cases = materialised["cal_cases"]
    test_cases = materialised["test_cases"]
    cal_idx = materialised["cal_idx"]
    test_idx = materialised["test_idx"]
    y = rows["y"]
    groups_by_axis = rows[axis]
    y_cal = np.asarray([y[i] for i in cal_idx], dtype=int)
    y_test = np.asarray([y[i] for i in test_idx], dtype=int)
    g_cal = [groups_by_axis[i] for i in cal_idx]
    g_test = [groups_by_axis[i] for i in test_idx]
    cause_test = [rows["cause"][i] for i in test_idx]
    refs_test = [rows["cause_refs"][i] for i in test_idx]
    truth_test = [rows["truth_type"][i] for i in test_idx]
    axes_test = [rows["axes"][i] for i in test_idx]

    axis_result: dict[str, Any] = {
        "summary": summary,
        "pooled": {},
        "per_truth_type": {},
        "per_axis": {},
        "cost": {},
        "train_cases": int(train_X.shape[0]),
    }
    if lengths:
        axis_result["renderings"] = print_lengths(materialised["lengths"], materialised["length_count"])

    print(f"\n== pooled metrics ({axis} group split; all questions) ==")
    print(POOLED_HEADER)
    for reader_name, reader in readers.items():
        started = time.perf_counter()
        cal_scores = validate_scores(reader.score(cal_cases, "raw"), len(cal_cases))
        test_scores = validate_scores(reader.score(test_cases, "raw"), len(test_cases))
        elapsed = time.perf_counter() - started
        pred_cause = None
        pointers = None
        if hasattr(reader, "cause_argmax"):
            pred_cause = reader.cause_argmax(test_cases, "raw")
        if hasattr(reader, "pointers"):
            pointers = reader.pointers(test_cases, "raw")
        latency = measure_latency(reader, test_cases)
        print(
            f"score_batch reader={reader_name} cal={len(cal_cases)} test={len(test_cases)} "
            f"wall_s={elapsed:.3f} items_per_s={(len(cal_cases) + len(test_cases)) / elapsed if elapsed > 0 else float('nan'):.1f}"
        )
        print(
            f"cost reader={reader_name} mean_ms={_fmt(latency.get('mean_ms'))} "
            f"mean_ms_lo={_fmt(latency.get('mean_ms_lo'))} "
            f"mean_ms_hi={_fmt(latency.get('mean_ms_hi'))} "
            f"p50_ms={_fmt(latency.get('p50_ms'))} p99_ms={_fmt(latency.get('p99_ms'))} "
            f"gpu_seconds_per_1000={_fmt(latency.get('gpu_seconds_per_1000'))} "
            f"n_decisions={latency.get('n_decisions')}"
        )
        axis_result["cost"][reader_name] = latency
        axis_result["pooled"][reader_name] = {}
        for question in QUESTIONS:
            r_cal = _risk(cal_scores[question], question)
            r_test = _risk(test_scores[question], question)
            bundle = compute_bundle(
                y_cal,
                r_cal,
                g_cal,
                y_test,
                r_test,
                g_test,
                cause_test,
                refs_test,
                pred_cause,
                pointers,
                n_boot=n_boot,
            )
            print(_metric_row((reader_name, question), bundle))
            cov_extra = bundle["coverage"].get("extra", {})
            good_allowed = cov_extra.get("good_allowed_test", 0)
            bad_allowed = cov_extra.get("bad_allowed_test", 0)
            denom_allowed = good_allowed + bad_allowed
            test_false_allow = (bad_allowed / denom_allowed) if denom_allowed else float("nan")
            tc_extra = bundle["top_cause"].get("extra", {})
            pa_extra = bundle["pointer"].get("extra", {})
            print(
                f"metric_detail reader={reader_name} question={question} "
                f"coverage_rule={cov_extra.get('rule')} "
                f"cal_upper={_fmt(cov_extra.get('cal_upper'))} "
                f"cal_allowed={cov_extra.get('cal_allowed')} cal_bad={cov_extra.get('cal_bad')} "
                f"test_bad={cov_extra.get('bad_test')} bad_allowed_test={bad_allowed} "
                f"good_allowed_test={good_allowed} "
                f"abstained_clean_test={cov_extra.get('n_abstained_clean_test')} "
                f"test_false_allow_among_allowed={_fmt(test_false_allow)} "
                f"top_cause_n={tc_extra.get('n_flagged_positive')} "
                f"top_cause_hits={tc_extra.get('hits')} "
                f"pointer_n={pa_extra.get('n_with_refs')} "
                f"pointer_hits={pa_extra.get('hits')}"
            )
            axis_result["pooled"][reader_name][question] = {
                key: value
                for key, value in bundle.items()
                if key not in ("held", "escalated")
            }

    # Per truth type and per axis: the code reader, question "supported".
    # The four questions of this trivial reader share one risk score, so one
    # question is the honest representative; the pooled table carries all four.
    # Every slice is evaluated at the POOLED operating point so rows share one
    # threshold and are comparable.  A slice-selected threshold is also stored
    # for transparency, but it is not the reported table.
    pooled_tau = float(axis_result["pooled"]["code_features_logistic"]["supported"]["tau"])
    pooled_hold_all = bool(axis_result["pooled"]["code_features_logistic"]["supported"].get("hold_all", False))
    print(
        f"slice_operating_point tau={_fmt_tau(pooled_tau, pooled_hold_all)} "
        f"source=pooled code_features_logistic/supported (fixed for every slice)"
    )
    print("\n== per truth type (code reader, supported) ==")
    print(SLICE_HEADER)
    code_scores_test = validate_scores(code_reader.score(test_cases, "raw"), len(test_cases))
    code_scores_cal = validate_scores(code_reader.score(cal_cases, "raw"), len(cal_cases))
    r_test_all = _risk(code_scores_test["supported"], "supported")
    r_cal_all = _risk(code_scores_cal["supported"], "supported")
    pred_all = code_reader.cause_argmax(test_cases, "raw")
    ptr_all = code_reader.pointers(test_cases, "raw")
    for truth in TRUTH_TYPES:
        pos = np.asarray([(yy == 1 and tt == truth) for yy, tt in zip(y_test, truth_test)], dtype=bool)
        neg = y_test == 0
        slice_test = pos | neg
        cal_pos = np.asarray(
            [(yy == 1 and rows["truth_type"][i] == truth) for yy, i in zip(y_cal, cal_idx)],
            dtype=bool,
        )
        cal_slice = cal_pos | (y_cal == 0)
        slice_kwargs = dict(
            cause_test=[c for c, keep in zip(cause_test, slice_test) if keep],
            refs_test=[r for r, keep in zip(refs_test, slice_test) if keep],
            pred_cause_test=[c for c, keep in zip(pred_all, slice_test) if keep],
            pointers_test=[p for p, keep in zip(ptr_all, slice_test) if keep],
        )
        bundle = compute_bundle(
            y_cal[cal_slice],
            r_cal_all[cal_slice],
            [g for g, keep in zip(g_cal, cal_slice) if keep],
            y_test[slice_test],
            r_test_all[slice_test],
            [g for g, keep in zip(g_test, slice_test) if keep],
            slice_kwargs["cause_test"],
            slice_kwargs["refs_test"],
            slice_kwargs["pred_cause_test"],
            slice_kwargs["pointers_test"],
            n_boot=slice_boot,
            tau=pooled_tau,
        )
        self_tau = compute_bundle(
            y_cal[cal_slice],
            r_cal_all[cal_slice],
            [g for g, keep in zip(g_cal, cal_slice) if keep],
            y_test[slice_test],
            r_test_all[slice_test],
            [g for g, keep in zip(g_test, slice_test) if keep],
            slice_kwargs["cause_test"],
            slice_kwargs["refs_test"],
            slice_kwargs["pred_cause_test"],
            slice_kwargs["pointers_test"],
            n_boot=slice_boot,
        )
        print(_metric_row(("code_features_logistic", "supported", truth), bundle))
        print(
            f"slice_self_tau slice={truth} tau={_fmt_tau(self_tau.get('tau'), bool(self_tau.get('hold_all')))} "
            f"coverage={_fmt(self_tau['coverage'].get('value'))} "
            f"false_holds={_fmt(self_tau['false_holds'].get('value'))} "
            f"escalation={_fmt(self_tau['escalation'].get('value'))}"
        )
        axis_result["per_truth_type"][truth] = {
            key: value for key, value in bundle.items() if key not in ("held", "escalated")
        }
        axis_result.setdefault("per_truth_type_self_tau", {})[truth] = {
            key: value for key, value in self_tau.items() if key not in ("held", "escalated")
        }

    print("\n== per shift axis (code reader, supported) ==")
    print(SLICE_HEADER)
    for shift_axis in SHIFT_AXES:
        pos = np.asarray(
            [(yy == 1 and shift_axis in ax) for yy, ax in zip(y_test, axes_test)],
            dtype=bool,
        )
        neg = y_test == 0
        slice_test = pos | neg
        cal_pos = np.asarray(
            [
                (yy == 1 and shift_axis in rows["axes"][i])
                for yy, i in zip(y_cal, cal_idx)
            ],
            dtype=bool,
        )
        cal_slice = cal_pos | (y_cal == 0)
        bundle = compute_bundle(
            y_cal[cal_slice],
            r_cal_all[cal_slice],
            [g for g, keep in zip(g_cal, cal_slice) if keep],
            y_test[slice_test],
            r_test_all[slice_test],
            [g for g, keep in zip(g_test, slice_test) if keep],
            [c for c, keep in zip(cause_test, slice_test) if keep],
            [r for r, keep in zip(refs_test, slice_test) if keep],
            [c for c, keep in zip(pred_all, slice_test) if keep],
            [p for p, keep in zip(ptr_all, slice_test) if keep],
            n_boot=slice_boot,
            tau=pooled_tau,
        )
        self_tau = compute_bundle(
            y_cal[cal_slice],
            r_cal_all[cal_slice],
            [g for g, keep in zip(g_cal, cal_slice) if keep],
            y_test[slice_test],
            r_test_all[slice_test],
            [g for g, keep in zip(g_test, slice_test) if keep],
            [c for c, keep in zip(cause_test, slice_test) if keep],
            [r for r, keep in zip(refs_test, slice_test) if keep],
            [c for c, keep in zip(pred_all, slice_test) if keep],
            [p for p, keep in zip(ptr_all, slice_test) if keep],
            n_boot=slice_boot,
        )
        print(_metric_row(("code_features_logistic", "supported", shift_axis), bundle))
        print(
            f"slice_self_tau slice={shift_axis} tau={_fmt_tau(self_tau.get('tau'), bool(self_tau.get('hold_all')))} "
            f"coverage={_fmt(self_tau['coverage'].get('value'))} "
            f"false_holds={_fmt(self_tau['false_holds'].get('value'))} "
            f"escalation={_fmt(self_tau['escalation'].get('value'))}"
        )
        axis_result["per_axis"][shift_axis] = {
            key: value for key, value in bundle.items() if key not in ("held", "escalated")
        }
        axis_result.setdefault("per_axis_self_tau", {})[shift_axis] = {
            key: value for key, value in self_tau.items() if key not in ("held", "escalated")
        }

    axis_result["slice_operating_point"] = {
        "tau": pooled_tau,
        "hold_all": pooled_hold_all,
        "source": "pooled code_features_logistic/supported",
    }
    results["axes"][axis] = axis_result



def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.floating):
        return _json_safe(float(value))
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/ref")
    parser.add_argument("--limit", type=int, default=40, help="episodes per family/shift file")
    parser.add_argument("--n-boot", type=int, default=300)
    parser.add_argument("--slice-boot", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument("--render-limit", type=int, default=0, help="0 means every case")
    parser.add_argument("--split-axes", default="owner,episode,company")
    args = parser.parse_args(argv)

    print("== T15 frozen evaluation bench ==")
    print(f"data_dir: {args.data_dir}")
    print(f"limit_per_file: {args.limit if args.limit is not None else 'all'}")
    print(f"n_boot: {args.n_boot} slice_boot: {args.slice_boot} seed: {args.seed}")
    actual = spec_hash()
    print(f"spec_sha256: {actual}")
    ok, got, expected = verify_spec()
    print(f"spec_sha256_matches_committed: {ok} actual={got} expected={expected}")

    rows, corpus = collect_metadata(args.data_dir, args.limit)
    print("\n== corpus ==")
    print(f"episodes: {corpus['episodes']}")
    print(f"actions: {corpus['actions']}")
    print(f"positives: {corpus['positives']}")
    print(f"agent_id_present: {corpus['agent_id_present']}")
    print("cell,episodes,actions,positives,rate")
    for key in sorted(corpus["by_cell"]):
        cell = corpus["by_cell"][key]
        rate = cell["positives"] / cell["actions"] if cell["actions"] else float("nan")
        print(f"{key},{cell['episodes']},{cell['actions']},{cell['positives']},{_fmt(rate)}")

    print("\n== group splits ==")
    print("axis,groups,available,episode_disjoint,episodes_on_both_sides,train_groups,cal_groups,test_groups,train_cases,cal_cases,test_cases")
    splits: dict[str, np.ndarray] = {}
    split_summaries: dict[str, Any] = {}
    for axis in SPLIT_AXES:
        split, summary = _split_for_axis(
            rows,
            axis,
            args.seed,
            agent_id_present=bool(corpus["agent_id_present"]),
        )
        split_summaries[axis] = summary
        if split is None:
            print(f"{axis},{summary['groups']},False,,,,,,,,")
            print(f"  # {axis}: {summary.get('reason', 'unavailable')}")
            continue
        splits[axis] = split
        print(
            f"{axis},{summary['groups_total']},True,{summary.get('episode_disjoint')},"
            f"{summary.get('episodes_on_both_sides')},"
            f"{summary['train']['groups']},"
            f"{summary['cal']['groups']},{summary['test']['groups']},"
            f"{summary['train']['cases']},{summary['cal']['cases']},{summary['test']['cases']}"
        )

    results: dict[str, Any] = {
        "spec_sha256": actual,
        "spec_hash_matches": ok,
        "args": vars(args),
        "corpus": {k: v for k, v in corpus.items() if k != "episode_sizes"},
        "splits": split_summaries,
        "axes": {},
    }
    requested = [a.strip() for a in args.split_axes.split(",") if a.strip()]
    for axis in requested:
        if axis not in splits:
            print(f"== split axis: {axis} unavailable ==")
            continue
        run_axis(
            axis,
            rows,
            corpus,
            splits[axis],
            data_dir=args.data_dir,
            limit=args.limit,
            n_boot=args.n_boot,
            slice_boot=args.slice_boot,
            lengths=(axis == "owner"),
            render_limit=args.render_limit,
            results=results,
        )

    out_path = HERE / "results.json"
    out_path.write_text(
        json.dumps(_json_safe(results), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"\nresults_json: {out_path.name}")
    print(f"spec_sha256: {spec_hash()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
