"""The Swarm Theater: a guided replay of one REAL recorded arena run (1,000 agents, 2,000 steps, seed 7).

Nothing here is simulated for the page. `build()` reads committed files (the recorded event stream, its summary, the order-risk
replay, the Jev triage study, the L8 agreement result) and compresses them into one compact document: a packed event strip (14 bits
an event), per-step aggregates, a few hundred feed lines with their plain-English reasons, three focus attacks followed end to end,
the held-order queue and a list of sourced `facts`. Every number the page prints is either a fact (with the file and JSON pointer it
came from) or an aggregate of the stream that `checks` reconcile with the run's own summary. The result is deterministic: the same
files always give the same bytes (no clock, no path, no random).

    python -m orderguard_app.theater build      write results/theater/timeline.json
    python -m orderguard_app.theater check      exit 1 if that file is stale

The endpoint (`GET /api/theater/timeline`) serves the committed file when its inputs are unchanged and builds in memory otherwise.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import struct
import sys
import threading
import unicodedata
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, Response

from .services import AppError

ROOT = Path(__file__).resolve().parents[2]
VERSION = 1
OUT = ROOT / "results" / "theater" / "timeline.json"

# id -> (repo-relative path, what it is). The page links every number to one of these.
SOURCES: dict[str, tuple[str, str]] = {
    "stream": ("results/arena/arena-s7-k1000-t2000.jsonl", "Recorded arena event stream: one row per order proposal, with the decision and the oracle label"),
    "summary": ("results/arena/arena-s7-k1000-t2000.summary.json", "Arena summary: decisions, bad and legitimate dollars, throughput and latency"),
    "risk": ("results/risk/arena-replay-arena-s7-k1000-t2000.json", "Order-risk layer replayed over the same stream (tighten-only)"),
    "latency": ("results/risk/latency.json", "Order-risk scoring latency over the 20,503 orders"),
    "triage": ("results/review/triage.json", "Held-order triage study: queue orderings with and without the Jev advice"),
    "l8": ("results/arena/l8-agreement-s23-k1000.txt", "L8 receiver agreement check (seed 23, 1,000 agents)"),
    "receiver": ("docs/receiver/results.md", "Receiver evidence register, including the recorded-action revocation replay (Q5)"),
    "review_doc": ("docs/REVIEW.md", "The escalation lane: how the human queue is ordered, and what the advice may and may not do"),
    "arena_doc": ("docs/ARENA.md", "Arena design, the attack mix and the measured results"),
    "risk_doc": ("docs/RISK.md", "The order-risk layer: programmed units, the learned residual, the tighten-only rule"),
    "model": ("data/models/order_risk.json", "The shipped order-risk model file"),
}
INPUTS = ("stream", "summary", "risk", "latency", "triage", "l8", "receiver", "model")   # the files the timeline is computed from
BENCH = "results/bench/summary.json"

# One byte pair per event: low 10 bits the agent, high 4 bits the state.
STATES = ["allow", "hold", "refuse", "stopped_by_risk", "leak", "bad_hold", "bad_refuse", "duplicate", "honest_tightened"]
S_ALLOW, S_HOLD, S_REFUSE, S_STOP, S_LEAK, S_BHOLD, S_BREFUSE, S_DUP, S_TIGHT = range(9)
FAMILIES = ["homoglyph", "fake_news", "stale_price", "fat_finger", "off_list", "runaway_loop", "compromised_unlisted", "compromised_oversize",
            "compromised_transfer", "compromised_sell_all", "collusion", "runaway_dup"]
FAMILY_TEXT = {
    "homoglyph": "look-alike ticker", "fake_news": "orders on uncorroborated news", "stale_price": "stale limit price", "fat_finger": "fat-finger sizing",
    "off_list": "off-list ticker", "runaway_loop": "runaway loop", "compromised_unlisted": "compromised: unlisted ticker",
    "compromised_oversize": "compromised: oversize at a fake reference price", "compromised_transfer": "compromised: transfer request",
    "compromised_sell_all": "compromised: sell everything", "collusion": "colluding agents splitting one position", "runaway_dup": "runaway: duplicate deliveries",
}
UNIT_TEXT = {
    "split_under_threshold": "one position split into near-limit slices that each stay under the step-up threshold",
    "coordinated_burst": "several agents sending the same kind of order in a burst",
    "order_rate": "orders arriving far faster than this agent's own rhythm",
    "repeat_loop": "the same order repeated in a loop",
    "size_discontinuity": "a size far above this agent's own history",
    "limit_far_from_trusted": "a limit price far from the trusted price",
    "schedule_break": "activity off this agent's usual schedule",
}
TOKENS_FORMAT = ("usd", "usdm", "pct", "int", "num", "text", "us")


# ---- small helpers ---------------------------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _usd(n: float) -> str:
    return f"${n:,.0f}"


def _px(n: float) -> str:
    return f"${n:,.2f}"


def _r(n: float) -> int:
    return int(round(n))


def _canon(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _pointer(doc, pointer: str):
    """RFC 6901 JSON pointer. The test suite and the page's fact table resolve numbers with the same rule."""
    cur = doc
    for part in [p for p in pointer.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def source_path(sid: str) -> Path:
    return ROOT / SOURCES[sid][0]


def read_json(sid: str):
    return json.loads(source_path(sid).read_text())


def _l8_numbers() -> dict:
    """The L8 result file is JSON followed by a PASS line; the JSON part is what the facts point into."""
    text = source_path("l8").read_text()
    return json.loads(text[: text.rindex("}") + 1])


# ---- the reasons: plain English from the event's own fields ----------------------------------------------------------------

def _layer(e: dict) -> str:
    code = e.get("code")
    if code == "money":
        return "L1"
    if code == "ticker":
        return "L1" if any(ord(c) > 127 for c in str(e["order"].get("ticker") or "")) else "L5"
    return {"l7": "L7"}.get(code, "L5")


def _rule(e: dict, env: dict | None, used: float) -> str:
    """The mandate rule that fired, with the numbers that made it fire."""
    o, code, usd = e["order"], e["code"], float(e.get("risk") or 0.0)
    tk = str(o.get("ticker") or "")
    if code == "money":
        return f"Money movement is not an order: a transfer of {_usd(o.get('amount_usd') or 0)} to {o.get('destination_account')}."
    if code == "ticker":
        bad = [c for c in tk if ord(c) > 127]
        if bad:
            return f"The ticker “{tk}” contains {unicodedata.name(bad[0]).title()} (U+{ord(bad[0]):04X}), a look-alike letter, so it matches no listed symbol."
        return f"{tk} is not on the {e.get('env')} envelope's allow-list."
    if code == "l7":
        return f"The order acts on news {e['trigger'].get('news_id')}, and fewer than two independent sources confirm it."
    if env is None:
        return "No envelope applies."
    if code == "per_order":
        return f"{o['quantity']} {tk} at the trusted {_px(e['tp'])} is {_usd(usd)}, over the {env['name']} per-order cap of {_usd(env['per_order'])}."
    if code == "band":
        dev = abs(o["limit_price"] / e["tp"] - 1.0) * 100.0
        return f"The limit {_px(o['limit_price'])} is {dev:.1f}% from the trusted {_px(e['tp'])}; the {env['name']} price band is ±{env['band_pct']:g}%."
    if code == "daily":
        return f"{_usd(usd)} would take the {env['name']} daily budget past its {_usd(env['daily'])} cap, with {_usd(used)} already committed today."
    if code == "stepup":
        return f"{_usd(usd)} is above the {env['name']} step-up threshold of {_usd(env['step_up'])}, so a human decides."
    return "The gate declined the order."


# ---- the build -------------------------------------------------------------------------------------------------------------

def _load_stream() -> tuple[list[str], dict, list[dict]]:
    lines = source_path("stream").read_text().splitlines()
    meta = json.loads(lines[0])
    return lines, meta, [json.loads(x) for x in lines[1:]]


def _risk_cases(meta: dict, events: list[dict]):
    """Score the stream point in time with the shipped order-risk model and add the Jev advice to the held-order cases.
    Replay only: a recording that is missing means no advice, never a model call."""
    from orderguard_guard.decisions import Decisions
    from orderguard_review import advice as A
    from orderguard_review import study
    cases, info = study.build_cases(events, {"envelopes": meta["envelopes"], "config": meta["config"]})
    return study, cases, info, Decisions(A.DEFAULT_MODEL, mode="replay")


def build() -> dict:
    lines, meta, events = _load_stream()
    summary, risk, lat, triage_doc, l8 = read_json("summary"), read_json("risk"), read_json("latency"), read_json("triage"), _l8_numbers()
    envs = {e["name"]: e for e in meta["envelopes"]}
    env_names = [e["name"] for e in meta["envelopes"]]
    spd = int(meta["config"]["steps_per_day"])
    n_steps, n_agents = int(meta["config"]["steps"]), int(meta["agents"])

    study, cases, info, decisions = _risk_cases(meta, events)
    case_by_i = {c["i"]: c for c in cases}

    # -- per event: the state, the aggregates, the reserve accounting -------------------------------------------------------
    series = {k: [0] * n_steps for k in ("legit", "legit_allow", "legit_hold", "legit_refuse", "legit_tight", "bad_n", "bad_usd", "bad_gate_usd", "bad_risk_usd", "bad_leak_usd")}
    reserve = {n: [0] * n_steps for n in env_names}
    used: dict[tuple[str, int], float] = {}
    packed, counts = bytearray(), [0] * n_steps
    states: list[int] = []
    reasons: dict[int, str] = {}
    used_before: dict[int, float] = {}
    agent_sleeve: dict[int, str] = {}
    agent_family: dict[int, int] = {}
    daily_violations = 0
    for n, e in enumerate(events):
        st, a, usd = int(e["step"]), int(e["agent"]), float(e.get("risk") or 0.0)
        label, d = e["label"], e["d"]
        bad = label != "legit"
        agent_sleeve.setdefault(a, e["sleeve"])
        if bad:
            agent_family.setdefault(a, FAMILIES.index(label))
        c = case_by_i.get(n)
        risk_action = c["action"] if c is not None and not c["gate_held"] else "none"
        if e.get("replay"):
            state = S_DUP
        elif d == "allow":
            stopped = risk_action in ("hold", "refuse")
            state = (S_STOP if stopped else S_LEAK) if bad else (S_TIGHT if stopped else S_ALLOW)
        elif d == "hold":
            state = S_BHOLD if bad else S_HOLD
        else:
            state = S_BREFUSE if bad else S_REFUSE
        states.append(state)
        packed += struct.pack("<H", a | (state << 10))
        counts[st] += 1
        env_name = e.get("env")
        day = st // spd
        before = used.get((env_name, day), 0.0) if env_name else 0.0
        used_before[n] = before
        if e["code"] == "daily" and env_name and before + usd <= envs[env_name]["daily"]:
            daily_violations += 1
        if env_name and d in ("allow", "hold") and not e.get("replay"):
            used[(env_name, day)] = before + usd
            reserve[env_name][st] += _r(usd * 100)               # integer cents; the page divides by 100
        if d != "allow":
            reasons[n] = _rule(e, envs.get(env_name), before)
        if bad:
            series["bad_n"][st] += 1
            series["bad_usd"][st] += _r(usd * 100)
            if state in (S_BHOLD, S_BREFUSE):
                series["bad_gate_usd"][st] += _r(usd * 100)
            elif state == S_STOP:
                series["bad_risk_usd"][st] += _r(usd * 100)
            elif state == S_LEAK:
                series["bad_leak_usd"][st] += _r(usd * 100)
        else:
            series["legit"][st] += 1
            series["legit_allow" if state == S_ALLOW else "legit_hold" if state == S_HOLD else "legit_refuse" if state == S_REFUSE else "legit_tight"][st] += 1

    # -- reconciliation against the run's own summary ----------------------------------------------------------------------
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    dec = {k: sum(1 for e in events if e["d"] == k) for k in ("allow", "hold", "refuse")}
    check("event count equals the summary's proposals", len(events) == summary["proposals"], f"{len(events)} rows, summary says {summary['proposals']}")
    check("decision counts equal the summary's", dec == summary["decisions"], f"allow {dec['allow']}, hold {dec['hold']}, refuse {dec['refuse']}")
    bad_total = sum(float(e["risk"]) for e in events if e["label"] != "legit")
    check("bad-order dollars equal the summary's attack notional", abs(bad_total - summary["bad"]["attack_notional_usd"]) < 0.02, f"{bad_total:,.2f} against {summary['bad']['attack_notional_usd']:,.2f}")
    legit = [e for e in events if e["label"] == "legit"]
    check("legitimate counts equal the summary's", (len(legit), sum(e["d"] == "allow" for e in legit), sum(e["d"] == "hold" for e in legit), sum(e["d"] == "refuse" for e in legit))
          == (summary["legit"]["proposals"], summary["legit"]["allowed"], summary["legit"]["held"], summary["legit"]["refused"]), f"{len(legit)} honest proposals")
    # the sampled utilisation is the budget committed so far on that day: rebuild it from the per-step reserve
    cum_day = {n_: 0 for n_ in env_names}
    worst = 0.0
    sampled = {(row["day"], row["step"]): row for row in summary["utilisation_series"]}
    for st in range(n_steps):
        for n_ in env_names:
            if st % spd == 0:
                cum_day[n_] = 0
        for n_ in env_names:
            cum_day[n_] += reserve[n_][st]               # the summary samples the budget committed through the end of that step
        row = sampled.get((st // spd, st))
        if row:
            for n_ in env_names:
                worst = max(worst, abs(cum_day[n_] / 100.0 / envs[n_]["daily"] - row[n_]))
    check("the envelope gauges reproduce the summary's utilisation series", worst < 0.0001, f"largest difference {worst:.5f} of a daily cap, {len(sampled)} samples")
    check("every refusal for the daily cap is consistent with the budget committed before it", daily_violations == 0, f"{sum(1 for e in events if e['code'] == 'daily')} refusals, {daily_violations} inconsistent")
    risk_leak = sum(float(e["risk"]) for k, e in enumerate(events) if states[k] == S_LEAK)
    risk_stop = sum(float(e["risk"]) for k, e in enumerate(events) if states[k] == S_STOP)
    check("the order-risk layer's stopped and leaked dollars equal results/risk", abs(risk_stop - (risk["bad_held_usd"] + risk["bad_refused_usd"])) < 0.05 and abs(risk_leak - risk["leak_after_usd"]) < 0.05,
          f"stopped {risk_stop:,.2f}, leaked {risk_leak:,.2f}")

    # -- the recording's hash chain (a tamper-evident index of the rows, not the receiver's ledger) ---------------------------
    chain = [hashlib.sha256(lines[0].encode()).hexdigest()]
    for line in lines[1:]:
        chain.append(hashlib.sha256((chain[-1] + line).encode()).hexdigest())
    chain_head = chain[-1]

    # -- the swarm -----------------------------------------------------------------------------------------------------------
    sleeve_code = "".join(str(env_names.index(agent_sleeve[a])) if a in agent_sleeve else "3" for a in range(n_agents))
    bad_agents = sorted(agent_family)
    fam_by_agent = "".join(chr(ord("a") + agent_family[a]) if a in agent_family else "-" for a in range(n_agents))

    # -- first events of each family, the beat windows --------------------------------------------------------------------------
    first = {}
    for n, e in enumerate(events):
        first.setdefault(e["label"], n)
    first_step = lambda lab: int(events[first[lab]]["step"])          # noqa: E731
    first_attack = min(first_step(f) for f in FAMILIES if f in first)
    ff, run, col = first_step("fat_finger"), first_step("runaway_loop"), first_step("collusion")
    calm_end = first_attack
    col_last = max(int(e["step"]) for e in events if e["label"] == "collusion")
    windows = [[first_attack, ff + 8], [run - 4, run + 36], [col - 3, col_last + 7]]
    segs_naive = [[0, calm_end, 9.0]]
    segs_guard = []
    for k, (a, b) in enumerate(windows):
        if k:
            segs_naive.append([windows[k - 1][1], a, 1.0]), segs_guard.append([windows[k - 1][1], a, 1.0])
        segs_naive.append([a, b, [8.0, 5.0, 11.0][k]])
        segs_guard.append([a, b, [9.0, 6.0, 13.0][k]])

    # -- the feed: every non-allow decision and every gate-allowed bad order inside the beat windows ---------------------------
    feed, feed_texts = [], {}                      # one row per decision; the English is interned because many rows share it
    for n, e in enumerate(events):
        st = int(e["step"])
        if not any(a <= st < b for a, b in windows) or states[n] in (S_ALLOW, S_DUP):
            continue
        s = states[n]
        if s in (S_STOP, S_TIGHT):
            c = case_by_i[n]
            unit = max(c["risk"].get("units") or [{}], key=lambda u: u.get("activation", 0)).get("name")
            text = f"The gate allowed it. The order-risk layer would {c['action']} it for {UNIT_TEXT.get(unit, 'unusual behaviour')} (risk {c['p_model']:.2f})."
        elif s == S_LEAK:
            text = "Allowed by the gate and by the order-risk layer."
        else:
            text = reasons[n]
        feed.append([n, st, int(e["agent"]), s, feed_texts.setdefault(text, len(feed_texts))])

    # -- focus attacks, end to end ---------------------------------------------------------------------------------------------
    def focus_rows(n: int) -> dict:
        lo = max(0, n - 2)
        return {"first_row": lo + 1, "prev": chain[lo], "rows": lines[lo + 1: lo + 6], "hashes": chain[lo + 1: lo + 6], "at": n - lo}

    def claimed_vs_trusted(e: dict) -> dict | None:
        o, tp = e["order"], e.get("tp")
        if tp is None or "limit_price" not in o:
            return None
        return {"limit": o["limit_price"], "trusted": tp, "qty": o["quantity"], "notional_at_limit": round(o["quantity"] * o["limit_price"], 2),
                "notional_at_trusted": round(o["quantity"] * tp, 2)}

    def ledger_entry(n: int, e: dict, state: int) -> dict:
        env = e.get("env")
        if e["d"] == "refuse" or (e["d"] == "hold" and not env):
            effect = "Nothing reserved: a refusal or a hold before any envelope applies moves no budget."
            reserved = 0.0
        else:
            effect = "Reserved against the envelope's daily budget, atomically, in integer cents."
            reserved = float(e["risk"])
        out = {"row": n + 1, "envelope": env, "day": int(e["step"]) // spd, "reserved_usd": round(reserved, 2), "effect": effect,
               "budget_before_usd": round(used_before[n], 2) if env else None, "budget_after_usd": round(used_before[n] + reserved, 2) if env else None,
               "cap_usd": envs[env]["daily"] if env else None, "chain": focus_rows(n)}
        return out

    def focus_gate(n: int, title: str, blurb: str) -> dict:
        e = events[n]
        env = envs.get(e.get("env"))
        return {"id": f"{e['label']}-{n + 1}", "title": title, "blurb": blurb, "step": int(e["step"]), "row": n + 1, "agent": int(e["agent"]), "family": FAMILIES.index(e["label"]),
                "order": e["order"], "note": e.get("note"), "claimed": claimed_vs_trusted(e), "layer": _layer(e),
                "rule": {"layer": _layer(e), "code": e["code"], "text": _rule(e, env, used_before[n])}, "decision": e["d"], "notional_usd": float(e["risk"]),
                "ledger": ledger_entry(n, e, states[n])}

    n_over = next(n for n, e in enumerate(events) if e["label"] == "compromised_oversize" and e["d"] == "refuse")
    n_news = next(n for n, e in enumerate(events) if e["label"] == "fake_news" and e["d"] == "hold")
    n_col = next(n for n, e in enumerate(events) if states[n] == S_STOP and e["label"] == "collusion"
                 and any(u["name"] == "split_under_threshold" and u["activation"] >= 0.5 for u in case_by_i[n]["risk"].get("units") or []))
    focus = [
        focus_gate(n_news, "Orders on a rumour", "Agents read a story and want to act on it. The standing rule needs two independent sources, and there is one."),
        focus_gate(n_over, "An injected oversize order", "A compromised agent was told to buy far more than the signed envelope allows, at a fake reference price."),
    ]
    e = events[n_col]
    c = case_by_i[n_col]
    env = envs[e["env"]]
    f = {"id": f"collusion-{n_col + 1}", "title": "Five agents, one position", "blurb": "Each order fits the envelope. Together they are one oversized position split to stay under the step-up threshold.",
         "step": int(e["step"]), "row": n_col + 1, "agent": int(e["agent"]), "family": FAMILIES.index("collusion"), "order": e["order"], "note": e.get("note"),
         "claimed": claimed_vs_trusted(e), "layer": "L5", "notional_usd": float(e["risk"]),
         "gate_checks": [
             f"Allow-list: {e['order']['ticker']} is listed on {env['name']}.",
             f"Per-order cap: {_usd(e['risk'])} is {100 * e['risk'] / env['per_order']:.0f}% of the {_usd(env['per_order'])} cap.",
             f"Step-up: below the {_usd(env['step_up'])} threshold, so no human is asked.",
             f"Daily budget: {_usd(used_before[n_col])} committed of {_usd(env['daily'])}, so there is room.",
             f"Price band: the limit {_px(e['order']['limit_price'])} is within ±{env['band_pct']:g}% of the trusted {_px(e['tp'])}."],
         "rule": {"layer": "RISK", "code": "split_under_threshold", "text": c["risk"]["reasons"][0] if c["risk"]["reasons"] else "",
                  "units": [{"name": u["name"], "family": u["family"], "activation": u["activation"]} for u in c["risk"].get("units") or []],
                  "risk": c["p_model"]},
         "decision": "allow", "then": c["action"], "ledger": ledger_entry(n_col, e, states[n_col])}
    f["ledger"]["effect"] = ("The gate reserved this against core's daily budget. The risk layer's " + c["action"] + " comes after the gate in this replay, so the recorded "
                             "budget is unchanged; budget a stopped order would have freed is not re-simulated.")
    focus.append(f)

    # -- the held-order queue (docs/REVIEW.md `all_held`), one hour ----------------------------------------------------------------
    hour = int(events[n_col]["step"] * 8 // spd)
    queue_cases = [c for c in cases if c["hour"] == hour]
    study.triage_all(queue_cases, decisions)
    ranked = sorted(queue_cases, key=lambda c: (-c["t"]["queue_rank_key"], c["i"]))
    fifo_rank = {c["i"]: k + 1 for k, c in enumerate(sorted(queue_cases, key=lambda c: c["i"]))}
    queue_items = []
    for k, c in enumerate(ranked[:8]):
        e, adv = events[c["i"]], c["t"]["advice"]
        queue_items.append({
            "rank": k + 1, "fifo_rank": fifo_rank[c["i"]], "row": c["i"] + 1, "step": int(e["step"]), "agent": int(e["agent"]), "order": e["order"], "notional_usd": float(e["risk"]),
            "why_held": "The gate held it: " + _rule(e, envs.get(e.get("env")), used_before[c["i"]]) if c["gate_held"] else "The gate allowed it; the order-risk model flagged it.",
            "p_model": round(c["p_model"], 4), "p_bad": c["t"]["p_bad"], "rank_key_usd": c["t"]["queue_rank_key"],
            "model_reason": (c["risk"]["reasons"] or [""])[0] if not c["gate_held"] else "",
            "advice": ({"available": True, "p_jev": adv["compromised_probability"], "pattern": adv["pattern"], "confidence": adv["pattern_confidence"],
                        "urgency": adv["urgency_level"], "suggested": adv["suggested_action"], "model": adv["model"]} if adv.get("available") else {"available": False}),
            "truth": e["label"]})
    queue = {"hour": hour, "of_day": hour // 8, "orders": len(queue_cases), "bad": sum(1 for c in queue_cases if c["bad"]), "opens": 8, "items": queue_items,
             "ordering": "jev+model: noisy-OR of the risk model and the Jev probability, times the order's notional (docs/REVIEW.md)"}

    # -- facts: the numbers the page prints, each with its source ---------------------------------------------------------------
    facts: dict[str, dict] = {}
    docs = {"summary": summary, "risk": risk, "latency": lat, "triage": triage_doc, "l8": l8, "stream": meta}

    def F(fid: str, fmt: str, source: str, pointer, text: str, scale: int = 1) -> None:
        """A number the page prints. `pointer` is one JSON pointer into the source file, or a list of them to add up; `scale` is 100 where the file holds a fraction."""
        assert fmt in TOKENS_FORMAT
        ptrs = [pointer] if isinstance(pointer, str) else list(pointer)
        value = sum(_pointer(docs[source], q) for q in ptrs)
        value = value * scale if scale != 1 else value
        facts[fid] = {"value": round(value, 6) if isinstance(value, float) else value, "fmt": fmt, "source": source, "pointer": pointer, "scale": scale, "text": text}

    def D(fid: str, value, fmt: str, source: str, text: str) -> None:
        """A derived fact: not a pointer into a file. The test suite recomputes each one."""
        facts[fid] = {"value": value, "fmt": fmt, "source": source, "pointer": None, "scale": 1, "text": text}
    F("agents", "int", "stream", "/agents", "agents in the recorded run")
    F("proposals", "int", "summary", "/proposals", "order proposals in the run")
    F("steps", "int", "stream", "/config/steps", "market ticks")
    F("days", "int", "summary", "/config/days", "simulated trading days")
    F("seed", "int", "stream", "/config/seed", "the run's seed")
    F("attack_usd", "usdm", "summary", "/bad/attack_notional_usd", "dollars of bad orders that reached the gate")
    F("attack_orders", "int", "summary", "/bad/proposals", "bad order proposals, duplicates included")
    F("dup_usd", "usdm", "summary", "/bad/duplicates_absorbed_usd", "of that, duplicate deliveries absorbed by idempotency")
    F("gate_blocked_usd", "usdm", "summary", "/bad/blocked_usd", "refused or held by the mandate gate")
    F("gate_blocked_share", "pct", "summary", "/bad/blocked_share", "share of bad dollars the mandate gate blocked", 100)
    F("gate_leaked_usd", "usdm", "summary", "/bad/leaked_usd", "authorized by the gate because each order fit the envelope")
    F("gate_leaked_orders", "int", "summary", "/bad/allowed", "bad orders the gate authorized")
    F("risk_before_usd", "usdm", "risk", "/leak_before_usd", "bad dollars the gate authorized, as the order-risk layer saw them")
    F("risk_after_usd", "usd", "risk", "/leak_after_usd", "bad dollars left after the order-risk layer")
    F("risk_stopped_usd", "usdm", "risk", ["/bad_held_usd", "/bad_refused_usd"], "held or refused by the order-risk layer")
    F("risk_stopped_share", "pct", "risk", "/bad_stopped_share", "share of the gate-authorized bad dollars the order-risk layer stopped", 100)
    F("risk_honest_tightened", "int", "risk", ["/honest_held", "/honest_refused"], "honest orders the order-risk layer held or refused")
    F("risk_honest_tightened_usd", "usd", "risk", "/honest_tightened_usd", "dollars of those honest orders")
    F("risk_honest_allowed", "int", "risk", "/honest_allowed", "honest orders the gate allowed")
    F("legit_orders", "int", "summary", "/legit/proposals", "honest proposals")
    F("legit_allowed", "int", "summary", "/legit/allowed", "honest proposals allowed")
    F("legit_held", "int", "summary", "/legit/held", "honest proposals held for a human")
    F("legit_refused", "int", "summary", "/legit/refused", "honest proposals refused")
    F("false_refusal", "pct", "summary", "/legit/false_refusal_rate", "share of honest proposals refused", 100)
    F("decisions_per_s", "int", "summary", "/timing/authority_decisions_per_s", "authority decisions per second, one process")
    F("lat_p50_us", "us", "summary", "/timing/latency_us/p50", "median authority latency")
    F("lat_p99_us", "us", "summary", "/timing/latency_us/p99", "99th percentile authority latency")
    F("risk_p50_us", "us", "latency", "/p50_us", "median order-risk scoring latency")
    F("risk_p99_us", "us", "latency", "/p99_us", "99th percentile order-risk scoring latency")
    F("l8_agree", "int", "l8", "/l8/agree", "decisions on which the TypeScript receiver agreed")
    F("l8_sampled", "int", "l8", "/l8/sampled", "decisions compared with the receiver")
    F("fifo_90", "int", "triage", "/queues/model_flagged/reviews_to_catch/fifo/90%", "reviews to open 90% of bad dollars, first in first out")
    F("jev_90", "int", "triage", "/queues/model_flagged/reviews_to_catch/jev+model/90%", "reviews to open 90% of bad dollars, Jev plus risk model")
    F("model_90", "int", "triage", "/queues/model_flagged/reviews_to_catch/model/90%", "reviews to open 90% of bad dollars, risk model alone")
    F("jev_cost_1000", "num", "triage", "/jev_cost/cost_per_1000_usd", "US dollars per 1,000 triage calls")
    F("peak_core", "pct", "summary", "/utilisation_peak/core", "peak share of the core envelope's daily cap used", 100)
    D("stopped_total_usd", round(summary["bad"]["blocked_usd"] + risk["bad_held_usd"] + risk["bad_refused_usd"], 2), "usdm", "summary",
      "bad dollars stopped by the two layers together: the gate's blocked_usd plus the order-risk layer's held and refused")
    D("legit_daily_refusals", sum(1 for e in events if e["label"] == "legit" and e["code"] == "daily"), "int", "stream", "honest proposals refused because the shared daily budget was spent")
    D("chain_rows", len(events), "int", "stream", "rows in the recording's hash chain")
    D("chain_head", chain_head, "text", "stream", "head of the SHA-256 chain over every row of the stream file")
    D("revoke_text", "30/30 had post-revocation effects in the front-door-only comparator and 0/30 in the receiver-side replay", "text", "receiver",
      "recorded-action revocation replay, Q5: the sentence is quoted from the file")
    D("checks_ok", f"{sum(1 for c_ in checks if c_['ok'])} of {len(checks)}", "text", "stream", "reconciliation checks that passed when this file was built")

    beats = _beats(windows, calm_end, first_attack, segs_naive, segs_guard, first, events, n_col)

    return {
        "version": VERSION, "title": "OrderGuard Swarm Theater",
        "run": {"name": meta["name"], "agents": n_agents, "steps": n_steps, "steps_per_day": spd, "days": summary["config"]["days"], "symbols": meta["symbols"], "note": meta["note"]},
        "sources": [{"id": k, "path": v[0], "what": v[1], "sha256": _sha256(ROOT / v[0]), "bytes": (ROOT / v[0]).stat().st_size} for k, v in SOURCES.items() if (ROOT / v[0]).exists()],
        "inputs": input_hashes(),
        "envelopes": [{"name": e["name"], "purpose": e["purpose"], "per_order": e["per_order"], "daily": e["daily"], "step_up": e["step_up"], "band_pct": e["band_pct"],
                       "symbols": e["symbols"], "id": e["id"]} for e in meta["envelopes"]],
        "states": STATES, "families": [{"id": f, "text": FAMILY_TEXT[f], "first_step": first_step(f) if f in first else None,
                                        "orders": sum(1 for e in events if e["label"] == f)} for f in FAMILIES],
        "swarm": {"sleeve": sleeve_code, "family": fam_by_agent, "silent": sleeve_code.count("3")},
        "events": base64.b64encode(bytes(packed)).decode(), "per_step": counts, "series": series, "reserve_cents": reserve,
        "beats": beats, "feed": feed, "feed_texts": list(feed_texts), "focus": focus, "queue": queue, "facts": facts, "checks": checks,
        "chain": {"genesis": hashlib.sha256(lines[0].encode()).hexdigest(), "head": chain_head, "rows": len(events),
                  "rule": "hash(row n) = SHA-256(hash(row n-1) + the row's line as written in the file); the first link uses the SHA-256 of the meta line"},
        "limits": [
            "Agents, fills and labels are simulated: the arena's labels are ground truth the guard never sees.",
            "The mandate gate's decisions are the recorded ones. The order-risk layer is replayed over those decisions point in time; budget a stopped colluder would have freed for honest agents is not re-simulated.",
            "The order-risk model never trained on seed 7. The Jev advice is replayed from recordings; it is advice, and code decides.",
            "The recording's hash chain is an index of the stream file, not the L8 receiver's ledger. The receiver's agreement and its revocation behaviour come from separate runs and are labelled as such.",
        ],
    }


def _beats(windows, calm_end, first_attack, segs_naive, segs_guard, first, events, n_col) -> list[dict]:
    """Authored copy. {tokens} are facts, formatted by the page; every number is a token or comes from the live counters."""
    return [
        {"id": "calm", "title": "Calm", "kicker": "1 of 5", "view": "calm", "segments": [[0, calm_end, 9.0]],
         "caption": "A swarm of {agents} agents trades inside three human-signed envelopes. Each gauge is the day's budget, shared by every agent that draws on it."},
        {"id": "attack", "title": "The attack starts", "kicker": "2 of 5", "view": "naive", "segments": segs_naive[1:],
         "caption": "Same run, now with the arena's labels revealed. Red dots are bad orders. With nothing in front of them, every one reaches the exchange: {attack_usd} of bad orders reached the gate in this run."},
        {"id": "guard", "title": "The guard", "kicker": "3 of 5", "view": "guard", "segments": segs_guard,
         "caption": "Rewind to the first attack and replay it with the verdicts. The mandate gate refuses or holds {gate_blocked_share} of bad dollars. The rest fit the envelope and pass it: the order-risk layer is what stops those."},
        {"id": "human", "title": "The human", "kicker": "4 of 5", "view": "human", "segments": [], "dwell": 12.0,
         "caption": "Held orders go to a person, ordered by expected bad dollars. Jev's advice is shown as advice only: it can raise an order in the queue, never approve or release one."},
        {"id": "proof", "title": "The proof", "kicker": "5 of 5", "view": "proof", "segments": [], "dwell": 12.0,
         "caption": "Every figure here comes from a committed result file, linked beside it. The caveats sit next to the numbers they qualify."},
    ]


# ---- cache, CLI, routes ----------------------------------------------------------------------------------------------------

_lock = threading.Lock()
_memo: dict[str, tuple] = {}


def input_hashes() -> dict:
    """SHA-256 of every file the timeline is computed from, and of this builder: change any of them and the committed file is stale."""
    return {**{k: _sha256(source_path(k)) for k in INPUTS}, "builder": _sha256(Path(__file__))}


def _fingerprint() -> str:
    parts = [str(VERSION), str(Path(__file__).stat().st_mtime_ns)]
    for k in INPUTS:
        p = source_path(k)
        st = p.stat()
        parts.append(f"{k}:{st.st_size}:{st.st_mtime_ns}")
    return "|".join(parts)


def serialise(doc: dict) -> str:
    return _canon(doc)


def timeline_text() -> str:
    """The committed file when its recorded input hashes still match the files; otherwise a fresh build, kept in memory."""
    missing = [SOURCES[k][0] for k in INPUTS if not source_path(k).exists()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    fp = _fingerprint()
    with _lock:
        if _memo.get("fp") == fp:
            return _memo["text"]
        text = None
        if OUT.exists():
            cached = OUT.read_text()
            try:
                doc = json.loads(cached)
                if doc.get("version") == VERSION and doc.get("inputs") == input_hashes():
                    text = cached
            except ValueError:
                text = None
        if text is None:
            text = serialise(build())
        _memo.clear()
        _memo.update({"fp": fp, "text": text})
        return text


def bench_headline() -> dict:
    """results/bench/summary.json when it has been written; the page shows a marked slot otherwise. The shape of that file is not assumed: the
    scalar entries of its `headline` object (or of the file itself) are listed. The keys of this answer never change, so the API docs stay stable."""
    p = ROOT / BENCH
    if not p.exists():
        return {"present": False, "path": BENCH, "rows": [], "sha256": None}
    try:
        doc = json.loads(p.read_text())
    except ValueError:
        return {"present": False, "path": BENCH, "rows": [], "sha256": None}
    head = doc.get("headline", doc) if isinstance(doc, dict) else {}
    rows = []
    if isinstance(head, dict):
        for k, v in head.items():
            if isinstance(v, (int, float, str)) and not isinstance(v, bool) and len(rows) < 8:
                rows.append([str(k), v])
    return {"present": True, "path": BENCH, "rows": rows, "sha256": _sha256(p)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "build"
    if cmd not in ("build", "check"):
        print("usage: python -m orderguard_app.theater [build|check]", file=sys.stderr)
        return 2
    fresh = serialise(build())
    if cmd == "check":
        ok = OUT.exists() and OUT.read_text() == fresh
        print("results/theater/timeline.json is current" if ok else "results/theater/timeline.json is stale: run python -m orderguard_app.theater build")
        return 0 if ok else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(fresh)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(fresh.encode()):,} bytes")
    return 0


router = APIRouter()
_gz: dict[str, bytes] = {}


def _timeline_response(request: Request) -> Response:
    try:
        text = timeline_text()
    except FileNotFoundError as e:
        raise AppError(404, f"the Swarm Theater needs recorded results that are not installed here: {e}") from None
    if "gzip" in request.headers.get("accept-encoding", ""):
        with _lock:
            if _gz.get("fp") != _memo.get("fp"):
                _gz.clear()
                _gz.update({"fp": _memo["fp"], "body": gzip.compress(text.encode(), 6, mtime=0)})
            body = _gz["body"]
        return Response(body, media_type="application/json", headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(text, media_type="application/json", headers={"Vary": "Accept-Encoding"})


@router.get("/api/theater/timeline")
def theater_timeline(request: Request):
    """The precomputed Swarm Theater timeline: the packed event strip, per-step aggregates, feed, focus attacks, queue and sourced facts of the recorded run. Served gzip-compressed when the client accepts it."""
    return _timeline_response(request)


@router.get("/api/theater/bench")
def theater_bench():
    """The headline of results/bench/summary.json when it exists, else `present: false`. Read on every request; never cached."""
    return bench_headline()


@router.get("/api/theater/source")
def theater_source(id: str | None = Query(None, pattern=r"^[a-z0-9_]{1,24}$")):
    """Without `id`, the list of source files. With one of those ids (or `bench`), that committed file as plain text. An allow-list of exact ids; no path is ever taken from the request."""
    if id is None:
        return {"sources": [{"id": k, "path": v[0], "what": v[1]} for k, v in SOURCES.items()], "bench": BENCH}
    rel = BENCH if id == "bench" else SOURCES[id][0] if id in SOURCES else None
    if rel is None:
        raise AppError(404, "no such source; call this endpoint without an id to list them")
    p = ROOT / rel
    if not p.is_file():
        raise AppError(404, f"{rel} is not installed or has not been written yet")
    return FileResponse(p, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


if __name__ == "__main__":
    raise SystemExit(main())
