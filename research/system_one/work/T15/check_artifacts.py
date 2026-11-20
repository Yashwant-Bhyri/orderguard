"""Check the T15 produced files for absolute home paths and oversized files.

The scan never prints a matched path: a hit would itself leak the path.  It
prints only the relative file name, the pattern family and a count.

Patterns are assembled at run time so this file does not contain the literal
strings it searches for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCAN_ROOTS = [HERE, ROOT / "og_s1"]
MAX_BYTES = 5 * 1024 * 1024

# Match an actual absolute home path with a user component, not a bare
# "/Users/" mentioned as prose.  Patterns are assembled so this file does not
# contain a literal absolute path either.
PATTERNS = {
    "unix_users": re.compile(r"/" + "Users" + r"/[A-Za-z0-9._-]+/"),
    "unix_home": re.compile(r"/" + "home" + r"/[A-Za-z0-9._-]+/"),
    "windows_users": re.compile(r"[A-Za-z]:\\\\" + "Users" + r"\\\\[^\\\\]+\\\\"),
}


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file():
            yield path


def main() -> int:
    hits: list[tuple[str, str, int]] = []
    oversized: list[tuple[str, int]] = []
    scanned = 0
    for root in SCAN_ROOTS:
        for path in _iter_files(root):
            if "__pycache__" in path.parts:
                hits.append((str(path.relative_to(ROOT)), "bytecode_cache", 1))
                continue
            scanned += 1
            try:
                size = path.stat().st_size
                text = path.read_bytes().decode("utf-8", errors="ignore")
            except OSError:
                continue
            if size > MAX_BYTES:
                oversized.append((str(path.relative_to(ROOT)), size))
            for name, pattern in PATTERNS.items():
                count = len(pattern.findall(text))
                if count:
                    hits.append((str(path.relative_to(ROOT)), name, count))

    print(f"artifact_scan files={scanned} absolute_home_hits={len(hits)} oversized={len(oversized)}")
    for relative, name, count in hits:
        print(f"absolute_home_hit file={relative} pattern={name} count={count}")
    for relative, size in oversized:
        print(f"oversized file={relative} bytes={size} limit={MAX_BYTES}")
    return 1 if hits or oversized else 0


if __name__ == "__main__":
    sys.exit(main())
