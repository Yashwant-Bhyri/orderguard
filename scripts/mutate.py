#!/usr/bin/env python3
"""Small offline AST mutation tester for OrderGuard's money path.

Each mutation is written to one source file, exercised in a fresh pytest
process, then the exact original bytes are restored even if pytest fails.
No mutation survives a run. No network services or third-party tools are used.
"""
from __future__ import annotations

import argparse
import ast
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "gate": "python/orderguard_guard/gate.py",
    "envelopes": "python/orderguard_arena/envelopes.py",
    "mandate_fit": "python/orderguard_guard/mandate_fit.py",
    "tighten": "python/orderguard_risk/scorer.py",
}

GATE_TESTS = [
    "python/tests/safety/test_gate_edges.py",
    "python/tests/safety/test_gate_properties.py::test_allow_and_hold_never_exceed_the_signed_mandate",
    "python/tests/safety/test_gate_properties.py::test_the_orders_own_limit_price_cannot_raise_allowed_notional",
    "python/tests/safety/test_gate_metamorphic.py",
    "python/tests/guard/test_order_gate.py",
    "python/tests/guard/test_portfolio_limits.py::test_envelope_check_agrees_with_order_gate_on_random_states",
    "python/tests/arena/test_authority.py::test_fast_path_agrees_with_the_real_order_gate_on_random_orders",
]
ENVELOPE_TESTS = [
    "python/tests/arena/test_authority.py::test_fast_path_agrees_with_the_real_order_gate_on_random_orders",
    "python/tests/arena/test_authority.py::test_sizing_uses_the_trusted_price_not_the_agents_limit_price",
    "python/tests/arena/test_authority_stateful.py",
    "python/tests/safety/test_gate_metamorphic.py",
    "python/tests/guard/test_portfolio_limits.py::test_envelope_check_agrees_with_order_gate_on_random_states",
    "python/tests/guard/test_portfolio_limits.py::test_fast_path_and_strict_gate_agree_through_the_authority_with_state_accumulating",
]
MANDATE_FIT_TESTS = [
    "python/tests/guard/test_mandate_fit.py",
    "python/tests/guard/test_portfolio_limits.py::test_draft_cannot_loosen_or_drop_a_parent_limit",
]
TIGHTEN_TESTS = [
    "python/tests/risk/test_order_risk.py::test_tighten_never_loosens",
    "python/tests/risk/test_programmed_weights.py",
]


def source_for(key: str) -> Path:
    return ROOT / TARGETS[key]


def replace_comparison(tree: ast.AST, needle: str, *, reverse: bool = False) -> int:
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and needle in ast.unparse(node) and len(node.ops) == 1:
            flips = ({ast.Gt: ast.Lt, ast.GtE: ast.LtE, ast.Lt: ast.Gt, ast.LtE: ast.GtE}
                     if reverse else
                     {ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Lt: ast.LtE, ast.LtE: ast.Lt,
                      ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot, ast.IsNot: ast.Is})
            old = type(node.ops[0])
            if old in flips:
                node.ops[0] = flips[old]()
                return node.lineno
    raise ValueError(f"no single comparison found for {needle!r}")


def drop_reason(tree: ast.AST, phrase: str) -> int:
    class Drop(ast.NodeTransformer):
        line = None

        def generic_visit(self, node):
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    kept = []
                    for child in value:
                        if (isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                                and isinstance(child.value.func, ast.Attribute) and child.value.func.attr == "append"
                                and phrase in ast.unparse(child)):
                            self.line = child.lineno
                            kept.append(ast.copy_location(ast.Pass(), child))
                        else:
                            if isinstance(child, ast.AST):
                                child = self.visit(child)
                            kept.append(child)
                    setattr(node, field, kept)
                elif isinstance(value, ast.AST):
                    setattr(node, field, self.visit(value))
            return node

    drop = Drop()
    tree = drop.visit(tree)
    if drop.line is None:
        raise ValueError(f"no reason append found for {phrase!r}")
    return drop.line


def swap_trusted_for_limit(tree: ast.AST) -> int:
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"notional", "cents"} for t in node.targets)
                and "qty * trusted" in ast.unparse(node.value)):
            class Swap(ast.NodeTransformer):
                def visit_Name(self, name):
                    if name.id == "trusted":
                        name.id = "limit"
                    return name
            node.value = Swap().visit(node.value)
            return node.lineno
    raise ValueError("no trusted-price notional assignment found")


def negate_if(tree: ast.AST, needle: str) -> int:
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and needle in ast.unparse(node.test):
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
            return node.lineno
    raise ValueError(f"no if condition found for {needle!r}")


def negate_boolean(tree: ast.AST, needle: str) -> int:
    # A boolean negation mutation is most clearly represented by changing `not x` to `x`.
    class RemoveNot(ast.NodeTransformer):
        line = None

        def visit_UnaryOp(self, node):
            if isinstance(node.op, ast.Not) and needle in ast.unparse(node):
                self.line = node.lineno
                return self.visit(node.operand)
            return self.generic_visit(node)

    remover = RemoveNot()
    tree = remover.visit(tree)
    if remover.line is None:
        raise ValueError(f"no negated boolean found for {needle!r}")
    return remover.line


def early_return(tree: ast.AST, function: str, return_expr: str) -> int:
    class Insert(ast.NodeTransformer):
        found = None

        def visit_FunctionDef(self, node):
            if node.name == function and self.found is None:
                early = ast.parse("def _():\n    return " + return_expr + "\n").body[0].body[0]
                node.body.insert(0, early)
                self.found = node.lineno
                return node
            return self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

    ins = Insert()
    tree = ins.visit(tree)
    if ins.found is None:
        raise ValueError(f"no function named {function!r}")
    return ins.found


def mutated_source(key: str, kind: str, selector: str | None = None) -> tuple[str, int]:
    path = source_for(key)
    original = path.read_text(encoding="utf-8")
    tree = ast.parse(original, filename=str(path))
    if kind == "compare":
        line = replace_comparison(tree, selector or "")
    elif kind == "reverse_compare":
        line = replace_comparison(tree, selector or "", reverse=True)
    elif kind == "drop_reason":
        line = drop_reason(tree, selector or "")
    elif kind == "trusted_to_limit":
        line = swap_trusted_for_limit(tree)
    elif kind == "negate_if":
        line = negate_if(tree, selector or "")
    elif kind == "negate_boolean":
        line = negate_boolean(tree, selector or "")
    elif kind == "early_return":
        returns = {
            "gate": ("_evaluate", "{'decision': 'allow', 'reasons': [], 'checks': {}}"),
            "envelopes": ("check", "([], [], None)"),
            "mandate_fit": ("check_mandate_fit", "{'fits': True, 'parent_id': None, 'draft': draft, 'violations': []}"),
            "tighten": ("tighten", "'allow'"),
        }
        function, expr = returns[key]
        line = early_return(tree, function, expr)
    else:
        raise ValueError(kind)
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n", line


def mutations():
    rows = [
        ("gate", "compare", "notional > m.maxOrderNotionalUsd", GATE_TESTS),
        ("gate", "compare", "placed + notional > m.maxDailyNotionalUsd", GATE_TESTS),
        ("gate", "compare", "notional > m.stepUpAboveUsd", GATE_TESTS),
        ("gate", "drop_reason", "above the per-order cap", GATE_TESTS),
        ("gate", "trusted_to_limit", None, GATE_TESTS),
        ("gate", "negate_if", "kind in", GATE_TESTS),
        ("gate", "early_return", None, GATE_TESTS),
        ("envelopes", "compare", "cents > round(self.max_order * 100)", ENVELOPE_TESTS),
        ("envelopes", "compare", "round(used * 100) + cents > round(m.maxDailyNotionalUsd * 100)", ENVELOPE_TESTS),
        ("envelopes", "compare", "round(notional * 100) > round(self.stepup * 100)", ENVELOPE_TESTS),
        ("envelopes", "drop_reason", "above the per-order cap", ENVELOPE_TESTS),
        ("envelopes", "trusted_to_limit", None, ENVELOPE_TESTS),
        ("envelopes", "negate_if", "problem", ENVELOPE_TESTS),
        ("envelopes", "early_return", None, ENVELOPE_TESTS),
        ("mandate_fit", "compare", "candidate.maxOrderNotionalUsd <= maximum.maxOrderNotionalUsd", MANDATE_FIT_TESTS),
        ("mandate_fit", "compare", "candidate.priceBandPct <= maximum.priceBandPct", MANDATE_FIT_TESTS),
        ("mandate_fit", "compare", "child <= parent", MANDATE_FIT_TESTS),
        ("mandate_fit", "negate_boolean", "violations", MANDATE_FIT_TESTS),
        ("mandate_fit", "early_return", None, MANDATE_FIT_TESTS),
        ("tighten", "reverse_compare", "ORDER[decision] >= ORDER[want]", TIGHTEN_TESTS),
        ("tighten", "negate_if", "decision not in ORDER", TIGHTEN_TESTS),
        ("tighten", "early_return", None, TIGHTEN_TESTS),
    ]
    for key, kind, selector, tests in rows:
        yield {"key": key, "kind": kind, "selector": selector, "tests": tests,
               "mutant": f"{key}:{kind}" + (f":{selector}" if selector else "")}


def run_one(mutation: dict, timeout: int) -> dict:
    key = mutation["key"]
    path = source_for(key)
    original = path.read_bytes()
    started = time.monotonic()
    try:
        replacement, line = mutated_source(key, mutation["kind"], mutation["selector"])
        path.write_text(replacement, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "python") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["OG_LLM"] = "replay"
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *mutation["tests"]]
        try:
            proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
            killed = proc.returncode != 0
            failed = sorted(set(re.findall(r"FAILED\s+([^\s]+::[^\s]+)", proc.stdout + "\n" + proc.stderr)))
            if killed and not failed:
                failed = [f"pytest exited {proc.returncode} before reporting a failed test"]
            return {"mutant": mutation["mutant"], "file": path.relative_to(ROOT).as_posix(), "line": line,
                    "killed": killed, "killed_by": failed, "exit_code": proc.returncode,
                    "duration_s": round(time.monotonic() - started, 2)}
        except subprocess.TimeoutExpired:
            return {"mutant": mutation["mutant"], "file": path.relative_to(ROOT).as_posix(), "line": line,
                    "killed": True, "killed_by": ["pytest timeout"], "timeout": True,
                    "duration_s": round(time.monotonic() - started, 2)}
    finally:
        path.write_bytes(original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="run", help="result key (use before_additions / after_additions for comparison)")
    parser.add_argument("--output", type=Path, default=ROOT / "results/testing/mutation.json")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true", help="list mutants without editing files or running tests")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps([m["mutant"] for m in mutations()], indent=2))
        return 0

    results = []
    for i, mutation in enumerate(mutations(), 1):
        print(f"[{i}] {mutation['mutant']}", flush=True)
        replacement, line = mutated_source(mutation["key"], mutation["kind"], mutation["selector"])
        del replacement
        result = run_one(mutation, args.timeout)
        result["file:line"] = f"{result['file']}:{result['line']}"
        results.append(result)
        print(f"    {'killed' if result['killed'] else 'SURVIVED'} by {', '.join(result['killed_by']) or 'no selected test'}", flush=True)
    killed = sum(1 for r in results if r["killed"])
    snapshot = {"mutants": len(results), "killed": killed, "survived": len(results) - killed,
                "score_percent": round(100 * killed / len(results), 2) if results else 100.0,
                "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    existing[args.label] = snapshot
    existing["runner"] = "scripts/mutate.py; stdlib AST mutations; pytest with OG_LLM=replay"
    latest = existing.get("after_additions") or existing.get("run") or existing.get("before_additions") or snapshot
    existing["survivors"] = sorted(r["mutant"] for r in latest["results"] if not r["killed"])
    args.output.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if snapshot["survived"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
