"""Reproducibility guard for the numbers printed in README.md and the docs.

Two kinds of check, both offline and deterministic:

  doc_claims()          every headline figure is rebuilt from the committed result files (never typed twice) and must appear, in the
                        exact words, in the README or the doc that quotes it. A number edited by hand, or a result regenerated
                        without updating the text, fails with the sentence that is stale.
  regeneration_checks() the committed results are regenerated from their seeds with the real tools and must match byte for byte
                        (timing fields excepted: they measure a machine, not the system). This is what `og-arena verify` runs.

Run `og-arena verify` (full) or `og-arena verify --quick` (docs against results only, about a second).
"""
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal
import tempfile
from dataclasses import dataclass
from pathlib import Path

from orderguard_guard import ROOT

RES = ROOT / "results" / "arena"
BASE = "arena-s7-k1000-t2000"
BINANCE = "replay-binance-public-20261111T000117Z-k1000"
FEED = ROOT / "data" / "arena" / "feeds" / "binance-public-20261111T000117Z.jsonl"
FLASH = "deepseek/deepseek-v4.1-flash-1017"

# Frontier parameters the committed .frontier.json was produced with (the og-arena frontier flags in docs/ARENA.md).
FRONTIER_ARGS = dict(samples=240, seed=0, max_leak_per_day=250000.0, max_approvals_per_day=60.0, max_false_refusal=0.05)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _json(p: Path):
    return json.loads(_read(p))


def m(x: float) -> str:                       # $7.97M
    return f"${x / 1e6:.2f}M"


def usd(x: float) -> str:                     # 7,965,456 (no symbol: tables carry the $ in the header)
    return f"{x:,.0f}"


def hu(x: float, nd: int = 1) -> str:             # round half up on the printed decimal (the docs round that way; float formatting rounds to even)
    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP))


def pc(x: float, nd: int = 2) -> str:
    return f"{100 * x:.{nd}f}%"


def _events(name: str = BASE) -> list[dict]:
    lines = _read(RES / f"{name}.jsonl").splitlines()
    return [json.loads(x) for x in lines[1:] if x.strip()]


# ---------------------------------------------------------------------------------------------------------------- arena claims
def arena_expectations() -> list[tuple[str, str, str]]:
    """(doc, label, exact text that must appear) for ARENA.md and the README's arena paragraphs."""
    s = _json(RES / f"{BASE}.summary.json")
    fs = _json(RES / f"{BASE}-fairshare.summary.json")
    tf = _json(RES / f"{BASE}-tightestfit.summary.json")
    st = _json(RES / f"{BASE}-strict.summary.json")
    bench = _json(RES / "bench.json")["rows"]
    fr = _json(RES / f"{BASE}.frontier.json")
    rp = _json(RES / f"{BINANCE}.summary.json")
    ev = _events()
    out: list[tuple[str, str, str]] = []

    def A(label, text):
        out.append(("docs/ARENA.md", label, text))

    def R(label, text):
        out.append(("README.md", label, text))

    fresh = {d: sum(1 for e in ev if e["d"] == d and not e["replay"]) for d in ("allow", "hold", "refuse")}
    dup = {d: sum(1 for e in ev if e["d"] == d and e["replay"]) for d in ("allow", "hold")}
    n_dup = sum(dup.values())
    assert fresh["allow"] + fresh["hold"] + fresh["refuse"] + n_dup == s["proposals"] == len(ev)
    l7_holds = sum(1 for e in ev if e["d"] == "hold" and e["code"] == "l7" and not e["replay"])
    step_holds = sum(1 for e in ev if e["d"] == "hold" and e["code"] == "stepup" and not e["replay"])
    A("decision counts", f"The {s['proposals']:,} proposals produced {fresh['allow']:,} fresh allows, {fresh['hold']} fresh holds, {fresh['refuse']:,} refusals and "
                         f"{n_dup} duplicate-key responses. The duplicate responses repeated {dup['allow']} allows and {dup['hold']} holds")
    A("hold reasons", f"Of the fresh holds, {l7_holds} were for uncorroborated news and {step_holds} were step-up holds.")
    rr = {e["code"]: 0 for e in ev}
    for e in ev:
        if e["d"] == "refuse":
            rr[e["code"]] += 1
    A("refusal reasons", f"The refusals were for the daily cap ({rr['daily']:,}), price band ({rr['band']}), off-list or look-alike tickers ({rr['ticker']}), "
                         f"per-order cap ({rr['per_order']}) and money movement ({rr['money']}).")
    # per-label table
    bl = s["by_label"]
    rows = {k: v for k, v in bl.items()}
    merged = {k: v for k, v in rows.items() if k not in ("off_list", "homoglyph")}
    merged["off_list / homoglyph"] = {k: rows["off_list"][k] + rows["homoglyph"][k] for k in rows["off_list"]}
    for lab, v in merged.items():
        A(f"table row {lab}", f"| {lab} | {v['n']:,} | {v['allow']:,} | {v['hold']:,} | {v['refuse']:,} | {v['replays']:,} | {v['notional']:,.0f} | {v['allow_usd']:,.0f} |")
    b, L = s["bad"], s["legit"]
    A("bad notional paragraph", f"Of {m(b['attack_notional_usd'])} in measured bad-proposal notional, {m(b['blocked_usd'])} was refused or held ({100 * b['blocked_share']:.1f}%), "
                                f"{m(b['leaked_usd'])} was authorized ({m(b['executed_usd'])} filled), and {m(b['duplicates_absorbed_usd'])} was absorbed as duplicate deliveries.")
    A("colluder share", f"The colluding group accounted for {m(bl['collusion']['allow_usd'])} of authorized notional.")
    legit_codes = {}
    for e in ev:
        if e["label"] == "legit" and e["d"] == "refuse":
            legit_codes[e["code"]] = legit_codes.get(e["code"], 0) + 1
    A("legit refusals", f"The arena refused {L['refused']:,} of {L['proposals']:,} legitimate proposals ({100 * L['false_refusal_rate']:.2f}%), or {m(L['refused_usd'])} of {m(L['notional_usd'])}. "
                        f"The core daily cap accounted for {legit_codes['daily']:,} of those refusals, the price band for {legit_codes['band']}, and the per-order cap for {legit_codes['per_order']}. "
                        f"Another {L['held']} legitimate proposals received step-up holds.")
    A("fair share", f"A separate run with the same seed and a 1% share refused {100 * fs['legit']['false_refusal_rate']:.2f}% of legitimate proposals, authorized "
                    f"{m(fs['bad']['leaked_usd'])} of bad notional and blocked {100 * fs['bad']['blocked_share']:.1f}% of bad notional.")
    A("tightest fit", f"A separate `tightest_fit` run refused {100 * tf['legit']['false_refusal_rate']:.2f}% of legitimate proposals and authorized {m(tf['bad']['leaked_usd'])} "
                      f"in bad notional, with {100 * tf['bad']['blocked_share']:.1f}% blocked.")
    A("strict digest", f"**same event digest** (`{s['digest'][:8]}...`)")
    A("strict rate", f"The authority processed about {round(st['timing']['authority_decisions_per_s'], -3):,.0f} proposals per second in that run.")
    A("baseline p99", f"The separate 2,000-tick baseline recorded an inline p99 of {s['timing']['latency_us']['p99']} µs.")
    for r in bench:
        lat, rl = r["inline_latency_us"], r["replay_latency_us"]
        A(f"bench row {r['agents']}", f"| {r['agents']:,} | {r['proposals']:,} | {r['authority_inline_decisions_per_s']:,} | {r['authority_replay_pass_orders_per_s']:,} | "
                                      f"{hu(lat['p50'])} / {hu(lat['p95'])} / {hu(lat['p99'])} | {r['strict_orderGate_orders_per_s']:,} | {r['arena_end_to_end_proposals_per_s']:,} |")
    one = next(r for r in bench if r["agents"] == 1000)
    R("bench headline", f"the strict path processed **{one['strict_orderGate_orders_per_s']:,} decisions/s** on a {one['strict_sample']:,}-proposal sample. The inline path had a "
                        f"**{one['inline_latency_us']['p99']} µs p99**, and the end-to-end run processed **{one['arena_end_to_end_proposals_per_s']:,} proposals/s**.")
    # frontier
    base, rec = fr["baseline"], fr["recommendation"]["candidate"]
    pr = fr["profile"]
    A("frontier size", f"{len(fr['all']) - 2} Latin-hypercube candidates plus two anchors, {len(fr['frontier'])} on the frontier")
    A("frontier demand", f"Honest agents proposed about {m(pr['legit_daily_usd'])}/day in legitimate notional. The stream contains about {m(fr['bad_attempted_per_day_usd'])}/day in bad notional")
    A("frontier baseline", f"Replaying the baseline envelopes allowed {m(base['utility_per_day_usd'])}/day in legitimate notional ({100 * base['utility_share']:.1f}%), refused "
                           f"{100 * base['false_refusal_rate']:.1f}% of legitimate proposals, leaked {m(base['leaked_per_day_usd'])}/day and recorded {base['approvals_per_day']} holds/day.")
    A("frontier recommended", f"per-order cap of ${rec['per_order']:,.0f}, a daily cap of ${rec['daily']:,.0f}, a {rec['band_pct']:g}% price band, {rec['breadth']} allowed symbols, "
                              f"a step-up above ${rec['step_up']:,.0f} and a {100 * rec['agent_share']:.1f}% per-agent share. On replay it would have allowed "
                              f"${rec['utility_per_day_usd']:,.0f}/day in legitimate notional ({100 * rec['utility_share']:.1f}%), refused {100 * rec['false_refusal_rate']:.2f}% of "
                              f"legitimate proposals, leaked ${rec['leaked_per_day_usd']:,.0f}/day and recorded {rec['approvals_per_day']:.0f} holds/day.")
    R("frontier readme", f"The recommended envelope would have authorized {100 * rec['utility_share']:.1f}% of legitimate notional, leaked ${rec['leaked_per_day_usd']:,.0f} per simulated day "
                         f"and refused {100 * rec['false_refusal_rate']:.2f}% of legitimate proposals.")
    mono = fr["monotonicity"]
    sh = mono["agent_share"]["violations"][0]
    A("sweep share", f"raising the per-agent share from {100 * sh['from']:.0f}% to {100 * sh['to']:.0f}% increased total leak by {m(sh['leak_change_usd'])} and lowered legitimate notional allowed by ${-sh['utility_change_usd']:,.0f}.")
    po = mono["per_order"]["violations"][0]
    A("sweep per-order", f"Raising the per-order cap from ${po['from']:,.2f} to ${po['to']:,.2f} lowered total leak by ${-po['leak_change_usd']:,.0f} and legitimate notional allowed by ${-po['utility_change_usd']:,.0f}.")
    # Binance replay
    d = rp["decisions"]
    A("binance replay", f"Of {rp['proposals']:,} proposals, {d['allow']:,} were allowed, {d['hold']} held and {d['refuse']} refused. The run blocked "
                        f"{100 * rp['bad']['blocked_share']:.2f}% of labeled bad notional and refused {100 * rp['legit']['false_refusal_rate']:.2f}% of legitimate proposals.")
    # README arena paragraph
    R("readme arena", f"It held {l7_holds} uncorroborated news proposals.")
    R("readme baseline", f"The baseline authorized ${b['leaked_usd'] / 1e6:.2f}M of bad notional, including ${bl['collusion']['allow_usd'] / 1e6:.2f}M from one colluding group. "
                         f"The daily cap accounted for {legit_codes['daily']:,} of the {L['refused']:,} legitimate refusals. A separate run with the same seed and a 1% per-agent share authorized "
                         f"${fs['bad']['leaked_usd'] / 1e6:.2f}M of bad notional and refused {100 * fs['legit']['false_refusal_rate']:.2f}% of legitimate proposals.")
    # L8
    l8 = _read(RES / "l8-agreement-s23-k1000.txt")
    j = json.loads(l8[: l8.rindex("}") + 1])
    ag = j["l8"]
    A("l8", f"All **{ag['agree']:,} of {ag['sampled']:,}** eligible comparisons agreed, with zero unreachable requests. The arena processed {sum(j['decisions'].values()):,} proposals in total.")
    R("l8 readme", f"**{ag['agree']:,} of {ag['sampled']:,}** eligible decisions agreed with the TypeScript receiver.")
    return out


# ---------------------------------------------------------------------------------------------------------------- lab claims
def _md_rows(text: str, heading: str) -> list[list[str]]:
    """Rows of the first markdown table after `heading` (the generated RESULTS.md)."""
    i = text.index(heading)
    rows = []
    for ln in text[i:].splitlines()[1:]:
        if ln.startswith("|"):
            rows.append([c.strip() for c in ln.strip("|").split("|")])
        elif rows:
            break
    return rows[2:]


def _kn(cell: str) -> tuple[int, int]:
    k, n = re.match(r"(\d+)/(\d+)", cell).groups()
    return int(k), int(n)


def lab_expectations() -> list[tuple[str, str, str]]:
    from orderguard_lab import tables
    res = _read(ROOT / "docs" / "RESULTS.md")
    out: list[tuple[str, str, str]] = []

    def R(label, text):
        out.append(("README.md", label, text))

    fixed = _md_rows(res, f"### {FLASH} (live)")
    def tot(arm, col):
        k = n = 0
        for r in fixed:
            if r[0][0] in "ABCD" and r[1] == arm and r[col] != "-":
                a, b = _kn(r[col])
                k, n = k + a, n + b
        return k, n
    succ = {a: tot(a, 6) for a in ("naive", "full")}
    exe = {a: tot(a, 4) for a in ("naive", "full")}
    bel = {a: tot(a, 5) for a in ("naive", "full")}
    R("A-D success", f"| Attack goals achieved (families A–D) | {succ['naive'][0]} of {succ['naive'][1]} | **{succ['full'][0]} of {succ['full'][1]}** |")
    R("A-D executed", f"| Attacker actions executed (same A–D trials) | {exe['naive'][0]} of {exe['naive'][1]} | {exe['full'][0]} of {exe['full'][1]} |")
    R("belief", f"| Planted claims repeated without a matching doubt term (belief-targeted A–D trials) | {bel['naive'][0]} of {bel['naive'][1]} | **{bel['full'][0]} of {bel['full'][1]}** |")
    e = {r[1]: _kn(r[6]) for r in fixed if r[0].startswith("E ")}
    R("E dropped", f"| Legitimate trades dropped (family E denial-of-service trials) | {e['naive'][0]} of {e['naive'][1]} | **{e['full'][0]} of {e['full'][1]}** |")
    ctl_rows = _md_rows(res[res.index(f"### {FLASH} (live)"):], "Utility on clean controls")
    c = {r[0]: _kn(r[2]) for r in ctl_rows}
    R("controls", f"| Clean controls completed | {c['naive'][0]} of {c['naive'][1]} | {c['full'][0]} of {c['full'][1]} |")

    sweeps = tables.load_dir(tables.SWEEPS)
    last = {(r["seed"], r["case_id"], r["arm"], r["who"], r.get("rep", 0)): r for r in sweeps}
    rows = [r for r in last.values() if r["who"] == FLASH and r["mode"] == "live"]
    scen = [r for r in rows if not r["control"]]
    jobs = [r for r in scen if r["family"] != "F"]
    att = {a: [r for r in jobs if r["arm"] == a and not r["attack"].get("error")] for a in ("naive", "full")}
    sk = {a: (sum(bool(r["attack"]["success"]) for r in att[a]), len(att[a])) for a in att}
    harm = {a: sum(r["attack"].get("harm_usd") or 0 for r in att[a]) for a in att}
    nt = len({r["technique"] for r in jobs})
    seeds = len({r["seed"] for r in jobs})
    R("sandbox attacks", f"| Sandbox attack goals achieved ({nt} techniques × {seeds} seeds) | {sk['naive'][0]} of {sk['naive'][1]} evaluable trials, ${harm['naive']:,.2f} executed notional | "
                         f"**{sk['full'][0]} of {sk['full'][1]}**, ${harm['full']:,.0f} executed notional |")
    tw = {a: [r for r in scen if r["arm"] == a and not r["twin"].get("error")] for a in ("naive", "full")}
    tu = {a: (sum(bool(r["twin"]["utility"]) for r in tw[a]), len(tw[a])) for a in tw}
    R("sandbox twins", f"| Sandbox benign-twin tasks completed | {tu['naive'][0]} of {tu['naive'][1]} | **{tu['full'][0]} of {tu['full'][1]}** |")
    # error and composition statements
    flash_runs = [r for r in tables.load_runs() if r.get("model") == FLASH and r.get("mode", "live") == "live"]
    ctl_err = sum(1 for r in flash_runs if r["family"] == "control" and r["arm"] == "naive" and r.get("error"))
    atk_err = sum(1 for r in jobs if r["arm"] == "naive" and r["attack"].get("error"))
    nat = sum(1 for r in scen if r["arm"] == "naive" and r["family"] == "F")
    trig = sum(1 for r in scen if r["arm"] == "naive" and r["trigger_world"])
    word = {1: "One", 2: "two", 6: "six", 18: "18"}
    R("errors", f"{word[ctl_err]} bare-model clean control and {word[atk_err]} bare-model sandbox attack trials ended in errors. Benign-twin utility includes "
                f"{word[nat]} natural-error scenarios and correct abstention in {word[trig]} trigger scenarios per arm.")
    # adaptive
    ad = [json.loads(x) for x in _read(ROOT / "results" / "adaptive" / "20261110T232836.jsonl").splitlines() if x.strip()]
    goals, wins = len(ad), sum(1 for r in ad if r.get("success_round"))
    early = [r for r in ad if r.get("incomplete")]
    assert wins == 0 and len(early) == 1 and goals == 5 and max(len(r["rounds"]) for r in ad) == 5, "adaptive claim no longer holds"
    R("adaptive", f"An adaptive attacker recorded **0 observed successes** across five goals with up to five rounds each. One campaign stopped after "
                  f"{'two' if sum('target_actions' in x for x in early[0]['rounds']) == 2 else sum('target_actions' in x for x in early[0]['rounds'])} evaluated rounds when the attacker produced unusable output.")
    # detectors
    det = {r[0]: r for r in _md_rows(res, "## Detectors")}
    fl, lo = det["deepseek/deepseek-v4.1-flash"], det["cascade: local only"]
    R("detector flash", f"The recorded earlier DeepSeek Flash detector flagged {_kn(fl[3])[0]} of {_kn(fl[3])[1]} false-data chunks in the lab.")
    R("detector local", f"On the mixed lab chunk set, the local classifier flagged {_kn(lo[4])[0]} of {_kn(lo[4])[1]} attacks and {_kn(lo[5])[0]} of {_kn(lo[5])[1]} clean chunks. "
                        f"The earlier DeepSeek Flash detector flagged {_kn(fl[4])[0]} attacks and {_kn(fl[5])[0]} clean chunks.")
    return out


# ---------------------------------------------------------------------------------------------------------------- risk claims (read only)
def risk_expectations() -> list[tuple[str, str, str]]:
    """The README and RISK.md quote results/risk/*.json. This module only reads them (the order-risk package owns them).
    Layout: the v2 order-risk model (programmed units + learned trees), evaluated at fixed honest-hold budgets."""
    import numpy as np
    RK = ROOT / "results" / "risk"
    ev = _json(RK / "eval.json")
    out: list[tuple[str, str, str]] = []

    def K(label, text):
        out.append(("docs/RISK.md", label, text))

    def Rd(label, text):
        out.append(("README.md", label, text))

    def pc(x, nd=1):
        return f"{100 * x:.{nd}f}%"

    B = f"{ev['operating_budget']:.2%}"
    new, old = ev["v2_programmed"], ev["v1_architecture"]

    def brow(part, b):
        n, o = new[part]["budgets"][b], old[part]["budgets"][b]
        return (f"| {b} | **{pc(n['usd_recall'], 2)}** | {pc(n['honest_hold_rate'], 2)} | {pc(n['hold_precision'])} | {n['honest_holds_per_run_day']} | "
                f"{pc(o['usd_recall'], 2)} | {pc(o['honest_hold_rate'], 2)} | {pc(o['hold_precision'])} | {o['honest_holds_per_run_day']} |")
    for b in ("0.10%", "0.25%", "0.50%", "1.00%"):
        K(f"held-out budget {b}", brow("held_out_seeds", b))
        K(f"adaptive budget {b}", brow("adaptive_colluders", b))
    for nm, key in (("regime shift: train calm/normal, test volatile", "regime_shift_volatile"), ('regime shift: test "shifted"', "regime_shift_shifted"),
                    ("time split: train early steps, test late", "time_split")):
        r = ev[key]["budgets"][B]
        K(f"{key} row", f"| {nm} | {pc(r['usd_recall'], 2)} | {pc(r['honest_hold_rate'], 2)} | {pc(r['hold_precision'])} |")
    L = ev["leave_one_family_out"]
    for fam in ("collusion", "compromised", "fat_finger", "runaway", "stale_price"):
        r = L[fam]
        K(f"lofo {fam}", f"| {pc(r['v1_learned_only']['zero_shot'])} | {pc(r['learned_only']['zero_shot'])} |")
        K(f"lofo programmed {fam}", f"| **{pc(r['programmed']['zero_shot'])}** |")
    h, a = new["held_out_seeds"]["budgets"][B], new["adaptive_colluders"]["budgets"][B]
    ho, ao = old["held_out_seeds"]["budgets"][B], old["adaptive_colluders"]["budgets"][B]
    Rd("held-out", f"**On held-out seeds, at a review budget of {B} of honest orders,** {pc(h['usd_recall'], 2)} of bad dollars are held or refused with {pc(h['honest_hold_rate'], 2)} of honest orders held "
                   f"(the first model's architecture at the same budget: {pc(ho['usd_recall'], 2)} with {pc(ho['honest_hold_rate'], 2)}).")
    Rd("adaptive", f"**On adaptive colluders it never trained on: {pc(a['usd_recall'], 2)} with {pc(a['honest_hold_rate'], 2)} held** (first architecture: {pc(ao['usd_recall'], 2)} with {pc(ao['honest_hold_rate'], 2)}).")
    ff, sp, co = L["fat_finger"], L["stale_price"], L["compromised"]
    Rd("lofo", f"with a family left out of training entirely, the programmed units still stop {pc(ff['programmed']['zero_shot'])} of fat-finger dollars and {pc(sp['programmed']['zero_shot'])} of stale-price dollars "
               f"(trees alone: {pc(ff['learned_only']['zero_shot'])} and {pc(sp['learned_only']['zero_shot'])}); compromised agents remain the weak family at {pc(co['programmed']['zero_shot'])}")
    q = ff["learned_only"]["1_shot"]["usd_recall_q25_median_q75"]
    Rd("oneshot", f"one labelled fat-finger order took a model that had never seen the family from {pc(ff['learned_only']['zero_shot'])} to a median of {pc(q[1])} of that family's dollars (quartiles {pc(q[0])} to {pc(q[2])})")
    adv = _json(RK / "adversary.json")
    f2, f1 = adv["optimised_against_v2_programmed"]["fresh_seeds"], adv["optimised_against_v1_architecture"]["fresh_seeds"]
    Rd("adversary", f"gets ${f2['v2_programmed']['undetected_usd_per_day'] / 1e6:.2f}M a day past the new model, against ${f1['v1_architecture']['undetected_usd_per_day'] / 1e6:.2f}M a day for the attacker tuned on the first model against the first model")
    K("adversary v2", f"**${f2['v2_programmed']['undetected_usd_per_day']:,.0f}**")
    K("adversary v1", f"**${f1['v1_architecture']['undetected_usd_per_day']:,.0f}**")
    reps = {}
    for nm, tag, label in (("arena-replay-arena-s7-k1000-t2000.json", "synthetic", "synthetic, seed 7, 1,000 agents, 2,000 steps"),
                           ("arena-replay-replay-binance-public-20261111T000117Z-k1000.json", "binance", "recorded Binance public prices, 1,000 agents")):
        r = reps[tag] = _json(RK / nm)
        assert r["leak_after_usd"] == 0, "the risk replay no longer stops every bad dollar"
        K(f"arena replay {tag}", f"| {label} | ${r['leak_before_usd']:,.0f} | ${r['leak_after_usd']:,.0f} | {pc(r['honest_tightened_rate'], 2)} ({r['honest_held'] + r['honest_refused']} orders) |")
    a7, bn = reps["synthetic"], reps["binance"]
    Rd("risk arena", f"inline replay held or refused all ${a7['bad_allowed_usd'] / 1e6:.2f}M of bad notional the gate allowed, and sent {pc(a7['honest_tightened_rate'], 2)} of allowed honest orders to a human. "
                     f"On the recorded Binance-price stream: ${bn['bad_allowed_usd'] / 1e6:.2f}M to $0, {pc(bn['honest_tightened_rate'], 2)} of honest orders.")
    lat = _json(RK / "latency.json")
    Rd("latency", f"scored in pure Python ({lat['p50_us']:.0f} µs median, {lat['p99_us']:.0f} µs p99, features included)")
    K("latency", f"**{lat['p50_us']:.0f} µs median, {lat['p99_us']:.0f} µs p99**")
    z = np.load(ROOT / "data" / "risk" / "corpus.npz", allow_pickle=True)
    n_runs = len(set(z["run"].tolist()))
    Rd("corpus size", f"fitted on {len(z['run']):,} labelled proposals from {n_runs} simulated swarms")
    K("corpus size", f"{n_runs} times across seeds, swarm sizes (300 to 1,000 agents), archetype mixes, market regimes")
    K("corpus count", f"**{len(z['run']):,} labelled proposals**")
    size_mb = (ROOT / "data" / "models" / "order_risk.json").stat().st_size / 1e6
    Rd("model size", f"exported to {size_mb:.2f} MB of JSON")
    return out


def check_texts(expect: list[tuple[str, str, str]], label: str) -> list[Check]:
    docs: dict[str, str] = {}
    out = []
    for doc, what, text in expect:
        body = docs.setdefault(doc, _read(ROOT / doc))
        ok = text in body
        out.append(Check(f"{label}: {doc} {what}", ok, "" if ok else f"expected text not found in {doc}: {text!r}"))
    return out


class RiskSchemaChanged(RuntimeError):
    pass


def risk_checks() -> list[Check]:
    try:
        return check_texts(risk_expectations(), "risk")
    except (KeyError, IndexError, TypeError) as exc:
        return [Check("risk: results/risk/*.json layout", False,
                      f"the risk results no longer have the layout this check reads (missing {exc}); re-point claims.risk_expectations() at the new files "
                      f"when the README and docs/RISK.md are updated")]


def doc_claims(*, risk: bool = True) -> list[Check]:
    checks = check_texts(arena_expectations(), "arena") + check_texts(lab_expectations(), "lab")
    if risk:
        checks += risk_checks()
    return checks


# ---------------------------------------------------------------------------------------------------------------- regeneration
def _strip_timing(summary: dict) -> dict:
    s = dict(summary)
    s.pop("timing", None)
    return s


def _with_defaults(config: dict) -> dict:
    """A committed config predates later ArenaConfig fields; fill them with their defaults (which is what those runs used)."""
    from dataclasses import asdict
    from .arena import ArenaConfig
    merged = asdict(ArenaConfig()) | config
    merged.pop("keep_events", None)               # memory policy of the run, not part of what was simulated
    return merged


def _same_summary(a: dict, b: dict) -> str:
    """'' when equal; otherwise the first differing key. Timing excluded; configs compared after defaults are filled."""
    a, b = _strip_timing(a), _strip_timing(b)
    a["config"], b["config"] = _with_defaults(a["config"]), _with_defaults(b["config"])
    for k in sorted(set(a) | set(b)):
        if json.dumps(a.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True):
            return k
    return ""


def regeneration_checks(*, frontier: bool = True) -> list[Check]:
    from .arena import ArenaConfig, load_stream, run_arena
    from .feeds import RecordedFeed
    from .frontier import run_frontier
    out: list[Check] = []
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        runs = {"": dict(), "-fairshare": dict(agent_share=0.01), "-tightestfit": dict(routing="tightest_fit"), "-strict": dict(strict=True)}
        for suffix, kw in runs.items():
            name = BASE + suffix
            cfg = ArenaConfig(seed=7, agents=1000, steps=2000, name=name if suffix else None, keep_events=False, **kw)    # the baseline was run unnamed
            r = run_arena(cfg, out_dir=d, write=True)
            diff = _same_summary(r.summary, _json(RES / f"{name}.summary.json"))
            out.append(Check(f"regenerate {name} summary (timing excluded)", not diff, f"first difference in '{diff}': re-run `og-arena run --seed 7 --agents 1000 --steps 2000` with the same flags" if diff else ""))
            if suffix == "":
                same = _read(d / f"{name}.jsonl").split("\n", 1)[1] == _read(RES / f"{name}.jsonl").split("\n", 1)[1]
                out.append(Check(f"regenerate {name} event log (every event byte-identical)", same, "" if same else "the 20,503-event log differs from the committed one"))
        feed = RecordedFeed(FEED)
        r = run_arena(ArenaConfig(seed=7, agents=1000, steps=len(feed), steps_per_day=feed.steps_per_day, name=BINANCE, keep_events=False), feed=feed, out_dir=d, write=True)
        diff = _same_summary(r.summary, _json(RES / f"{BINANCE}.summary.json"))
        same = _read(d / f"{BINANCE}.jsonl").split("\n", 1)[1] == _read(RES / f"{BINANCE}.jsonl").split("\n", 1)[1]
        out.append(Check("regenerate recorded-feed replay summary", not diff, f"first difference in '{diff}'" if diff else ""))
        out.append(Check("regenerate recorded-feed replay event log", same))
        from .cli import bench_one
        for row in _json(RES / "bench.json")["rows"]:
            new = bench_one(row["agents"], row["steps"])
            bad = [k for k in ("proposals", "decisions", "digest", "strict_sample") if new[k] != row[k]]
            out.append(Check(f"regenerate bench {row['agents']} agents (deterministic columns)", not bad, f"differs in {bad}" if bad else ""))
        if frontier:
            meta, events = load_stream(RES / f"{BASE}.jsonl")
            f = run_frontier(events, meta, **FRONTIER_ARGS)
            slim = {k: v for k, v in f.items() if k != "all"}
            slim["all"] = [{k: r[k] for k in ("label", "utility_per_day_usd", "leaked_per_day_usd", "false_refusal_rate", "approvals_per_day", "utility_share", "blocked_share")} for r in f["all"]]
            ok = json.loads(json.dumps(slim, sort_keys=True)) == _json(RES / f"{BASE}.frontier.json")
            out.append(Check("regenerate envelope frontier from the committed event log", ok,
                             "" if ok else "run `og-arena frontier --stream results/arena/arena-s7-k1000-t2000.jsonl --max-leak 250000 --max-approvals 60`"))
    return out


def run_all(*, quick: bool = False, frontier: bool = True) -> list[Check]:
    checks = doc_claims()
    if not quick:
        checks += regeneration_checks(frontier=frontier)
    return checks
