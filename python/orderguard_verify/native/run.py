"""Run arms over the drafted memos and write one JSON file of records per arm. `og native` is the entry point."""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ..finance.truth_store import TruthStore
from ..grader.score import rate, score
from ..paths import DATA, RESULTS, ROOT
from . import arms

OUT = RESULTS / "native"
LABELS = DATA / "native" / "labels"
# Models are recorded in docs/PROTOCOL.md before any hold-out run. Environment variables are for a paid rerun.
ENGINE = os.getenv("OG_NATIVE_ENGINE", "nvidia/nemotron-3.5-super-vl:free")
JUDGE_SAME = os.getenv("OG_NATIVE_JUDGE_SAME", ENGINE)
JUDGE_OTHER = os.getenv("OG_NATIVE_JUDGE_OTHER", "cohere/north-mini-code:free")
ARMS = ("none", "judge_same", "judge_other", "engine")


def load_labels(split: str) -> list[dict]:
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    out = []
    for f in sorted(LABELS.glob("*.json")):
        for m in json.loads(f.read_text())["memos"]:
            if memos.get(m["memo_id"], {}).get("split") == split:
                out += [{**c, "memo_id": m["memo_id"]} for c in m["claims"]]
    return out


def git_state() -> dict:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    tags = subprocess.run(["git", "tag", "--points-at", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return {"commit": sha, "dirty": dirty, "tags": tags}


def run_split(split: str, which: tuple[str, ...] = ARMS, workers: int = 4, again: bool = False, suffix: str = "") -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    markers = {arm: OUT / f"{split}_{arm}{suffix}_run.json" for arm in which}
    if split == "holdout" and not suffix and any(m.exists() for m in markers.values()) and not again:
        raise SystemExit("The hold-out was already run once for this arm (results/native/holdout_<arm>_run.json). Pass --again to repeat it; that is recorded.")
    memos = {k: v for k, v in json.loads((DATA / "native" / "memos.json").read_text()).items() if v["split"] == split}
    labelled = {c["memo_id"] for c in load_labels(split)}
    memos = {k: v for k, v in memos.items() if k in labelled}
    store = TruthStore()
    runners = {"none": arms.none, "judge_same": arms.judge("judge_same", JUDGE_SAME, store),
               "judge_other": arms.judge("judge_other", JUDGE_OTHER, store), "engine": arms.engine(ENGINE, store)}
    for arm in which:
        fn = runners[arm]
        with ThreadPoolExecutor(workers) as pool:
            recs = list(pool.map(lambda kv: fn(kv[0], kv[1]["text"], kv[1]["ticker"], date.fromisoformat(kv[1]["as_of"])), sorted(memos.items())))
        (OUT / f"{split}_{arm}{suffix}.json").write_text(json.dumps(recs, indent=1))
        print(f"{split}/{arm}: {len(recs)} memos, {sum(r['action'] == 'error' for r in recs)} errors", flush=True)
    meta = {"split": split, "memos": len(memos), "models": {"engine": ENGINE, "judge_same": JUDGE_SAME, "judge_other": JUDGE_OTHER},
            **git_state(), "at": date.today().isoformat()}
    for arm, marker in markers.items():
        marker.write_text(json.dumps({**meta, "arm": arm, "repeat": marker.exists()}, indent=1))
    return meta


def report(split: str, include_borderline: bool = False, suffix: str = "") -> str:
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    labels = load_labels(split)
    sets = {"native memos (written from memory)": [lab for lab in labels if memos[lab["memo_id"]]["drafter"] != "control"],
            "honest controls (written from a table of filing figures)": [lab for lab in labels if memos[lab["memo_id"]]["drafter"] == "control"]}
    L = [f"Native-error test, {split} companies. Labels by a separate labelling agent from the filing documents; agent-labelled, not human-reviewed.", ""]
    for name, labs in sets.items():
        ids = {lab["memo_id"] for lab in labs}
        L += [f"### {name}: {len(ids)} memos, {sum(lab['verdict'] in ('true', 'false') for lab in labs)} labelled claims "
              f"({sum(lab['verdict'] == 'false' for lab in labs)} false)", "",
              "| Arm | Honest memos wrongly stopped | False claims: sentence flagged wrong | ...exact figure named | True claims flagged wrong | ...no false figure in that sentence | Memos with a false claim stopped | Claims it could check at all (any matching quote) | Strict one-to-one count (superseded) | Time / memo |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        detail = []
        for arm in ARMS:
            f = OUT / f"{split}_{arm}{suffix}.json"
            if not f.exists():
                continue
            recs = [r for r in json.loads(f.read_text()) if r["memo_id"] in ids]
            s = score(labs, recs, include_borderline)
            n = max(1, s["memos"])
            L.append(f"| {arm} | {rate(s['clean_stopped'], s['clean_memos'])} | {rate(s['flagged'], s['false_claims'])} | {rate(s['named'], s['false_claims'])} | "
                     f"{rate(s['true_flagged'], s['true_claims'])} | {s['true_flagged_clean']} | {rate(s['flawed_stopped'], s['flawed_memos'])} | "
                     f"{rate(s['checked_loose'], s['labelled'])} | {rate(s['caught'], s['false_claims'])} | {s['seconds'] / n:.0f}s |")
            detail.append((arm, s, recs))
        for arm, s, recs in detail:
            by_writer = []
            for writer in sorted({memos[i]["drafter"] for i in ids}):
                w = {i for i in ids if memos[i]["drafter"] == writer}
                part = score([lab for lab in labs if lab["memo_id"] in w], [r for r in recs if r["memo_id"] in w], include_borderline)
                by_writer.append(f"{writer}: flagged {part['flagged']}/{part['false_claims']}, true flagged {part['true_flagged']}/{part['true_claims']}")
            L += ["", f"{arm}: flagged / named by error class " + (", ".join(f"{c} {v['flagged']}/{v['named']} of {v['n']}" for c, v in sorted(s["by_class_flagged"].items())) or "none")
                  + f"; by memo writer: " + "; ".join(by_writer) + f"; model failures: {s['errors']}"]
        L.append("")
    return "\n".join(L)


def misses_report(split: str, arm: str = "engine", include_borderline: bool = False) -> str:
    """Every failure of one arm, in plain words, so nobody has to take a rate on trust: false claims it missed and why, true claims it called
    wrong, honest memos it stopped."""
    f = OUT / f"{split}_{arm}.json"
    if not f.exists():
        return ""
    labels = load_labels(split)
    recs = json.loads(f.read_text())
    s = score(labels, recs, include_borderline)
    info = {(lab["memo_id"], lab["quote"]): lab for lab in labels}
    L = [f"# Known failures: {arm}, {split} companies", "",
         f"Missed false claims ({len(s['misses'])} of {s['false_claims']}; a miss = no matching claim of the arm was marked wrong). 'not_extracted' = the arm never turned that sentence into a claim; "
         "'unchecked' = it did, but its sources could not settle it; 'ok' = it checked it and called it right.", "",
         "| Memo | Error class | Why missed | Claim | What the filing says (labeller) |", "|---|---|---|---|---|"]
    for m in s["misses"]:
        lab = info.get((m["memo_id"], m["quote"]), {})
        L.append(f"| {m['memo_id']} | {m['error_class']} | {m['why_missed']} | {m['quote'][:90]} | {str(lab.get('filing_value', ''))[:110]} |")
    L += ["", f"True claims flagged wrong ({s['true_flagged']} of {s['true_claims']}); the strict one-to-one list follows, and {s['true_flagged_clean']} of the flagged ones had no false figure beside them:", ""]
    L += [f"- {x['memo_id']}: {x['quote']}  (labeller: {info.get((x['memo_id'], x['quote']), {}).get('filing_value', '')[:100]})" for x in s["false_alarm_list"]] or ["- none"]
    L += ["", f"Memos with no false claim that were stopped ({s['clean_stopped']} of {s['clean_memos']}):", ""]
    L += [f"- {x['memo_id']}: {x['action']}" for x in s["clean_stopped_list"]] or ["- none"]
    L += ["", f"Model failures (counted as misses): {s['errors']}"]
    return "\n".join(L) + "\n"


ARM_NAMES = {"none": "No checker", "judge_same": "Prompt-only judge, same model family", "judge_other": "Prompt-only judge, other model family", "engine": "Engine (model reads, code decides)"}


def headline(split: str = "holdout", suffix: str = "") -> str:
    """The short table for the README and the demo, with the dataset and the models named."""
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    native = [lab for lab in load_labels(split) if memos[lab["memo_id"]]["drafter"] != "control"]
    ctl = [lab for lab in load_labels(split) if memos[lab["memo_id"]]["drafter"] == "control"]
    ids = {lab["memo_id"] for lab in native}
    cids = {lab["memo_id"] for lab in ctl}
    def short(k, n):
        return f"{k}/{n} ({k / n:.0%})" if n else "n/a"
    L = ["| Arm | False claims: sentence flagged wrong | ...exact figure named | Memos with a false claim, stopped | True claims flagged wrong | ...of those, no false figure beside them | Honest control memos wrongly stopped |",
         "|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        f = OUT / f"{split}_{arm}{suffix}.json"
        if not f.exists():
            continue
        recs = json.loads(f.read_text())
        a = score(native, [r for r in recs if r["memo_id"] in ids])
        c = score(ctl, [r for r in recs if r["memo_id"] in cids])
        L.append(f"| {ARM_NAMES[arm]} | {short(a['flagged'], a['false_claims'])} | {short(a['named'], a['false_claims'])} | {short(a['flawed_stopped'], a['flawed_memos'])} | "
                 f"{short(a['true_flagged'], a['true_claims'])} | {a['true_flagged_clean']} | {short(c['clean_stopped'], c['clean_memos'])} |")
    models = f"engine and same-family judge `{ENGINE}`, other-family judge `{JUDGE_OTHER}`"
    return (f"{split} companies, {len(ids)} memos drafted from memory by two free models (the same memos and labels), {sum(lab["verdict"] in ("true", "false") and not lab.get("borderline") for lab in native)} claims labelled from the filings by a separate agent "
            f"(agent-labelled, not human-reviewed); {"free" if "free" in ENGINE else "paid"} models: {models}.\n\n" + "\n".join(L))


def changed_decisions(split: str = "holdout", suffix: str = "_post_audit") -> str:
    """Engine decisions and counts before and after a change made after the hold-out was seen. The frozen records are never overwritten."""
    memos = json.loads((DATA / "native" / "memos.json").read_text())
    old = {r["memo_id"]: r for r in json.loads((OUT / f"{split}_engine.json").read_text())}
    new = {r["memo_id"]: r for r in json.loads((OUT / f"{split}_engine{suffix}.json").read_text())}
    L = [f"# Engine after a change made after the {split} was seen ({suffix.strip('_')})", "",
         "Replayed from recorded model answers; no model was called. The frozen result (`results/native/holdout_engine.json`) is unchanged and remains the result.", ""]
    diff = [(k, old[k]["action"], new[k]["action"]) for k in sorted(old) if old[k]["action"] != new[k]["action"]]
    claim_diff = [k for k in sorted(old) if [(c["quote"], c["verdict"]) for c in old[k]["claims"]] != [(c["quote"], c["verdict"]) for c in new[k]["claims"]]]
    L.append(f"Memos whose decision changed: {len(diff)}" + "".join(f"\n- {k}: {a} -> {b}" for k, a, b in diff))
    L.append(f"\nMemos whose claim verdicts changed: {len(claim_diff)}" + "".join(f"\n- {k}" for k in claim_diff))
    labels = load_labels(split)
    for name, kind in (("native memos", False), ("honest controls", True)):
        labs = [lab for lab in labels if (memos[lab["memo_id"]]["drafter"] == "control") == kind]
        ids = {lab["memo_id"] for lab in labs}
        for tag, recs in (("frozen", old), ("after", new)):
            s = score(labs, [r for k, r in recs.items() if k in ids])
            L.append(f"\n{name}, engine {tag}: flagged {s['flagged']}/{s['false_claims']}, named {s['named']}, true flagged {s['true_flagged']}/{s['true_claims']}, "
                     f"memos stopped (honest) {s['clean_stopped']}/{s['clean_memos']}")
    return "\n".join(L) + "\n"
