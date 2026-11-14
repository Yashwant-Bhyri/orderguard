"""`og-review`: the escalation lane from the command line.

    og-review triage --stream results/arena/arena-s7-k1000-t2000.jsonl [--workers 6] [--floor 3e-4] [--out results/review/triage.json]
    og-review draft  --parent demo|configured|<signed mandate.json> --draft <draft.json> --purpose "rebalance into index ETFs" [--key signing.pub]
    og-review drafts [--out results/review/copilot.json]        measure the copilot on the labelled draft set
    og-review scope  [--out results/review/scope.json]          measure the scope check on the labelled order and intent set

Model calls follow OG_LLM (replay by default under CI; record replays a saved answer or makes a live call and saves it) and OG_BUDGET_USD.
Advice is advisory: any model failure prints "no advice" and nothing else changes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "review"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


def cmd_triage(a) -> int:
    from orderguard_guard.decisions import Decisions
    from . import advice as A
    from .study import FLOOR, STREAM, run_study
    res = run_study(Path(a.stream or STREAM), decisions=Decisions(A.model_name()), floor=a.floor if a.floor is not None else FLOOR, workers=a.workers, limit=a.limit)
    out = Path(a.out) if a.out else RESULTS / "triage.json"
    if res["jev_calls"].get("live_latency_ms"):
        _write(RESULTS / "jev_latency.json", res["jev_calls"]["live_latency_ms"])
    lat = RESULTS / "jev_latency.json"
    if lat.exists():
        res["jev_calls"]["live_latency_ms"] = json.loads(lat.read_text())
    _write(out, res)
    print(f"calls {res['jev_calls']['calls']}  no advice {res['jev_calls']['no_advice']}  recorded cost US${res['jev_cost']['cost_usd']}")
    for name, q in res["queues"].items():
        k = str(q["headline_k"])
        row = {o: q["caught_by_k"][o][k]["bad_usd_caught_share"] for o in ("fifo", "notional", "model", "jev", "jev+model")}
        print(f"{name:10s} queue {q['orders']:5d} orders ({q['honest_orders']} honest), K={k}/hour: bad $ caught " + "  ".join(f"{o} {v:.1%}" if v is not None else f"{o} -" for o, v in row.items()))
    return 0


def _load_parent(parent: str, key: str | None):
    from orderguard_arena.policy_review import load_parent
    from orderguard_guard.gate import public_key_from_b64
    if parent in ("demo", "configured"):
        return load_parent(parent)
    p = Path(parent)
    mandate = json.loads(p.read_text(encoding="utf-8"))
    kp = Path(key) if key else p.with_name("signing.pub")
    return mandate, public_key_from_b64(kp.read_text(encoding="utf-8").strip()), ()


def cmd_draft(a) -> int:
    from .copilot import review_draft
    try:
        parent, pub, revoked = _load_parent(a.parent, a.key)
        draft = json.loads(Path(a.draft).read_text(encoding="utf-8"))
        res = review_draft(parent, draft, a.purpose, trusted_key=pub, revoked=revoked)
    except (OSError, ValueError, KeyError) as e:
        print(f"og-review: error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=1, sort_keys=True))
    return 0 if res["fits"] else 1


def cmd_drafts(a) -> int:
    from .evaluate import evaluate_drafts
    res = evaluate_drafts(workers=a.workers)
    _write(Path(a.out) if a.out else RESULTS / "copilot.json", res)
    print(json.dumps({k: res[k] for k in ("n", "auc", "signal_auc", "baseline_breadth_auc", "calibration", "recall_by_category", "flag_rate_on_appropriate", "no_advice")}, indent=1))
    return 0


def cmd_scope(a) -> int:
    from .evaluate import evaluate_scope
    res = evaluate_scope(workers=a.workers)
    _write(Path(a.out) if a.out else RESULTS / "scope.json", res)
    print(json.dumps({k: res[k] for k in ("n", "auc", "accuracy", "no_advice")}, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="og-review", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("triage", help="replay an arena stream: review-queue outcome under FIFO, model-only and typed triage")
    p.add_argument("--stream")
    p.add_argument("--floor", type=float, default=None, help="lowest model risk that enters the larger queues (default 3e-4)")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_triage)
    p = sub.add_parser("draft", help="review one unsigned draft against a signed parent and a stated purpose")
    p.add_argument("--parent", required=True, help="demo, configured, or the path of a signed mandate file")
    p.add_argument("--key", help="pinned public key file for a parent path (default: signing.pub beside it)")
    p.add_argument("--draft", required=True, help="path of the unsigned draft JSON")
    p.add_argument("--purpose", required=True)
    p.set_defaults(fn=cmd_draft)
    p = sub.add_parser("drafts", help="measure the copilot on the labelled draft set")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_drafts)
    p = sub.add_parser("scope", help="measure the scope check on the labelled set")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_scope)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
