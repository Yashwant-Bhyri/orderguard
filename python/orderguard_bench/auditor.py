"""The independent auditor. It never reads the system's counters, envelopes, budgets or reservations. Its inputs are:

  * the decision logs the shard workers wrote (one JSON record per decision, SHA-256 chained), or a receiver's SQLite ledger file;
  * the signed mandates and the owners' public keys (what the humans signed);
  * the raw venue quotes and news of the bench market (it computes its own trusted price: the median of the venue quotes).

From these it recomputes everything, envelope by envelope, in log order:

  chain        every line's hash recomputes and links to the previous one (and, for a receiver ledger, the same for the event chain)
  signature    every mandate verifies against its owner's key (Ed25519 over the auditor's own canonical JSON)
  price        every sized decision used the trusted price (the venue median), never the agent's limit; notional = qty x trusted, in cents
  caps         daily cap, per-order cap, per-symbol daily cap, net position cap and orders per day are never exceeded, counting every
               allowed and step-up-held order (what reserves budget), at the moment of the decision
  idempotency  one effect per key however many deliveries; a repeated delivery returns the first decision; a key reused for a
               different order is refused and reserves nothing
  revocation   nothing is allowed or held on an envelope after its revoke; replayed, widened and foreign-signed mandates do not take
  L7           every allowed order that claims a news trigger has >= 2 independent origins for that news id on the feed
  reproduce    every allow and every step-up hold is reproduced by the strict `orderguard_guard.gate.OrderGate` evaluating the signed
               mandate with the auditor's own state (the gate is the specification; the arena authority is the implementation under test)

A breach is anything that violates a guarantee. `refusal_disagreements` (the gate would have allowed an order the system refused) is
reported separately: it costs availability, not safety.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import math
import multiprocessing as mp
import sqlite3
import statistics
import unicodedata
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from orderguard_arena.feeds import BASE_DATE
from orderguard_guard.gate import OrderGate, normalise_ticker
from orderguard_guard.money import js_round, usd_cents
from orderguard_guard.market import UnknownTicker

GENESIS = "0" * 64
MAX_EXAMPLES = 8


# ---- market truth ---------------------------------------------------------------------------------------------------------------------
def trusted_table(market) -> list[dict]:
    """The auditor's own trusted prices: median of the venue quotes, rounded to 4 dp, per step."""
    return [{s: round(statistics.median(list(q.values())), 4) for s, q in snap.quotes.items()} for snap in market.snaps]


def news_origins(market) -> dict:
    out: dict[str, set] = {}
    for snap in market.snaps:
        for e in snap.news:
            out.setdefault(str(e["news_id"]), set()).add(e.get("origin"))
    return {k: len(v) for k, v in out.items()}


class _Quotes:
    def __init__(self, prices: dict):
        self.prices = prices

    def quote(self, ticker: str) -> dict:
        p = self.prices.get(ticker.upper())
        if p is None:
            raise UnknownTicker(ticker)
        return {"price": p, "as_of": "audit", "source": "venue-median"}

    def status(self, ticker: str) -> dict:
        return {"halted": False, "lot_size": 1, "band_pct": None, "as_of": "audit", "source": "venue-median"}


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_signature(mandate: dict, public_key_b64: str) -> bool:
    body = {k: v for k, v in mandate.items() if k not in ("signature", "signerPublicKey") and v is not None}
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(base64.b64decode(mandate["signature"]), canonical(body))
        return True
    except Exception:
        return False


def py_cents(x: float) -> int:          # the Python authority's rounding: ONE rule with the receiver (orderguard_guard.money)
    return js_round(x)


def js_cents(x: float) -> int:          # the receiver's rounding: Math.round, exactly
    return js_round(x)


# ---- per-envelope state ---------------------------------------------------------------------------------------------------------------
class Book:
    """The auditor's own tally for one envelope: integer cents, from the effects it has seen so far."""

    def __init__(self, mandate: dict):
        self.m = mandate
        self.cap = usd_cents(mandate["maxDailyNotionalUsd"])
        self.per_order = usd_cents(mandate["maxOrderNotionalUsd"])
        self.sym_cap = None if mandate.get("maxSymbolDailyNotionalUsd") is None else usd_cents(mandate["maxSymbolDailyNotionalUsd"])
        self.pos_cap = None if mandate.get("maxPositionUsd") is None else usd_cents(mandate["maxPositionUsd"])
        self.n_cap = mandate.get("maxOrdersPerDay")
        self.allowed = {unicodedata.normalize("NFKC", s).upper() for s in mandate["symbols"]}
        self.sides = {s.lower() for s in mandate["sides"]}
        self.band = float(mandate["priceBandPct"]) / 100.0
        self.used: dict = {}
        self.sym: dict = {}
        self.count: dict = {}
        self.net: dict = {}
        self.held: dict = {}

    def state(self, day: int) -> dict:
        return {"daily_total_usd": self.used.get(day, 0) / 100.0, "as_of": (BASE_DATE + dt.timedelta(days=day)).isoformat(),
                "symbol_daily_usd": {s: c / 100.0 for (d, s), c in self.sym.items() if d == day}, "positions": dict(self.net),
                "held_qty": {k: dict(v) for k, v in self.held.items()}, "orders_today": self.count.get(day, 0)}

    def exposure_cents(self, sym: str, side: str, qty: int, px: float, rnd) -> int:
        h = self.held.get(sym, {"buy": 0, "sell": 0})
        net = self.net.get(sym, 0)
        s = qty if side == "buy" else -qty
        return rnd(max(abs(net + h["buy"] + s), abs(net - h["sell"] + s)) * px * 100)

    def apply(self, day: int, sym: str, side: str, qty: int, cents: int, held: bool) -> None:
        self.used[day] = self.used.get(day, 0) + cents
        self.sym[(day, sym)] = self.sym.get((day, sym), 0) + cents
        self.count[day] = self.count.get(day, 0) + 1
        if held:
            h = self.held.setdefault(sym, {"buy": 0, "sell": 0})
            h[side] += qty
        else:
            self.net[sym] = self.net.get(sym, 0) + (qty if side == "buy" else -qty)


class Findings:
    def __init__(self):
        self.breaches: dict[str, int] = {}
        self.examples: list[dict] = []
        self.checked: dict[str, int] = {}
        self.notes: dict[str, int] = {}

    def ok(self, name: str, n: int = 1) -> None:
        self.checked[name] = self.checked.get(name, 0) + n

    def bad(self, name: str, detail: dict) -> None:
        self.breaches[name] = self.breaches.get(name, 0) + 1
        if len(self.examples) < MAX_EXAMPLES:
            self.examples.append({"breach": name, **detail})

    def note(self, name: str, n: int = 1) -> None:
        self.notes[name] = self.notes.get(name, 0) + n

    def merge(self, other: "Findings") -> None:
        for a, b in ((self.breaches, other.breaches), (self.checked, other.checked), (self.notes, other.notes)):
            for k, v in b.items():
                a[k] = a.get(k, 0) + v
        self.examples += other.examples[: max(0, MAX_EXAMPLES - len(self.examples))]

    def to_dict(self) -> dict:
        return {"breaches": dict(sorted(self.breaches.items())), "breach_total": sum(self.breaches.values()), "checked": dict(sorted(self.checked.items())),
                "notes": dict(sorted(self.notes.items())), "examples": self.examples}


# ---- decision-log audit -----------------------------------------------------------------------------------------------------------------
def read_log(path: str | Path, f: Findings) -> list[str]:
    """Verify the chain and return the record bodies in order."""
    prev = GENESIS
    bodies = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            h, _, body = line.rstrip("\n").partition(" ")
            if hashlib.sha256((prev + "|" + body).encode()).hexdigest() != h:
                f.bad("chain", {"log": Path(path).name, "line": n})
                prev = h
            else:
                prev = h
            bodies.append(body)
    f.ok("chain_links", len(bodies))
    return bodies


def audit_logs(logs: list[str], reg: dict, market, *, procs: int = 0, expect_ctl: bool = True) -> dict:
    """Audit every decision log of one run. Envelopes are independent, so they are audited in parallel."""
    f = Findings()
    by_env: dict[str, list[str]] = {}
    for lp in logs:
        for body in read_log(lp, f):
            env = json.loads(body)["e"] if '"x":"ctl"' in body else body[body.index('"e":"') + 5: body.index('"', body.index('"e":"') + 5)]
            by_env.setdefault(env, []).append(body)
    prices = trusted_table(market)
    origins = news_origins(market)
    spd = market.steps_per_day
    envs = sorted(by_env)
    n = procs or min(8, mp.cpu_count() or 1)
    chunks = [envs[i::n] for i in range(n)] if len(envs) >= n else [envs]
    jobs = [([(e, by_env[e]) for e in ch], {e: reg[e] for e in ch if e in reg}, prices, origins, spd) for ch in chunks if ch]
    if n > 1 and len(jobs) > 1:
        with mp.get_context("spawn").Pool(len(jobs)) as pool:
            parts = pool.map(_audit_chunk, jobs)
    else:
        parts = [_audit_chunk(j) for j in jobs]
    env_digests = {}
    totals = {"decisions": 0, "allow": 0, "hold": 0, "refuse": 0, "final_allow": 0, "final_hold": 0, "final_refuse": 0, "effects": 0, "effect_usd": 0.0}
    for ff, dig, tot in parts:
        f.merge(ff)
        env_digests.update(dig)
        for k, v in tot.items():
            totals[k] = totals.get(k, 0) + v
    gate_digest = hashlib.sha256("".join(f"{e}:{env_digests[e][0]}" for e in sorted(env_digests)).encode()).hexdigest()[:32]
    final_digest = hashlib.sha256("".join(f"{e}:{env_digests[e][1]}" for e in sorted(env_digests)).encode()).hexdigest()[:32]
    out = f.to_dict()
    out.update({"envelopes": len(envs), "gate_digest": gate_digest, "final_digest": final_digest, "totals": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in totals.items()}})
    return out


def _audit_chunk(job):
    envs, reg, prices, origins, spd = job
    f = Findings()
    digests = {}
    totals = {"decisions": 0, "allow": 0, "hold": 0, "refuse": 0, "final_allow": 0, "final_hold": 0, "final_refuse": 0, "effects": 0, "effect_usd": 0.0}
    for env, bodies in envs:
        r = reg.get(env)
        if r is None:
            f.bad("unknown_envelope", {"env": env})
            continue
        dg, df = _audit_envelope(env, [json.loads(b) for b in bodies], r, prices, origins, spd, f, totals)
        digests[env] = (dg, df)
    return f, digests, totals


def _audit_envelope(env: str, recs: list[dict], reg: dict, prices: list[dict], origins: dict, spd: int, f: Findings, totals: dict):
    m = reg["mandate"]
    if verify_signature(m, reg["public_key"]):
        f.ok("signature")
    else:
        f.bad("signature", {"env": env})
    gate = OrderGate(m, _Quotes({}))
    book = Book(m)
    seen: dict[str, tuple] = {}
    revoked_at = None
    hg, hf = hashlib.sha256(), hashlib.sha256()
    for rec in recs:
        if rec.get("x") == "ctl":
            act, res = rec["ctl"], rec["res"]
            if act == "revoke":
                revoked_at = rec["t"]
                f.ok("revocations")
            elif act == "replay_mandate":
                f.ok("mandate_replays")             # whether it took is decided by what follows: no effect may land after the revoke
            elif act in ("tampered_mandate", "foreign_mandate"):
                if str(res).startswith("rejected"):
                    f.ok("forged_mandates_rejected")
                else:
                    f.bad("forged_mandate_accepted", {"env": env, "action": act})
            continue
        totals["decisions"] += 1
        g, d, key, order, step = rec["g"], rec["d"], rec["k"], rec["q"], rec["t"]
        totals[g] += 1
        totals["final_" + d] += 1
        if d != g and not (g == "allow" and d in ("hold", "refuse")):
            f.bad("risk_loosened", {"env": env, "key": key, "gate": g, "final": d})
        hg.update(f"{key}|{g}|{rec['c']}|{rec['r']}|{rec['n']}\n".encode())
        hf.update(f"{key}|{d}\n".encode())
        fp = canonical(order)
        day = step // spd
        prior = seen.get(key)
        if prior is not None:
            if prior[0] == fp:
                if not rec["r"] or g != prior[1]:
                    f.bad("idempotent_replay", {"env": env, "key": key, "first": prior[1], "again": g, "replay": rec["r"]})
                else:
                    f.ok("replays_identical")
                if (not rec["r"]) and g in ("allow", "hold") and rec.get("y") != "L7":
                    f.bad("double_execution", {"env": env, "key": key, "step": step})
            else:
                if g != "refuse":
                    f.bad("key_conflict_not_refused", {"env": env, "key": key, "decision": g})
                else:
                    f.ok("key_conflicts_refused")
            continue
        seen[key] = (fp, g)
        effect = g in ("allow", "hold") and rec.get("y") != "L7"
        # price and size: the decision must have used the venue median, never the agent's limit
        ticker, problem = normalise_ticker(order.get("ticker")) if order.get("ticker") is not None else ("", "no ticker")
        px_tab = prices[step]
        tp = px_tab.get(ticker) if not problem else None
        if rec["p"] is not None:
            if tp is None or abs(rec["p"] - tp) > 1e-9:
                f.bad("trusted_price", {"env": env, "key": key, "used": rec["p"], "venue_median": tp})
            else:
                f.ok("trusted_price")
        if not effect:
            if g == "refuse" and rec.get("y") == "L5" and not problem and tp is not None and (revoked_at is None or step < revoked_at):
                gate.market = _Quotes(px_tab)
                res = gate.evaluate(order, book.state(day))
                if res["decision"] != "refuse":
                    f.note("refusal_disagreements")
            continue
        totals["effects"] += 1
        # an effect: re-derive everything from the mandate and the auditor's own tally
        if revoked_at is not None and step >= revoked_at:
            f.bad("effect_after_revoke", {"env": env, "key": key, "step": step, "revoked_at": revoked_at})
        side = str(order.get("side", "")).strip().lower()
        qty = order.get("quantity")
        if problem or tp is None or ticker not in book.allowed or side not in book.sides or not isinstance(qty, int) or qty <= 0:
            f.bad("out_of_scope", {"env": env, "key": key, "ticker": ticker, "side": side, "qty": qty})
            continue
        cents = py_cents(qty * tp * 100)
        if rec["n"] is None or usd_cents(rec["n"]) != cents:
            f.bad("notional", {"env": env, "key": key, "logged": rec["n"], "recomputed": cents / 100})
        lim = order.get("limit_price")
        if not isinstance(lim, (int, float)) or abs((lim - tp) / tp) > book.band + 1e-12:
            f.bad("price_band", {"env": env, "key": key, "limit": lim, "trusted": tp})
        if cents > book.per_order:
            f.bad("per_order_cap", {"env": env, "key": key, "cents": cents})
        if book.used.get(day, 0) + cents > book.cap:
            f.bad("daily_cap", {"env": env, "day": day, "used": book.used.get(day, 0) / 100, "order": cents / 100, "cap": book.cap / 100})
        if book.sym_cap is not None and book.sym.get((day, ticker), 0) + cents > book.sym_cap:
            f.bad("symbol_daily_cap", {"env": env, "day": day, "symbol": ticker})
        if book.n_cap is not None and book.count.get(day, 0) + 1 > book.n_cap:
            f.bad("orders_per_day", {"env": env, "day": day})
        if book.pos_cap is not None and book.exposure_cents(ticker, side, qty, tp, py_cents) > book.pos_cap:
            f.bad("position_cap", {"env": env, "symbol": ticker, "key": key})
        if rec.get("tr") is not None:
            if not rec["tr"] or origins.get(str(rec.get("nid")), 0) < 2:
                f.bad("l7_unconfirmed_effect", {"env": env, "key": key, "news_id": rec.get("nid")})
            else:
                f.ok("l7_confirmed")
        gate.market = _Quotes(px_tab)
        res = gate.evaluate(order, book.state(day))
        want = "allow" if g == "allow" else "hold"
        if res["decision"] != want:
            f.bad("not_reproducible_by_order_gate", {"env": env, "key": key, "system": g, "order_gate": res["decision"], "why": (res.get("reasons") or [""])[0][:140]})
        else:
            f.ok("reproduced_by_order_gate")
        book.apply(day, ticker, side, qty, cents, held=(g == "hold"))
        totals["effect_usd"] += cents / 100
    f.ok("envelopes")
    return hg.hexdigest(), hf.hexdigest()


# ---- receiver ledger audit -------------------------------------------------------------------------------------------------------------
def audit_ledger(path: str | Path, mandate: dict, *, prices: dict | None = None, acked: dict | None = None, day_of=None) -> dict:
    """Audit a receiver SQLite ledger directly (Python sqlite3, not the receiver's own verifier).

    mandate   the signed mandate (OrderGate field names) the receiver ran under
    prices    optional {client_order_id: set of trusted prices at which it was delivered}: every row's trusted price must be one of them
    acked     optional {client_order_id: decision the client was told}: an order acknowledged as filled/held must be in the ledger
    """
    f = Findings()
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        events = db.execute("SELECT seq, type, order_id, payload, prev_hash, hash FROM events ORDER BY seq").fetchall()
        orders = db.execute("SELECT seq, order_id, client_order_id, symbol, side, quantity, limit_price, trusted_price, notional_cents, status, day "
                            "FROM orders ORDER BY seq").fetchall()
        meta = dict(db.execute("SELECT k, v FROM meta").fetchall())
    finally:
        db.close()
    prev = GENESIS
    for i, (seq, typ, oid, payload, ph, h) in enumerate(events, 1):
        if seq != i or ph != prev or hashlib.sha256("|".join([prev, str(seq), typ, oid or "", payload]).encode()).hexdigest() != h:
            f.bad("ledger_chain", {"seq": seq})
        prev = h
    f.ok("ledger_chain_links", len(events))
    revoked_seq = int(meta["revoked_seq"]) if "revoked_seq" in meta else None
    if revoked_seq is not None:
        for seq, typ, *_ in events:
            if seq > revoked_seq and typ in ("filled", "held", "approved"):
                f.bad("effect_after_revoke", {"seq": seq, "type": typ})
    book = Book(mandate)
    gate = OrderGate(mandate, _Quotes({}))
    per_key: dict[str, int] = {}
    days = sorted({r[10] for r in orders})
    dix = {d: i for i, d in enumerate(days)}
    used_usd = 0.0
    for seq, oid, coid, sym, side, qty, lim, tp, cents, status, day in orders:
        per_key[coid] = per_key.get(coid, 0) + 1
        if per_key[coid] > 1:
            f.bad("double_execution", {"client_order_id": coid, "rows": per_key[coid]})
        if status == "cancelled":
            continue
        d = dix[day]
        if js_cents(qty * tp * 100) != cents:
            f.bad("notional", {"client_order_id": coid})
        if prices is not None and coid in prices:
            if not any(abs(x - tp) <= 1e-9 for x in prices[coid]):
                f.bad("trusted_price", {"client_order_id": coid, "ledger": tp, "workload": sorted(prices[coid])})
            else:
                f.ok("trusted_price")
        if sym not in book.allowed or side not in book.sides:
            f.bad("out_of_scope", {"client_order_id": coid})
        if cents > book.per_order:
            f.bad("per_order_cap", {"client_order_id": coid})
        if abs(lim - tp) > tp * book.band + 1e-9:
            f.bad("price_band", {"client_order_id": coid})
        if book.used.get(d, 0) + cents > book.cap:
            f.bad("daily_cap", {"day": day, "used": book.used.get(d, 0) / 100, "order": cents / 100, "cap": book.cap / 100})
        if book.sym_cap is not None and book.sym.get((d, sym), 0) + cents > book.sym_cap:
            f.bad("symbol_daily_cap", {"day": day, "symbol": sym})
        if book.n_cap is not None and book.count.get(d, 0) + 1 > book.n_cap:
            f.bad("orders_per_day", {"day": day})
        if book.pos_cap is not None and book.exposure_cents(sym, side, qty, tp, js_cents) > book.pos_cap:
            f.bad("position_cap", {"symbol": sym, "client_order_id": coid})
        gate.market = _Quotes({sym: tp})
        st = book.state(d)
        st["as_of"] = day
        res = gate.evaluate({"ticker": sym, "side": side, "quantity": qty, "limit_price": lim}, st)
        want = "hold" if status == "held" else "allow"
        if res["decision"] != want:
            # Python and the receiver share one cents rule (orderguard_guard.money), so even an exact half cent must agree
            f.bad("not_reproducible_by_order_gate", {"client_order_id": coid, "status": status, "order_gate": res["decision"],
                                                     "why": (res.get("reasons") or [""])[0][:140]})
        else:
            f.ok("reproduced_by_order_gate")
        book.apply(d, sym, side, qty, cents, held=(status == "held"))
        used_usd += cents / 100
    if acked:
        rows = {r[2]: r[9] for r in orders}
        for coid, dec in acked.items():
            if dec in ("filled", "held"):
                if coid not in rows:
                    f.bad("acked_effect_lost", {"client_order_id": coid})
                else:
                    f.ok("acked_effects_durable")
    out = f.to_dict()
    out.update({"events": len(events), "orders": len(orders), "revoked": revoked_seq is not None, "used_usd": round(used_usd, 2),
                "head": {"seq": events[-1][0], "hash": events[-1][5]} if events else None})
    return out
