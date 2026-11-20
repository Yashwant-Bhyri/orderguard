"""Check the T20 task folder against the lab's disk limit.

POLICY.md: no task adds more than 500 MB, and anything over 5 MB in the task
folder is an error.  Generated data lives in ``data/t20``; this check covers the
task folder only, and prints the number instead of a hand-typed claim.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "work" / "T20"
LIMIT = 5 * 1024 * 1024


def main() -> None:
    files = [path for path in TASK.rglob("*") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    largest = max(files, key=lambda path: path.stat().st_size) if files else None
    size = largest.stat().st_size if largest else 0
    print(
        f"task folder: {total / 1024 / 1024:.2f} MB in {len(files)} files; "
        f"largest {largest.name if largest else 'n/a'} {size / 1024:.1f} KB"
    )
    if total > LIMIT:
        raise SystemExit(
            f"task folder is {total / 1024 / 1024:.2f} MB, over the 5 MB policy limit"
        )
    if size > 500 * 1024 * 1024:
        raise SystemExit(f"{largest.name} is over 500 MB")


if __name__ == "__main__":
    main()
