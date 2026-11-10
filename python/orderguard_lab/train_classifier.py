"""Train the local injection classifier (L2 first stage) on the attack lab and the sandbox, with honest held-out evaluation.

    python -m orderguard_lab.train_classifier --out data/models/injection_clf.json

Data: every attack chunk and clean chunk the detector test uses (lab cases), plus attacked sandbox worlds and their benign twins over
many seeds. A chunk is split into lines; a line is an attack line if it is not in the clean control / twin of the same world, so the
labels are exact. Groups are techniques (each lab case, each sandbox technique), never mixed between train and test.
Evaluation: 5-fold technique-grouped cross-validation. A line whose text occurs in any test chunk is removed from the training side, so
test text is never seen. The threshold of each fold is chosen on an inner grouped CV of that fold's training data only (nested), so the
recall and false-alarm numbers are out-of-fold. A second check trains on one source (lab / sandbox) and tests on the other.
Export: JSON (no pickle). Deterministic: no randomness anywhere (greedy fold assignment, lbfgs, fixed vocabularies).
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from orderguard_guard import classifier as clf
from orderguard_guard.classifier import FORMAT, prepare_lines

from . import cases as C
from . import detect
from .envs import chunks_of, feed_windows, page_text
from .sandbox.compiler import TECHNIQUES, compile_case

SEEDS = 16
FOLDS = 5
TARGET_FPR = 0.015              # chunk-level false-alarm target on clean when picking the threshold
PREFILTER_FPR = 0.003           # stricter target for the "quarantine without a model call" threshold
C_REG = 10.0
MAX_FEATURES = {"char": 30000, "word": 15000}
FAMILY_NAMES = {"A": "instruction", "B": "authority", "C": "false data", "D": "spoofed data", "E": "denial of service"}
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "models" / "injection_clf.json"


# ---- data ------------------------------------------------------------------------------------------------------------------

def world_chunks(env) -> list[tuple[str, str]]:
    """Every chunk of untrusted text in a sandbox WorldEnv, across all surfaces, the way the screen meets it."""
    out = [("doc", c) for c in chunks_of(env.filing_text(env.world.focal) or "")]
    out += [("web", page_text(p)) for p in env.ranked]
    out += [("feed", w) for w in feed_windows(env.events)]
    out.append(("tool", json.dumps(env._get_market_summary({"ticker": env.world.focal}), ensure_ascii=False)))
    out += [("tool", t["function"]["description"]) for t in env.tools("full") if t["function"]["name"] in env.tool_descriptions]
    out.append(("tool", env.notes))
    return [(k, t) for k, t in out if t and t.strip()]


def _chunk(cid, group, source, family, kind, label, case, text):
    return {"id": cid, "group": group, "source": source, "family": family, "kind": kind, "label": label, "case": case, "text": text, "lines": prepare_lines(text)}


def build_chunks(seeds: int = SEEDS) -> list[dict]:
    """Chunks with labels and groups. Line labels are added by `_label_lines`."""
    out: list[dict] = []
    seen: set = set()

    def add(**kw):
        key = (kw["label"], kw["group"], kw["text"])
        if key not in seen and kw["text"].strip():
            seen.add(key)
            out.append(_chunk(len(out), **kw))

    attack, clean_ = detect.chunk_sets()
    lab_family = {c.id: c.family for c in C.all_cases()}
    for c in clean_:
        add(group="lab-clean:" + c["case"].split(":")[1], source="lab", family="", kind=c["kind"], label=0, case=c["case"], text=c["text"])
    for a in attack:
        add(group="lab:" + a["case"], source="lab", family=lab_family[a["case"]], kind=a["kind"], label=1, case=a["case"], text=a["text"])
    for seed in range(seeds):
        for name, t in TECHNIQUES.items():
            sc = compile_case(seed, name)
            twin = world_chunks(sc.twin_env())
            known = {ln for _, t in twin for ln in t.split("\n") if ln.strip()}
            for k, tx in twin:
                add(group="sbx:" + name, source="sandbox", family="", kind=k, label=0, case=f"sbx/{name}/s{seed}", text=tx)
            if t.control or t.family == "F":
                continue
            for k, tx in world_chunks(sc.attack_env()):
                if not any(ln.strip() and ln not in known for ln in tx.split("\n")):
                    continue
                add(group="sbx:" + name, source="sandbox", family=t.family, kind=k, label=1, case=f"sbx/{name}/s{seed}", text=tx)
    _label_lines(out)
    return out


def _label_lines(chunks: list[dict]) -> None:
    """A line of an attack chunk is an attack line unless the same line occurs in clean text of the same source."""
    clean_lines = defaultdict(set)
    for c in chunks:
        if c["label"] == 0:
            clean_lines[c["source"]].update(c["lines"])
    for c in chunks:
        c["y"] = [(0 if c["label"] == 0 or ln in clean_lines[c["source"]] else 1) for ln in c["lines"]]


def data_hash(chunks: list[dict]) -> str:
    h = hashlib.sha256()
    for r in sorted((c["label"], c["group"], c["text"]) for c in chunks):
        h.update(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n")
    return h.hexdigest()


def assign_folds(chunks: list[dict], n: int) -> dict[str, int]:
    """Deterministic grouped folds: greedy, largest group first, into the lightest fold."""
    size = defaultdict(int)
    for c in chunks:
        size[c["group"]] += 1
    load = [0] * n
    fold = {}
    for g in sorted(size, key=lambda g: (-size[g], g)):
        k = min(range(n), key=lambda i: (load[i], i))
        fold[g] = k
        load[k] += size[g]
    return fold


# ---- model -----------------------------------------------------------------------------------------------------------------

class Fitted:
    def __init__(self, vecs, lr):
        self.vecs, self.lr = vecs, lr

    def matrix(self, lines: list[str]):
        import scipy.sparse as sp
        return sp.hstack([v.transform(lines) for v in self.vecs.values()], format="csr")

    def proba(self, lines: list[str]) -> list[float]:
        return list(self.lr.predict_proba(self.matrix(lines))[:, 1]) if lines else []


def fit(chunks: list[dict], exclude_texts: set = frozenset()) -> Fitted:
    """Fit on the unique lines of `chunks` (a line seen as clean anywhere in them is clean), minus any line in `exclude_texts`."""
    import scipy.sparse as sp
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    y_of: dict[str, int] = {}
    for c in chunks:
        for ln, y in zip(c["lines"], c["y"]):
            if ln not in exclude_texts:
                y_of[ln] = min(y, y_of.get(ln, 1))
    # An attack line that differs from a clean line only in its digits (an edited figure, a lied price) has identical features: text alone
    # cannot separate them, so it is not used as a training example (it still counts as a miss when evaluated).
    clean_keys = {clf._norm(ln) for ln, v in y_of.items() if v == 0}
    lines = sorted(ln for ln in y_of if y_of[ln] == 0 or clf._norm(ln) not in clean_keys)
    y = [y_of[ln] for ln in lines]
    vecs = {name: TfidfVectorizer(analyzer=clf.ANALYZERS[name], min_df=2, max_features=MAX_FEATURES[name], sublinear_tf=True, norm="l2")
            for name in ("char", "word")}
    mats = [v.fit_transform(lines) for v in vecs.values()]
    lr = LogisticRegression(C=C_REG, class_weight="balanced", max_iter=3000, solver="lbfgs")
    lr.fit(sp.hstack(mats, format="csr"), y)
    return Fitted(vecs, lr)


def chunk_scores(model: Fitted, chunks: list[dict]) -> list[float]:
    uniq = sorted({ln for c in chunks for ln in c["lines"]})
    p = dict(zip(uniq, model.proba(uniq)))
    return [max((p[ln] for ln in c["lines"]), default=0.0) for c in chunks]


def pick_threshold(clean_scores: list[float], target: float) -> float:
    """Lowest threshold (>= 0.5) with at most target * n clean chunks at or above it."""
    if not clean_scores:
        return 0.5
    d = sorted(clean_scores, reverse=True)
    k = int(target * len(d))
    t = (d[k] + d[k - 1]) / 2 if 0 < k < len(d) and d[k] != d[k - 1] else (d[k] + 1e-6 if k < len(d) else 0.5)
    return max(0.5, t)


def grouped_oof(chunks: list[dict], n_folds: int, strict_clean: bool = False) -> list[float]:
    """Out-of-fold chunk scores: each chunk is scored by a model that saw neither its group nor any of its lines."""
    fold = assign_folds(chunks, n_folds)
    scores = [0.0] * len(chunks)
    for k in range(n_folds):
        test = [i for i, c in enumerate(chunks) if fold[c["group"]] == k]
        train = [c for c in chunks if fold[c["group"]] != k]
        texts = {ln for i in test for ln, y in zip(chunks[i]["lines"], chunks[i]["y"]) if strict_clean or y}
        m = fit(train, texts)
        for i, s in zip(test, chunk_scores(m, [chunks[i] for i in test])):
            scores[i] = s
    return scores


def train_and_score(train: list[dict], test: list[dict], inner_folds: int = 4, strict_clean: bool = False) -> tuple[list[float], float]:
    """Fit on `train` (without lines present in `test`), threshold from an inner grouped CV of `train`; return test scores, threshold."""
    inner = grouped_oof(train, inner_folds, strict_clean)
    thr = pick_threshold([s for s, c in zip(inner, train) if c["label"] == 0], TARGET_FPR)
    m = fit(train, {ln for c in test for ln, y in zip(c["lines"], c["y"]) if strict_clean or y})
    return chunk_scores(m, test), thr


# ---- metrics ---------------------------------------------------------------------------------------------------------------

def _auc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score([1] * len(pos) + [0] * len(neg), pos + neg))


def summarise(chunks: list[dict], scores: list[float], thr_of: list[float]) -> dict:
    flag = [s >= t for s, t in zip(scores, thr_of)]
    att = [i for i, c in enumerate(chunks) if c["label"] == 1]
    cln = [i for i, c in enumerate(chunks) if c["label"] == 0]
    tp = sum(flag[i] for i in att)
    fp = sum(flag[i] for i in cln)
    neg = [scores[i] for i in cln]

    def block(idx_att, idx_cln=cln):
        r = sum(flag[i] for i in idx_att)
        f = sum(flag[i] for i in idx_cln)
        return {"n_attack": len(idx_att), "recall": round(r / len(idx_att), 4) if idx_att else None, "n_clean": len(idx_cln),
                "false_alarm_rate": round(f / len(idx_cln), 4) if idx_cln else None, "precision": round(r / (r + f), 4) if r + f else None,
                "auc": None if not idx_att else (None if not (a := _auc([scores[i] for i in idx_att], [scores[i] for i in idx_cln])) else round(a, 4))}

    out = {"overall": block(att), "by_family": {}, "by_source": {}, "by_kind": {}, "by_technique": {}, "clean_by_source": {}}
    for fam in sorted({chunks[i]["family"] for i in att}):
        out["by_family"][fam] = dict(block([i for i in att if chunks[i]["family"] == fam]), name=FAMILY_NAMES.get(fam, fam))
    for src in sorted({c["source"] for c in chunks}):
        out["by_source"][src] = block([i for i in att if chunks[i]["source"] == src], [i for i in cln if chunks[i]["source"] == src])
    for kind in sorted({c["kind"] for c in chunks}):
        out["by_kind"][kind] = block([i for i in att if chunks[i]["kind"] == kind], [i for i in cln if chunks[i]["kind"] == kind])
    for g in sorted({chunks[i]["group"] for i in att}):
        ix = [i for i in att if chunks[i]["group"] == g]
        out["by_technique"][g] = {"n": len(ix), "recall": round(sum(flag[i] for i in ix) / len(ix), 3)}
    return out


# ---- driver ----------------------------------------------------------------------------------------------------------------

def nested_oof(chunks: list[dict], n_folds: int = FOLDS) -> tuple[list[float], list[float]]:
    """Out-of-fold scores and the per-chunk threshold chosen without that chunk's group (nested)."""
    fold = assign_folds(chunks, n_folds)
    scores, thr = [0.0] * len(chunks), [0.5] * len(chunks)
    for k in range(n_folds):
        test = [i for i, c in enumerate(chunks) if fold[c["group"]] == k]
        train = [c for c in chunks if fold[c["group"]] != k]
        s, t = train_and_score(train, [chunks[i] for i in test])
        for i, v in zip(test, s):
            scores[i], thr[i] = v, t
    return scores, thr


@functools.lru_cache(maxsize=2)
def out_of_fold(seeds: int = SEEDS, folds: int = FOLDS) -> tuple[list[dict], list[float], list[float]]:
    chunks = build_chunks(seeds)
    s, t = nested_oof(chunks, folds)
    return chunks, s, t


def cross_source(chunks: list[dict]) -> dict:
    res = {}
    for a, b in (("lab", "sandbox"), ("sandbox", "lab")):
        tr = [c for c in chunks if c["source"] == a]
        te = [c for c in chunks if c["source"] == b]
        # lab-only training has little clean text outside the shared 10-K, so the inner threshold CV keeps clean lines (test text stays excluded)
        s, t = train_and_score(tr, te)
        m = summarise(te, s, [t] * len(te))
        res[f"train {a} -> test {b}"] = {"overall": m["overall"], "by_family": {k: {x: v[x] for x in ("n_attack", "recall", "auc")} for k, v in m["by_family"].items()}}
    return res


def export(model: Fitted, thr: float, pre: float, metrics: dict, dhash: str, path: Path) -> int:
    n_char = len(model.vecs["char"].vocabulary_)
    coef = model.lr.coef_[0]
    blocks, off = {}, 0
    for name, v in model.vecs.items():
        terms = [t for t, _ in sorted(v.vocabulary_.items(), key=lambda kv: kv[1])]
        n = len(terms)
        blocks[name] = {"terms": terms, "idf": [round(float(x), 6) for x in v.idf_], "coef": [round(float(x), 6) for x in coef[off:off + n]]}
        off += n
    assert n_char == len(blocks["char"]["terms"])
    art = {"format": FORMAT, "threshold": round(thr, 6), "prefilter_threshold": round(max(pre, thr), 6), "intercept": round(float(model.lr.intercept_[0]), 6),
           "config": {"char": {"analyzer": "char_wb", "ngram_range": [3, 5], "digits_folded": True}, "word": {"ngram_range": [1, 2], "digits_folded": True},
                      "tfidf": "sublinear_tf, smooth idf, l2 per block", "C": C_REG, "class_weight": "balanced", "unit": "line, chunk score = max",
                      "preprocessing": "orderguard_guard.normalise.clean, then unicode-tag payload as an extra line"},
           "training_data_sha256": dhash, "metrics": metrics, "blocks": blocks}
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(art, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")
    return len(text.encode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train the local injection classifier and export it as JSON.")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seeds", type=int, default=SEEDS, help="sandbox seeds per technique")
    ap.add_argument("--folds", type=int, default=FOLDS)
    a = ap.parse_args(argv)
    chunks, oof, thr_of = out_of_fold(a.seeds, a.folds)
    metrics = {"held_out": summarise(chunks, oof, thr_of), "cross_source": cross_source(chunks),
               "data": {"chunks": len(chunks), "attack_chunks": sum(c["label"] for c in chunks), "clean_chunks": sum(1 - c["label"] for c in chunks),
                        "groups": len({c["group"] for c in chunks}), "seeds": a.seeds, "folds": a.folds, "target_fpr": TARGET_FPR,
                        "protocol": "technique-grouped CV; test lines removed from training; threshold chosen by inner CV (nested)"}}
    clean_oof = [s for s, c in zip(oof, chunks) if c["label"] == 0]
    thr, pre = pick_threshold(clean_oof, TARGET_FPR), pick_threshold(clean_oof, PREFILTER_FPR)
    model = fit(chunks)
    size = export(model, thr, pre, metrics, data_hash(chunks), Path(a.out))
    ho = metrics["held_out"]["overall"]
    print(f"wrote {a.out} ({size / 1e6:.2f} MB), threshold {thr:.3f}, prefilter {max(pre, thr):.3f}; held-out recall {ho['recall']}, false alarms {ho['false_alarm_rate']}, auc {ho['auc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
