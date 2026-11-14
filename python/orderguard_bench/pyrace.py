"""Threads racing one envelope's shared daily budget inside one Python process (the arena authority is thread-safe: one lock per
envelope covers the portfolio re-check, the budget reservation and the record). Half the threads also deliver the same keys, so each
of those keys races duplicates of itself. `lock_off=True` replaces the reservation with an unlocked check-then-act (the mutation) so
the auditor can be shown to catch the over-spend.
"""
from __future__ import annotations

import contextlib
import tempfile
import threading
import time
from pathlib import Path

from orderguard_arena.authority import Authority
from orderguard_arena.envelopes import EnvelopeBook, make_envelope, owner_key_from_seed
from orderguard_guard.gate import public_key_to_b64

from . import auditor as A
from .engine import DecisionLog


def thread_race(market, threads: int, per_thread: int, *, lock_off: bool = False) -> dict:
    key = owner_key_from_seed("bench-thread-race")
    price = market.trusted[0]["BTCUSDT"]
    qty = 100
    cents = round(qty * price * 100)
    entitled = 20
    env = make_envelope(key, name="race", symbols=["BTCUSDT"], per_order=1_000_000.0, daily=cents * entitled / 100, band_pct=1.0,
                        expires="2099-01-01T00:00:00Z")
    book = EnvelopeBook(key.public_key())
    book.add(env)
    auth = Authority(book, steps_per_day=market.steps_per_day)
    auth.set_prices(market.trusted[0])
    if lock_off:
        b = env.budget

        def racy(day, amount, agent=None, agent_cap=None):
            c = round(amount * 100)
            cur = b._used.get(day, 0)
            time.sleep(0.0002)                             # yield between the check and the write: a lost update is now possible
            if cur + c > b._cap_c:
                return False
            b._used[day] = cur + c
            return True
        b.reserve = racy
        env.plock = contextlib.nullcontext()
    tmp = Path(tempfile.mkdtemp(prefix="og-bench-race-"))
    log = DecisionLog(tmp / "race.log")
    lk = threading.Lock()
    barrier = threading.Barrier(threads)
    order = {"ticker": "BTCUSDT", "side": "buy", "quantity": qty, "limit_price": round(price, 2)}

    def run(t: int):
        barrier.wait()
        for i in range(per_thread):
            k = f"shared-{i}" if t % 2 else f"t{t}-{i}"
            d = auth.authorize(dict(order), key=k, envelope="race", step=0, agent=t)
            with lk:
                log.append({"i": log.n, "t": 0, "k": k, "e": "race", "o": 0, "a": t, "l": "burst", "x": "orig", "q": order, "g": d.decision,
                            "d": d.decision, "r": d.replay, "n": d.notional, "p": d.trusted, "c": d.code, "y": d.layer, "tr": None, "nid": None, "rk": None})
    ts = [threading.Thread(target=run, args=(t,)) for t in range(threads)]
    t0 = time.perf_counter()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.perf_counter() - t0
    log.close()
    reg = {"race": {"owner": 0, "id": env.id, "public_key": public_key_to_b64(key.public_key()), "mandate": env.mandate}}
    audit = A.audit_logs([str(tmp / "race.log")], reg, market, procs=1)
    (tmp / "race.log").unlink(missing_ok=True)
    tmp.rmdir()
    return {"threads": threads, "per_thread": per_thread, "lock_off": lock_off, "attempts": threads * per_thread, "entitled_fills": entitled,
            "allowed_fresh": audit["totals"]["effects"], "wall_s": round(wall, 4),
            "audit": {k: audit[k] for k in ("breaches", "breach_total", "checked", "examples")}}
