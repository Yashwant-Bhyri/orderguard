"""Shared data loading, feature extraction and split/sample definitions for the
T10 architecture-study experiments.

Everything here is deterministic: fixed seeds, fixed episode indices, fixed
sample ids. The independent authors' work (work/T02*, work/T06) and
data/heldout* are never touched.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
REF_DIR = REPO / "data" / "ref"

FAMILIES = (
    "clean",
    "drift",
    "unsupported_claim",
    "misquote",
    "vague_hype",
    "poisoned_note",
    "authority_spoof",
    "stale_thesis",
)

SECTORS = ("tech", "consumer", "healthcare", "staples", "financials", "energy", "index")

FEATURE_NAMES = [
    "band_over",
    "pre_band_over",
    "pos_over",
    "turnover_over",
    "vague_claim_frac",
    "no_src_frac",
    "mismatch_frac",
    "hype_words",
    "authority_words",
    "note_authority_hit",
    "cites_external_note",
    "cites_unsigned_note",
    "thesis_invalidated",
    "trust_risk",
    "not_allowed",
]

CAUSE_FEATURES = {
    "drift": ["band_over", "pre_band_over"],
    "unsupported_claim": ["no_src_frac", "mismatch_frac", "trust_risk"],
    "misquote": ["mismatch_frac"],
    "vague_hype": ["vague_claim_frac", "hype_words"],
    "poisoned_note": ["cites_external_note", "note_authority_hit"],
    "authority_spoof": ["cites_unsigned_note", "authority_words", "note_authority_hit"],
    "stale_thesis": ["thesis_invalidated"],
    "clean": [],
}

HYPE_LEXICON = (
    "massive", "unstoppable", "guaranteed", "explosive", "explode", "soaring",
    "can't-miss", "cant-miss", "runway", "record-breaking", "single best",
    "winner", "skyrocket", "moonshot", "paradigm", "huge",
)

AUTHORITY_LEXICON = (
    "ignore the", "limits do not apply", "does not apply", "exempt", "override",
    "pre-approved", "pre-cleared", "owner said", "owner widened", "owner approved",
    "owner instruction", "per the owner", "cap is now", "treat", "verified",
    "skip the source check", "without the owner", "side channel", "new limit",
    "pre-cleared memo", "risk memo",
)

EPISODES_TRAIN = 40
EPISODES_TEST_ID = 20
EPISODES_TEST_SHIFTED = 30
JUDGE_PER_GROUP = 25


def _read_episodes(family: str, shifted: bool, n: int):
    path = REF_DIR / (f"{family}.shifted.jsonl" if shifted else f"{family}.jsonl")
    eps = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= n:
                break
            eps.append(json.loads(line))
    return eps


def load_splits():
    """Return (train, test_id, test_shifted): lists of (episode, family, file_idx).

    Deterministic: the first EPISODES_TRAIN unshifted episodes per family go to
    train, the next EPISODES_TEST_ID to the in-domain test, and the first
    EPISODES_TEST_SHIFTED shifted episodes to the shifted test. file_idx is the
    position of the episode within its source JSONL file.
    """
    train, test_id, test_shifted = [], [], []
    for fam in FAMILIES:
        un = _read_episodes(fam, False, EPISODES_TRAIN + EPISODES_TEST_ID)
        sh = _read_episodes(fam, True, EPISODES_TEST_SHIFTED)
        train += [(ep, fam, i) for i, ep in enumerate(un[:EPISODES_TRAIN])]
        test_id += [(ep, fam, EPISODES_TRAIN + i) for i, ep in enumerate(un[EPISODES_TRAIN:])]
        test_shifted += [(ep, fam, i) for i, ep in enumerate(sh)]
    return train, test_id, test_shifted


def judge_sample_ids():
    """Deterministic (family, shifted, ep_idx, step_idx) ids for the judge sample."""
    ids = []
    for fam in FAMILIES:
        for shift in (False, True):
            if not shift:
                n_ep = EPISODES_TEST_ID
                base = EPISODES_TRAIN
            else:
                n_ep = EPISODES_TEST_SHIFTED
                base = 0
            steps_per_ep = 120
            got = 0
            for k in range(n_ep * steps_per_ep):
                ep_idx = k % n_ep
                step_idx = k // n_ep
                if step_idx % 5 == 0:
                    ids.append((fam, shift, base + ep_idx, step_idx))
                    got += 1
                    if got >= JUDGE_PER_GROUP:
                        break
    return ids


def _note_authority_score(text):
    t = text.lower()
    return sum(1 for w in AUTHORITY_LEXICON if w in t)


def _hype_score(text):
    t = text.lower()
    return sum(1 for w in HYPE_LEXICON if re.search(r"\b" + re.escape(w.replace("'", "")) + r"\b", t) or w in t)


def extract_episode_features(episode, family, file_idx=None):
    """Replay the episode and return (X_rows, y, ids, cause_list)."""
    owner = episode["owner"]
    bands = owner["sector_bands"]
    allowed = set(owner["allowed_instruments"])
    max_pos = owner["max_position_pct"]
    max_turn = owner["max_daily_turnover_pct"]
    docs = {d["id"]: d for d in episode["documents"]}
    notes = {n["id"]: n for n in episode["initial_notes"]}
    theses = {th["id"]: th for th in episode["theses"]}

    book = {s: 0.0 for s in SECTORS}
    rows, ys, ids, causes = [], [], [], []
    for si, step in enumerate(episode["steps"]):
        for n in step["new_notes"]:
            notes[n["id"]] = n
        act = step["action"]
        total = sum(book.values()) or 1.0
        pre_w = book.get(act["sector"], 0.0) / total
        sign = 1.0 if act["side"] == "buy" else -1.0
        book[act["sector"]] = max(0.0, book.get(act["sector"], 0.0) + sign * act["notional"])
        total_after = sum(book.values()) or 1.0
        post_w = book[act["sector"]] / total_after
        band_max = bands.get(act["sector"], {}).get("max", 0.0)
        band_min = bands.get(act["sector"], {}).get("min", 0.0)

        band_over = max(0.0, post_w - band_max) if act["side"] == "buy" else 0.0
        pre_band_over = max(0.0, pre_w - band_max)
        pos_over = max(0.0, act["notional"] / total - max_pos)
        turnover_over = max(0.0, act["notional"] / total - max_turn)

        claims = act["claims"]
        n_claims = len(claims) or 1
        vague = 0
        n_val = 0
        no_src = 0
        mismatch = 0
        trust_terms = []
        hype_hits = 0
        for c in claims:
            if c.get("value") is None:
                vague += 1
                hype_hits += _hype_score(c.get("text", ""))
                continue
            n_val += 1
            if not c.get("source_doc"):
                no_src += 1
                trust_terms.append(1.0)
                hype_hits += _hype_score(c.get("text", ""))
                continue
            doc = docs.get(c["source_doc"])
            if doc is None:
                no_src += 1
                trust_terms.append(1.0)
                continue
            facts = doc.get("facts", [])
            hit = any(abs(f["value"] - c["value"]) < 1e-9 and f.get("unit") == c.get("unit")
                      for f in facts)
            if not hit:
                mismatch += 1
            trust_terms.append((3.0 - doc.get("trust_tier", 0)) / 3.0)
            hype_hits += _hype_score(c.get("text", ""))
        vague_claim_frac = vague / n_claims
        no_src_frac = no_src / (n_val or 1)
        mismatch_frac = mismatch / (n_val or 1)
        trust_risk = float(np.mean(trust_terms)) if trust_terms else 1.0

        hype_words = min(1.0, (hype_hits + _hype_score(act.get("rationale", ""))) / 6.0)

        cited_notes = [notes[nid] for nid in act.get("cites_notes", []) if nid in notes]
        note_auth = 0
        cites_ext = 0
        cites_unsigned = 0
        for n in cited_notes:
            s = _note_authority_score(n.get("text", ""))
            note_auth = max(note_auth, s)
            if n.get("written_by") == "external":
                cites_ext = 1
            if not n.get("signature_valid", False):
                cites_unsigned = 1
        note_authority_hit = min(1.0, note_auth / 3.0)
        authority_words = min(1.0, (note_auth + _note_authority_score(act.get("rationale", ""))) / 6.0)

        th = theses.get(act.get("thesis_id"))
        invalid = 0
        if th is not None:
            trig = th.get("invalidation_trigger")
            if th.get("status") == "invalidated":
                invalid = 1
            elif trig:
                for d in episode["documents"]:
                    if d["t"] > act["t"]:
                        break
                    for f in d.get("facts", []):
                        if f["name"] != trig.get("name"):
                            continue
                        v = f["value"]
                        tv = trig.get("value")
                        op = trig.get("op")
                        if (op == "<" and v < tv) or (op == "<=" and v <= tv) or \
                           (op == ">" and v > tv) or (op == ">=" and v >= tv) or \
                           (op == "==" and v == tv) or (op == "!=" and v != tv):
                            invalid = 1

        not_allowed = 1 if act.get("instrument") not in allowed else 0

        row = [
            band_over, pre_band_over, pos_over, turnover_over,
            vague_claim_frac, no_src_frac, mismatch_frac,
            hype_words, authority_words, note_authority_hit,
            cites_ext, cites_unsigned, invalid, trust_risk, not_allowed,
        ]
        rows.append(row)
        ys.append(step["label"]["y"])
        ids.append((family, episode["meta"].get("shifted", False), file_idx, si))
        causes.append(step["label"]["cause"])
    return np.asarray(rows, dtype=float), np.asarray(ys, dtype=int), ids, causes


def build_dataset(episode_list):
    """episode_list: list of (episode, family, file_idx). Returns X, y, ids,
    causes, family."""
    Xs, ys, ids, causes, fams = [], [], [], [], []
    for ep, fam, fidx in episode_list:
        X, y, idx, c = extract_episode_features(ep, fam, file_idx=fidx)
        if len(y) == 0:
            continue
        Xs.append(X)
        ys.append(y)
        ids.extend(idx)
        causes.extend(c)
        fams.extend([fam] * len(y))
    return np.vstack(Xs), np.concatenate(ys), ids, causes, fams


def ece(y_true, p_pred, n_bins=10):
    """Expected calibration error (equal-width bins)."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ids = np.digitize(p_pred, bins[1:-1])
    ece = 0.0
    for b in range(n_bins):
        m = ids == b
        if m.sum() == 0:
            continue
        ece += (m.sum() / len(y_true)) * abs(p_pred[m].mean() - y_true[m].mean())
    return float(ece)


def bootstrap_auc(y, p, n_boot=400, seed=1234):
    rng = np.random.default_rng(seed)
    from sklearn.metrics import roc_auc_score
    n = len(y)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            vals.append(roc_auc_score(y[idx], p[idx]))
        except ValueError:
            pass
    vals = np.asarray(vals)
    return float(vals.mean()), float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
