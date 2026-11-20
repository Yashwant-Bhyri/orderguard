"""Fill the T20 caches from OpenRouter: the model catalog and 4 x 200 answers.

This is the only script in the task folder that touches the network.  It reads
``OPENROUTER_API_KEY`` by name, never prints it, and refuses to continue once
the cache spend passes the brief's $5 cap.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from og_s1 import triage  # noqa: E402

MODELS = [
    "typesafe/jev-1.14",
    "cloudflare/clef-flash",
    "liquid/d1.2-ultra",
    "perplexity/pplx-decider-v1.3:free",
]
CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=decisions"
# Both cache files count against one $5 budget.  Earlier rounds checked each
# file separately, so two refreshes could each pass while the lifetime total
# did not.
CACHE_FILES = (
    ROOT / "work" / "T20" / "cache" / "triage_responses.jsonl",
    ROOT / "work" / "T20" / "cache" / "triage_blind.jsonl",
)


def combined_spend(cache_path: Path) -> float:
    """Provider-reported spend in every known cache, counting ``cache_path`` once."""
    resolved = cache_path.resolve()
    total = 0.0
    seen: set[Path] = set()
    for path in (*CACHE_FILES, cache_path):
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        if key.exists():
            total += triage.cache_cost(key)
    return total


def other_cache_spend(cache_path: Path) -> float:
    """Spend in the known caches other than ``cache_path``."""
    resolved = cache_path.resolve()
    total = 0.0
    for path in CACHE_FILES:
        key = path.resolve()
        if key != resolved and key.exists():
            total += triage.cache_cost(key)
    return total



def fetch_catalog(path: Path) -> dict[str, Any]:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set")
    request = urllib.request.Request(
        CATALOG_URL,
        headers={"Authorization": "Bearer " + key, "User-Agent": "og-s1-t20"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("data") or []
    rows = [
        {
            "id": model.get("id"),
            "name": model.get("name"),
            "context_length": model.get("context_length"),
            "pricing": model.get("pricing"),
            "input_modalities": (model.get("architecture") or {}).get("input_modalities"),
            "description": model.get("description"),
        }
        for model in models
    ]
    rows.sort(key=lambda row: str(row.get("id")))
    out = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "count": len(rows),
        "models": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    try:
        shown = path.relative_to(ROOT)
    except ValueError:
        shown = Path(path.name)
    print(f"catalog: {len(rows)} decision models -> {shown}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--handset", default=str(ROOT / "data" / "t20" / "handset.jsonl"))
    parser.add_argument(
        "--cache",
        default=str(ROOT / "work" / "T20" / "cache" / "triage_responses.jsonl"),
    )
    parser.add_argument(
        "--catalog",
        default=str(ROOT / "work" / "T20" / "cache" / "model_catalog.json"),
    )
    parser.add_argument("--models", nargs="*", default=MODELS)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-catalog", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY is not set")
    cache_path = Path(args.cache)
    if not args.skip_catalog:
        fetch_catalog(Path(args.catalog))

    with Path(args.handset).open("r", encoding="utf-8") as handle:
        items = [json.loads(line) for line in handle if line.strip()]
    print(f"items: {len(items)}")

    cap = float(os.environ.get("T20_SPEND_CAP", "5.0"))
    for model in args.models:
        total_before = combined_spend(cache_path)
        if total_before >= cap:
            raise SystemExit(f"lifetime spend ${total_before:.4f} already at the ${cap:.2f} cap")
        before = triage.cache_cost(cache_path, model=model)
        # One lifetime budget: other cache files + this one.
        spent_before = other_cache_spend(cache_path)
        workers = 2 if model.endswith(":free") else args.workers
        print(f"fetching {model} (workers={workers}) ...")
        triage.triage(
            items,
            model=model,
            cache_path=cache_path,
            allow_network=True,
            workers=workers,
            max_spend=cap,
            spent_before=spent_before,
        )
        after = triage.cache_cost(cache_path, model=model)
        total = combined_spend(cache_path)
        print(f"  spend this model: ${after - before:.6f}; lifetime: ${total:.6f}")
        if total > cap:
            raise SystemExit(f"spend ${total:.4f} exceeds the ${cap:.2f} cap")

    print(f"lifetime cache spend: ${combined_spend(cache_path):.6f}")


if __name__ == "__main__":
    main()
