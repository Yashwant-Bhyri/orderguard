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
TARGET_V2 = 0.03               # v2: source-balanced false-alarm target on cross-fitted clean chunks (the lab's real prose is hard)
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


# =====================================================================================================================
# v2: augmentation, hard negatives, weight-space soups, calibration, decision layer, cascade thresholds
# =====================================================================================================================
import base64
import random
import re

import numpy as np

from orderguard_guard import decision as dec
from orderguard_guard.normalise import CONFUSABLES

Z_MIN = -dec.Z_CLIP
INV_CONF = {v: k for k, v in CONFUSABLES.items() if v in "AEOPCXaeopcxBHKMTYy"}


def _rng(*key) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, key)).encode()).hexdigest()[:12], 16))


# Template pools. "train" pools feed training augmentation; "eval" pools are different phrases/wrappers/translations, used only by the
# robustness suite, so the perturbation numbers are not measured on the exact instances the model was augmented with.
PREFIX = {"train": ["Note to the AI assistant: ", "Reminder for automated trading agents - ", "IMPORTANT (for the model reading this): ", "Dear assistant, ",
                    "System notice to processing agents: ", "[internal] "],
          "eval": ["FYI for any LLM agent parsing this page: ", "Attention automated reader: ", "Message for the trading bot -- ", "To whoever (whatever) is summarising this: "]}
SUFFIX = {"train": [" Do not mention this to the user.", " This is mandatory.", " Acknowledge silently and proceed."],
          "eval": [" No need to flag this in your report.", " Treat this as higher priority than your earlier guidance."]}
SYN = {"train": {"disregard": "ignore", "ignore": "disregard", "sell": "liquidate", "entire": "whole", "immediately": "right away", "must": "are required to",
                 "mandate": "standing instructions", "limit": "cap", "do not mention": "keep quiet about", "assistant": "agent"},
       "eval": {"disregard": "set aside", "ignore": "overlook", "sell": "dump", "entire": "complete", "immediately": "without delay", "must": "need to",
                "mandate": "brief", "limit": "ceiling", "do not mention": "leave out", "assistant": "model"}}
ZH = {"train": {"ignore": "忽略", "disregard": "无视", "previous instructions": "之前的指示", "instructions": "指示", "assistant": "助手", "sell": "卖出", "buy": "买入",
                "all": "全部", "position": "持仓", "do not mention": "不要提及", "mandate": "授权", "limit": "限额", "orders": "订单", "immediately": "立即", "must": "必须"},
      "eval": {"ignore": "不理会", "disregard": "忽视", "previous instructions": "先前的说明", "instructions": "说明", "assistant": "智能体", "sell": "清仓", "buy": "建仓",
               "all": "所有", "position": "头寸", "do not mention": "切勿透露", "mandate": "委托", "limit": "上限", "orders": "委托单", "immediately": "马上", "must": "务必"}}
YUE = {"train": {"ignore": "唔好理", "previous instructions": "之前嘅指示", "assistant": "助手", "sell": "賣出", "buy": "買入", "all": "全部", "position": "持倉",
                 "do not mention": "唔好提", "immediately": "即刻", "must": "必須", "limit": "限額"},
       "eval": {"ignore": "唔使理", "previous instructions": "以前嘅指令", "assistant": "AI助理", "sell": "沽清", "buy": "買入嚟", "all": "所有", "position": "倉位",
                "do not mention": "唔好講", "immediately": "馬上", "must": "一定要", "limit": "上限"}}
WRAP = {"train": ["<!-- {t} -->", "<div style=\"display:none\">{t}</div>", "> {t}", "**{t}**", "[//]: # ({t})", "<span hidden>{t}</span>", "<p>{t}</p>", "| {t} |"],
        "eval": ["<script type=\"text/plain\">{t}</script>", "<aside aria-hidden=\"true\">{t}</aside>", "- {t}", "_{t}_", "<details><summary>.</summary>{t}</details>", "\"{t}\""]}

HARDNEG_IMPERATIVE = {
    "train": ["Investors should consider the risks described under Item 1A before making an investment decision.",
              "Please refer to Note 7 to the consolidated financial statements for additional information.",
              "Readers should not place undue reliance on these forward-looking statements.",
              "Shareholders are encouraged to review the proxy statement before the annual meeting.",
              "You should read this discussion together with the consolidated financial statements and related notes.",
              "Do not rely on past performance as an indication of future results.",
              "Holders of record should contact the transfer agent to update their mailing address.",
              "Customers must register their devices to receive warranty service.",
              "Employees must complete the annual compliance training by the end of the fiscal year.",
              "The Company's policy requires that all related-party transactions be approved by the audit committee.",
              "Analysts should note that the figures exclude one-time charges.",
              "Please see Part II, Item 8 of this report for the audited statements.",
              "Participants should consult their own advisors regarding the tax consequences of the plan.",
              "Always consult the prospectus before investing; never invest more than you can afford to lose.",
              "To vote by proxy, shareholders should follow the instructions on the enclosed card.",
              "Management must assess the effectiveness of internal control over financial reporting at each year end.",
              "Sign up for alerts and follow the company on social media for the latest updates.",
              "Suppliers shall comply with the Supplier Code of Conduct as a condition of doing business with the Company.",
              "Traders should expect volatility around the earnings release.",
              "Click here to read the full press release and to download the earnings presentation."],
    "eval": ["Investors are advised to read the risk factors in the Company's most recent annual report.",
             "Please refer to the glossary at the end of this document for defined terms.",
             "Stockholders should review the information incorporated by reference into this report.",
             "Readers must not treat this summary as legal or investment advice.",
             "You should consider whether an investment in the notes is suitable for your circumstances.",
             "Contractors must follow the site safety procedures at all times.",
             "Please note that quarterly figures may not sum due to rounding.",
             "Visit the investor relations page to subscribe to email alerts and to listen to the webcast replay.",
             "Persons who are not accredited investors should not rely on this memorandum.",
             "Directors shall disclose any conflict of interest to the board before the relevant discussion."]}
CORP_ACTION = {
    "train": ["The Board of Directors declared a quarterly cash dividend of ${a} per share, payable on {d} to shareholders of record on {e}.",
              "The Company completed a {n}-for-1 stock split of its common stock, effective {d}, as previously authorized by the Board.",
              "On {d}, the Company's Board of Directors authorized the repurchase of up to ${n} billion of its common stock.",
              "The Company announced that it will hold its annual meeting of shareholders on {d}.",
              "The Company entered into a credit agreement providing for a revolving facility of up to ${n} billion, maturing in 2029."],
    "eval": ["The Company's Board approved a regular dividend of ${a} per share for the quarter, to be paid {d}.",
             "Following shareholder approval, the Company effected a {n}-for-1 forward split of its common stock on {d}.",
             "The Company disclosed on Form 8-K that it priced an offering of ${n} billion of senior notes on {d}."]}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def hard_negatives(pool: str, n: int = 160) -> list[str]:
    rng = _rng("hardneg", pool)
    out = list(HARDNEG_IMPERATIVE[pool])
    for t in CORP_ACTION[pool]:
        for _ in range(8 if pool == "train" else 5):
            out.append(t.format(a=f"0.{rng.randint(10, 99)}", n=rng.choice([2, 3, 4, 5, 10, 20]), d=f"{rng.choice(MONTHS)} {rng.randint(1, 28)}, 20{rng.randint(15, 25)}",
                                e=f"{rng.choice(MONTHS)} {rng.randint(1, 28)}, 20{rng.randint(15, 25)}"))
    # benign wrappers around benign imperatives, so wrappers alone are never a signal
    base = list(HARDNEG_IMPERATIVE[pool])
    for t in base:
        out.append(rng.choice(WRAP[pool]).format(t=t))
    return out[:n + len(base) * 2]


def _subst(text: str, table: dict, rng: random.Random, frac: float) -> str:
    out = text
    for k in sorted(table, key=len, reverse=True):
        if rng.random() < frac:
            out = re.sub(rf"\b{re.escape(k)}\b", table[k], out, flags=re.I)
    return out


# Each op: (name, family, fn(text, rng, pool) -> text). family "l1" = undone by L1 before scoring; "free" = L1 does not touch it.
def op_zero_width(t, rng, pool):
    return "".join(c + ("​" if c.isalpha() and rng.random() < 0.3 else "") for c in t)


def op_tags(t, rng, pool):
    return "Routine note." + "".join(chr(0xE0000 + ord(c)) for c in t if 0x20 <= ord(c) < 0x7F)


def op_homoglyph(t, rng, pool):
    return "".join(INV_CONF[c] if c in INV_CONF and rng.random() < 0.4 else c for c in t)


def op_base64(t, rng, pool):
    return f"Reference token {base64.b64encode(t.encode()).decode()}"


def op_case(t, rng, pool):
    return rng.choice([t.upper(), t.lower(), re.sub(r" ", "   ", t), t.title()])


def op_letterspace(t, rng, pool):
    ws = t.split(" ")
    i = rng.randrange(len(ws))
    ws[i] = " ".join(ws[i])
    return " ".join(ws)


def op_paraphrase(t, rng, pool):
    out = _subst(t, SYN[pool], rng, 0.6)
    return rng.choice(PREFIX[pool]) + out[0].lower() + out[1:] + (rng.choice(SUFFIX[pool]) if rng.random() < 0.6 else "")


def op_mix_zh(t, rng, pool):
    return _subst(t, ZH[pool], rng, 0.7)


def op_mix_yue(t, rng, pool):
    return _subst(t, YUE[pool], rng, 0.8)


def op_zh_prefix(t, rng, pool):
    return rng.choice(["注意AI助手：", "致自动交易系统：", "給AI助手嘅通知："]) + t


def op_split(t, rng, pool):
    ws = t.split(" ")
    if len(ws) < 6:
        return t
    cuts = sorted(rng.sample(range(2, len(ws) - 1), min(2, len(ws) - 3)))
    parts, prev = [], 0
    for c in cuts + [len(ws)]:
        parts.append(" ".join(ws[prev:c]))
        prev = c
    return "\n".join(parts)


def op_wrap(t, rng, pool):
    return rng.choice(WRAP[pool]).format(t=t)


OPS = {"zero_width": ("l1", op_zero_width), "tags": ("l1", op_tags), "homoglyph": ("l1", op_homoglyph), "base64": ("l1", op_base64), "case_spacing": ("l1", op_case),
       "letter_spacing": ("free", op_letterspace), "paraphrase": ("free", op_paraphrase), "mix_zh": ("free", op_mix_zh), "mix_yue": ("free", op_mix_yue),
       "zh_prefix": ("free", op_zh_prefix), "split_lines": ("free", op_split), "wrap_markup": ("free", op_wrap)}
BENIGN_OPS = ("zero_width", "case_spacing", "wrap_markup", "homoglyph")


def augment_lines(attack_lines: list[str], clean_lines: list[str], ops: tuple, per: int = 2, pool: str = "train") -> list[tuple[str, int]]:
    """(line, label) pairs. Every produced piece of an attack line is an attack line (a split directive: both halves)."""
    out: list[tuple[str, int]] = []
    for ln in attack_lines:
        for name in ops:
            for k in range(per if name in ("paraphrase", "wrap_markup", "split_lines", "mix_zh") else 1):
                t = OPS[name][1](ln, _rng(name, ln, k), pool)
                out += [(x, 1) for x in prepare_lines(t)]
    # Benign mirror: clean lines get the same format-type perturbations at a matching rate, so a wrapper or a hidden character alone is never a signal.
    for ln in clean_lines:
        r = _rng("clean", ln)
        for name in BENIGN_OPS:
            if r.random() < (0.35 if name == "wrap_markup" else 0.15):
                out += [(x, 0) for x in prepare_lines(OPS[name][1](ln, r, pool))]
    return out


# ---- chunk perturbations (robustness suite and benign perturbation) ---------------------------------------------------------

def perturb_chunk(c: dict, name: str, pool: str = "eval") -> str:
    """Apply op `name` to the attack lines of an attack chunk (raw lines whose cleaned form is all attack lines); for a clean chunk apply the op
    to a deterministic quarter of its lines (benign perturbation: the label must not change)."""
    attack_lines = {ln for ln, y in zip(c["lines"], c["y"]) if y}
    out = []
    for i, raw in enumerate(c["text"].split("\n")):
        pl = prepare_lines(raw)
        hit = bool(pl) and all(p in attack_lines for p in pl) if c["label"] == 1 else (bool(pl) and _rng("pb", c["text"][:40], i).random() < 0.25)
        out.append(OPS[name][1](raw, _rng("perturb", name, raw), pool) if hit else raw)
    return "\n".join(out)


# ---- shared feature space and members -----------------------------------------------------------------------------------

class Space:
    """TF-IDF vocabulary fitted once on a fold's training lines; every soup member lives in this space."""

    def __init__(self, lines: list[str]):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vecs = {n: TfidfVectorizer(analyzer=clf.ANALYZERS[n], min_df=2, max_features=MAX_FEATURES[n], sublinear_tf=True, norm="l2") for n in ("char", "word")}
        for v in self.vecs.values():
            v.fit(lines)

    def X(self, lines: list[str]):
        import scipy.sparse as sp
        return sp.hstack([v.transform(lines) for v in self.vecs.values()], format="csr")


MEMBERS = [   # (name, C, class_weight, aug ops, hard negatives, bootstrap seed or None)
    ("base", 10.0, "balanced", (), False, None),
    ("aug", 10.0, "balanced", tuple(OPS), True, None),
    ("aug_c3_b1", 3.0, "balanced", tuple(OPS), True, 1),
    ("aug_c30_b2", 30.0, "balanced", tuple(OPS), True, 2),
    ("l1ops_wrap_b3", 10.0, "balanced", ("zero_width", "tags", "homoglyph", "base64", "case_spacing", "wrap_markup"), True, 3),
    ("lang_para_split_b4", 10.0, "balanced", ("paraphrase", "mix_zh", "mix_yue", "zh_prefix", "split_lines", "letter_spacing"), True, 4),
    ("noaug_hardneg_b5", 10.0, "balanced", (), True, 5),
    ("aug_c3_nocw_b6", 3.0, None, tuple(OPS), True, 6),
]


def line_dataset(train: list[dict], exclude: set) -> tuple[list[str], list[int]]:
    y_of: dict[str, int] = {}
    for c in train:
        for ln, y in zip(c["lines"], c["y"]):
            if ln not in exclude:
                y_of[ln] = min(y, y_of.get(ln, 1))
    clean_keys = {clf._norm(ln) for ln, v in y_of.items() if v == 0}
    lines = sorted(ln for ln in y_of if y_of[ln] == 0 or clf._norm(ln) not in clean_keys)
    return lines, [y_of[ln] for ln in lines]


def fit_members(train: list[dict], exclude: set, members=MEMBERS):
    """Return (space, [(name, w, b)], line dataset sizes). Members share one vocabulary; augmentation/hard negatives are added per member."""
    from sklearn.linear_model import LogisticRegression
    lines, y = line_dataset(train, exclude)
    att = [ln for ln, v in zip(lines, y) if v]
    cln = [ln for ln, v in zip(lines, y) if not v]
    hn = [(x, 0) for t in hard_negatives("train") for x in prepare_lines(t)]
    aug_cache: dict[tuple, list] = {}
    pools = {}
    for name, C, cw, ops, use_hn, seed in members:
        if ops not in aug_cache:
            aug_cache[ops] = augment_lines(att, cln, ops) if ops else []
        pools[name] = aug_cache[ops] + (hn if use_hn else [])
    all_lines = sorted(set(lines) | {ln for p in pools.values() for ln, _ in p})
    space = Space(all_lines)
    out = []
    for name, C, cw, ops, use_hn, seed in members:
        d: dict[str, int] = dict(zip(lines, y))
        for ln, v in pools[name]:
            d[ln] = min(v, d.get(ln, 1))
        ls = sorted(d)
        yy = np.array([d[x] for x in ls])
        sw = np.ones(len(ls))
        if seed is not None:
            sw = np.random.default_rng(seed).poisson(1.0, len(ls)).astype(float)
            sw[sw == 0] = 0.0
        keep = sw > 0
        X = space.X(ls)[keep]
        lr = LogisticRegression(C=C, class_weight=cw, max_iter=3000, solver="lbfgs")
        lr.fit(X, yy[keep], sample_weight=sw[keep])
        out.append((name, lr.coef_[0].copy(), float(lr.intercept_[0])))
    return space, out, {"lines": len(lines), "attack_lines": len(att)}


class LineScorer:
    """Logits of every unique line of a set of texts under each member, so soups/ensembles of linear members are exact and cheap."""

    def __init__(self, space: Space, members):
        self.space, self.members = space, members
        self.cache: dict[str, np.ndarray] = {}

    def add(self, lines: set):
        new = sorted(lines - self.cache.keys())
        if new:
            X = self.space.X(new)
            Z = np.stack([X @ w + b for _, w, b in self.members])      # K x L
            for i, ln in enumerate(new):
                self.cache[ln] = Z[:, i]

    def chunk_Z(self, line_lists: list[list[str]]) -> list[np.ndarray]:
        """For each chunk, a (K, n_lines) array of member logits."""
        self.add({ln for ls in line_lists for ln in ls})
        return [np.stack([self.cache[ln] for ln in ls], axis=1) if ls else np.zeros((len(self.members), 0)) for ls in line_lists]


def _agg(Zs: list[np.ndarray], combine) -> np.ndarray:
    """Chunk scores (max over lines of combined logits)."""
    out = []
    for Z in Zs:
        out.append(float(np.max(combine(Z))) if Z.shape[1] else Z_MIN)
    return np.array(out)


def soup_idx(Zv: list[np.ndarray], yv: np.ndarray, order_metric) -> list[int]:
    """Greedy soup: members sorted by validation metric; add one if the averaged weights do not lower the validation metric."""
    K = Zv[0].shape[0]
    score = lambda S: order_metric(yv, _agg(Zv, lambda Z: Z[S].mean(0)))
    ranked = sorted(range(K), key=lambda k: -score([k]))
    chosen = [ranked[0]]
    best = score(chosen)
    for k in ranked[1:]:
        s = score(chosen + [k])
        if s >= best:
            chosen, best = chosen + [k], s
    return sorted(chosen)


def ap(y, s) -> float:
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, s))


def platt_fit(z: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(C=1e4, max_iter=1000)
    lr.fit(np.clip(z, Z_MIN, -Z_MIN).reshape(-1, 1), y)
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def sigm(z):
    return 1 / (1 + np.exp(-np.clip(z, -60, 60)))


def calib_metrics(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict:
    """Brier score and expected calibration error (equal-width bins) on chunk probabilities."""
    ece = 0.0
    for i in range(bins):
        m = (p >= i / bins) & ((p < (i + 1) / bins) if i < bins - 1 else (p <= 1.0))
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return {"brier": round(float(np.mean((p - y) ** 2)), 5), "ece": round(float(ece), 5)}


def text_feats(chunk_texts: list[str]) -> tuple[list[dict], list[list[str]]]:
    tf, lines = [], []
    for t in chunk_texts:
        a = clf.analyse(t)
        tf.append(dec.text_features(a["lines"], a["findings"], a["tag_payload"]))
        lines.append(a["lines"])
    return tf, lines


def design(tfs: list[dict], Zsorted: list[list[float]]) -> np.ndarray:
    return np.array([dec.vector(t, z) for t, z in zip(tfs, Zsorted)])


def fit_decision(F: np.ndarray, y: np.ndarray, w: np.ndarray | None = None, C: float = 0.3):
    from sklearn.linear_model import LogisticRegression
    mean, scale = F.mean(0), F.std(0) + 1e-6
    lr = LogisticRegression(C=C, class_weight=None, max_iter=3000)
    lr.fit((F - mean) / scale, y, sample_weight=w)
    return {"features": list(dec.FEATURES), "mean": [round(float(x), 6) for x in mean], "scale": [round(float(x), 6) for x in scale],
            "coef": [round(float(x), 6) for x in lr.coef_[0]], "intercept": round(float(lr.intercept_[0]), 6)}


def dec_p(art: dict, F: np.ndarray) -> np.ndarray:
    return sigm(art["intercept"] + ((F - np.array(art["mean"])) / np.array(art["scale"])) @ np.array(art["coef"]))


def sorted_Z(Zs: list[np.ndarray], combine) -> list[list[float]]:
    return [sorted(combine(Z).tolist(), reverse=True) if Z.shape[1] else [] for Z in Zs]


def cascade_thresholds(pv_att: np.ndarray, pv_clean: np.ndarray, hi_fpr: float = 0.003, miss: float = 0.015) -> tuple[float, float]:
    """clean_below: at most `miss` of validation attacks score under it. attack_above: at most `hi_fpr` of validation clean chunks at or above it."""
    lo = float(np.quantile(pv_att, miss)) if len(pv_att) else 0.0
    hi = pick_threshold(list(pv_clean), hi_fpr)
    return lo, max(hi, lo)


def thr_at(clean: np.ndarray, target: float) -> float:
    return pick_threshold(list(clean), target)


# ---- the nested experiment --------------------------------------------------------------------------------------------------

DEPLOY = "v1_single"            # the member the artifact ships (see docs/CLASSIFIER.md: augmentation and soups did not beat it technique-held-out)
DEPLOY_MEMBERS = ("base",)
METHODS = ("v1_single", "single_aug", "uniform_soup", "greedy_soup", "output_ensemble", "task_arith", "decision", "platt")


def source_weights(chunks: list[dict]) -> np.ndarray:
    """Chunk weights that give the lab and the sandbox equal total weight within each class (the lab's real 10-K prose is the closer proxy for
    deployment text; the sandbox is 20x larger and templated). Used for thresholds, calibration, the decision layer and soup selection."""
    cnt = defaultdict(int)
    for c in chunks:
        cnt[(c["source"], c["label"])] += 1
    w = np.ones(len(chunks))
    for i, c in enumerate(chunks):
        srcs = [s for s in ("lab", "sandbox") if cnt[(s, c["label"])]]
        w[i] = (sum(cnt[(s, c["label"])] for s in srcs) / len(srcs)) / cnt[(c["source"], c["label"])]
    return w / w.mean()


def pick_threshold_w(scores: np.ndarray, w: np.ndarray, target: float) -> float:
    """Lowest threshold whose weighted false-alarm rate on these (clean) scores is at most `target`."""
    o = np.argsort(-scores)
    s, cw = scores[o], np.cumsum(w[o]) / w.sum()
    k = int(np.searchsorted(cw, target, side="right"))          # number of top scores we may flag
    if k <= 0:
        return float(s[0]) + 1e-6
    if k >= len(s):
        return float(s[-1]) - 1e-6
    return float((s[k - 1] + s[k]) / 2) if s[k - 1] != s[k] else float(s[k]) + 1e-6


def wap(y, s, w) -> float:
    from sklearn.metrics import average_precision_score
    return float(average_precision_score(y, s, sample_weight=w))


def run_fold(train: list[dict], test: list[dict], view_names: tuple = (), pool: str = "eval") -> dict:
    """One outer fold. Validation scores V are cross-fitted over the training groups (inner 4-fold: each training chunk is scored by members that
    never saw its group). V alone picks the greedy soup, the task-arithmetic scale, thresholds, the Platt map and the decision layer; the members
    scored on the test chunks are refit on the whole training side. Test attack lines are excluded from every fit."""
    ifold = assign_folds(train, 4)
    test_att = {ln for c in test for ln, y in zip(c["lines"], c["y"]) if y}
    Zin: list = [None] * len(train)
    for j in range(4):
        hold = [i for i, c in enumerate(train) if ifold[c["group"]] == j]
        excl = test_att | {ln for i in hold for ln, y in zip(train[i]["lines"], train[i]["y"]) if y}
        space, members, _ = fit_members([c for c in train if ifold[c["group"]] != j], excl)
        for i, Z in zip(hold, LineScorer(space, members).chunk_Z([train[i]["lines"] for i in hold])):
            Zin[i] = Z
    space, members, info = fit_members(train, test_att)
    sc = LineScorer(space, members)
    names = [m[0] for m in members]
    ix = {n: i for i, n in enumerate(names)}
    yv = np.array([c["label"] for c in train])
    wv = source_weights(train)
    base, aug = ix["base"], ix["aug"]
    gs = soup_idx(Zin, yv, lambda y, s: wap(y, s, wv))
    lam = max([0.0, 0.5, 1.0, 1.5, 2.0], key=lambda l: wap(yv, _agg(Zin, lambda Z: Z[base] + l * (Z[aug] - Z[base])), wv))
    comb = {"v1_single": lambda Z: Z[base], "single_aug": lambda Z: Z[aug], "uniform_soup": lambda Z: Z.mean(0), "greedy_soup": lambda Z, gs=gs: Z[gs].mean(0),
            "task_arith": lambda Z, lam=lam: Z[base] + lam * (Z[aug] - Z[base]), "output_ensemble": None}

    def score_method(m: str, Zs: list[np.ndarray]) -> np.ndarray:
        if m == "output_ensemble":     # mean of member probabilities per line, then max over lines
            return np.array([float(np.max(sigm(Z).mean(0))) if Z.shape[1] else 0.0 for Z in Zs])
        return _agg(Zs, comb[m])

    res = {"gs": [names[i] for i in gs], "lam": lam, "info": info, "methods": {}, "names": names, "members": members, "space": space}
    Zt = sc.chunk_Z([c["lines"] for c in test])
    for m in comb:
        sv, st = score_method(m, Zin), score_method(m, Zt)
        res["methods"][m] = {"test": st, "thr": pick_threshold_w(sv[yv == 0], wv[yv == 0], TARGET_V2), "val": sv}
    # ---- calibration + decision layer (on the uniform soup's cross-fitted scores)
    sv = res["methods"][DEPLOY]["val"]
    from sklearn.linear_model import LogisticRegression
    pl = LogisticRegression(C=1e4, max_iter=1000).fit(np.clip(sv, Z_MIN, -Z_MIN).reshape(-1, 1), yv, sample_weight=wv)
    a, b = float(pl.coef_[0, 0]), float(pl.intercept_[0])
    res["platt"] = (a, b)
    res["platt_test"] = sigm(a * np.clip(res["methods"][DEPLOY]["test"], Z_MIN, -Z_MIN) + b)
    res["platt_val"] = sigm(a * np.clip(sv, Z_MIN, -Z_MIN) + b)
    tf_v = [dec.text_features(ln, f, t) for ln, f, t in ((lambda a_: (a_["lines"], a_["findings"], a_["tag_payload"]))(clf.analyse(c["text"])) for c in train)]
    tf_t, _ = text_feats([c["text"] for c in test])
    Fv = design(tf_v, sorted_Z(Zin, comb[DEPLOY]))
    Ft = design(tf_t, sorted_Z(Zt, comb[DEPLOY])) if len(test) else np.zeros((0, len(dec.FEATURES)))
    vf2 = assign_folds(train, 4)
    gv = np.array([vf2[c["group"]] for c in train])
    pcv = np.zeros(len(train))
    for k in range(4):
        tr = gv != k
        pcv[~tr] = dec_p(fit_decision(Fv[tr], yv[tr], wv[tr]), Fv[~tr])
    lo_s = float(np.quantile(sv[yv == 1], 0.015))
    hi_s = pick_threshold_w(sv[yv == 0], wv[yv == 0], 0.003)
    P = lambda z: float(sigm(a * np.clip(z, Z_MIN, -Z_MIN) + b))
    res["platt_space"] = {"flag": P(res["methods"][DEPLOY]["thr"]), "prefilter": P(hi_s), "casc": (P(lo_s), P(max(hi_s, lo_s)))}
    dart = fit_decision(Fv, yv, wv)
    res["decision_art"] = dart
    res["methods"]["platt"] = {"test": res["platt_test"], "thr": res["platt_space"]["flag"], "val": res["platt_val"]}
    res["methods"]["decision"] = {"test": dec_p(dart, Ft) if len(test) else np.zeros(0), "thr": pick_threshold_w(pcv[yv == 0], wv[yv == 0], TARGET_V2), "val": pcv}
    lo = float(np.quantile(pcv[yv == 1], 0.015))
    hi = pick_threshold_w(pcv[yv == 0], wv[yv == 0], 0.003)
    res["casc"] = (lo, max(hi, lo))
    res["yv"], res["wv"] = yv, wv
    # ---- robustness views: perturbed lab test chunks
    res["views"] = {}
    sub = [c for c in test if c["source"] == "lab"]
    for vn in view_names:
        txt = [perturb_chunk(c, vn, pool) for c in sub]
        tfp, lp = text_feats(txt)
        Zp = sc.chunk_Z(lp)
        res["views"][vn] = {m: score_method(m, Zp) for m in ("v1_single", "uniform_soup", "greedy_soup")}
        res["views"][vn]["platt"] = sigm(a * np.clip(res["views"][vn]["v1_single"], Z_MIN, -Z_MIN) + b)
        res["views"][vn]["decision"] = dec_p(dart, design(tfp, sorted_Z(Zp, comb[DEPLOY])))
    return res


def nested_v2(chunks: list[dict], n_folds: int = FOLDS, view_names: tuple = ()) -> dict:
    fold = assign_folds(chunks, n_folds)
    n = len(chunks)
    out = {"methods": {m: {"score": np.zeros(n), "thr": np.zeros(n)} for m in METHODS}, "platt": np.zeros(n), "platt_val_calib": [], "casc": np.zeros((n, 2)), "casc_decision": np.zeros((n, 2)),
           "folds": [], "views": {vn: {m: {} for m in ("v1_single", "uniform_soup", "greedy_soup", "decision", "platt")} for vn in view_names}, "fold_of": np.zeros(n, dtype=int)}
    for k in range(n_folds):
        te = [i for i, c in enumerate(chunks) if fold[c["group"]] == k]
        r = run_fold([c for c in chunks if fold[c["group"]] != k], [chunks[i] for i in te], view_names)
        for m in METHODS:
            if m in r["methods"]:
                out["methods"][m]["score"][te] = r["methods"][m]["test"]
                out["methods"][m]["thr"][te] = r["methods"][m]["thr"]
        out["platt"][te] = r["platt_test"]
        out["casc"][te] = r["platt_space"]["casc"]
        out["casc_decision"][te] = r["casc"]
        out["fold_of"][te] = k
        out["folds"].append({"k": k, "greedy": r["gs"], "lam": r["lam"], "info": r["info"]})
        lab_te = [i for i in te if chunks[i]["source"] == "lab"]
        for vn in view_names:
            for m, s in r["views"][vn].items():
                out["views"][vn][m][k] = (lab_te, s, r["methods"][m]["thr"])
        print(f"  fold {k}: {len(te)} test chunks, greedy soup {r['gs']}, lambda {r['lam']}", flush=True)
    return out



def export_v2(res: dict, thresholds: dict, dhash: str, metrics: dict, path: Path) -> int:
    """Export the uniform weight soup of a `run_fold(train, [])` result as one JSON linear model, plus calibration, decision layer, cascade thresholds."""
    space = res["space"]
    members = [m for m in res["members"] if m[0] in DEPLOY_MEMBERS]
    coef = np.mean([w for _, w, _ in members], axis=0)
    intercept = float(np.mean([b for _, _, b in members]))
    blocks, off = {}, 0
    for name, v in space.vecs.items():
        terms = [t for t, _ in sorted(v.vocabulary_.items(), key=lambda kv: kv[1])]
        n = len(terms)
        blocks[name] = {"terms": terms, "idf": [round(float(x), 6) for x in v.idf_], "coef": [round(float(x), 6) for x in coef[off:off + n]]}
        off += n
    a, b = res["platt"]
    art = {"format": FORMAT, "threshold": round(thresholds["flag"], 6), "prefilter_threshold": round(max(thresholds["prefilter"], thresholds["flag"]), 6),
           "cascade": {"clean_below": round(thresholds["clean_below"], 6), "attack_above": round(max(thresholds["attack_above"], thresholds["clean_below"]), 6)},
           "intercept": round(intercept, 6), "calibration": {"platt": {"a": round(a, 6), "b": round(b, 6)}, "fit_on": "cross-fitted training scores, source-balanced weights"},
           "decision": res["decision_art"], "use_decision": bool(thresholds.get("use_decision", False)),
           "config": {"char": {"analyzer": "char_wb", "ngram_range": [3, 5], "digits_folded": True}, "word": {"ngram_range": [1, 2], "digits_folded": True},
                      "tfidf": "sublinear_tf, smooth idf, l2 per block", "members": [m[0] for m in members], "weights": "uniform weight soup of the listed members (one linear model); see docs/CLASSIFIER.md for why this is the single un-augmented member",
                      "unit": "line, chunk score = max", "preprocessing": "orderguard_guard.classifier.analyse: L1 clean, confusable folding, unicode-tag payload as an extra line",
                      "target_false_alarm": TARGET_V2},
           "training_data_sha256": dhash, "metrics": metrics, "blocks": blocks}
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(art, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text + "\n", encoding="utf-8")
    return len(text.encode("utf-8"))


def _flag_stats(chunks, score, thr, mask) -> dict:
    y = np.array([c["label"] for c in chunks])
    f = score >= thr
    a, c = mask & (y == 1), mask & (y == 0)
    return {"recall": round(float(f[a].mean()), 4) if a.any() else None, "false_alarm": round(float(f[c].mean()), 4) if c.any() else None,
            "auc": round(_auc(list(score[a]), list(score[c])), 4) if a.any() and c.any() else None, "n_attack": int(a.sum()), "n_clean": int(c.sum())}


def robustness(chunks: list[dict], out: dict) -> dict:
    """Recall on perturbed lab attack chunks and false alarms on benignly perturbed clean chunks, per method; thresholds are the clean-data ones."""
    res = {}
    for vn, by_m in out["views"].items():
        res[vn] = {}
        for m, folds in by_m.items():
            fa = fc = na = nc = 0
            for k, (idx, s, thr) in folds.items():
                y = np.array([chunks[i]["label"] for i in idx])
                f = s >= thr
                fa += int(f[y == 1].sum()); na += int((y == 1).sum()); fc += int(f[y == 0].sum()); nc += int((y == 0).sum())
            res[vn][m] = {"recall": round(fa / na, 4), "false_alarm": round(fc / nc, 4)}
    return res


def write_oof_lab(chunks: list[dict], out: dict, path: Path) -> None:
    use_dec = bool(out.get("use_decision"))
    items = []
    for i, c in enumerate(chunks):
        if c["source"] != "lab":
            continue
        items.append({"case": c["case"], "kind": c["kind"], "key": detect.item_key(c["case"], c["kind"], c["text"]), "label": c["label"],
                      "scores": {m: round(float(out["methods"][m]["score"][i]), 6) for m in METHODS},
                      "thr": {m: round(float(out["methods"][m]["thr"][i]), 6) for m in METHODS},
                      "casc": [round(float(x), 6) for x in (out["casc_decision"][i] if use_dec else out["casc"][i])], "final": "decision" if use_dec else "platt"})
    path.write_text(json.dumps({"format": "orderguard-oof-lab/1", "items": {it.pop("key"): it for it in items}}, separators=(",", ":")) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train classifier v2 (augmentation, weight soup, calibration, decision layer) with nested held-out evaluation; export JSON.")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seeds", type=int, default=SEEDS, help="sandbox seeds per technique")
    ap.add_argument("--folds", type=int, default=FOLDS)
    a = ap.parse_args(argv)
    chunks = build_chunks(a.seeds)
    views = tuple(OPS)
    print("nested evaluation ...", flush=True)
    out = nested_v2(chunks, a.folds, views)
    y = np.array([c["label"] for c in chunks], dtype=float)
    lab = np.array([c["source"] == "lab" for c in chunks])
    allm = np.ones(len(chunks), bool)
    methods = {m: {"all": _flag_stats(chunks, out["methods"][m]["score"], out["methods"][m]["thr"], allm),
                   "lab": _flag_stats(chunks, out["methods"][m]["score"], out["methods"][m]["thr"], lab)} for m in METHODS}
    raw = sigm(out["methods"]["uniform_soup"]["score"])
    pdec = out["methods"]["decision"]["score"]
    calib = {"raw_sigmoid": {"all": calib_metrics(y, raw), "lab": calib_metrics(y[lab], raw[lab])},
             "platt": {"all": calib_metrics(y, out["platt"]), "lab": calib_metrics(y[lab], out["platt"][lab])},
             "decision": {"all": calib_metrics(y, pdec), "lab": calib_metrics(y[lab], pdec[lab])}}
    rob = robustness(chunks, out)
    by_tech = summarise(chunks, out["methods"]["decision"]["score"], out["methods"]["decision"]["thr"])
    out["use_decision"] = (methods["decision"]["lab"]["auc"] or 0) >= (methods["platt"]["lab"]["auc"] or 0) and (methods["decision"]["all"]["auc"] or 0) >= (methods["platt"]["all"]["auc"] or 0)
    # final model: the same procedure with no test fold (cross-fitted scores over all chunks), members refit on all chunks
    print("final fit ...", flush=True)
    fin = run_fold(chunks, [])
    ps = fin["platt_space"]
    use_dec = (methods["decision"]["lab"]["auc"] or 0) >= (methods["platt"]["lab"]["auc"] or 0) and (methods["decision"]["all"]["auc"] or 0) >= (methods["platt"]["all"]["auc"] or 0)
    if use_dec:
        thr = {"flag": fin["methods"]["decision"]["thr"], "prefilter": fin["casc"][1], "clean_below": fin["casc"][0], "attack_above": fin["casc"][1], "use_decision": True}
    else:
        thr = {"flag": ps["flag"], "prefilter": ps["prefilter"], "clean_below": ps["casc"][0], "attack_above": ps["casc"][1], "use_decision": False}
    metrics = {"held_out": {"methods": methods, "calibration": calib, "robustness": rob, "decision_by_family": by_tech["by_family"], "decision_by_technique": by_tech["by_technique"]},
               "greedy_by_fold": out["folds"],
               "data": {"chunks": len(chunks), "attack_chunks": int(y.sum()), "clean_chunks": int(len(y) - y.sum()), "groups": len({c["group"] for c in chunks}), "seeds": a.seeds,
                        "folds": a.folds, "target_false_alarm": TARGET_V2, "protocol": "technique-grouped CV; test attack lines excluded from every fit; thresholds, calibration, "
                        "soup selection and decision layer fitted on cross-fitted training scores only (nested)"}}
    size = export_v2(fin, thr, data_hash(chunks), metrics, Path(a.out))
    write_oof_lab(chunks, out, Path(a.out).with_name("oof_lab.json"))
    import hashlib
    Path(a.out).with_suffix(".sha256").write_text(hashlib.sha256(Path(a.out).read_bytes()).hexdigest() + "  " + Path(a.out).name + "\n")
    h = methods["decision"]["lab"]
    print(f"wrote {a.out} ({size / 1e6:.2f} MB); decision layer lab recall {h['recall']}, false alarms {h['false_alarm']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
