"""Shared, deterministic building blocks for the safety suites. No network, no clock: every random draw comes from a seeded Random."""
from __future__ import annotations

import random

from orderguard_guard.gate import generate_keypair, sign_mandate
from orderguard_guard.market import SimMarket

AS_OF = "2024-11-06"
PRICES = {"AAPL": 222.70, "MSFT": 420.18, "NVDA": 140.50, "KO": 62.10, "TSLA": 250.00, "QNTX": 4.12}
HOMOGLYPHS = {"A": "А", "B": "В", "E": "Е", "K": "К", "M": "М", "O": "О", "P": "Р", "C": "С", "T": "Т", "X": "Х", "Y": "У", "S": "Ѕ", "I": "І"}
GREEK = {"A": "Α", "B": "Β", "E": "Ε", "K": "Κ", "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "X": "Χ", "Y": "Υ"}
ZERO_WIDTH = ["​", "‌", "‍", "⁠", "﻿"]

OWNER_PRIV, OWNER_PUB = generate_keypair()
ATTACKER_PRIV, ATTACKER_PUB = generate_keypair()


def make_market(rng: random.Random | None = None) -> SimMarket:
    """Trusted quotes; some names have three venues so the quote is a median."""
    prices = {}
    for t, p in PRICES.items():
        if rng is not None and rng.random() < 0.4:
            prices[t] = {"V1": p, "V2": round(p * 1.0004, 2), "V3": round(p * 0.9996, 2)}
        else:
            prices[t] = p
    return SimMarket(prices)


def signed(mandate: dict, key=OWNER_PRIV) -> dict:
    return sign_mandate(mandate, key)


def random_mandate(rng: random.Random, *, live: bool | None = None) -> dict:
    """An unsigned mandate with random limits. `live` True/False forces an unexpired/expired mandate; None is random."""
    symbols = rng.sample(sorted(PRICES), rng.randint(1, 4))
    if rng.random() < 0.2:
        symbols[0] = symbols[0].lower()                       # the allow-list is compared normalised
    sides = rng.choice([["buy"], ["sell"], ["buy", "sell"]])
    cap = rng.choice([500, 2_000, 5_000, 10_000, 25_000, 100_000])
    if live is None:
        live = rng.random() < 0.85
    expires = "2024-11-07T00:00:00Z" if live else rng.choice(["2024-11-06T00:00:00Z", "2024-11-05T12:00:00Z", "2023-01-01T00:00:00Z"])
    m = {"symbols": symbols, "sides": sides, "maxOrderNotionalUsd": cap, "maxDailyNotionalUsd": cap * rng.choice([1, 2, 3, 5]),
         "priceBandPct": rng.choice([0.5, 1, 2, 5, 10]), "expiresAt": expires,
         "referencePrices": {t: p for t, p in PRICES.items() if rng.random() < 0.5}}
    if rng.random() < 0.5:
        m["stepUpAboveUsd"] = rng.choice([100, 1_000, cap * 0.5, cap])
    return m


def ticker_variant(rng: random.Random, base: str) -> str:
    """The same symbol dressed up: case, padding, fullwidth, homoglyphs, invisible characters; or junk."""
    kind = rng.choice(["exact", "exact", "lower", "pad", "fullwidth", "cyrillic", "greek", "zwsp", "mixedcase", "junk", "empty", "suffix"])
    if kind == "exact":
        return base
    if kind == "lower":
        return base.lower()
    if kind == "mixedcase":
        return "".join(c.lower() if rng.random() < 0.5 else c for c in base)
    if kind == "pad":
        return rng.choice([" ", "\t", "\n", "  "]) + base + rng.choice([" ", "\n", ""])
    if kind == "fullwidth":
        return "".join(chr(ord(c) + 0xFEE0) if "A" <= c <= "Z" else c for c in base)
    if kind in ("cyrillic", "greek"):
        table = HOMOGLYPHS if kind == "cyrillic" else GREEK
        idx = [i for i, c in enumerate(base) if c in table] or [0]
        i = rng.choice(idx)
        return base[:i] + table.get(base[i], "Я") + base[i + 1:]
    if kind == "zwsp":
        i = rng.randint(0, len(base))
        return base[:i] + rng.choice(ZERO_WIDTH) + base[i:]
    if kind == "junk":
        return rng.choice(["AAPL;DROP", "AA PL", "", "A\u0000APL", "../AAPL", "AAPL‮", "  ", "$AAPL", "AAPL/B"])
    if kind == "empty":
        return rng.choice(["", None, 0, 123, ["AAPL"]])  # type: ignore[return-value]
    return base + rng.choice(["X", "1", ".", "-B"])


def random_order(rng: random.Random, mandate: dict, trusted: dict, *, friendly: float = 0.0) -> dict:
    """A random order. With probability `friendly` it is built to be mostly permitted (benign ticker dressing, a side the mandate allows,
    a quantity around the cap, a limit inside the band), so the generator reaches allow and hold as well as refuse."""
    if rng.random() < friendly:
        base = rng.choice([s.upper() for s in mandate["symbols"]])
        price = trusted.get(base, PRICES[base])
        band = mandate["priceBandPct"] / 100
        cap_qty = max(1, int(mandate["maxOrderNotionalUsd"] / price))
        return {"ticker": rng.choice([base, base.lower(), " " + base + " ", "".join(chr(ord(c) + 0xFEE0) for c in base)]),
                "side": rng.choice(mandate["sides"]).upper() if rng.random() < 0.3 else rng.choice(mandate["sides"]),
                "quantity": rng.choice([1, max(1, cap_qty // 2), cap_qty, cap_qty + 1]),
                "limit_price": round(price * (1 + rng.uniform(-band * 0.95, band * 0.95)), 4)}
    pool = list(PRICES)
    allowed = [s.upper() for s in mandate["symbols"]]
    base = rng.choice(allowed if rng.random() < 0.7 else pool)
    price = trusted.get(base, PRICES.get(base, 100.0))
    qty = rng.choice([1, 5, 10, 40, 100, 440, 2000, 0, -5, 3.5, "40", 40.0, float("nan"), float("inf"), True, None, "abc", 10 ** 9])
    if rng.random() < 0.5:                                  # sized to hover around the per-order cap
        qty = max(1, int(mandate["maxOrderNotionalUsd"] / price) + rng.randint(-2, 2))
    limit_kind = rng.choice(["near", "near", "near", "edge", "far", "tiny", "huge", "neg", "none", "junk"])
    band = mandate["priceBandPct"] / 100
    limit = {"near": price * (1 + rng.uniform(-band * 0.9, band * 0.9)), "edge": price * (1 + rng.choice([-1, 1]) * band * rng.choice([0.999, 1.001])),
             "far": price * rng.choice([0.1, 0.5, 2, 10]), "tiny": 0.01, "huge": 1e9, "neg": -price, "none": None, "junk": "abc"}[limit_kind]
    if isinstance(limit, float):
        limit = round(limit, 4)
    return {"ticker": ticker_variant(rng, base), "side": rng.choice(["buy", "buy", "sell", "BUY", " Sell ", "short", "", None]),
            "quantity": qty, "limit_price": limit}
