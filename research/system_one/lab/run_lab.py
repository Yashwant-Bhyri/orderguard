#!/usr/bin/env python3
"""System One lab runner: it keeps work flowing while the lead is away.

For each task brief in tasks/*.md whose dependencies have passed, it:
  1. runs the worker (DeepSeek or another model through OpenCode Go, or Codex for GPU work) on the brief;
  2. runs the brief's check command;
  3. runs a fresh, adversarial Codex review that writes REVIEW.md with a verdict;
  4. on REVISE, gives the review back to the worker (up to max_rounds), and on ESCALATE asks the escalation reviewer
     one precise question from ESCALATION.md.

All state lives on disk (lab/state.json, lab/events.log, STATUS.md), so the runner can be stopped and restarted at any time.
Standard library only. It never runs git and never prints secrets: the worker key is read by variable name from an env file
and passed only to the worker process.

Usage:
  python3 lab/run_lab.py --loop            run until nothing is left to do
  python3 lab/run_lab.py --status          print the board
  python3 lab/run_lab.py --reset T03       put a task back to pending (keeps its history)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]            # research/system_one
LAB = ROOT / "lab"
TASKS = ROOT / "tasks"
WORK = ROOT / "work"
RUNS = ROOT / "runs"
HELDOUT = ROOT / "data" / "heldout"
STATE = LAB / "state.json"
EVENTS = LAB / "events.log"
STATUS = ROOT / "STATUS.md"
CONFIG = json.loads((LAB / "config.json").read_text())
ISO_ROOT = Path(os.environ.get("OG_S1_ISO_ROOT", str(Path.home() / ".og_s1_isolated")))
import threading
_LOCK = threading.RLock()
TERMINAL = {"passed", "failed", "needs-lead", "blocked"}
SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|oc_sk_[A-Za-z0-9_]{16,}|apikey_[A-Za-z0-9_]{16,}|sk_[a-f0-9]{24,})")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Codex usage limits (2026-11-19): when Codex is out of quota, reviews and the steward fall back to DeepSeek at max
# reasoning, Codex-worker tasks wait, escalations are skipped, and no round is spent on a quota failure.
CODEX_DOWN_FILE = Path(__file__).resolve().parent / "codex_down_until"


def codex_down() -> bool:
    try:
        until = CODEX_DOWN_FILE.read_text().strip()
        return datetime.now(timezone.utc) < datetime.fromisoformat(until.replace("Z", "+00:00"))
    except (FileNotFoundError, ValueError):
        return False


def quota_hit(log_file: Path) -> bool:
    try:
        return "hit your usage limit" in log_file.read_text(errors="ignore").rsplit("\n===== ", 1)[-1]
    except FileNotFoundError:
        return False


def mark_codex_down(hours: float = 6) -> None:
    from datetime import timedelta
    until = datetime.now(timezone.utc) + timedelta(hours=hours)
    try:                                   # never shorten a known, later reset time
        known = datetime.fromisoformat(CODEX_DOWN_FILE.read_text().strip().replace("Z", "+00:00"))
        until = max(until, known)
    except (FileNotFoundError, ValueError):
        pass
    CODEX_DOWN_FILE.write_text(until.strftime("%Y-%m-%dT%H:%M:%SZ"))


def deepseek_cmd(cwd: Path, variant: str = "max") -> list[str]:
    return ["opencode", "run", "-m", CONFIG.get("fallback_model", "opencode-go/deepseek-v4.1-flash"), "--dir", str(cwd),
            "--variant", variant]


def log(msg: str) -> None:
    line = f"{now()} {msg}"
    with _LOCK:
        print(line, flush=True)
        with EVENTS.open("a") as f:
            f.write(line + "\n")


# --------------------------------------------------------------------------------------------------------------------
# Tasks and state
# --------------------------------------------------------------------------------------------------------------------

def parse_task(path: Path) -> dict:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    meta = {}
    for line in (m.group(1) if m else "").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    meta["depends"] = [d.strip() for d in meta.get("depends", "").split(",") if d.strip()]
    meta["inputs"] = [d.strip() for d in meta.get("inputs", "").split(",") if d.strip()]
    meta["isolate"] = meta.get("isolate", "false").lower() == "true"
    meta["env_keys"] = [d.strip() for d in meta.get("env_keys", "").split(",") if d.strip()]
    meta["timeout_min"] = int(meta.get("timeout_min", CONFIG["worker_timeout_min"]))
    meta["max_rounds"] = int(meta.get("max_rounds", 3))
    meta["brief"] = path
    return meta


def load_tasks() -> dict[str, dict]:
    return {t["id"]: t for t in (parse_task(p) for p in sorted(TASKS.glob("T*.md")))}


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"tasks": {}, "budget": {}, "checkpoints": []}


def save_state(st: dict) -> None:
    with _LOCK:
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2))
        tmp.replace(STATE)


def tstate(st: dict, tid: str) -> dict:
    return st["tasks"].setdefault(tid, {"status": "pending", "round": 0, "history": []})


def budget_ok(st: dict, kind: str) -> bool:
    day = now()[:10]
    used = st["budget"].get(day, {}).get(kind, 0)
    return used < CONFIG["budget_per_day"][kind]


def spend(st: dict, kind: str) -> None:
    day = now()[:10]
    st["budget"].setdefault(day, {}).setdefault(kind, 0)
    st["budget"][day][kind] += 1


def free_gb() -> float:
    return shutil.disk_usage(ROOT).free / 1e9


# --------------------------------------------------------------------------------------------------------------------
# Folders: a task works in work/<id> (in the repo), or, if isolated, in a folder outside the repo with only its inputs
# --------------------------------------------------------------------------------------------------------------------

def task_dir(task: dict) -> Path:
    return (ISO_ROOT / task["id"]) if task["isolate"] else (WORK / task["id"])


def prepare(task: dict) -> Path:
    d = task_dir(task)
    d.mkdir(parents=True, exist_ok=True)
    (WORK / task["id"]).mkdir(parents=True, exist_ok=True)
    if task["isolate"]:
        brief = task["brief"].read_text()
        brief = re.sub(r"^---\n.*?\n---\n", "", brief, flags=re.S)      # authors see the brief, not our task metadata
        (d / "BRIEF.md").write_text(brief)
        for rel in task["inputs"]:
            src = ROOT / rel
            dst = d / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy2(src, dst)
    if task["isolate"]:
        write_opencode_config(d, isolated=True)
    else:
        write_opencode_config(ROOT, isolated=False)
    return d


def write_opencode_config(d: Path, *, isolated: bool) -> None:
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {"opencode-go": {"options": {"apiKey": "{env:OPENCODE_API_KEY}"}}},
        "snapshot": False,  # undo snapshots copied the whole repo (2.5 GB per run)
        "permission": {
            "edit": "allow",
            "webfetch": "allow",
            "external_directory": "deny" if isolated else "allow",
            "bash": {"*": "allow", "git *": "deny", "git": "deny", "sudo *": "deny", "rm -rf /*": "deny", "rm -rf ~*": "deny"},
        },
    }
    (d / "opencode.json").write_text(json.dumps(cfg, indent=2))


def sync_back(task: dict) -> None:
    """Isolated tasks: copy small files back into work/<id>, and generated data (out/) into data/heldout/<id>."""
    if not task["isolate"]:
        return
    src = task_dir(task)
    dst = WORK / task["id"]
    for p in src.rglob("*"):
        if p.is_dir() or "/.venv/" in str(p) or "__pycache__" in str(p) or p.name == "opencode.json":
            continue
        rel = p.relative_to(src)
        if rel.parts[0] == "out":
            target = HELDOUT / task["id"] / rel
        elif p.stat().st_size > 5_000_000:
            continue
        else:
            target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


# --------------------------------------------------------------------------------------------------------------------
# Processes
# --------------------------------------------------------------------------------------------------------------------

def read_env_key(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env_file = os.environ.get("OG_ENV_FILE") or CONFIG.get("env_file_hint")
    if env_file and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return None


def child_env(with_worker_key: bool, isolated: bool = False, extra_keys: list[str] | None = None) -> dict:
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL", "SEC_USER_AGENT", "HF_HOME")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    if not isolated:                                   # isolated authors get no pointer into the repo
        env["PATH"] = f"{ROOT / '.venv' / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
        env["HF_HOME"] = str(ROOT / "data" / "models" / "hf")
        env["PYTHONPATH"] = str(ROOT)
    if with_worker_key:
        key = read_env_key("OPENCODE_API_KEY")
        if key:
            env["OPENCODE_API_KEY"] = key
    for name in extra_keys or []:                      # keys a brief asks for by name, e.g. OPENROUTER_API_KEY
        val = read_env_key(name)
        if val:
            env[name] = val
    return env


def run(cmd: list[str], cwd: Path, logfile: Path, timeout_s: int, env: dict) -> int:
    logfile.parent.mkdir(parents=True, exist_ok=True)
    oc_data = None
    if cmd and cmd[0] == "opencode":                     # a private, throwaway OpenCode store per run: the shared
        oc_data = logfile.parent / f".ocdata-{os.getpid()}-{int(time.time())}"   # opencode.db grew by GBs a day
        oc_data.mkdir(parents=True, exist_ok=True)
        env = dict(env, XDG_DATA_HOME=str(oc_data))
    try:
        return _run(cmd, cwd, logfile, timeout_s, env)
    finally:
        if oc_data is not None:
            shutil.rmtree(oc_data, ignore_errors=True)


def _run(cmd: list[str], cwd: Path, logfile: Path, timeout_s: int, env: dict) -> int:
    with logfile.open("a") as out:
        out.write(f"\n===== {now()} {' '.join(cmd[:4])} ... (cwd={cwd.name})\n")
        out.flush()
        p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                             start_new_session=True)
        try:
            return p.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM, signal.SIGKILL):      # macOS may refuse killpg on a group: fall back to the pid
                try:
                    os.killpg(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    try:
                        p.send_signal(sig)
                    except (ProcessLookupError, PermissionError):
                        pass
                time.sleep(5)
            out.write(f"\n===== TIMEOUT after {timeout_s}s\n")
            return 124


def scrub(path: Path) -> None:
    """Belt and braces: redact anything that looks like a key from logs the lab keeps."""
    if path.exists() and path.stat().st_size < 50_000_000:
        txt = path.read_text(errors="replace")
        new = SECRET_RE.sub("[REDACTED]", txt)
        if new != txt:
            path.write_text(new)


def codex_cmd(model: str, effort: str, cwd: Path, out_file: Path, sandbox: str = "workspace-write", network: bool = True,
              extra_dirs: list[Path] | None = None) -> list[str]:
    cmd = [CONFIG["codex_bin"].replace("~", str(Path.home())), "exec", "--skip-git-repo-check", "--ephemeral", "-m", model,
           "-c", f"model_reasoning_effort=\"{effort}\"", "-s", sandbox, "-C", str(cwd), "-o", str(out_file)]
    if network and sandbox == "workspace-write":
        cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    for d in extra_dirs or []:
        cmd += ["--add-dir", str(d)]
    return cmd


# --------------------------------------------------------------------------------------------------------------------
# One round: worker, check, review
# --------------------------------------------------------------------------------------------------------------------

def worker_prompt(task: dict, d: Path, rnd: int) -> str:
    if task["isolate"]:
        brief, policy_line = "BRIEF.md (in this folder)", "Follow the rules in BRIEF.md."
        folder = "this folder"
    else:
        brief = str(task["brief"].relative_to(ROOT))
        policy_line = "Read POLICY.md first and follow it exactly."
        folder = f"work/{task['id']}/"
    p = (f"You are a worker in the OrderGuard System One research lab. {policy_line} Your task brief is {brief}. Read it fully, "
         f"then do the whole task end to end without asking questions: nobody will answer, and waiting is a failure. Make "
         f"documented judgement calls instead. Your task folder is {folder}. Use the Python at .venv/bin/python if it exists "
         f"(python3 otherwise). Never run git. Never print or write secrets. Finish by writing REPORT.md in your task folder "
         f"with the required sections, and make sure the brief's run.sh reproduces every number.")
    if rnd > 1:
        p += (f" This is round {rnd}. A reviewer returned REVISE. Read REVIEW.md in your task folder (and SOL_ADVICE.md if "
              f"present), fix every item in order of importance, re-run everything, and add a section 'Round {rnd} changes' "
              f"to REPORT.md saying what you changed and what you did not and why.")
    return p


def hermes_cmd(cwd: Path, prompt: str, rundir: Path, name: str, timeout_s: int, reasoning: str = "max") -> list[str]:
    """Qwen-4 Max through the Hermes agent (Nous free tier; founder, 2026-11-20). The prompt goes through a file."""
    qf = rundir / f"{name}_prompt.md"
    qf.parent.mkdir(parents=True, exist_ok=True)
    qf.write_text(prompt)
    return ["hermes", "chat", "--query-file", str(qf), "--oneshot", "-Q", "--in", str(cwd), "--yolo",
            "--max-turns", str(CONFIG.get("hermes_max_turns", 250)), "--run-budget", str(timeout_s),
            "--reasoning", reasoning]


def hermes_env(isolated: bool, extra_keys: list[str] | None = None) -> dict:
    env = child_env(False, isolated, extra_keys)
    env["PATH"] = f"{LAB / 'shims'}:{env.get('PATH', '/usr/bin:/bin')}"   # a git shim that refuses: workers never run git
    return env


def run_worker(task: dict, d: Path, rnd: int, rundir: Path) -> int:
    timeout_s = task["timeout_min"] * 60
    if task["worker"] == "codex-gpu":
        brief = re.sub(r"^---\n.*?\n---\n", "", task["brief"].read_text(), flags=re.S)
        prompt = brief + ("\n\nYour Mac-side task folder is the current directory. Write HOWTO.md, SMOKE.md, READY or BLOCKED.md here."
                          + (f" This is round {rnd}: read REVIEW.md here and address it." if rnd > 1 else ""))
        cmd = codex_cmd(CONFIG["gpu_model"], CONFIG["gpu_effort"], d, rundir / "worker_last.md")
        return run(cmd + [prompt], d, rundir / "worker.log", timeout_s, child_env(False))
    if task["worker"].startswith("codex:"):
        cwd = d if task["isolate"] else ROOT
        cmd = codex_cmd(task["worker"].split(":", 1)[1], task.get("variant") or "xhigh", cwd, rundir / "worker_last.md",
                        network=not task["isolate"])
        return run(cmd + [worker_prompt(task, d, rnd)], cwd, rundir / "worker.log", timeout_s, child_env(False))
    if task["worker"].startswith("hermes:"):
        cwd = d if task["isolate"] else ROOT
        return run(hermes_cmd(cwd, worker_prompt(task, d, rnd), rundir, "worker", timeout_s, task.get("variant") or "xhigh"),
                   cwd, rundir / "worker.log",
                   timeout_s, hermes_env(task["isolate"], task["env_keys"]))
    cwd = d if task["isolate"] else ROOT
    cmd = ["opencode", "run", "-m", task["worker"], "--dir", str(cwd)]
    if task.get("variant"):
        cmd += ["--variant", task["variant"]]
    cmd.append(worker_prompt(task, d, rnd))
    return run(cmd, cwd, rundir / "worker.log", timeout_s, child_env(True, task["isolate"], task["env_keys"]))


def review_prompt(task: dict, d: Path) -> str:
    where = "this folder" if task["isolate"] else f"work/{task['id']}/"
    brief = "BRIEF.md" if task["isolate"] else str(task["brief"].relative_to(ROOT))
    policy = "" if task["isolate"] else " and POLICY.md"
    return (
        f"You are the adversarial reviewer for one task in the OrderGuard System One research lab. Read {brief}{policy}, then the "
        f"worker's REPORT.md and check.log in {where}. If SOL_ADVICE.md exists there, it is a binding ruling by the lead or the "
        f"escalation reviewer: check that the work follows it. Nothing else is context: do not assume anything the files do not show. "
        f"Re-run the task's entry point yourself. Hunt for: test-set peeking or leakage, isolation breaches, metrics computed "
        f"wrongly, hard-coded or hand-typed results, seeds or thresholds chosen after seeing test data, numbers in REPORT.md that "
        f"do not match what the code prints, missing pass-bar items, overclaims, secrets or absolute home paths in files, and "
        f"anything that would make the result weak or fragile. Do not edit the worker's code. Write REVIEW.md in {where}. Its "
        f"first line must be exactly one of: 'VERDICT: PASS', 'VERDICT: REVISE', 'VERDICT: FAIL', 'VERDICT: ESCALATE'. Then: "
        f"what you re-ran and what it printed; each pass-bar item with met/not met; a numbered list of required fixes in order "
        f"of importance (for REVISE); loopholes found. Write REVIEW.md EARLY, with a provisional verdict line, and update it as you "
        f"go, so a timeout never leaves you without a review. PASS only if every pass-bar item is met and every number reproduces. Use "
        f"ESCALATE only for a high-level question you cannot settle yourself: an architecture choice, whether a claim is sound, "
        f"or a methodology dispute. Never escalate a bug, a missing file, a style point or anything a REVISE can fix. Then also write ESCALATION.md with: the problem, what was "
        f"tried, the gray area, and one precise question, self-contained and under 600 words.")


def run_review(task: dict, d: Path, rundir: Path, st: dict) -> str:
    kind = "fallback_reviews" if codex_down() else "reviews"
    if not budget_ok(st, kind):
        log(f"{task['id']}: {kind} budget for today used up; the work is kept and waits for review")
        return "WAIT"
    spend(st, kind)
    save_state(st)
    (d / "REVIEW.md").unlink(missing_ok=True)
    cwd = d if task["isolate"] else ROOT
    if codex_down():
        # never review with the family that wrote the work: Qwen reviews DeepSeek's work, DeepSeek reviews Qwen's
        use_qwen = CONFIG.get("fallback_reviewer", "deepseek") == "hermes" and not task["worker"].startswith("hermes:")
        if use_qwen:
            log(f"{task['id']}: Codex is out of quota; reviewing with Qwen-4 Max (Hermes), a different family")
            t = CONFIG["review_timeout_min"] * 60
            rc = run(hermes_cmd(cwd, review_prompt(task, d), rundir, "review", t), cwd, rundir / "review.log", t,
                     hermes_env(task["isolate"], task["env_keys"]))
        else:
            log(f"{task['id']}: Codex is out of quota; reviewing with DeepSeek at max reasoning")
            rc = run(deepseek_cmd(cwd) + [review_prompt(task, d)], cwd, rundir / "review.log",
                     CONFIG["review_timeout_min"] * 60, child_env(True, task["isolate"], task["env_keys"]))
    else:
        cmd = codex_cmd(CONFIG["review_model"], CONFIG["review_effort"], cwd, rundir / "review_last.md")
        rc = run(cmd + [review_prompt(task, d)], cwd, rundir / "review.log", CONFIG["review_timeout_min"] * 60,
                 child_env(False, False, task["env_keys"]))
    review = d / "REVIEW.md"
    if not review.exists() and quota_hit(rundir / "review.log"):
        mark_codex_down()
        log(f"{task['id']}: Codex usage limit hit during review; round not counted, retrying with the fallback")
        return "WAIT"
    if not review.exists():
        log(f"{task['id']}: reviewer exited {rc} without REVIEW.md")
        return "ERROR"
    head = review.read_text().strip().splitlines()[:6]          # reviewers sometimes put a heading above the verdict
    line = next((x for x in head if re.match(r"\s*\**VERDICT:", x)), "")
    m = re.match(r"\s*\**VERDICT:\**\s*(PASS|REVISE|FAIL|ESCALATE)", line)
    if m and re.search(r"provisional|in progress", " ".join(head[:3]), re.I):
        log(f"{task['id']}: the review stopped while still provisional; the work is kept and the review is redone")
        return "WAIT"                                           # an unfinished review is not a verdict
    return m.group(1) if m else "ERROR"


def run_escalation(task: dict, d: Path, rundir: Path, st: dict) -> bool:
    esc = d / "ESCALATION.md"
    if not esc.exists() or not budget_ok(st, "escalations") or codex_down():
        return False
    spend(st, "escalations")
    save_state(st)
    prompt = ("Read ESCALATION.md in the current folder, and only the files it explicitly names. Answer its question precisely: "
              "recommend one course of action, say why, and list the risks. Under 500 words. Your answer is passed to the "
              "worker as SOL_ADVICE.md.")
    out = rundir / "sol_answer.md"
    run(codex_cmd(CONFIG["escalation_model"], CONFIG["escalation_effort"], d, out, sandbox="read-only", network=False) + [prompt],
        d, rundir / "escalation.log", CONFIG["review_timeout_min"] * 60, child_env(False))
    if out.exists():
        shutil.copy2(out, d / "SOL_ADVICE.md")
        return True
    return False


def archive(task: dict, d: Path, rundir: Path) -> None:
    for name in ("REPORT.md", "REVIEW.md", "ESCALATION.md", "SOL_ADVICE.md", "BLOCKED.md", "check.log"):
        if (d / name).exists():
            shutil.copy2(d / name, rundir / name)
    for p in rundir.glob("*.log"):
        scrub(p)


def pids_for(task: dict, rnd: int, kind: str) -> list[int]:
    """Live worker or reviewer processes of one task round: OpenCode, Codex or Hermes, in the repo or an isolated folder."""
    tid, td, rd = task["id"], str(task_dir(task)), f"/runs/{task['id']}/round{rnd}/"
    if kind == "worker":
        pats = [task["brief"].name, td + " --yolo", rd + "worker_prompt.md"]
        if task["isolate"]:
            pats.append(f"--dir {td} --variant {task.get('variant') or ''}".rstrip())
    else:
        pats = [f"work/{tid}/", f"--dir {td} --variant max You are the adversarial", rd + "review_prompt.md"]
    out: list[int] = []
    for p in pats:
        out += [x for x in live_pids(p) if x not in out]
    return out


def live_pids(pattern: str) -> list[int]:
    """Processes left over from a previous runner (it was restarted while a worker or reviewer was busy)."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    me = os.getpid()
    pids = []
    for line in out.splitlines():
        line = line.strip()
        if pattern in line and "run_lab.py" not in line and "ps -axo" not in line:
            pid = int(line.split(None, 1)[0])
            if pid != me:
                pids.append(pid)
    return pids


def wait_for(pids: list[int], timeout_s: int) -> None:
    end = time.time() + timeout_s
    while time.time() < end and any(_alive(p) for p in pids):
        time.sleep(15)
    for p in pids:                                 # past the limit: stop it, so a hung worker never edits under a review
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if _alive(p):
                try:
                    os.kill(p, sig)
                except (ProcessLookupError, PermissionError):
                    pass
                time.sleep(3)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def one_round(task: dict, st: dict, adopt: str | None = None) -> None:
    tid = task["id"]
    ts = tstate(st, tid)
    if adopt is None:
        ts["round"] += 1
    rnd = ts["round"]
    ts["status"] = "reviewing" if adopt == "review" else "working"   # an adopted review must stay a review on restart
    ts["started"] = now()
    save_state(st)
    d = prepare(task)
    rundir = RUNS / tid / f"round{rnd}"
    rundir.mkdir(parents=True, exist_ok=True)
    if adopt == "worker":
        pids = pids_for(task, rnd, "worker")
        log(f"{tid}: round {rnd} adopting running worker {pids}")
        wait_for(pids, task["timeout_min"] * 60)
        rc = 0
    elif adopt == "skipworker":
        rc = 0
    elif adopt == "review":
        pids = pids_for(task, rnd, "review")
        log(f"{tid}: round {rnd} adopting running review {pids}")
        wait_for(pids, CONFIG["review_timeout_min"] * 60)
        rc = 0
    else:
        log(f"{tid}: round {rnd} worker start ({task['worker']})")
        rc = run_worker(task, d, rnd, rundir)
        log(f"{tid}: round {rnd} worker exit {rc}")
        if rc != 0 and task["worker"].startswith("codex") and quota_hit(rundir / "worker.log"):
            mark_codex_down()
            ts["round"] -= 1
            ts["status"] = "pending" if ts["round"] == 0 else "revise"
            save_state(st)
            log(f"{tid}: Codex usage limit; round not counted, task waits for Codex")
            return
    if adopt == "review" and (d / "REVIEW.md").exists():
        return finish_review(task, st, d, rundir, rnd, rc)
    sync_back(task)
    if (d / "BLOCKED.md").exists() and not (d / "READY").exists():
        ts["status"] = "blocked"
        archive(task, d, rundir)
        sync_back(task)
        log(f"{tid}: BLOCKED — see work/{tid}/BLOCKED.md")
        save_state(st)
        return
    if task["worker"] != "codex-gpu" and not (d / "REPORT.md").exists():
        # the worker produced no report: retry without spending a review
        ts["history"].append({"round": rnd, "worker_rc": rc, "verdict": "NO-OUTPUT", "at": now()})
        ts["status"] = "revise" if rnd < task["max_rounds"] else "needs-lead"
        archive(task, d, rundir)
        log(f"{tid}: round {rnd} produced no REPORT.md; review skipped ({ts['status']})")
        save_state(st)
        return
    if task.get("check"):
        run(["bash", "-lc", task["check"]], d, d / "check.log", 45 * 60, child_env(False, False, task["env_keys"]))
    sync_back(task)
    ts["status"] = "reviewing"
    save_state(st)
    verdict = run_review(task, d, rundir, st)
    finish_review(task, st, d, rundir, rnd, rc, verdict)


def finish_review(task: dict, st: dict, d: Path, rundir: Path, rnd: int, rc: int, verdict: str | None = None) -> None:
    tid = task["id"]
    ts = tstate(st, tid)
    if verdict is None:
        first = (d / "REVIEW.md").read_text().strip().splitlines()[0] if (d / "REVIEW.md").read_text().strip() else ""
        m = re.match(r"VERDICT:\s*(PASS|REVISE|FAIL|ESCALATE)", first)
        verdict = m.group(1) if m else "ERROR"
    archive(task, d, rundir)
    sync_back(task)
    ts["history"].append({"round": rnd, "worker_rc": rc, "verdict": verdict, "at": now()})
    log(f"{tid}: round {rnd} verdict {verdict}")
    if verdict == "PASS":
        ts["status"] = "passed"
    elif verdict == "WAIT":
        ts["status"] = "review-wait"                    # keep the round's work; only the review is retried
    elif verdict == "ESCALATE" and run_escalation(task, d, rundir, st) and rnd < task["max_rounds"]:
        ts["status"] = "revise"
    elif verdict in ("REVISE", "ESCALATE", "ERROR") and rnd < task["max_rounds"]:
        ts["status"] = "revise"
    elif verdict == "FAIL":
        ts["status"] = "failed"
    else:
        ts["status"] = "needs-lead"
    save_state(st)


# --------------------------------------------------------------------------------------------------------------------
# Scheduler
# --------------------------------------------------------------------------------------------------------------------

def ready(task: dict, st: dict) -> bool:
    ts = tstate(st, task["id"])
    if ts["status"] not in ("pending", "revise"):
        return False
    if task["worker"].startswith("codex") and codex_down():
        return False
    return all(tstate(st, dep)["status"] == "passed" for dep in task["depends"])


def checkpoints(tasks: dict, st: dict) -> None:
    for name, ids in CONFIG["checkpoints"].items():
        if name in st["checkpoints"]:
            continue
        if all(tstate(st, i)["status"] in TERMINAL for i in ids if i in tasks):
            st["checkpoints"].append(name)
            with (LAB / "CHECKPOINTS.md").open("a") as f:
                f.write(f"- {now()} checkpoint **{name}** reached: "
                        + ", ".join(f"{i}={tstate(st, i)['status']}" for i in ids) + "\n")
            log(f"CHECKPOINT {name}")
    save_state(st)


def write_status(tasks: dict, st: dict) -> None:
    rows = ["# Lab status", "", f"Updated {now()} by lab/run_lab.py. Do not edit by hand.", "",
            "| Task | Title | Worker | Status | Round | Last verdict | Depends on |", "|---|---|---|---|---|---|---|"]
    for tid, t in tasks.items():
        ts = tstate(st, tid)
        last = ts["history"][-1]["verdict"] if ts["history"] else ""
        rows.append(f"| {tid} | {t.get('title', '')} | {t['worker']} | {ts['status']} | {ts['round']} | {last} | "
                    f"{', '.join(t['depends'])} |")
    day = now()[:10]
    rows += ["", f"Budget used today: {json.dumps(st['budget'].get(day, {}))}. Free disk: {free_gb():.1f} GB.",
             "", "Checkpoints reached: " + (", ".join(st["checkpoints"]) or "none")]
    STATUS.write_text("\n".join(rows) + "\n")


def loop() -> None:
    pidfile = LAB / "runner.pid"
    if pidfile.exists():
        try:
            os.kill(int(pidfile.read_text()), 0)
            sys.exit("another runner is already running")
        except (ProcessLookupError, ValueError):
            pass
    pidfile.write_text(str(os.getpid()))
    from concurrent.futures import ThreadPoolExecutor
    lock = _LOCK
    st = load_state()
    tasks0 = load_tasks()
    adopt: dict[str, str] = {}
    for tid, ts in st["tasks"].items():                 # a restart mid-round: adopt a live process, else redo the round
        if ts["status"] in ("working", "reviewing") and tid in tasks0:
            t = tasks0[tid]
            if ts["status"] == "working" and pids_for(t, ts["round"], "worker"):
                adopt[tid] = "worker"
            elif ts["status"] == "reviewing" and pids_for(t, ts["round"], "review"):
                adopt[tid] = "review"
            else:
                ts["status"] = "revise" if ts["round"] > 1 else "pending"
                ts["round"] -= 1
    save_state(st)
    log(f"runner start (adopting {adopt or 'nothing'})")
    running: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=CONFIG["parallel"]) as pool:
        for tid, how in adopt.items():
            running[tid] = pool.submit(one_round, tasks0[tid], st, how)
        while True:
            tasks = load_tasks()
            with lock:
                for req in sorted((LAB / "requests").glob("*.reopen")) if (LAB / "requests").exists() else []:
                    tid = req.stem                         # lead grants another round, keeping the round count
                    if tid in running:
                        continue
                    tstate(st, tid)["status"] = "revise"
                    req.unlink()
                    log(f"{tid}: reopened for another round by lead")
                for tid, ts_ in list(st["tasks"].items()):
                    if ts_.get("status") == "review-wait" and tid in tasks and tid not in running \
                            and len(running) < CONFIG["parallel"] \
                            and budget_ok(st, "fallback_reviews" if codex_down() else "reviews"):
                        log(f"{tid}: round {ts_['round']} retrying the review (work kept)")
                        running[tid] = pool.submit(one_round, tasks[tid], st, "skipworker")
                for req in sorted((LAB / "requests").glob("*.review")) if (LAB / "requests").exists() else []:
                    tid = req.stem                         # lead (or a lead-run subagent) did the round's work
                    if tid in running or tid not in tasks:
                        continue
                    req.unlink()
                    ts = tstate(st, tid)
                    ts["round"] += 1
                    log(f"{tid}: round {ts['round']} work supplied by the lead; running check and review")
                    running[tid] = pool.submit(one_round, tasks[tid], st, "skipworker")
                for req in sorted((LAB / "requests").glob("*.reset")) if (LAB / "requests").exists() else []:
                    tid = req.stem
                    if tid in running:
                        continue                         # never reset a task mid-round; try again next loop
                    ts = tstate(st, tid)
                    ts["status"], ts["round"] = "pending", 0
                    req.unlink()
                    log(f"{tid}: reset to pending by lead")
                save_state(st)
                for tid in [k for k, f in running.items() if f.done()]:
                    exc = running.pop(tid).exception()
                    if exc and tid.startswith("_"):
                        log(f"{tid}: error {exc!r}")
                    elif exc:
                        log(f"{tid}: runner error {exc!r}")
                        tstate(st, tid)["status"] = "needs-lead"
                checkpoints(tasks, st)
                write_status(tasks, st)
                todo = [t for t in tasks.values() if t["id"] not in running and ready(t, st)]
                if not [k for k in running if not k.startswith("_")] and not todo:
                    promoted = promote_backlog(tasks, st)       # never stall: lead-approved backlog first, then the steward
                    if promoted:
                        log(f"idle: promoted {promoted} from the backlog")
                        continue
                    if "_steward" not in running and steward_due(st):
                        st["last_steward"] = now()
                        save_state(st)
                        log("idle: starting the steward")
                        running["_steward"] = pool.submit(run_steward)
                if free_gb() < CONFIG["min_free_gb"]:
                    log(f"disk low ({free_gb():.1f} GB); not starting new work")
                    todo = []
                prio = CONFIG.get("priority", [])
                todo.sort(key=lambda t: prio.index(t["id"]) if t["id"] in prio else len(prio))
                for t in todo[: max(0, CONFIG["parallel"] - len(running))]:
                    tstate(st, t["id"])["status"] = "working"
                    running[t["id"]] = pool.submit(one_round, t, st)
            time.sleep(20)
    write_status(load_tasks(), st)
    pidfile.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------------------------------
# Never stall (founder, 2026-11-19): when nothing is runnable, promote a lead-approved backlog brief whose dependencies
# have passed; if there is none, run the steward (Codex Luna) at most once every few hours to diagnose and propose.
BACKLOG = LAB / "backlog"


def promote_backlog(tasks: dict, st: dict) -> str | None:
    if not BACKLOG.exists():
        return None
    for f in sorted(BACKLOG.glob("*.md")):
        m = re.search(r"^depends:\s*(.*)$", f.read_text(), flags=re.M)
        deps = [d.strip() for d in (m.group(1) if m else "").split(",") if d.strip()]
        if all(st["tasks"].get(d, {}).get("status") == "passed" for d in deps):
            target = ROOT / "tasks" / f.name
            if not target.exists():
                f.rename(target)
                return f.stem
    return None


def steward_due(st: dict) -> bool:
    last = st.get("last_steward")
    if not last:
        return True
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() \
            > CONFIG.get("steward_every_h", 3) * 3600
    except ValueError:
        return True


def run_steward() -> int:
    rundir = ROOT / "runs" / "_steward" / now().replace(":", "")
    rundir.mkdir(parents=True, exist_ok=True)
    prompt = (LAB / "STEWARD_PROMPT.md").read_text()
    if codex_down():
        return run(deepseek_cmd(ROOT) + [prompt], ROOT, rundir / "steward.log", CONFIG["review_timeout_min"] * 60,
                   child_env(True))
    cmd = codex_cmd(CONFIG["review_model"], CONFIG["review_effort"], ROOT, rundir / "steward_last.md")
    return run(cmd + [prompt], ROOT, rundir / "steward.log", CONFIG["review_timeout_min"] * 60, child_env(False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--reset", metavar="TASK")
    ap.add_argument("--reopen", metavar="TASK", help="grant one more round (lead), keeping history")
    a = ap.parse_args()
    if a.reset:
        pid_file = LAB / "runner.pid"
        alive = False
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 0)
                alive = True
            except (ProcessLookupError, ValueError):
                pass
        if alive:                                        # the running runner owns state.json: hand it a request
            (LAB / "requests").mkdir(exist_ok=True)
            (LAB / "requests" / f"{a.reset}.reset").write_text(now())
            print(f"reset of {a.reset} queued for the running runner")
        else:
            st = load_state()
            ts = tstate(st, a.reset)
            ts["status"], ts["round"] = "pending", 0
            save_state(st)
            log(f"{a.reset}: reset to pending by lead")
    if a.reopen:
        (LAB / "requests").mkdir(exist_ok=True)
        (LAB / "requests" / f"{a.reopen}.reopen").write_text(now())
        print(f"reopen of {a.reopen} queued (the runner must be running, or start it)")
    if a.status:
        tasks, st = load_tasks(), load_state()
        write_status(tasks, st)
        print(STATUS.read_text())
    if a.loop:
        loop()


if __name__ == "__main__":
    main()
