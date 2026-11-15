"""Orders exactly at the limits, through three implementations: the Python authority, the TypeScript receiver and the strict OrderGate.

Each envelope is signed so that a limit equals, to the cent, the notional of a whole number of units at the recorded BTCUSDT trusted
price of step 0. Each probe has the decision the signed mandate requires (at the cap: allowed; one share or one cent past it: refused,
or held for the step-up). Day 2 probes check that the daily counters roll over.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import Envelope, EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_guard.gate import OrderGate
from orderguard_guard.money import notional_cents

from . import auditor as A
from . import receiver as R
from .market import BenchMarket

FAR = "2099-01-01T00:00:00Z"


def _cents(q: int, px: float) -> int:
    return notional_cents(q, px)                    # the receiver's rule (orderguard_guard.money)


def scenarios(market: BenchMarket) -> list[dict]:
    px = market.trusted[0]["BTCUSDT"]
    ex = market.trusted[0]["ETHUSDT"]
    c10 = _cents(10, px) / 100
    big = 10_000_000.0
    up = math.floor(px * 1.01 * 100) / 100
    dn = math.ceil(px * 0.99 * 100) / 100
    B = lambda q, side="buy", lim=None, day=0, sym="BTCUSDT", p=None: {"sym": sym, "side": side, "q": q, "lim": round(lim if lim is not None else (p or px), 2), "day": day}
    return [
        {"name": "per_order", "terms": dict(symbols=["BTCUSDT"], per_order=c10, daily=big, band_pct=1.0),
         "probes": [("exactly at the per-order cap", B(10), "allow"), ("one unit over the per-order cap", B(11), "refuse")]},
        {"name": "daily", "terms": dict(symbols=["BTCUSDT"], per_order=big / 10, daily=round(3 * c10, 2), band_pct=1.0),
         "probes": [("1st of 3 equal orders", B(10), "allow"), ("2nd of 3", B(10), "allow"), ("3rd fills the daily cap exactly", B(10), "allow"),
                    ("one more unit the same day", B(1), "refuse"), ("next day: the cap has rolled over", B(10, day=1), "allow")]},
        {"name": "step_up", "terms": dict(symbols=["BTCUSDT"], per_order=big / 10, daily=big, band_pct=1.0, step_up=c10),
         "probes": [("exactly at the step-up threshold", B(10), "allow"), ("one unit above the step-up threshold", B(11), "hold")]},
        {"name": "band", "terms": dict(symbols=["BTCUSDT"], per_order=big / 10, daily=big, band_pct=1.0),
         "probes": [("buy limit at the last cent inside +1%", B(1, lim=up), "allow"), ("buy limit one cent outside", B(1, lim=up + 0.01), "refuse"),
                    ("sell limit at the last cent inside -1%", B(1, "sell", lim=dn), "allow"), ("sell limit one cent outside", B(1, "sell", lim=dn - 0.01), "refuse")]},
        {"name": "symbol_daily", "terms": dict(symbols=["BTCUSDT", "ETHUSDT"], per_order=big / 10, daily=big, band_pct=1.0, max_symbol_daily=round(2 * c10, 2)),
         "probes": [("BTC 1st", B(10), "allow"), ("BTC 2nd fills the per-symbol cap exactly", B(10), "allow"), ("one more BTC unit", B(1), "refuse"),
                    ("another symbol is unaffected", B(10, sym="ETHUSDT", p=ex), "allow")]},
        {"name": "position", "terms": dict(symbols=["BTCUSDT"], per_order=c10, daily=big, band_pct=1.0, max_position=c10),
         "probes": [("buy to exactly the position cap", B(10), "allow"), ("one more unit long", B(1), "refuse"), ("sell back to flat", B(10, "sell"), "allow"),
                    ("sell to exactly the cap short", B(10, "sell"), "allow"), ("one more unit short", B(1, "sell"), "refuse")]},
        {"name": "orders_per_day", "terms": dict(symbols=["BTCUSDT"], per_order=big / 10, daily=big, band_pct=1.0, max_orders_per_day=3),
         "probes": [("order 1 of 3", B(1), "allow"), ("order 2 of 3", B(1), "allow"), ("order 3 of 3", B(1), "allow"), ("order 4", B(1), "refuse"),
                    ("next day", B(1, day=1), "allow")]},
        {"name": "revoke", "terms": dict(symbols=["BTCUSDT"], per_order=big / 10, daily=big, band_pct=1.0),
         "probes": [("before the revoke", B(1), "allow"), ("REVOKE", None, None), ("after the revoke", B(1), "refuse"), ("REPLAY", None, None),
                    ("after the signed mandate is replayed", B(1), "refuse")]},
    ]


def run(market: BenchMarket, work_dir: Path) -> dict:
    key = owner_key_from_seed("bench-edges")
    spd = market.steps_per_day
    rows, rx_lines, envs = [], [], {}
    for sc in scenarios(market):
        env = make_envelope(key, name=f"edge-{sc['name']}", expires=FAR, **sc["terms"])
        book = EnvelopeBook(key.public_key())
        book.add(env)
        auth = Authority(book, steps_per_day=spd)
        gate_book = A.Book(env.mandate)
        gate = OrderGate(env.mandate, A._Quotes({}), public_key=key.public_key())
        envs[env.name] = {"mandateId": env.id, "scope": R.scope_of(env.mandate)}
        for i, (label, pr, want) in enumerate(sc["probes"]):
            if pr is None:
                if label == "REVOKE":
                    auth.revoke(env.name)
                    rx_lines.append({"e": env.name, "t": 0, "day": 0, "k": R.receiver_key(f"{env.name}-revoke"), "s": "", "sd": "", "q": 0, "l": 0, "tp": None, "py": "", "x": "revoke"})
                    gate.revoke()
                else:
                    book.add(Envelope(dict(env.mandate), name=env.name))
                continue
            step = pr["day"] * spd
            prices = market.trusted[step]
            auth.set_prices(prices)
            order = {"ticker": pr["sym"], "side": pr["side"], "quantity": pr["q"], "limit_price": pr["lim"]}
            k = f"{env.name}-{i}"
            d = auth.authorize(order, key=k, envelope=env.name, step=step)
            gate.market = A._Quotes(prices)
            g = gate.evaluate(order, gate_book.state(pr["day"]))["decision"]
            if g in ("allow", "hold"):
                gate_book.apply(pr["day"], pr["sym"], pr["side"], pr["q"], _cents(pr["q"], prices[pr["sym"]]), held=(g == "hold"))
            rows.append({"envelope": sc["name"], "probe": label, "expected": want, "python": d.decision, "order_gate": g, "key": k,
                         "notional_usd": round(pr["q"] * prices[pr["sym"]], 4), "limit": pr["lim"]})
            rx_lines.append({"e": env.name, "t": step, "day": pr["day"], "k": R.receiver_key(k), "s": pr["sym"], "sd": pr["side"], "q": pr["q"], "l": pr["lim"],
                             "tp": prices[pr["sym"]], "py": d.decision, "x": "probe"})
    path = work_dir / "edges.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "header", "base_date": "2026-01-05", "prices": market.trusted, "envelopes": envs}, separators=(",", ":")) + "\n")
        for ln in rx_lines:
            fh.write(json.dumps(ln, separators=(",", ":")) + "\n")
    rx = R.edges_receiver(path, work_dir / "edges-receiver.json")
    by_key = {}
    for k, dec, _env in rx["fast"].get("decisions", []):
        by_key[k] = {"filled": "allow", "held": "hold", "denied": "refuse"}[dec]
    for r in rows:
        r["receiver"] = by_key.get(R.receiver_key(r["key"]))
        r["ok"] = r["python"] == r["order_gate"] == r["receiver"] == r["expected"]
    return {"btcusdt_trusted_price": market.trusted[0]["BTCUSDT"], "probes": len(rows), "all_ok": all(r["ok"] for r in rows), "rows": rows}
