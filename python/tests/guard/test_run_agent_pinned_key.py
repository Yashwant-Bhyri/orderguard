"""run_agent with a pinned owner key refuses every order under a tampered or foreign-signed mandate. Offline, scripted agent."""
import importlib.util
from pathlib import Path

import pytest

from orderguard_guard import gate as G
from orderguard_guard.agent import run_agent
from orderguard_guard.llm import ScriptedLLM

EX = Path(__file__).resolve().parents[3] / "examples" / "python" / "guarded_agent.py"


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("guarded_agent_example", EX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_order(ex):
    return [[("place_order", {"ticker": "AAPL", "side": "buy", "key_figures": ex.FIGURES, "quantity": 10, "limit_price": 222.70})], "done"]


def _run(ex, mandate, **kw):
    broker = ex.ToyBroker(mandate)
    run_agent(ScriptedLLM(_one_order(ex)), "Buy 10 AAPL.", broker, arm="gate_only", **kw)
    return broker.filled


def test_genuine_mandate_fills_with_pinned_key(ex):
    priv, pub = G.generate_keypair()
    assert len(_run(ex, G.sign_mandate(ex.DEMO_MANDATE, priv), public_key=pub)) == 1


def test_tampered_mandate_refused_only_when_key_is_pinned(ex):
    priv, pub = G.generate_keypair()
    signed = G.sign_mandate(ex.DEMO_MANDATE, priv)
    tampered = {**signed, "maxOrderNotionalUsd": 10_000_000}          # an attacker widens the cap after signing
    assert _run(ex, tampered, public_key=pub) == []                   # pinned key: nothing fills
    assert len(_run(ex, tampered)) == 1                               # documented: without a pinned key only the limits are enforced


def test_foreign_signed_mandate_refused(ex):
    _, owner_pub = G.generate_keypair()
    attacker_priv, _ = G.generate_keypair()
    assert _run(ex, G.sign_mandate(ex.DEMO_MANDATE, attacker_priv), public_key=owner_pub) == []


def test_env_public_key_is_used(ex):
    priv, pub = G.generate_keypair()
    tampered = {**G.sign_mandate(ex.DEMO_MANDATE, priv), "maxDailyNotionalUsd": 9e9}
    broker = ex.ToyBroker(tampered)
    broker.public_key = pub
    run_agent(ScriptedLLM(_one_order(ex)), "Buy 10 AAPL.", broker, arm="gate_only")
    assert broker.filled == []
