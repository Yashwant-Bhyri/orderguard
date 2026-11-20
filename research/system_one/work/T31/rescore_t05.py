"""Re-score T05's registered readers with incoherent v2 negatives removed.

Uses T05's own sampler and scorer functions (imported, never edited), so the
baseline reproduces its sample and metric definitions.  Every y=0 action with
a coherence finding is dropped from the negative set by setting its score to
NaN; positives are untouched.  The external decision model is read from T05's
on-disk cache only: if any key is missing this script skips it rather than
making a network call.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1.coherence import (  # noqa: E402
    build_context,
    case_for_step,
    coherence,
    finding_kinds,
)

BRIEF_THREE = ("rationale_direction", "rationale_foreign_instrument", "claim_not_about_trade")
from og_s1.readers import decision  # noqa: E402
from og_s1.schema import Episode  # noqa: E402

EVALUATE_PATH = ROOT / "work" / "T05" / "evaluate.py"


def _load_t05():
    spec = importlib.util.spec_from_file_location("t05_evaluate_for_t31", EVALUATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "ref"))
    parser.add_argument("--episodes-per-file", type=int, default=30)
    parser.add_argument("--actions-per-episode", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261119)
    parser.add_argument(
        "--readers",
        default="lexicon,nli,embed_lr,injection,injection_fmops,decision",
        help="comma-separated registered readers to re-score",
    )
    parser.add_argument("--cache", default=str(ROOT / "work" / "T31" / "t05_scores.npz"),
                        help="score cache; delete to force a full re-score")
    args = parser.parse_args()

    t05 = _load_t05()
    data_dir = Path(args.data_dir)
    records = []
    incoherent = []
    brief_incoherent = []
    episodes: dict[str, dict[int, Episode]] = {}
    contexts = {}
    for shifted in (False, True):
        suffix = ".shifted" if shifted else ""
        for family in t05.FAMILIES:
            path = data_dir / f"{family}{suffix}.jsonl"
            sample = t05._sample_file(path, args.episodes_per_file, args.actions_per_episode, args.seed)
            key = path.name
            if key not in episodes:
                loaded = {}
                with path.open("r", encoding="utf-8") as handle:
                    for ordinal, line in enumerate(handle):
                        line = line.strip()
                        if line:
                            loaded[ordinal] = Episode.from_dict(json.loads(line))
                episodes[key] = loaded
            for record in sample:
                ordinal = int(record["episode_key"].rsplit(":", 1)[1])
                episode = episodes[key][ordinal]
                ctx_key = (key, ordinal)
                if ctx_key not in contexts:
                    contexts[ctx_key] = build_context(episode)
                i = record["action_index"]
                findings = coherence(
                    episode.steps[i].action,
                    case_for_step(episode, i, context=contexts[ctx_key]),
                )
                record["findings"] = finding_kinds(findings)
                records.append(record)
                incoherent.append(record["y"] == 0 and bool(findings))
                brief_incoherent.append(
                    record["y"] == 0 and bool(set(record["findings"]) & set(BRIEF_THREE))
                )

    incoh_mask = np.asarray(incoherent, dtype=bool)
    brief3_mask = np.asarray(brief_incoherent, dtype=bool)
    print(f"eval actions: {len(records)} from {len({r['episode_key'] for r in records})} episodes")
    print(f"incoherent y=0 actions removed (any finding): {int(incoh_mask.sum())}")
    print(f"incoherent y=0 actions removed (brief three): {int(brief3_mask.sum())}")
    print("removed by family,shift:")
    counts = {}
    for record, drop in zip(records, incoh_mask):
        if drop:
            key = (record["family"], bool(record["shifted"]))
            counts[key] = counts.get(key, 0) + 1
    for shifted in (False, True):
        for family in t05.FAMILIES:
            print(f"  {family},{'shifted' if shifted else 'unshifted'}: {counts.get((family, shifted), 0)}")

    device = t05.nli.default_device()
    print(f"device: {device}")
    readers = [r.strip() for r in args.readers.split(",") if r.strip()]
    scores = {}
    cache_path = Path(args.cache)
    cache_meta_path = cache_path.with_suffix(".json")
    fingerprint = json.dumps({
        "data_dir": str(Path(args.data_dir).resolve().relative_to(ROOT)),
        "episodes_per_file": args.episodes_per_file,
        "actions_per_episode": args.actions_per_episode,
        "seed": args.seed,
        "readers": readers,
    }, sort_keys=True)
    if cache_path.exists() and cache_meta_path.exists():
        try:
            meta = json.loads(cache_meta_path.read_text(encoding="utf-8"))
            if meta.get("fingerprint") == fingerprint:
                with np.load(cache_path) as saved:
                    scores = {r: saved[r] for r in readers if r in saved.files}
                print(f"loaded score cache: {cache_path.name}")
        except Exception:
            scores = {}
    for reader in readers:
        if reader in scores:
            print(f"{reader}: cached score")
            continue
        if reader == "decision":
            items = [r["decision_item"] for r in records]
            keys = [decision.request_key(decision.request_body(it)) for it in items]
            cache = decision._load_cache()
            missing = [k for k in keys if k not in cache]
            if missing:
                print(f"decision: SKIPPED, {len(missing)} of {len(keys)} response keys missing from cache")
                continue
            try:
                matrix = decision.score(items, workers=4)
                scores[reader] = matrix
                print("decision: scored from cache (no network call)")
            except Exception as exc:  # pragma: no cover - cache path only
                print(f"decision: SKIPPED ({type(exc).__name__}: {exc})")
            continue
        try:
            matrix, _times = t05._score_local(reader, records, device)
            scores[reader] = matrix
            print(f"{reader}: scored")
        except Exception as exc:
            print(f"{reader}: SKIPPED ({type(exc).__name__}: {exc})")

    if scores and not (cache_path.exists() and cache_meta_path.exists()
                       and json.loads(cache_meta_path.read_text(encoding="utf-8")).get("fingerprint") == fingerprint):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache_path, **scores)
        cache_meta_path.write_text(json.dumps({"fingerprint": fingerprint}, sort_keys=True), encoding="utf-8")
        print(f"saved score cache: {cache_path.name}")

    print("\n== T05 AUROC with incoherent negatives removed ==")
    print("feature,reader,baseline_auroc,filtered_any,delta_any,filtered_brief3,delta_brief3,"
          "n_pos,n_neg_baseline,n_removed_any,n_removed_brief3")
    summary = {}
    for feature in t05.text.FEATURES:
        col = t05.text.FEATURES.index(feature)
        y = np.asarray([t05._feature_target(r, feature) for r in records], dtype=int)
        for reader, matrix in scores.items():
            s = np.asarray(matrix[:, col], dtype=float)
            keep = (y >= 0) & np.isfinite(s)
            base = float(t05.auroc(y[keep], s[keep])) if keep.any() else float("nan")
            masked_any = s.copy()
            masked_any[incoh_mask] = np.nan
            keep_any = (y >= 0) & np.isfinite(masked_any)
            any_auroc = float(t05.auroc(y[keep_any], masked_any[keep_any])) if keep_any.any() else float("nan")
            masked_b3 = s.copy()
            masked_b3[brief3_mask] = np.nan
            keep_b3 = (y >= 0) & np.isfinite(masked_b3)
            b3_auroc = float(t05.auroc(y[keep_b3], masked_b3[keep_b3])) if keep_b3.any() else float("nan")
            print(
                f"{feature},{reader},{base:.4f},{any_auroc:.4f},{any_auroc - base:+.4f},"
                f"{b3_auroc:.4f},{b3_auroc - base:+.4f},"
                f"{int((keep & (y == 1)).sum())},{int((keep & (y == 0)).sum())},"
                f"{int((incoh_mask & keep).sum())},{int((brief3_mask & keep).sum())}"
            )
            summary[(feature, reader)] = (base, any_auroc, b3_auroc)
    print("\n== all registered readers, shifted only ==")
    print("feature,reader,baseline,filtered_any,delta_any,filtered_brief3,delta_brief3,n_pos,n_neg")
    shifted_idx = np.asarray([r["shifted"] for r in records], dtype=bool)
    for feature in t05.text.FEATURES:
        y = np.asarray([t05._feature_target(r, feature) for r in records], dtype=int)
        for reader, matrix in scores.items():
            s = np.asarray(matrix[:, t05.text.FEATURES.index(feature)], dtype=float)
            masked_any = s.copy()
            masked_any[incoh_mask] = np.nan
            masked_b3 = s.copy()
            masked_b3[brief3_mask] = np.nan
            base_keep = shifted_idx & (y >= 0) & np.isfinite(s)
            keep_any = shifted_idx & (y >= 0) & np.isfinite(masked_any)
            keep_b3 = shifted_idx & (y >= 0) & np.isfinite(masked_b3)
            if not base_keep.any():
                continue
            base = float(t05.auroc(y[base_keep], s[base_keep]))
            any_v = float(t05.auroc(y[keep_any], masked_any[keep_any])) if keep_any.any() else float("nan")
            b3_v = float(t05.auroc(y[keep_b3], masked_b3[keep_b3])) if keep_b3.any() else float("nan")
            print(
                f"{feature},{reader},{base:.4f},{any_v:.4f},{any_v - base:+.4f},"
                f"{b3_v:.4f},{b3_v - base:+.4f},"
                f"{int((base_keep & (y == 1)).sum())},{int((base_keep & (y == 0)).sum())}"
            )

    print("\n== selected and best readers (shifted) ==")
    print("feature,reader,role,baseline_auroc,filtered_any,delta_any,filtered_brief3,delta_brief3")
    for feature in t05.text.FEATURES:
        shifted_idx = np.asarray([r["shifted"] for r in records], dtype=bool)
        y = np.asarray([t05._feature_target(r, feature) for r in records], dtype=int)
        best = None
        for reader, matrix in scores.items():
            s = np.asarray(matrix[:, t05.text.FEATURES.index(feature)], dtype=float)
            masked = s.copy()
            masked[incoh_mask] = np.nan
            keep = shifted_idx & (y >= 0) & np.isfinite(masked)
            base_keep = shifted_idx & (y >= 0) & np.isfinite(s)
            if not keep.any() or not base_keep.any():
                continue
            base = float(t05.auroc(y[base_keep], s[base_keep]))
            filt = float(t05.auroc(y[keep], masked[keep]))
            if best is None or filt > best[2]:
                best = (reader, base, filt)
        selected = t05.text.DEFAULT_READERS[feature]
        for role, reader in (("selected", selected), ("best", best[0] if best else "-")):
            if reader not in scores:
                continue
            s = np.asarray(scores[reader][:, t05.text.FEATURES.index(feature)], dtype=float)
            masked_any = s.copy()
            masked_any[incoh_mask] = np.nan
            masked_b3 = s.copy()
            masked_b3[brief3_mask] = np.nan
            keep_any = shifted_idx & (y >= 0) & np.isfinite(masked_any)
            keep_b3 = shifted_idx & (y >= 0) & np.isfinite(masked_b3)
            base_keep = shifted_idx & (y >= 0) & np.isfinite(s)
            base = float(t05.auroc(y[base_keep], s[base_keep])) if base_keep.any() else float("nan")
            any_v = float(t05.auroc(y[keep_any], masked_any[keep_any])) if keep_any.any() else float("nan")
            b3_v = float(t05.auroc(y[keep_b3], masked_b3[keep_b3])) if keep_b3.any() else float("nan")
            print(
                f"{feature},{reader},{role},{base:.4f},{any_v:.4f},{any_v - base:+.4f},"
                f"{b3_v:.4f},{b3_v - base:+.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
