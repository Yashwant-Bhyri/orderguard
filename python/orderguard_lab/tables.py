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
                pass                      # tolerated when building (an interrupted run); `corrupt_lines()` reports it and `--check` fails on it
    return out


def raw_dirs() -> list[Path]:
    return [RUNS, ADAPTIVE, DETECT, SWEEPS]


def corrupt_lines() -> list[str]:
    """`file:line` of every unparsable line in the raw result files (a truncated or damaged recording). Tables skip them; the check refuses them."""
    bad = []
    for d in raw_dirs():
        for p in sorted(d.glob("*.jsonl")) if d.exists() else []:
            for n, line in enumerate(p.read_text().splitlines(), 1):
                if line.strip():
                    try:
                        json.loads(line)
                    except ValueError:
                        bad.append(f"{p.parent.name}/{p.name}:{n}")
    if SPEND.exists():
        for n, line in enumerate(SPEND.read_text().splitlines(), 1):
            if line.strip():
                try:
                    json.loads(line)
                except ValueError:
                    bad.append(f"{SPEND.name}:{n}")
    return bad


def _has_replay_miss(node) -> bool:
    """True if any `error` field anywhere in a record names a ReplayMiss (the agent loop stores errors as "<ExceptionName>: ...")."""
    if isinstance(node, dict):
        return any((k == "error" and isinstance(v, str) and v.startswith("ReplayMiss")) or _has_replay_miss(v) for k, v in node.items())
    if isinstance(node, list):
        return any(_has_replay_miss(v) for v in node)
    return False


def replay_misses() -> list[str]:
    """Raw records whose run ended in a ReplayMiss: a replay that lacked a recording, which would silently shrink the denominators."""
    hits = []
    for d in raw_dirs():
        for p in sorted(d.glob("*.jsonl")) if d.exists() else []:
            for n, line in enumerate(p.read_text().splitlines(), 1):
                if "ReplayMiss" in line:
                    try:
                        if _has_replay_miss(json.loads(line)):
                            hits.append(f"{p.parent.name}/{p.name}:{n}")
                    except ValueError:
                        pass
    return hits


def integrity_problems() -> list[str]:
    out = [f"unparsable line {x}" for x in corrupt_lines()]
    out += [f"ReplayMiss error recorded at {x}" for x in replay_misses()]
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
           "An attempted action is one the agent tried. An executed action reached the simulated ledger. The belief score counts planted markers repeated without a matching doubt term. "
           "Family E reports whether the agent abandoned the legitimate purchase. The model headings include errored runs, which are excluded from the rates. "
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
                attempted = pct(sum(bool(r["attempted"]) for r in x), n) if fam != "E" else "-"
                executed = pct(sum(bool(r["executed"]) for r in x), n) if fam != "E" else "-"
                rows.append([FAM_NAME[fam], arm, n, attempted, executed,
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
    return ("## Which layer stopped what\n\nThese counts pool live and offline fixed-case runs. Attribution uses the transcript's gate decisions and quarantine records. "
            "`model` is the label for resistance without an attributed guard layer. `through` marks a successful attack.\n\n" + md(["family", "arm", "runs"] + layers, rows) +
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
    return ("## Natural errors (no attacker)\n\nThese counts pool live and offline fixed-case runs on clean inputs. "
            "A wrong figure may appear in an order's `key_figures` or in the summary. The first-order column counts only the first order the agent tried.\n\n" + md(["arm", "runs", "wrong figure cited", "first order cited a wrong figure"], rows))


# ---------------------------------------------------------------------------------------------------- adaptive
def section_adaptive() -> str:
    rows = load_dir(ADAPTIVE)
    if not rows:
        return "## Adaptive campaigns\n\n_No campaigns recorded yet. `og-lab adaptive` writes results/adaptive/*.jsonl._\n"
    out = []
    won = sum(bool(r.get("success_round")) for r in rows)
    incomplete = 0
    for r in sorted(rows, key=lambda r: (str(r.get("target")), str(r.get("target_arm")), str(r.get("goal")))):
        rounds = r.get("rounds") or []
        failures = [item for item in rounds if item.get("attacker_refused_or_failed")]
        incomplete += bool(failures)
        refusals = sum(item.get("reason") == "refused" for item in failures)
        failure = (failures[-1].get("reason") or "unknown") if failures else "-"
        out.append([r.get("target"), r.get("target_arm"), r.get("goal"), len(rounds) - len(failures),
                    r.get("success_round") or "-", refusals, failure, r.get("stopped_by") or "-", f"{r.get('cost_usd', 0):.4f}"])
    return ("## Adaptive campaigns\n\nAn attacker model rewrites the top-ranked page after seeing what the target did. "
            f"Across {len(rows)} campaigns, {won} succeeded in the observed rounds. "
            f"{incomplete} campaigns ended early after the attacker failed to supply a usable page.\n\n"
            + md(["target", "arm", "goal", "target rounds", "success round", "confirmed attacker refusals",
                  "attacker failure", "stopped by", "cost US$"], out))


# ---------------------------------------------------------------------------------------------------- detectors
def section_detect() -> str:
    rows = load_dir(DETECT)
    if not rows:
        return "## Detectors\n\n_No detector runs recorded yet. `og-lab detect` writes results/detect/*.jsonl._\n"
    by = defaultdict(list)
    for r in rows:
        by[r["screen"]].append(r)
    out = []
    timed = any(r.get("latency_ms") is not None or r.get("cost_usd") for r in rows)
    for s, rs in sorted(by.items()):
        row = [s]
        for cat in ("instruction", "authority", "data"):
            x = [r for r in rs if r["label"] == "attack" and r["category"] == cat]
            row.append(pct(sum(bool(r["flagged"]) for r in x), len(x)))
        x = [r for r in rs if r["label"] == "attack"]
        row.append(pct(sum(bool(r["flagged"]) for r in x), len(x)))
        neg = [r for r in rs if r["label"] == "clean"]
        row.append(pct(sum(bool(r["flagged"]) for r in neg), len(neg)))
        if timed:
            lat = sorted(r["latency_ms"] for r in rs if r.get("latency_ms") is not None)
            cost = [r["cost_usd"] for r in rs if r.get("cost_usd") is not None]
            row += [f"{lat[len(lat) // 2]:.0f}" if lat else "n/a", f"{lat[min(len(lat) - 1, int(0.95 * len(lat)))]:.0f}" if lat else "n/a",
                    f"{1000 * sum(cost) / len(cost):.3f}" if cost else "n/a"]
        out.append(row)
    head = ["screen", "instruction recall", "authority recall", "false-data recall", "all attacks", "false alarms on clean"] + (["median latency ms", "p95 latency ms", "cost US$ per 1k chunks"] if timed else [])
    return ("## Detectors\n\nRecall uses attack chunks that differ from the matched control. False alarms use deduplicated clean chunks, including the trigger control. "
            "Standalone model timings use recorded live request wall time under parallel load where available. Local rows use out-of-fold predictions. "
            "Cascade timings use a local-stage estimate and, where applicable, the recorded fast-stage median. The replayed main-stage latency is omitted.\n\n"
            + md(head, out))


# ---------------------------------------------------------------------------------------------------- sweeps
def section_sweeps() -> str:
    rows = load_dir(SWEEPS)
    if not rows:
        return "## Sandbox sweeps\n\n_No sweeps recorded yet. `og-lab sweep` writes results/sweeps/*.jsonl._\n"
    last: dict = {}
    for r in rows:
        last[(r["seed"], r["case_id"], r["arm"], r["who"], r.get("rep", 0))] = r
    rows = [last[k] for k in sorted(last, key=lambda k: tuple(str(x) for x in k))]
    out = [f"## Sandbox sweeps\n\n{len(rows)} job results ({len({r['world'] for r in rows})} distinct worlds, {len({r['case_id'] for r in rows})} scenarios). "
           "Rates are k/n (rate, 95% Wilson interval in percent). The $ at risk column sums executed attacker notional at trusted prices. "
           "Blast radius is the same measure for trigger worlds.\n"]
    for (who, mode), rs in sorted({(r["who"], r["mode"]): None for r in rows}.items()):
        rs = [r for r in rows if r["who"] == who and r["mode"] == mode]
        out.append(f"### {who} ({mode})\n")
        scenarios = [r for r in rs if not r["control"]]
        attack_jobs = [r for r in scenarios if r["family"] != "F"]
        attacks = [r for r in attack_jobs if not r["attack"].get("error")]
        error_counts = ", ".join(f"{arm} {sum(r['arm'] == arm and bool(r['attack'].get('error')) for r in attack_jobs)}" for arm in ARMS)
        out.append("Attack rates exclude natural-error scenarios and attack-world runs that ended in an error. "
                   f"Excluded attack-world errors by arm are {error_counts}.\n")
        t = []
        for fam in ("A", "B", "C", "D", "E"):
            for arm in ARMS:
                x = [r for r in attacks if r["family"] == fam and r["arm"] == arm]
                if not x:
                    continue
                n = len(x)
                usd = sum(r["attack"].get("harm_usd") or 0 for r in x)
                blast = sum(r["blast_radius_usd"] or 0 for r in x if r["trigger_world"])
                attempted = pct(sum(bool(r["attack"]["attempted"]) for r in x), n) if fam != "E" else "-"
                t.append([FAM_NAME[fam], arm, n, attempted, pct(sum(bool(r["attack"]["success"]) for r in x), n),
                          f"{usd:,.2f}", f"{blast:,.2f}"])
        out.append(md(["family", "arm", "runs", "attempted", "attack succeeded", "$ at risk (executed)", "blast radius $"], t))
        out.append("Benign-twin utility includes natural-error scenarios. Correct abstention completes a trigger twin. "
                   "Twin errors are excluded independently of attack-world errors.\n")
        u = []
        for arm in ARMS:
            twins = [r for r in scenarios if r["arm"] == arm and not r["twin"].get("error")]
            if not twins:
                continue
            non_trigger = [r for r in twins if not r["trigger_world"]]
            attack_world = [r for r in scenarios if r["arm"] == arm and not r["trigger_world"] and not r["attack"].get("error")]
            u.append([arm, len(twins), pct(sum(bool(r["twin"]["utility"]) for r in twins), len(twins)),
                      pct(sum(bool(r["twin"]["utility"]) for r in non_trigger), len(non_trigger)),
                      pct(sum(not r["twin"]["utility"] for r in non_trigger), len(non_trigger)),
                      pct(sum(bool(r["attack"].get("utility_in_attack_world")) for r in attack_world), len(attack_world))])
        out.append(md(["arm", "twin runs", "all twin tasks completed", "non-trigger twin tasks completed",
                       "non-trigger twin tasks incomplete", "non-trigger attack-world tasks completed"], u))
        lay = defaultdict(lambda: defaultdict(int))
        for r in attacks:
            lay[r["arm"]][r["attack"].get("stopped_by") or "through"] += 1
        cols = ["L1", "L2", "L3", "L5", "L6", "L7", "L8", "model", "through"]
        out.append("Per-layer attribution of attack runs\n\n" + md(["arm"] + cols, [[a] + [lay[a].get(c, 0) for c in cols] for a in ARMS if a in lay]))
        tech = defaultdict(lambda: [0, 0])
        for r in attacks:
            if r["arm"] == "full":
                tech[r["technique"]][0] += bool(r["attack"]["success"])
                tech[r["technique"]][1] += 1
        out.append("Full-guard attack success by technique\n\n" + md(["technique", "succeeded"], [[k, pct(*v)] for k, v in sorted(tech.items())]))
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------- spend and limits
def section_spend() -> str:
    if not SPEND.exists():
        return "## Spend\n\nNo live calls recorded (results/spend.jsonl absent). Offline sweeps cost nothing.\n"
    rows = _jsonl(SPEND)
    by = defaultdict(lambda: [0, 0.0, 0, 0])
    for r in rows:
        b = by[(r.get("model") or "unknown", r.get("provider") or "unknown")]
        b[0] += 1
        b[1] += float(r.get("cost_usd") or 0)
        b[2] += int(r.get("prompt_tokens") or 0)
        b[3] += int(r.get("completion_tokens") or 0)
    tot = sum(v[1] for v in by.values())
    return ("## Spend\n\nRecorded model spend across logged requests from `results/spend.jsonl`. "
            "Provider labels come from the historical log. Unconfirmed attempts may be logged without a settled cost.\n\n"
            + md(["model", "provider", "log entries", "tokens in", "tokens out", "US$"],
                 [[model, provider, v[0], f"{v[2]:,}", f"{v[3]:,}", f"{v[1]:.4f}"] for (model, provider), v in sorted(by.items())])
            + f"\nTotal US${tot:.4f}.\n")


LIMITS = """## Limits

- Cases are hand-written or generated by seeded techniques; the attack set is not exhaustive and was designed by the same people who designed the defences.
- Offline sweeps use scripted policy agents and a keyword screen to exercise the pipeline and metrics. Sweep tables label those runs `offline`. The fixed-case attribution and natural-error tables explicitly pool live and scripted runs.
- Live agent evaluations use two variants of one DeepSeek Flash family with few repeats. Detector and spend tables include other model families.
- Belief judgements are keyword-based (the doubt list is printed by `og-lab doubt`) and every one is listed for hand review by `og-lab review`.
- Adaptive campaigns cover a small set of goals and rounds. The campaign table records early stops when the attacker supplies unusable output.
- The lab uses simulated orders, markets and fills. Here, live refers to calls to a model provider.
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
    return path.exists() and path.read_text() == build() and not integrity_problems()
