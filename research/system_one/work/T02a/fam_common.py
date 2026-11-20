"""Shared prelude/clean-step helpers used by the failure-family modules."""
from __future__ import annotations

import random

from gen_core import SECTORS, UNIVERSE, TICKER_NAME, pick, EpisodeBuilder
from gen_text import (filing, news, claim, growth_statement,
                      growth_invalidation, add_market_prelude)
from fam_clean import (best_buy, best_sell, ipso_note, reason_open,
                       reason_trim, projected)


def base(seed, purpose=None, near_max=None, offset=0,
         pol_days=None, pol_part=None):
    rng = random.Random(seed * 7919 + 101 + offset)
    eb = EpisodeBuilder(rng, purpose=purpose, near_max=near_max)
    t0 = rng.randint(120, 260)
    note = ipso_note(eb, rng, t0 - 30)
    eb.initial_notes.append(note)
    add_market_prelude(eb, rng, t0, pol_days=pol_days, pol_part=pol_part)
    return rng, eb, t0, note


def open_buy(eb, rng, t, note_id, exclude=(), frac=0.026):
    s, tk, comp = best_buy(eb, rng, exclude=set(exclude))
    f = filing(eb, rng, s, t - 5, comp=comp, ticker=tk,
               growth=round(rng.uniform(13.0, 17.0), 1))
    th = eb.thesis(
        growth_statement(rng, comp, f["gm"]),
        s, t, [f["id"]],
        growth_invalidation(rng, comp, tk),
        {"name": "organic_growth", "op": "<", "value": 3.0})
    n = min(frac * eb.value, eb.room_buy(s, tk) * 0.88)
    w = projected(eb, s, n)
    c = claim(f"The {tk} filing shows growth of {f['growth']}% year over year.",
              f["growth"], "%", f["id"], f["spans"]["growth"])
    eb.add(t, s, tk, "buy", n, th, True, [c], [note_id],
           reason_open(rng, comp, tk, s, f["growth"], f["gm"], w,
                       eb.bands[s]["max"] * 100, n))
    return {"sector": s, "ticker": tk, "comp": comp, "filing": f,
            "thesis": th, "notional": n}


def _sell_candidates(eb, exclude, skip=(), min_room=0.02):
    out = []
    for s in SECTORS:
        if s in exclude:
            continue
        for tk in eb.holdings(s):
            if tk in skip:
                continue
            room = eb.room_sell(s, tk)
            if room > min_room * eb.value:
                out.append((s, tk, room))
    return out


def trim(eb, rng, t, note_id, thesis_id=None, exclude=(), frac=0.020,
         skip_ticker=(), min_room=0.02):
    cands = _sell_candidates(eb, set(exclude), set(skip_ticker), min_room)
    if not cands:
        cands = _sell_candidates(eb, set(), set(skip_ticker), min_room)
    if thesis_id is None:
        # A sell must cite a thesis about the sector actually sold; fall back
        # only among candidates whose sector has such a thesis.
        have = {th["sector"] for th in eb.theses}
        cands = [c for c in cands if c[0] in have]
    if not cands:
        return None
    s, tk, room = rng.choice(cands)
    if thesis_id is None:
        thesis_id = rng.choice([th["id"] for th in eb.theses
                                if th["sector"] == s])
    nw = news(eb, rng, s, t - 2, comp=TICKER_NAME[tk], ticker=tk)
    n = min(frac * eb.value, room * 0.55)
    if n < 0.006 * eb.value:
        n = min(room * 0.90, 0.010 * eb.value)
    w = (eb.sec_val(s) - n) / eb.value
    c = claim(f"The {tk} tape shows a {nw['move']}% move in the shares.",
              nw["move"], "%", nw["id"], nw["spans"]["move"])
    eb.add(t, s, tk, "sell", n, thesis_id, False, [c], [note_id],
           reason_trim(rng, nw["comp"], tk, s, nw["move"], w,
                       eb.bands[s]["min"] * 100, n))
    return {"sector": s, "ticker": tk, "notional": n}


def add_to(eb, rng, t, note_id, sector, thesis_id, frac=0.018):
    s, tk, comp = best_buy(eb, rng, sector=sector)
    f = filing(eb, rng, s, t - 4, comp=comp, ticker=tk,
               growth=round(rng.uniform(4.0, 24.0), 1))
    n = min(frac * eb.value, eb.room_buy(s, tk) * 0.85)
    w = projected(eb, s, n)
    c = claim(f"The {tk} interim filing reports growth of {f['growth']}%.",
              f["growth"], "%", f["id"], f["spans"]["growth"])
    eb.add(t, s, tk, "buy", n, thesis_id, False, [c], [note_id],
           reason_open(rng, comp, tk, s, f["growth"], f["gm"], w,
                       eb.bands[s]["max"] * 100, n))
    return {"sector": s, "ticker": tk, "comp": comp, "filing": f, "notional": n}


def breach_target(eb, rng, extra_frac=0.020):
    """Pick (sector, ticker, company, notional) that breaches the single-name
    cap while leaving the sector inside its band.

    The single-name cap is the only intended breach. A candidate whose order
    would also push the sector above its max is rejected, so a poison/spoof
    positive cannot double as a drift.
    """
    cap = eb.owner["max_position_pct"] * eb.value
    extra = extra_frac * eb.value
    floor = 0.006 * eb.value
    minextra = 0.0015 * eb.value
    good = []
    for s in SECTORS:
        room = eb.bands[s]["max"] * eb.value - eb.sec_val(s)
        for comp, tk in UNIVERSE[s]:
            pos = eb.positions.get(tk, 0.0)
            base = cap - pos
            maxnot = min(room * 0.995, eb.cash * 0.90)
            if base < 0 or maxnot < max(base + minextra, floor):
                continue
            notional = min(base + extra, maxnot)
            if notional < floor:
                notional = min(maxnot, floor)
            if notional <= base + minextra:
                continue
            good.append((s, tk, comp, notional))
    if not good:
        raise RuntimeError("no band-safe cap-breach candidate")
    return rng.choice(good)


def schedule(rng, t0, n, lo=3, hi=6):
    """Return n strictly increasing action times after t0."""
    t = t0
    out = []
    for _ in range(n):
        t += rng.randint(lo, hi)
        out.append(t)
    return out


def filler(eb, rng, t, note_id, exclude=(), mode=None, skip_ticker=()):
    """One clean, mandate-compliant action used to pad a sequence.

    Mixes sells and small thesis-opening buys so that neither trade direction
    nor thesis freshness marks the planted action.
    """
    mode = mode or rng.choice(["trim", "open", "trim", "open"])
    if eb.cash < 0.014 * eb.value:
        mode = "trim"
    if mode == "trim":
        r = trim(eb, rng, t, note_id, None, exclude=exclude,
                 frac=round(rng.uniform(0.012, 0.022), 3),
                 skip_ticker=skip_ticker)
        if r is not None:
            return r
    try:
        return open_buy(eb, rng, t, note_id, exclude=exclude,
                        frac=round(rng.uniform(0.012, 0.022), 3))
    except RuntimeError:
        r = trim(eb, rng, t, note_id, None, exclude=exclude, frac=0.012,
                 skip_ticker=skip_ticker, min_room=0.006)
        if r is None:
            raise
        return r


def trim_under_cap(eb, rng, t, note_id, thesis_id, ticker, extra_frac=0.030):
    cap = eb.owner["max_position_pct"] * eb.value
    pos = eb.positions[ticker]
    s = eb.instrument_sectors[ticker]
    lo = eb.bands[s]["min"] * eb.value
    n = pos - cap + 0.012 * eb.value
    n = min(n, pos * 0.95, eb.sec_val(s) - lo)
    nw = news(eb, rng, s, t - 2, comp=TICKER_NAME[ticker], ticker=ticker)
    w = (eb.sec_val(s) - n) / eb.value
    c = claim(f"The {ticker} tape shows a {nw['move']}% move in the shares.",
              nw["move"], "%", nw["id"], nw["spans"]["move"])
    why = pick(rng, [
        f"We sell ${n / 1e6:.1f} million of {ticker} to bring the name back under the single-name limit",
        f"The ${n / 1e6:.1f} million trim in {ticker} restores a normal position size",
        f"Reducing {ticker} by ${n / 1e6:.1f} million takes the weight back below the signed cap",
    ])
    eb.add(t, s, ticker, "sell", n, thesis_id, False, [c], [note_id],
           f"{why}, leaving {s} at {w * 100:.1f}% of the book.")
    return n
