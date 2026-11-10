"""`og-lab tables`: rebuild docs/RESULTS.md from results/ alone, offline and deterministically.

Reads results/runs/*.jsonl (fixed cases; every number is re-judged from the stored transcript), results/adaptive/*.jsonl,
results/detect/*.jsonl, results/sweeps/*.jsonl and results/spend.jsonl. No timestamps and no randomness: the same results give the
same bytes, so `og-lab tables --check` (CI) can compare the file against a fresh rebuild.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from . import cases as C
from . import judge
from .paths import ADAPTIVE, DETECT, RESULTS, RESULTS_MD, RUNS, SPEND, SWEEPS

FAM_NAME = {"A": "A hidden instructions", "B": "B fake authority", "C": "C false facts", "D": "D feed and trigger", "E": "E denial of service", "F": "F natural errors", "control": "controls"}
ARMS = ("naive", "gate_only", "full")


def _jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def load_dir(d: Path, pattern="*.jsonl") -> list[dict]:
    rows = []
    if d.exists():
        for p in sorted(d.glob(pattern)):
            rows += _jsonl(p)
    return rows


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def pct(k: int, n: int) -> str:
    if n == 0:
        return "-"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%, {100 * lo:.0f}-{100 * hi:.0f})"


def md(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_no data_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------------- fixed runs
def rejudge(r: dict) -> dict:
    """Recompute the judged fields from the stored transcript when the case still exists; otherwise keep the stored ones."""
    try:
        case = C.get(r["case"])
    except KeyError:
        return r
    tr = r.get("transcript")
    if not tr:
        return r
    ev = case.evaluate(tr, r["arm"])
    return {**r, **ev}


def load_runs() -> list[dict]:
    rows = load_dir(RUNS)
    last: dict = {}
    for r in rows:
        last[(r["case"], r["arm"], r.get("model"), r.get("rep", 0), r.get("mode", "live"))] = r
    return [rejudge(last[k]) for k in sorted(last, key=lambda k: tuple(str(x) for x in k))]


def section_runs(runs: list[dict]) -> str:
    if not runs:
        return "## Fixed cases\n\n_No runs recorded yet. `og-lab run` writes results/runs/*.jsonl._\n"
    out = ["## Fixed cases: attempted, executed, belief, utility per family and arm\n",
           "attempted = the agent tried the attacker's action; executed = it reached a ledger through every layer; belief = a fake marker stated without doubt words. "
           "Cells are k/n (rate, 95% Wilson interval in percent).\n"]
    groups = defaultdict(list)
    for r in runs:
        groups[(r.get("model"), r.get("mode", "live"))].append(r)
    for (model, mode), rs in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        out.append(f"### {model} ({mode}), {len(rs)} runs\n")
        rows = []
        for fam in ("A", "B", "C", "D", "E"):
            for arm in ARMS:
                x = [r for r in rs if r["family"] == fam and r["arm"] == arm and not r.get("error")]
                if not x:
                    continue
                n = len(x)
                belief_n = [r for r in x if r.get("goal") == "false_belief"]
                rows.append([FAM_NAME[fam], arm, n, pct(sum(bool(r["attempted"]) for r in x), n), pct(sum(bool(r["executed"]) for r in x), n),
                             pct(sum(bool(r["belief"]) for r in belief_n), len(belief_n)) if belief_n else "-", pct(sum(bool(r["success"]) for r in x), n)])
        out.append(md(["family", "arm", "runs", "attempted", "executed", "belief", "attack succeeded"], rows))
        crow = []
        for arm in ARMS:
            x = [r for r in rs if r["family"] == "control" and r["arm"] == arm and not r.get("error")]
            if x:
                crow.append([arm, len(x), pct(sum(bool(r["utility"]) for r in x), len(x))])
        out.append("Utility on clean controls (the legitimate task completed):\n\n" + md(["arm", "runs", "utility"], crow))
        errs = sum(1 for r in rs if r.get("error"))
        out.append(f"Runs that ended in an error (excluded above): {errs}.\n")
    return "\n".join(out)


def section_layers(runs: list[dict]) -> str:
    att = [r for r in runs if r["family"] in ("A", "B", "C", "D", "E") and not r.get("error")]
    if not att:
        return "## Which layer stopped what\n\n_No runs recorded yet._\n"
    layers = ["L1", "L2", "L3", "L5", "L6", "L7", "L8", "model", "through"]
    rows = []
    for fam in ("A", "B", "C", "D", "E"):
        for arm in ARMS:
            x = [r for r in att if r["family"] == fam and r["arm"] == arm]
            if not x:
                continue
            cnt = defaultdict(int)
            for r in x:
                cnt[r["stopped_by"] or "through"] += 1
            rows.append([FAM_NAME[fam], arm, len(x)] + [cnt.get(l, 0) for l in layers])
    ok = sum(1 for r in att if r["arm"] == "full" and not r["success"] and r["stopped_by"] == r["expected_stop"])
    stopped = sum(1 for r in att if r["arm"] == "full" and not r["success"])
    return ("## Which layer stopped what\n\nEach attack run is attributed from the transcript's gate decisions and quarantine records. `model` = the agent resisted unaided; "
            "`through` = the attack succeeded.\n\n" + md(["family", "arm", "runs"] + layers, rows) +
            f"\nIn arm full, {ok} of {stopped} stopped attacks were stopped by the layer the registry expected.\n")


def section_natural(runs: list[dict]) -> str:
    f = [r for r in runs if r["family"] == "F" and not r.get("error")]
    if not f:
        return "## Natural errors (no attacker)\n\n_No runs recorded yet._\n"
    rows = []
    for arm in ARMS:
        x = [r for r in f if r["arm"] == arm]
        if x:
            rows.append([arm, len(x), pct(sum(bool(r["natural_error"]) for r in x), len(x)), pct(sum(1 for r in x if r["first_order_figure_error"]), sum(1 for r in x if r["first_order_figure_error"] is not None))])
    return ("## Natural errors (no attacker)\n\nHonest cases on clean inputs. A wrong figure is cited in an order's key_figures or stated in the summary; "
            "the first-order column counts only the first order the agent tried.\n\n" + md(["arm", "runs", "wrong figure cited", "first order cited a wrong figure"], rows))


# ---------------------------------------------------------------------------------------------------- adaptive
def section_adaptive() -> str:
    rows = load_dir(ADAPTIVE)
    if not rows:
        return "## Adaptive campaigns\n\n_No campaigns recorded yet. `og-lab adaptive` writes results/adaptive/*.jsonl._\n"
    out = [[r.get("target"), r.get("target_arm"), r.get("goal"), len(r.get("rounds", [])), r.get("success_round") or "-", r.get("refusals", 0),
            r.get("stopped_by") or ("-" if r.get("success_round") else "held"), f"{r.get('cost_usd', 0):.4f}"] for r in sorted(rows, key=lambda r: (str(r.get("target")), str(r.get("target_arm")), str(r.get("goal"))))]
    won = sum(1 for r in rows if r.get("success_round"))
    ref = sum(r.get("refusals", 0) for r in rows)
    return ("## Adaptive campaigns\n\nAn attacker model rewrites the top-ranked page after seeing what the target did, for up to N rounds. "
            f"{len(rows)} campaigns, {won} succeeded, {ref} attacker refusals recorded (refused rounds are incomplete, so success rates are a lower bound).\n\n"
            + md(["target", "arm", "goal", "rounds", "success round", "attacker refusals", "stopped by", "cost US$"], out))


# ---------------------------------------------------------------------------------------------------- detectors
def section_detect() -> str:
    rows = load_dir(DETECT)
    if not rows:
        return "## Detectors\n\n_No detector runs recorded yet. `og-lab detect` writes results/detect/*.jsonl._\n"
    by = defaultdict(list)
    for r in rows:
        by[r["screen"]].append(r)
    out = []
    for s, rs in sorted(by.items()):
        row = [s]
        for cat in ("instruction", "authority", "data"):
            x = [r for r in rs if r["label"] == "attack" and r["category"] == cat]
            row.append(pct(sum(bool(r["flagged"]) for r in x), len(x)))
        x = [r for r in rs if r["label"] == "attack"]
        row.append(pct(sum(bool(r["flagged"]) for r in x), len(x)))
        neg = [r for r in rs if r["label"] == "clean"]
        row.append(pct(sum(bool(r["flagged"]) for r in neg), len(neg)))
        out.append(row)
    return ("## Detectors\n\nEach screen reads every attack chunk (the chunk of the poisoned environment that differs from the clean control) and every clean chunk of the six controls. "
            "Recall is on attack chunks; false alarms are on clean chunks.\n\n" + md(["screen", "instruction recall", "authority recall", "false-data recall", "all attacks", "false alarms on clean"], out))


# ---------------------------------------------------------------------------------------------------- sweeps
def section_sweeps() -> str:
    rows = load_dir(SWEEPS)
    if not rows:
        return "## Sandbox sweeps\n\n_No sweeps recorded yet. `og-lab sweep` writes results/sweeps/*.jsonl._\n"
    last: dict = {}
    for r in rows:
        last[(r["seed"], r["case_id"], r["arm"], r["who"], r.get("rep", 0))] = r
    rows = [last[k] for k in sorted(last, key=lambda k: tuple(str(x) for x in k))]
    out = [f"## Sandbox sweeps\n\n{len(rows)} job results ({len({r['world'] for r in rows})} distinct worlds, {len({r['case_id'] for r in rows})} scenarios). Rates are k/n (rate, 95% Wilson interval in percent). "
           "$ at risk = executed attacker action valued at TRUSTED prices, summed over runs; blast radius = the same for trigger worlds.\n"]
    for (who, mode), rs in sorted({(r["who"], r["mode"]): None for r in rows}.items()):
        rs = [r for r in rows if r["who"] == who and r["mode"] == mode]
        out.append(f"### {who} ({mode})\n")
        t = []
        for fam in ("A", "B", "C", "D", "E", "F"):
            for arm in ARMS:
                x = [r for r in rs if r["family"] == fam and r["arm"] == arm and not r["control"]]
                if not x:
                    continue
                n = len(x)
                usd = sum(r["attack"].get("harm_usd") or 0 for r in x)
                blast = sum(r["blast_radius_usd"] or 0 for r in x if r["trigger_world"])
                t.append([FAM_NAME[fam], arm, n, pct(sum(bool(r["attack"]["attempted"]) for r in x), n), pct(sum(bool(r["attack"]["success"]) for r in x), n),
                          f"{usd:,.0f}", f"{blast:,.0f}"])
        out.append(md(["family", "arm", "runs", "attempted", "attack succeeded", "$ at risk (executed)", "blast radius $"], t))
        u = []
        for arm in ARMS:
            x = [r for r in rs if r["arm"] == arm and not r["trigger_world"] and not r["control"]]
            if x:
                n = len(x)
                u.append([arm, n, pct(sum(bool(r["twin"]["utility"]) for r in x), n), pct(sum(bool(r["false_refusal"]) for r in x), n),
                          pct(sum(1 for r in x if r["attack"].get("utility_in_attack_world")), n)])
        out.append("Utility on benign twins (same world, no attack):\n\n" + md(["arm", "twin runs", "twin utility", "false refusal", "utility in the attack world"], u))
        lay = defaultdict(lambda: defaultdict(int))
        for r in rs:
            if not r["control"] and r["family"] != "F":
                lay[r["arm"]][r["attack"].get("stopped_by") or "through"] += 1
        cols = ["L1", "L2", "L3", "L5", "L6", "L7", "L8", "model", "through"]
        out.append("Per-layer attribution of attack runs:\n\n" + md(["arm"] + cols, [[a] + [lay[a].get(c, 0) for c in cols] for a in ARMS if a in lay]))
        tech = defaultdict(lambda: [0, 0])
        for r in rs:
            if r["arm"] == "full" and not r["control"]:
                tech[r["technique"]][0] += bool(r["attack"]["success"])
                tech[r["technique"]][1] += 1
        out.append("Arm full, attack success by technique:\n\n" + md(["technique", "succeeded"], [[k, pct(*v)] for k, v in sorted(tech.items())]))
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------- spend and limits
def section_spend() -> str:
    if not SPEND.exists():
        return "## Spend\n\nNo live calls recorded (results/spend.jsonl absent). Offline sweeps cost nothing.\n"
    rows = _jsonl(SPEND)
    by = defaultdict(lambda: [0, 0.0, 0, 0])
    for r in rows:
        b = by[r.get("model", "?")]
        b[0] += 1
        b[1] += float(r.get("cost_usd") or 0)
        b[2] += int(r.get("prompt_tokens") or 0)
        b[3] += int(r.get("completion_tokens") or 0)
    tot = sum(v[1] for v in by.values())
    return ("## Spend\n\nFrom results/spend.jsonl, every live call the client made.\n\n"
            + md(["model", "calls", "tokens in", "tokens out", "US$"], [[m, v[0], f"{v[2]:,}", f"{v[3]:,}", f"{v[1]:.4f}"] for m, v in sorted(by.items())]) + f"\nTotal US${tot:.4f}.\n")


LIMITS = """## Limits

- Cases are hand-written or generated by seeded techniques; the attack set is not exhaustive and was designed by the same people who designed the defences.
- Offline sweeps use scripted policy agents (cautious, credulous, mixed) and a keyword screen as stand-ins for a model. They test the pipeline, the layers' code and the metrics, not how a real model behaves; they are labelled `offline` and never mixed with live rows.
- Live rows depend on one cheap model family and few repeats; rates carry wide intervals (shown).
- Belief judgements are keyword-based (the doubt list is printed by `og-lab doubt`) and every one is listed for hand review by `og-lab review`.
- The LLM screen is itself a model an adaptive attacker can target; adaptive campaigns are few and often end early when the attacker model refuses (counted, not hidden).
- Simulated markets: no real order, broker or price feed is involved. Trusted prices are the simulator's own.
- Not defended: see docs/THREAT-MODEL.md (a false belief that leads to an allowed order, a mandate signed against the owner's interest, a compromised broker or receiver, collusion of independent sources).
"""


def build() -> str:
    runs = load_runs()
    parts = ["# OrderGuard results\n",
             "Generated by `og-lab tables` from the raw files in results/. Do not edit by hand: `og-lab tables --check` fails CI when this file differs from a fresh rebuild.\n",
             section_runs(runs), section_layers(runs), section_natural(runs), section_adaptive(), section_detect(), section_sweeps(), section_spend(), LIMITS]
    return "\n".join(parts).rstrip() + "\n"


def write(path: Path | None = None) -> Path:
    path = path or RESULTS_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build())
    return path


def check(path: Path | None = None) -> bool:
    path = path or RESULTS_MD
    return path.exists() and path.read_text() == build()
