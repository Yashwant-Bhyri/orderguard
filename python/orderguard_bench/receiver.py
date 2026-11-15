"""Drive the TypeScript receiver benchmarks (receiver/bench/*) and audit their SQLite ledgers with the Python auditor.

  export_workload   envelopes' full order streams from a Python run's decision log -> a JSONL workload for the receiver
  inprocess         ReceiverCore in one Node process, fast and durable storage, per-stage profile, agreement with Python
  race              K Node processes, each with its own ReceiverCore on ONE ledger file, firing at the same instant
  fault             a durable receiver killed with SIGKILL at random moments and restarted, K times
  http              the real bridge over loopback HTTP (skips with the reason when the sandbox forbids binding a port)
"""
from __future__ import annotations

import json
import random
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

from orderguard_guard import ROOT
from orderguard_guard.money import notional_cents

from . import auditor as A

BENCH = ROOT / "receiver" / "bench"


def node() -> str:
    exe = shutil.which("node")
    if not exe:
        raise RuntimeError("node is not on PATH; the receiver benchmarks need Node >= 22.13")
    return exe


def node_version() -> str:
    try:
        return subprocess.run([node(), "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        return "unavailable"


def ts(script: str, *args: str, timeout: float = 1800, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([node(), "--no-warnings", "--import", "tsx", str(BENCH / script), *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, **kw)


def scope_of(mandate: dict) -> dict:
    """The receiver's MandateScope for a signed bench mandate (same limits; the receiver calls the step-up field stepUpThresholdUsd)."""
    s = {k: mandate[k] for k in ("symbols", "sides", "maxOrderNotionalUsd", "maxDailyNotionalUsd", "priceBandPct", "expiresAt")}
    s["referencePrices"] = dict(mandate.get("referencePrices") or {})
    if mandate.get("stepUpAboveUsd") is not None:
        s["stepUpThresholdUsd"] = mandate["stepUpAboveUsd"]
    for k in ("maxSymbolDailyNotionalUsd", "maxPositionUsd", "maxOrdersPerDay"):
        if mandate.get(k) is not None:
            s[k] = mandate[k]
    return s


def receiver_key(key: str) -> str:
    return key.replace("_", ".")[:96]               # the receiver accepts [A-Za-z0-9._:-]{1,96}


# ---- workload export -------------------------------------------------------------------------------------------------------------------
def pick_envelopes(logs: list[str], k: int) -> list[str]:
    """The k busiest envelopes, plus one of each special kind when present: a burst target, a revoked envelope, a probed envelope,
    one with portfolio limits (even owner) and one without."""
    counts: dict[str, int] = {}
    for lp in logs:
        with open(lp, encoding="utf-8") as fh:
            for line in fh:
                body = line.split(" ", 1)[1]
                i = body.index('"e":"') + 5
                e = body[i: body.index('"', i)]
                counts[e] = counts.get(e, 0) + 1
    ranked = sorted(counts, key=lambda e: (-counts[e], e))
    owner = lambda e: int(e.split("-")[0][1:])
    special = []
    for want in (lambda e: owner(e) % 10 == 7 and e.endswith("core"), lambda e: owner(e) % 10 == 5 and e.endswith("tactical"),
                 lambda e: owner(e) % 10 == 3 and e.endswith("crypto"), lambda e: owner(e) % 2 == 0, lambda e: owner(e) % 2 == 1):
        hit = next((e for e in ranked if want(e) and e not in special), None)
        if hit:
            special.append(hit)
    out = special + [e for e in ranked if e not in special]
    return sorted(out[: max(k, len(special))])


def export_workload(logs: list[str], reg: dict, market, envs: list[str], path: Path, max_orders: int) -> dict:
    """Every decision the Python authority made for `envs`, in order, as receiver orders. Orders the receiver cannot express (money
    movement, a non-string ticker, a non-integer quantity) are skipped and counted, as are orders whose news trigger was NOT confirmed:
    L7 is the Python layer's job and holds those without reserving anything. A confirmed trigger is an ordinary order to the receiver."""
    want = set(envs)
    lines, skipped = [], {}
    for lp in logs:
        with open(lp, encoding="utf-8") as fh:
            for line in fh:
                rec = json.loads(line.split(" ", 1)[1])
                if rec.get("e") not in want:
                    continue
                if rec.get("x") == "ctl":
                    if rec["ctl"] == "revoke":
                        lines.append({"e": rec["e"], "t": rec["t"], "day": rec["t"] // market.steps_per_day, "k": rec["k"], "s": "", "sd": "", "q": 0,
                                      "l": 0, "tp": None, "py": "", "x": "revoke"})
                    continue
                q = rec["q"]
                why = None
                if q.get("type") == "transfer" or "destination_account" in q:
                    why = "money_movement"
                elif not isinstance(q.get("ticker"), str):
                    why = "no_ticker"
                elif type(q.get("quantity")) is not int or not isinstance(q.get("limit_price"), (int, float)):
                    why = "non_integer_quantity_or_limit"
                elif rec.get("tr") is False:
                    why = "l7_unconfirmed_trigger"
                if why:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
                lines.append({"e": rec["e"], "t": rec["t"], "day": rec["t"] // market.steps_per_day, "k": receiver_key(rec["k"]), "s": q["ticker"],
                              "sd": q["side"], "q": q["quantity"], "l": float(q["limit_price"]),
                              "tp": market.trusted[rec["t"]].get(q["ticker"]), "py": rec["g"], "x": rec["x"]})
    lines = lines[:max_orders]
    header = {"type": "header", "base_date": "2026-01-05", "prices": market.trusted,
              "envelopes": {e: {"mandateId": reg[e]["id"], "scope": scope_of(reg[e]["mandate"])} for e in envs}}
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(header, separators=(",", ":")) + "\n")
        for ln in lines:
            fh.write(json.dumps(ln, separators=(",", ":")) + "\n")
    return {"envelopes": envs, "orders": sum(1 for x in lines if x["x"] != "revoke"), "revokes": sum(1 for x in lines if x["x"] == "revoke"), "skipped": skipped}


def busiest(path: Path) -> str:
    """The envelope with the most orders in a receiver workload."""
    counts: dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            e = json.loads(line)["e"]
            counts[e] = counts.get(e, 0) + 1
    return max(sorted(counts), key=lambda e: counts[e])


def _prices_by_key(path: Path) -> dict:
    """Every trusted price at which each key was delivered. The receiver keeps no record of a denial, so a key that was denied and
    delivered again later (a retry) is evaluated afresh at that later step's price."""
    out: dict[str, set] = {}
    with open(path, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            d = json.loads(line)
            if d["tp"] is not None:
                out.setdefault(d["k"], set()).add(d["tp"])
    return out


# ---- in-process ------------------------------------------------------------------------------------------------------------------------------
def inprocess(work: Path, reg: dict, out_dir: Path, durable_max: int) -> dict:
    out = out_dir / "receiver-inprocess.json"
    r = ts("inprocess.ts", "--workload", str(work), "--dir", str(out_dir / "ledgers"), "--out", str(out), "--durable-max", str(durable_max))
    if r.returncode != 0:
        raise RuntimeError("receiver in-process bench failed: " + (r.stderr or r.stdout)[-800:])
    res = json.loads(out.read_text())
    prices = _prices_by_key(work)
    audits = {}
    for mode in ("fast", "durable"):
        dec = res[mode].pop("decisions", [])
        acked: dict[str, dict] = {}
        for k, d, env in dec:
            acked.setdefault(env, {}).setdefault(k, d)
        f = A.Findings()
        rows = 0
        for env, path in res[mode]["ledgers"].items():
            a = A.audit_ledger(path, reg[env]["mandate"], prices=prices, acked=acked.get(env))
            rows += a["orders"]
            ff = A.Findings()
            ff.breaches, ff.checked, ff.notes, ff.examples = a["breaches"], a["checked"], a["notes"], a["examples"]
            f.merge(ff)
        audits[mode] = {**f.to_dict(), "ledgers": len(res[mode]["ledgers"]), "ledger_rows": rows}
        res[mode].pop("ledgers", None)
    for k in ("fast_profile", "durable_profile"):
        if k in res:
            res[k].pop("ledgers", None)
    res["audit"] = audits
    return res


# ---- race ----------------------------------------------------------------------------------------------------------------------------------
def race(out_dir: Path, procs: int, per_proc: int, *, shared_keys: bool, mutation: str | None = None, tag: str = "race") -> dict:
    """K processes, one ledger. Unique keys: the daily cap fits exactly 20 orders; every process tries per_proc. Shared keys: every
    process delivers the SAME per_proc keys (ample budget), so each key races K-1 duplicates of itself."""
    price, qty = 73.77, 100
    notional = notional_cents(qty, price) / 100
    entitled = 20
    scope = {"symbols": ["BTCUSDT"], "sides": ["buy"], "maxOrderNotionalUsd": 1_000_000.0,
             "maxDailyNotionalUsd": round(notional * entitled, 2) if not shared_keys else 1e9, "priceBandPct": 1.0,
             "expiresAt": "2099-01-01T00:00:00Z", "referencePrices": {}}
    if shared_keys:
        orders = [[{"symbol": "BTCUSDT", "side": "buy", "quantity": qty, "limitPrice": price, "clientOrderId": f"dup-{i}"} for i in range(per_proc)]]
    else:
        orders = [[{"symbol": "BTCUSDT", "side": "buy", "quantity": qty, "limitPrice": price, "clientOrderId": f"w{w}-{i}"} for i in range(per_proc)]
                  for w in range(procs)]
    d = out_dir / tag
    d.mkdir(parents=True, exist_ok=True)
    ledger = d / "shared.sqlite"
    for suffix in ("", "-wal", "-shm"):
        Path(str(ledger) + suffix).unlink(missing_ok=True)
    spec = d / "spec.json"
    spec.write_text(json.dumps({"mandateId": f"bench-{tag}", "scope": scope, "price": price, "orders": orders}))
    start_at = int(time.time() * 1000) + 2000
    ps = [subprocess.Popen([node(), "--no-warnings", "--import", "tsx", str(BENCH / "race-worker.ts"), "--ledger", str(ledger), "--spec", str(spec),
                            "--worker", str(w), "--start-at", str(start_at), "--mutation", mutation or "none"], cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True) for w in range(procs)]
    outs = [p.communicate(timeout=300) for p in ps]
    results, errors, failed = [], 0, []
    for (so, se), p in zip(outs, ps):
        if p.returncode != 0 or not so.strip():
            failed.append(se[-300:])
            continue
        r = json.loads(so.strip().splitlines()[-1])
        results += r["results"]
        errors += r["errors"]
    mandate = {**{k: v for k, v in scope.items()}, "referencePrices": {}}
    audit = A.audit_ledger(ledger, mandate)
    counts: dict[str, int] = {}
    for _, dec in results:
        counts[dec.split(":")[0]] = counts.get(dec.split(":")[0], 0) + 1
    filled_rows = audit["orders"]
    return {"processes": procs, "orders_per_process": per_proc, "shared_keys": shared_keys, "mutation": mutation, "attempts": len(results),
            "decisions": counts, "errors": errors, "failed_processes": failed, "ledger_rows": filled_rows,
            "entitled_fills": None if shared_keys else entitled, "distinct_keys": per_proc if shared_keys else procs * per_proc,
            "audit": {k: audit[k] for k in ("breaches", "breach_total", "checked", "notes", "examples", "used_usd")},
            "daily_cap_usd": scope["maxDailyNotionalUsd"]}


# ---- kill / restart ------------------------------------------------------------------------------------------------------------------
def fault(work: Path, reg: dict, env: str, out_dir: Path, cycles: int, max_orders: int, seed: int = 0) -> dict:
    """SIGKILL a durable receiver at random moments `cycles` times, restart it on the same ledger (verify-on-open), re-send every order
    without an acknowledgement plus a few with one, and finish the stream. Then audit the ledger against every acknowledgement."""
    d = out_dir / "fault"
    d.mkdir(parents=True, exist_ok=True)
    sub = d / "workload.jsonl"
    with open(work, encoding="utf-8") as src, open(sub, "w", encoding="utf-8") as dst:
        header = json.loads(next(src))
        header["envelopes"] = {env: header["envelopes"][env]}
        dst.write(json.dumps(header, separators=(",", ":")) + "\n")
        n = 0
        for line in src:
            if n >= max_orders:
                break
            rec = json.loads(line)
            if rec["e"] == env and rec["x"] != "revoke":
                dst.write(line)
                n += 1
    ledger = d / "ledger.sqlite"
    for suffix in ("", "-wal", "-shm"):
        Path(str(ledger) + suffix).unlink(missing_ok=True)
    rng = random.Random(seed)
    acked: dict[str, str] = {}
    by_index: dict[int, str] = {}
    acked_idx = -1
    kills, opens, replays, mismatches, in_flight_commits, restarts_verified = 0, [], 0, 0, 0, 0
    frm = 0
    done = False
    attempts = 0
    while not done and attempts < cycles + 20:
        attempts += 1
        p = subprocess.Popen([node(), "--no-warnings", "--import", "tsx", str(BENCH / "fault-child.ts"), "--workload", str(sub), "--env", env,
                              "--ledger", str(ledger), "--from", str(frm)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        kill_after = rng.randint(3, 40) if kills < cycles else None
        seen_this = 0
        assert p.stdout is not None
        for line in p.stdout:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "OPEN_OK":
                opens.append({"events": int(parts[1]), "verified": parts[2] == "verified", "ms": float(parts[3])})
                restarts_verified += parts[2] == "verified"
            elif parts[0] == "OPEN_FAIL":
                opens.append({"failed": " ".join(parts[1:])[:200]})
                break
            elif parts[0] == "A":
                i, key, dec = int(parts[1]), parts[2], parts[3]
                if len(parts) > 4 and parts[4] == "replay":
                    replays += 1
                prev = by_index.get(i)
                if prev in ("filled", "held") and dec != prev:
                    mismatches += 1                      # the same order, acknowledged as an effect before, must replay as that effect
                by_index.setdefault(i, dec)
                acked.setdefault(key, dec)
                acked_idx = max(acked_idx, i)
                seen_this += 1
                if kill_after is not None and seen_this >= kill_after:
                    time.sleep(rng.uniform(0, 0.003))     # land somewhere inside the next propose(), often inside its commit
                    p.send_signal(signal.SIGKILL)
                    kills += 1
                    break
            elif parts[0] == "DONE":
                done = True
        p.wait(timeout=60)
        if p.stdout:
            p.stdout.close()
        if p.stderr:
            p.stderr.close()
        if not done:
            # what did the killed process commit that it never acknowledged?
            db = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
            try:
                keys = {r[0] for r in db.execute("SELECT client_order_id FROM orders")}
            finally:
                db.close()
            in_flight_commits += len(keys - set(acked))
            frm = max(0, acked_idx + 1 - rng.randint(0, 3))     # re-send everything unacknowledged, plus up to three acknowledged
    mandate = reg[env]["mandate"]
    audit = A.audit_ledger(ledger, mandate, prices=_prices_by_key(sub), acked=acked)
    return {"envelope": env, "orders": n, "kills": kills, "restarts": len(opens) - 1, "opens_verified": restarts_verified, "opens": len(opens), "completed": done,
            "commits_landed_without_ack": in_flight_commits, "resent_replays": replays, "acked_effect_mismatches": mismatches,
            "open_ms": [o.get("ms") for o in opens], "audit": {k: audit[k] for k in ("breaches", "breach_total", "checked", "notes", "examples", "used_usd", "orders", "events")}}


# ---- HTTP ------------------------------------------------------------------------------------------------------------------------------------
def http(work: Path, reg: dict, env: str, out: Path, requests: int, concurrency: int) -> dict:
    """The bridge prices orders from the mandate's referencePrices (it has no quote feed), so the spec pins the step-0 trusted prices."""
    with open(work, encoding="utf-8") as fh:
        header = json.loads(next(fh))
        orders = []
        for line in fh:
            d = json.loads(line)
            if d["e"] == env and d["x"] == "orig":
                orders.append(d)
    px0 = header["prices"][0]
    scope = scope_of(reg[env]["mandate"])
    scope["referencePrices"] = {s: px0[s] for s in scope["symbols"] if s in px0}
    scope.pop("stepUpThresholdUsd", None)                      # no step-up: keep every order a fill or a denial (http.mjs signs this body)
    spec_orders = [{"symbol": o["s"], "side": o["sd"], "quantity": o["q"], "limitPrice": round(scope["referencePrices"].get(o["s"], o["l"]), 2),
                    "clientOrderId": o["k"]} for o in orders if o["s"] in scope["referencePrices"]][:2000]
    spec = out.with_suffix(".spec.json")
    spec.write_text(json.dumps({"mandate": scope, "orders": spec_orders}))
    r = subprocess.run([node(), str(BENCH / "http.mjs"), "--spec", str(spec), "--out", str(out), "--requests", str(requests),
                        "--concurrency", str(concurrency)], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    spec.unlink(missing_ok=True)
    try:
        res = json.loads(out.read_text())
    except (OSError, ValueError):
        res = {"skipped": True, "reason": "the HTTP bench wrote no result: " + (r.stderr or r.stdout)[-300:]}
    res["envelope"] = env
    return res


def growth(out_dir: Path, orders: int, window: int) -> dict:
    """propose() latency as one day's ledger grows (fast storage), with and without the portfolio limits."""
    out = out_dir / "growth.json"
    r = ts("growth.ts", "--dir", str(out_dir / "growth"), "--orders", str(orders), "--window", str(window), "--out", str(out))
    if r.returncode != 0:
        raise RuntimeError("receiver growth bench failed: " + (r.stderr or r.stdout)[-800:])
    return json.loads(out.read_text())


def edges_receiver(path: Path, out: Path) -> dict:
    r = ts("inprocess.ts", "--workload", str(path), "--dir", str(out.parent / "edge-ledgers"), "--out", str(out), "--passes", "fast")
    if r.returncode != 0:
        raise RuntimeError("receiver edge run failed: " + (r.stderr or r.stdout)[-800:])
    return json.loads(out.read_text())

