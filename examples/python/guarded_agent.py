#!/usr/bin/env python3
"""A toy trading agent behind OrderGuard: the guard and a signed mandate sit between the agent and the broker.

Run it from the repository root, after `sh scripts/quickstart.sh --no-serve --skip-tests` (or `.venv/bin/pip install -e .`):

    .venv/bin/python examples/python/guarded_agent.py

It is offline. The agent is scripted (no model, no API key, no network) and the broker is a toy paper ledger. The script is
what a fooled agent might do: one honest order, one order sized from a forged "10-for-1 split" notice, one large order.
Expected output (about one second):

    OrderGuard guarded-agent example (scripted agent, no model, no network)
    Mandate: AAPL, MSFT, buy only, $10,000 per order, $20,000 per day, 5% price band, human step-up above $9,500
    Signature: verified against the owner's public key (a throwaway key made for this run)

    1. buy 10 AAPL @ 222.70   ALLOW   -> filled on the paper ledger as P-00001
    2. buy 440 AAPL @ 22.30   REFUSE
         The order is worth $97,988 at the trusted price of $222.70 (440 shares), above the per-order cap of $10,000.
         With $2,227 already placed today this order would bring the day's total to $100,215, above the daily cap of $20,000.
         The limit price $22.30 is 90.0% below the trusted price $222.70; the mandate allows at most 5%.
         The order is worth $97,988, above the $9,500 step-up threshold, so a human must approve it.
    3. buy 43 AAPL @ 222.70   HOLD
         The order is worth $9,576, above the $9,500 step-up threshold, so a human must approve it.

    Agent's last words: Done: bought 10 AAPL; the 440-share order was refused and the 43-share order is waiting for a human.
    Paper ledger: 1 order filled (AAPL 10). The refused and held orders never reached the broker.

The pattern to copy is in `main`: verify the signed mandate once, build the guard around your own tools, run your agent.
`run_agent` calls your broker's `place_order` only after the guard says allow. To use your own mandate instead of the
throwaway one, run `orderguard init` and then pass `--mandate var/orderguard/mandate.json` (the public key is read from
the `signing.pub` next to it, or from `--pub`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Replay mode means "never call a model" and the offline flag keeps the figure check on the local filings table.
os.environ.setdefault("OG_LLM", "replay")
os.environ.setdefault("ORDERGUARD_OFFLINE", "1")

try:
    from orderguard_guard import gate as G
    from orderguard_guard.agent import run_agent
    from orderguard_guard.llm import ScriptedLLM
    from orderguard_guard.market import SimMarket
except ImportError as e:  # a fresh clone that has not been installed yet
    sys.exit(f"orderguard is not installed in this Python ({e}).\n"
             "Fix: from the repository root run `sh scripts/quickstart.sh --no-serve --skip-tests`, then use `.venv/bin/python` to run this file.")

AS_OF = "2024-11-06"      # the decision date: the trusted prices and the SEC filings table in this repo are as of this day
DEMO_MANDATE = {"symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10000, "maxDailyNotionalUsd": 20000,
                "priceBandPct": 5, "stepUpAboveUsd": 9500, "expiresAt": "2099-01-01T00:00:00Z",
                "referencePrices": {"AAPL": 222.70, "MSFT": 420.18}}
# The filed FY2024 revenue of Apple in USD millions: the guard checks every figure an order cites against it.
FIGURES = [{"metric": "revenue", "fiscal_year": 2024, "value": 391035, "unit": "USD millions"}]


class ToyBroker:
    """Stands in for your broker or tool environment. run_agent calls `call("place_order", ...)` only after the guard allows the order."""

    def __init__(self, mandate: dict):
        self.mandate = mandate
        self.as_of = AS_OF
        self.market = SimMarket(mandate["referencePrices"], as_of=f"{AS_OF}T15:05:00Z")   # trusted prices: the agent cannot touch them
        self.filled: list[dict] = []

    def tools(self, arm: str) -> list[dict]:
        order = {"type": "object", "required": ["ticker", "side", "quantity", "limit_price"], "properties": {
            "ticker": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {"type": "integer"}, "limit_price": {"type": "number"}}}
        return [{"type": "function", "function": {"name": "place_order", "description": "Place a limit order.", "parameters": order}}]

    def call(self, name: str, args: dict) -> dict:
        if name != "place_order":
            return {"error": f"unknown tool {name}"}
        order_id = f"P-{len(self.filled) + 1:05d}"
        self.filled.append({"order_id": order_id, **args})
        return {"status": "filled", "order_id": order_id, "ledger_effect": True}


def load_mandate(path: str | None, pub_path: str | None) -> tuple[dict, str]:
    """Return (signed mandate, how it was signed). Every failure says what to do next."""
    if path is None:
        priv, pub = G.generate_keypair()
        return G.sign_mandate(DEMO_MANDATE, priv), G.public_key_to_b64(pub)
    mandate_file = Path(path)
    pub_file = Path(pub_path) if pub_path else mandate_file.with_name("signing.pub")
    if not mandate_file.is_file():
        sys.exit(f"No mandate at {mandate_file}. Create one with `orderguard init` (it writes var/orderguard/mandate.json), "
                 "or run this example without --mandate to use the built-in one.")
    if not pub_file.is_file():
        sys.exit(f"No owner public key at {pub_file}. Pass --pub FILE: the guard must check the mandate against the owner's key, never against a key inside the mandate.")
    try:
        return json.loads(mandate_file.read_text()), pub_file.read_text().strip()
    except ValueError:
        sys.exit(f"{mandate_file} is not valid JSON. Re-create it with `orderguard init --resign`.")


def verify(mandate: dict, public_key_b64: str) -> None:
    """Refuse to start an agent whose mandate is unsigned, altered or expired (the gate checks expiry again on every order)."""
    try:
        G.Mandate.from_dict(mandate).verify(G.public_key_from_b64(public_key_b64), now=AS_OF)
    except G.MandateInvalid as e:
        sys.exit(f"The mandate cannot be used: {e}. If you edited mandate.json, run `orderguard init --resign`; if it expired, extend expiresAt and re-sign.")
    except (KeyError, TypeError, ValueError):
        sys.exit("The mandate or the public key is malformed. Re-create them with `orderguard init`.")


def script() -> list:
    """What the toy agent does, as a model would: tool calls in order, then a final message."""
    buy = {"ticker": "AAPL", "side": "buy", "key_figures": FIGURES}
    return [[("place_order", {**buy, "quantity": 10, "limit_price": 222.70})],
            [("place_order", {**buy, "quantity": 440, "limit_price": 22.30})],       # sized from a forged 10-for-1 split notice
            [("place_order", {**buy, "quantity": 43, "limit_price": 222.70})],       # inside every cap, but big enough for a human to look
            "Done: bought 10 AAPL; the 440-share order was refused and the 43-share order is waiting for a human."]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mandate", help="a signed mandate.json (default: a built-in demo mandate signed with a throwaway key)")
    ap.add_argument("--pub", help="the owner's signing.pub (default: signing.pub next to --mandate)")
    a = ap.parse_args(argv)

    mandate, owner_pub = load_mandate(a.mandate, a.pub)
    verify(mandate, owner_pub)
    m = G.Mandate.from_dict(mandate)
    sides = " and ".join(m.sides)
    print("OrderGuard guarded-agent example (scripted agent, no model, no network)")
    print(f"Mandate: {', '.join(m.symbols)}, {sides} only, ${m.maxOrderNotionalUsd:,.0f} per order, ${m.maxDailyNotionalUsd:,.0f} per day, "
          f"{m.priceBandPct:g}% price band" + (f", human step-up above ${m.stepUpAboveUsd:,.0f}" if getattr(m, "stepUpAboveUsd", None) else ""))
    print("Signature: verified against the owner's public key" + (" (a throwaway key made for this run)" if a.mandate is None else ""))
    print()

    broker = ToyBroker(mandate)
    # arm="gate_only" is the order guard alone: every order goes through the signed mandate and the trusted price before the broker sees it.
    # arm="full" adds screening of everything the agent reads and needs a screening model (or recordings) for that.
    # public_key pins the owner: the gate re-verifies the signature, expiry and revocation on every order.
    transcript = run_agent(ScriptedLLM(script()), "Buy Apple for the account.", broker, arm="gate_only",
                           public_key=G.public_key_from_b64(owner_pub))

    refused = held = 0
    for n, call in enumerate((c for c in transcript["calls"] if c["name"] == "place_order"), 1):
        args, gate = call["args"], call["gate"] or {}
        decision = gate.get("decision", "?")
        line = f"{n}. {args['side']} {args['quantity']} {args['ticker']} @ {args['limit_price']:.2f}"
        if decision == "allow":
            print(f"{line:<26}ALLOW   -> filled on the paper ledger as {call['result'].get('order_id')}")
        else:
            refused += decision == "refuse"
            held += decision == "hold"
            print(f"{line:<26}{decision.upper()}")
            for reason in gate.get("reasons", []):
                print(f"     {reason}")
    if transcript["error"]:
        print(f"\nThe agent stopped early: {transcript['error']}")
        return 1
    print(f"\nAgent's last words: {transcript['final']}")
    filled = ", ".join(f"{o['ticker']} {o['quantity']}" for o in broker.filled)
    print(f"Paper ledger: {len(broker.filled)} order filled ({filled}). " if filled else "Paper ledger: no orders filled. ", end="")
    print("The refused and held orders never reached the broker.")
    return 0 if refused else 1      # the point of the example: at least one order was refused with a reason


if __name__ == "__main__":
    raise SystemExit(main())
