#!/usr/bin/env python3
"""Run pytest with a small stdlib line and branch tracer for OrderGuard money-path files.

This intentionally has no third-party coverage dependency. It counts executed
lines and distinct conditional-jump source/destination line arcs; when both
outcomes stay on the same line, line tracing cannot distinguish them. Usage:

    .venv/bin/python scripts/trace_coverage.py --output /tmp/coverage.json -- python/tests/safety
"""
from __future__ import annotations

import dis
import json
from pathlib import Path
import sys
from collections import defaultdict
from types import CodeType, FrameType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

TARGETS = {
    p.resolve(): p.relative_to(ROOT).as_posix()
    for base in (ROOT / "python" / "orderguard_guard",)
    for p in base.rglob("*.py")
}
for p in (ROOT / "python" / "orderguard_arena" / "envelopes.py",
          ROOT / "python" / "orderguard_arena" / "authority.py",
          ROOT / "python" / "orderguard_risk" / "scorer.py"):
    TARGETS[p.resolve()] = p.relative_to(ROOT).as_posix()


def nested_codes(code: CodeType):
    yield code
    for value in code.co_consts:
        if isinstance(value, CodeType):
            yield from nested_codes(value)


def static_targets():
    lines: dict[Path, set[int]] = {p: set() for p in TARGETS}
    branches: dict[Path, set[tuple[str, int, int]]] = {p: set() for p in TARGETS}
    for path in TARGETS:
        try:
            code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (OSError, SyntaxError):
            continue
        for obj in nested_codes(code):
            instructions = list(dis.get_instructions(obj))
            for start, _end, line in obj.co_lines():
                if line is not None:
                    lines[path].add(line)
            for index, ins in enumerate(instructions):
                conditional = (ins.opname.startswith("POP_JUMP") or ins.opname.startswith("JUMP_IF")
                               or ins.opname in {"FOR_ITER", "SEND"})
                if not conditional or not isinstance(ins.argval, int):
                    continue
                fallthrough = instructions[index + 1].offset if index + 1 < len(instructions) else None
                if fallthrough is None:
                    continue
                src = ins.starts_line or obj.co_firstlineno
                # Use the closest line-table location when the jump itself has no line marker.
                if ins.starts_line is None:
                    src = next((x.starts_line for x in reversed(instructions[:index + 1]) if x.starts_line is not None), obj.co_firstlineno)
                target_line = next((line for a, _b, line in obj.co_lines() if a == ins.argval and line is not None), src)
                fall_line = next((line for a, _b, line in obj.co_lines() if a == fallthrough and line is not None), src)
                code_id = f"{obj.co_qualname}:{obj.co_firstlineno}"
                branches[path].add((code_id, src, target_line))
                branches[path].add((code_id, src, fall_line))
    return lines, branches


EXEC_LINES, STATIC_BRANCHES = static_targets()
EXECUTED_LINES: dict[Path, set[int]] = {p: set() for p in TARGETS}
EXECUTED_BRANCHES: dict[Path, set[tuple[str, int, int]]] = {p: set() for p in TARGETS}
PREVIOUS_LINE: dict[FrameType, int] = {}
PATH_CACHE: dict[str, Path | None] = {}
BRANCH_DESTINATIONS: dict[Path, dict[tuple[str, int], set[int]]] = {}
for _path, _branches in STATIC_BRANCHES.items():
    _lookup: dict[tuple[str, int], set[int]] = defaultdict(set)
    for _code, _source_line, _target_line in _branches:
        _lookup[(_code, _source_line)].add(_target_line)
    BRANCH_DESTINATIONS[_path] = _lookup


def trace(frame: FrameType, event: str, arg):
    filename = frame.f_code.co_filename
    if filename not in PATH_CACHE:
        try:
            resolved = Path(filename).resolve()
        except OSError:
            resolved = None
        PATH_CACHE[filename] = resolved if resolved in TARGETS else None
    path = PATH_CACHE[filename]
    if path not in TARGETS:
        return trace
    if event == "call":
        pass
    elif event == "line":
        previous = PREVIOUS_LINE.get(frame)
        code_id = f"{frame.f_code.co_qualname}:{frame.f_code.co_firstlineno}"
        if previous is not None and frame.f_lineno in BRANCH_DESTINATIONS[path].get((code_id, previous), ()):
            EXECUTED_BRANCHES[path].add((code_id, previous, frame.f_lineno))
        EXECUTED_LINES[path].add(frame.f_lineno)
        PREVIOUS_LINE[frame] = frame.f_lineno
    elif event == "return":
        PREVIOUS_LINE.pop(frame, None)
    return trace


def main(argv: list[str]) -> int:
    output = None
    args = list(argv)
    if "--output" in args:
        i = args.index("--output")
        output = Path(args[i + 1])
        del args[i:i + 2]
    if args and args[0] == "--":
        args.pop(0)
    if not args:
        args = ["-q", "-p", "no:cacheprovider"]
    import pytest

    sys.settrace(trace)
    try:
        exit_code = int(pytest.main(args))
    finally:
        sys.settrace(None)
    rows = {}
    all_lines = hit_lines = all_branches = hit_branches = 0
    for path, name in sorted(TARGETS.items(), key=lambda item: item[1]):
        statements = EXEC_LINES[path]
        executed = EXECUTED_LINES[path] & statements
        possible = STATIC_BRANCHES[path]
        taken = EXECUTED_BRANCHES[path] & possible
        all_lines += len(statements)
        hit_lines += len(executed)
        all_branches += len(possible)
        hit_branches += len(taken)
        rows[name] = {
            "lines": {"covered": len(executed), "total": len(statements),
                      "percent": round(100 * len(executed) / len(statements), 2) if statements else 100.0},
            "branches": {"covered": len(taken), "total": len(possible),
                         "percent": round(100 * len(taken) / len(possible), 2) if possible else 100.0},
            "missing_lines": sorted(statements - executed),
        }
    report = {
        "runner": "stdlib sys.settrace lines and conditional-bytecode line arcs (same-line outcomes collapse)",
        "line_coverage": {"covered": hit_lines, "total": all_lines,
                          "percent": round(100 * hit_lines / all_lines, 2) if all_lines else 100.0},
        "branch_coverage": {"covered": hit_branches, "total": all_branches,
                            "percent": round(100 * hit_branches / all_branches, 2) if all_branches else 100.0},
        "files": rows,
        "pytest_exit_code": exit_code,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    print("TRACE_COVERAGE " + json.dumps({"line": report["line_coverage"], "branch": report["branch_coverage"]}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
