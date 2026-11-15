"""The bench workload: a swarm of simulated agents under many human-signed envelopes, plus traffic aimed at the system itself.

Owners and envelopes. Each owner has their own Ed25519 key and signs three envelopes (core, tactical, crypto: the arena's sleeves) sized
for the agents that share them, as `orderguard_arena.envelopes.default_envelopes` does. Every second owner also signs the portfolio
limits (per-symbol daily cap, net position cap, orders per day). Keys are derived from public labels (simulated owners; not secrets).

Agents. `orderguard_arena.agents.make_population` (unchanged): five honest strategies plus fat finger, stale price, off-list, homoglyph,
compromised, runaway and colluding agents at the arena's default rates. Colluding groups are split three ways: the arena's naive
colluders, the stealth colluders and the white-box adaptive colluders from `orderguard_risk.dataset` (the latter with the parameters
the attacker search found against the shipped model, results/risk/adversary.json). Every proposal carries the arena's oracle label.

Traffic aimed at the system (each item is tagged with a `kind`):
  retry      the same key and order delivered again 1-20 steps later (a client retry)
  dup_now    the same key and order delivered twice back to back (duplicate delivery)
  conflict   a key reused for a different order (a tampered retry): must be refused and consume nothing
  burst      ~1.6x an envelope's daily cap fired at it in one step by many agents (every tenth owner)
  probe      the largest order that fits the per-order cap, one share more, and limits one cent inside and outside the band
  ctl        control events: revoke an envelope, then replay its signed mandate, present a widened (tampered) copy and one signed by a
             key that is not the owner's

Generation is open-loop: agents never see the authority's answers, and every honest order is assumed to fill (so honest agents can
sell). It runs once into `partitions` owner partitions; a worker loads the partitions of the owners it serves. The order of items is
a global key (step, priority, agent, n), so every envelope sees the same sequence however the owners are sharded.
"""
from __future__ import annotations

import copy
import json
import math
import pickle
import random
from pathlib import Path

from orderguard_arena.agents import DEFAULT_RATES, Ctx, PopulationConfig, Proposal, make_population
from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import DEFAULT_LIMITS, PURPOSES, EnvelopeBook, make_envelope, owner_key_from_seed, split_sleeves
from orderguard_guard import ROOT
from orderguard_guard.gate import public_key_to_b64, sign_mandate
from orderguard_guard.money import notional_cents, usd_cents

from .market import BenchMarket
from .profiles import Profile

ADVERSARY = ROOT / "results" / "risk" / "adversary.json"
SLEEVES = ("core", "tactical", "crypto")
ORDERS_PER_AGENT_DAY = 4.0          # orders-per-day cap, per agent sharing the envelope, for owners with portfolio limits (sized from a measured run)


def owner_key(seed: int, o: int):
    return owner_key_from_seed(f"bench-{seed}-owner-{o}")


def attacker_key(seed: int):
    return owner_key_from_seed(f"bench-{seed}-attacker")


def env_name(o: int, sleeve: str) -> str:
    return f"o{o}-{sleeve}"


def agents_per_owner(p: Profile) -> float:
    return p.agents / p.owners


def envelope_terms(p: Profile, o: int, sleeve: str, symbols: list[str]) -> dict:
    per_order, daily100, band, su = DEFAULT_LIMITS[sleeve]
    apo = agents_per_owner(p)
    daily = round(daily100 * apo / 100.0, 2)
    terms = dict(name=env_name(o, sleeve), owner=f"owner-{o}", purpose=PURPOSES[sleeve], symbols=symbols, per_order=per_order, daily=daily,
                 band_pct=band, step_up=per_order * su)
    if o % 2 == 0:                     # every second owner signs the portfolio limits
        terms.update(max_symbol_daily=round(max(per_order, 0.5 * daily), 2), max_position=round(max(per_order, 0.25 * daily), 2),
                     max_orders_per_day=max(10, int(apo * ORDERS_PER_AGENT_DAY * (p.steps_per_day / 500.0))))
    return terms


def owner_book(p: Profile, o: int, sleeves: dict) -> EnvelopeBook:
    key = owner_key(p.seed, o)
    book = EnvelopeBook(key.public_key())
    for s in SLEEVES:
        if s in sleeves:
            book.add(make_envelope(key, **envelope_terms(p, o, s, sleeves[s])))
    return book


def registry(p: Profile, market: BenchMarket) -> dict:
    """What the auditor is given: every owner's public key and every signed mandate (exactly the bytes the owner signed)."""
    sleeves = split_sleeves(market.symbols)
    out = {}
    for o in range(p.owners):
        book = owner_book(p, o, sleeves)
        pub = public_key_to_b64(book.public_key)
        for e in book.envelopes():
            out[e.name] = {"owner": o, "id": e.id, "public_key": pub, "mandate": e.mandate}
    return out


def whitebox_theta() -> dict:
    try:
        return dict(json.loads(ADVERSARY.read_text())["optimised_against_v2_programmed"]["best_theta"])
    except (OSError, KeyError, ValueError):
        return {"period": 1, "p": 0.5, "lo": 0.05, "hi": 0.55, "warm": 0.0, "aggr": 0.001, "one_ticker": 0, "window": 400, "groups": 2}


def population(p: Profile, market: BenchMarket):
    """(agents, owner_of) with colluding groups split into naive / stealth / white-box adaptive."""
    from orderguard_risk.dataset import AdaptiveColluder, StealthColluder, _as_stealth
    sleeves = split_sleeves(market.symbols)
    agents = make_population(PopulationConfig(n=p.agents, seed=p.seed, rates=dict(DEFAULT_RATES), fail_prob=0.15), sleeves, p.steps)
    theta = whitebox_theta()
    owner_of = {}
    for i, a in enumerate(agents):
        if a.failure == "colluding" and a.group:
            gid = a.group["id"]
            owner_of[a.id] = (gid * 7919 + 3) % p.owners            # a whole group shares one owner's envelope
            if gid % 4 == 1:
                agents[i] = _as_stealth(a, StealthColluder)
            elif gid % 4 == 3:
                b = _as_stealth(a, AdaptiveColluder, theta)
                b.group["window"] = int(theta.get("window", b.group["window"]))
                b.adaptive = True
                agents[i] = b
        else:
            owner_of[a.id] = a.id % p.owners
    return agents, owner_of


def collude_caps(p: Profile, market: BenchMarket) -> tuple[dict, dict]:
    """What colluders know (worst case): their envelope's per-order cap lowered to the step-up threshold, and its daily cap. All owners'
    envelopes of a sleeve have the same terms (owners are equal-sized), so owner 0's terms stand for all."""
    sleeves = split_sleeves(market.symbols)
    caps, daily = {}, {}
    for s, syms in sleeves.items():
        t = envelope_terms(p, 0, s, syms)
        for sym in syms:
            if sym not in caps or t["per_order"] < caps[sym]:       # home envelope = the narrowest sleeve listing the symbol
                caps[sym] = min(t["per_order"], t["step_up"])
                daily[sym] = t["daily"]
    return caps, daily


# ---- item layout ---------------------------------------------------------------------------------------------------------------------
# (sort_key, kind, owner, env, agent, label, order, key, trigger, note)
#   sort_key = (step, priority, agent, n): priority 0 control, 1 proposal, 2 injected (retries, conflicts)
STEP, KIND, OWNER, ENV, AGENT, LABEL, ORDER, KEY, TRIG, NOTE = range(10)


def _item(step, prio, agent, n, kind, owner, env, label, order, key, trig=None, note=""):
    return ((step, prio, agent, n), kind, owner, env, agent, label, order, key, trig, note)


def generate_partition(p: Profile, part: int, market: BenchMarket | None = None) -> dict:
    """Generate every item for the owners o with o % partitions == part. Deterministic."""
    market = market or BenchMarket(p.seed, p.steps, p.steps_per_day)
    sleeves = split_sleeves(market.symbols)
    agents, owner_of = population(p, market)
    mine = [a for a in agents if owner_of[a.id] % p.partitions == part]
    owners = [o for o in range(p.owners) if o % p.partitions == part]
    ctx = Ctx(p.steps, *collude_caps(p, market))
    scratch = Authority(EnvelopeBook(owner_key(p.seed, 0).public_key()), steps_per_day=p.steps_per_day)
    items: list = []
    inj_rng = {a.id: random.Random(f"{p.seed}:{a.id}:inject") for a in mine}
    for snap in market:
        step = snap.step
        scratch.on_snapshot(snap)
        ctx.update(step, scratch.prices, snap.meta.get("fake_news", ()))
        for a in mine:
            props = a.propose(ctx, snap, step)
            if not props:
                continue
            o = owner_of[a.id]
            env = env_name(o, a.sleeve)
            for j, pr in enumerate(props):
                if getattr(a, "adaptive", False):
                    pr.label = "collusion_adaptive"
                trig = None
                if pr.trigger is not None:
                    ok, _ = scratch.confirm_trigger(pr.trigger, pr.order["ticker"], pr.order["side"])
                    trig = {**pr.trigger, "confirmed": ok}
                n = a.n * 4 + j
                items.append(_item(step, 1, a.id, n, "orig", o, env, pr.label, pr.order, pr.key, trig, pr.note))
                _inject(p, items, inj_rng[a.id], pr, step, a.id, n, o, env, trig)
                o_ = pr.order
                if pr.label == "legit" and o_.get("side") in ("buy", "sell") and o_.get("ticker") in scratch.prices:
                    a.on_fill(o_["ticker"], o_["side"], int(o_["quantity"]))       # open loop: honest orders are assumed to fill
    for o in owners:
        items.extend(_system_traffic(p, o, market, sleeves))
    items = [it for it in items if it[0][0] < p.steps]
    items.sort(key=lambda it: it[0])
    return {"part": part, "owners": owners, "items": items}


def _inject(p: Profile, items: list, rng: random.Random, pr: Proposal, step: int, agent: int, n: int, o: int, env: str, trig) -> None:
    u = rng.random()
    if u < p.retry_rate:
        items.append(_item(step + rng.randint(1, 20), 2, agent, n, "retry", o, env, pr.label, copy.deepcopy(pr.order), pr.key, trig, pr.note))
    elif u < p.retry_rate + p.dupnow_rate:
        items.append(_item(step, 1, agent, n + 1_000_000, "dup_now", o, env, pr.label, copy.deepcopy(pr.order), pr.key, trig, pr.note))
    elif u < p.retry_rate + p.dupnow_rate + p.conflict_rate:
        alt = copy.deepcopy(pr.order)
        if isinstance(alt.get("quantity"), int):
            alt["quantity"] += 1
        else:
            alt["amount_usd"] = float(alt.get("amount_usd") or 0) + 1
        items.append(_item(step + rng.randint(0, 5), 2, agent, n, "conflict", o, env, "key_conflict", alt, pr.key, trig, "tampered retry"))


def _system_traffic(p: Profile, o: int, market: BenchMarket, sleeves: dict) -> list:
    """Bursts at the shared budget, limit probes, and the revoke / replay / tamper sequence, for one owner. Deterministic."""
    out = []
    agent0 = -1 - o                                                    # system traffic uses negative agent ids (not swarm members)
    if o % 10 == 7 and "core" in sleeves:
        s = int(0.4 * p.steps)
        t = envelope_terms(p, o, "core", sleeves["core"])
        sym = sleeves["core"][0]
        px = market.trusted[s][sym]
        qty = max(1, int(t["step_up"] * 0.99 / px))
        count = int(math.ceil(1.6 * t["daily"] / (qty * px)))
        for i in range(count):
            out.append(_item(s, 1, agent0, i, "burst", o, t["name"], "burst", {"ticker": sym, "side": "buy", "quantity": qty,
                             "limit_price": round(px * 1.001, 2)}, f"burst-o{o}-{i}"))
    if o % 10 == 3:
        s = int(0.3 * p.steps)
        for sleeve in ("tactical", "crypto"):
            if sleeve not in sleeves:
                continue
            t = envelope_terms(p, o, sleeve, sleeves[sleeve])
            sym = sleeves[sleeve][-1]
            px = market.trusted[s][sym]
            fit = int(math.floor(t["per_order"] / px))
            while fit > 0 and notional_cents(fit, px) > usd_cents(t["per_order"]):
                fit -= 1
            band = t["band_pct"] / 100.0
            probes = [("cap_fit", fit, px), ("cap_plus_one", fit + 1, px),
                      ("band_inside", 1, math.floor(px * (1 + band) * 100) / 100), ("band_outside", 1, math.ceil(px * (1 + band) * 100 + 1) / 100)]
            for i, (tag, q, lim) in enumerate(probes):
                out.append(_item(s, 1, agent0, 100 + i + (10 if sleeve == "crypto" else 0), "probe", o, t["name"], "probe",
                                 {"ticker": sym, "side": "buy", "quantity": q, "limit_price": round(lim, 2)}, f"probe-o{o}-{sleeve}-{tag}", None, tag))
    if o % 10 == 5 and "tactical" in sleeves:
        s = int(0.6 * p.steps)
        name = env_name(o, "tactical")
        out.append(_item(s, 0, agent0, 0, "ctl", o, name, "ctl", {"action": "revoke"}, f"ctl-o{o}-revoke"))
        out.append(_item(s, 0, agent0, 1, "ctl", o, name, "ctl", {"action": "replay_mandate"}, f"ctl-o{o}-replay"))
        out.append(_item(s, 0, agent0, 2, "ctl", o, name, "ctl", {"action": "tampered_mandate"}, f"ctl-o{o}-tamper"))
        out.append(_item(s, 0, agent0, 3, "ctl", o, name, "ctl", {"action": "foreign_mandate"}, f"ctl-o{o}-foreign"))
        sym = sleeves["tactical"][0]
        for i in range(3):                                           # orders after the revoke, on the revoked envelope: all must be refused
            px = market.trusted[s][sym]
            out.append(_item(s + 1 + i, 1, agent0, 200 + i, "probe", o, name, "probe", {"ticker": sym, "side": "buy", "quantity": 1,
                             "limit_price": round(px, 2)}, f"probe-o{o}-after-revoke-{i}", None, "after_revoke"))
    return out


def tampered_copy(mandate: dict) -> dict:
    m = copy.deepcopy(mandate)
    m["maxDailyNotionalUsd"] = float(m["maxDailyNotionalUsd"]) * 10      # widened after signing, signature kept
    return m


def foreign_copy(mandate: dict, seed: int) -> dict:
    body = {k: v for k, v in mandate.items() if k not in ("signature", "signerPublicKey")}
    body["maxDailyNotionalUsd"] = float(body["maxDailyNotionalUsd"]) * 10
    return sign_mandate(body, attacker_key(seed))                          # validly signed, by a key that is not the owner's


# ---- partition files ---------------------------------------------------------------------------------------------------------------------
def write_partitions(p: Profile, out_dir: Path, workers: int = 0) -> dict:
    """Generate every partition (in parallel processes) into out_dir/part-<k>.pkl. Returns counts."""
    import multiprocessing as mp
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(p, k, str(out_dir)) for k in range(p.partitions)]
    n = workers or min(p.partitions, mp.cpu_count() or 1)
    if n <= 1:
        res = [_gen_job(j) for j in jobs]
    else:
        with mp.get_context("spawn").Pool(n) as pool:
            res = pool.map(_gen_job, jobs)
    return {"partitions": p.partitions, "items": sum(r["items"] for r in res), "by_kind": _merge([r["by_kind"] for r in res]),
            "by_label": _merge([r["by_label"] for r in res])}


def _merge(ds):
    out = {}
    for d in ds:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return dict(sorted(out.items()))


def _gen_job(job) -> dict:
    p, k, out = job
    part = generate_partition(p, k)
    with open(Path(out) / f"part-{k}.pkl", "wb") as fh:
        pickle.dump(part, fh, protocol=pickle.HIGHEST_PROTOCOL)
    by_kind, by_label = {}, {}
    for it in part["items"]:
        by_kind[it[KIND]] = by_kind.get(it[KIND], 0) + 1
        by_label[it[LABEL]] = by_label.get(it[LABEL], 0) + 1
    return {"items": len(part["items"]), "by_kind": by_kind, "by_label": by_label}


def load_items(out_dir: Path, parts: list[int]) -> tuple[list[int], list]:
    owners, items = [], []
    for k in parts:
        with open(Path(out_dir) / f"part-{k}.pkl", "rb") as fh:
            d = pickle.load(fh)
        owners += d["owners"]
        items += d["items"]
    items.sort(key=lambda it: it[0])
    return sorted(owners), items
