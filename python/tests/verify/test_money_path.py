"""Regression tests for the money-path bugs the 2026-11-06 audit found (docs/verify/AUDIT.md section 4). Each one fails on the old code."""
import json
from datetime import date

import anyio
import httpx
import pytest
from conftest import D, scripted, snap
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from orderguard_verify.core import mcp_server, review_ui
from orderguard_verify.core.gateway import Gateway
from orderguard_verify.core.pack import SourceUnavailable
from orderguard_verify.finance import edgar, sources
from orderguard_verify.finance.mandate import check_mandate
from orderguard_verify.finance.models import Mandate, Order
from orderguard_verify.finance.pack import FinancePack
from orderguard_verify.finance.truth_store import TruthStore

TRUE = {"text": "revenue of $5.0 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2024",
        "value": 5.0e9, "unit": "USD", "main_reason": True}
RUMOUR = {"text": "ACME is in talks to buy a rival", "type": "rumour", "ticker": "ACME", "key": True, "main_reason": True}
MEMO = "ACME had revenue of $5.0 billion in fiscal 2024. ACME is in talks to buy a rival."
CAP = Mandate(allowed_tickers=["ACME"], max_order_shares=10_000, max_order_notional=20_000)    # quote 55.10: 1000 shares = $55,100
ORDER = {"ticker": "ACME", "side": "buy", "quantity": 1000}


# (a) review page: approve/reject needs a per-boot token -------------------------------------------------------

@pytest.fixture
def held_page(make_gateway, tmp_path, monkeypatch):
    db = str(tmp_path / "og.db")
    reply = make_gateway([TRUE, RUMOUR], db=db).propose(MEMO, ORDER)
    assert reply["status"] == "held"
    sent = []
    monkeypatch.setattr(review_ui.httpx, "post", lambda url, **kw: sent.append((url, kw["json"])) or httpx.Response(200, json={}))
    return TestClient(review_ui.make_app(db, token="boot-token-123"), follow_redirects=False), reply["run_id"], sent


def test_review_without_the_token_is_refused_and_nothing_is_sent(held_page):
    client, run_id, sent = held_page
    assert client.post(f"/review/{run_id}", data={"decision": "approve"}).status_code == 403
    assert client.post(f"/review/{run_id}", data={"decision": "approve", "token": "guess"}).status_code == 403
    assert client.post(f"/review/{run_id}", data={"decision": "reject", "token": ""}).status_code == 403
    assert sent == []


def test_review_with_the_token_goes_through_and_the_page_never_shows_the_token(held_page):
    client, run_id, sent = held_page
    assert client.post(f"/review/{run_id}", data={"decision": "approve", "token": "boot-token-123"}).status_code == 303
    assert sent and sent[0][1] == {"run_id": run_id, "approve": True}
    page = client.get("/").text
    assert "boot-token-123" not in page and 'name="token"' in page


def test_every_boot_gets_a_different_random_token(tmp_path):
    a, b = review_ui.make_app(str(tmp_path / "a.db")), review_ui.make_app(str(tmp_path / "b.db"))
    assert a.state.token != b.state.token and len(a.state.token) >= 20


def test_the_serve_entry_point_prints_the_token(monkeypatch, capsys):
    from orderguard_verify import serve
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: None)
    serve.ui_main()
    assert "review token" in capsys.readouterr().out


# (b) mandate: normalised ticker, trusted quote, price band ---------------------------------------------------

def test_a_lowercase_ticker_with_a_tiny_limit_price_cannot_clear_an_oversize_order(make_gateway):
    gw = make_gateway([TRUE], CAP)
    reply = gw.propose("ACME had revenue of $5.0 billion in fiscal 2024.", {"ticker": "acme", "side": "buy", "quantity": 1000, "limit_price": 0.01})
    assert reply["status"] == "blocked"
    # the old check also let this through when the Order model was bypassed entirely
    raw = Order.model_construct(ticker="acme", side="buy", quantity=1000, limit_price=0.01, as_of=D("2025-03-04"))
    problems = check_mandate(raw, CAP, gw.pack.store)
    assert any("notional" in p for p in problems) and any("band" in p for p in problems)


def test_the_order_is_valued_at_the_trusted_quote_never_its_own_limit_price(store):
    raw = Order.model_construct(ticker="ACME", side="buy", quantity=1000, limit_price=1.0, as_of=D("2025-03-04"))
    assert any("notional $55,100" in p for p in check_mandate(raw, CAP, store))
    ok = Order(ticker="ACME", side="buy", quantity=300, limit_price=55.0, as_of=D("2025-03-04"))
    assert check_mandate(ok, CAP, store) == []


def test_the_price_band_is_enforced_around_the_trusted_quote(store):
    far = Order(ticker="ACME", side="buy", quantity=1, limit_price=80.0, as_of=D("2025-03-04"))
    assert any("band" in p for p in check_mandate(far, CAP, store))
    nan = Order.model_construct(ticker="ACME", side="buy", quantity=1, limit_price=float("nan"), as_of=D("2025-03-04"))
    assert any("band" in p for p in check_mandate(nan, CAP, store))


def test_no_trusted_quote_means_no_order_even_with_a_tiny_limit_price(store):
    early = Order(ticker="ACME", side="buy", quantity=1000, limit_price=0.01, as_of=D("2023-01-01"))   # before the first quote
    assert any("no reference price" in p for p in check_mandate(early, CAP, store))
    old = Order(ticker="ACME", side="buy", quantity=1000, limit_price=55.0, as_of=D("2026-01-01"))     # newest quote is far too old
    assert any("no reference price" in p for p in check_mandate(old, CAP, store))


def test_ticker_is_trimmed_nfkc_uppercased_and_ascii_only(store):
    assert Order(ticker="  acme ", side="buy", quantity=1).ticker == "ACME"
    assert Order(ticker="ａｃｍｅ", side="buy", quantity=1).ticker == "ACME"       # full-width letters fold to ASCII
    for bad in ("АCME", "AC ME", "", "ACME​", "A;B"):                                      # Cyrillic A, space, empty, zero-width, junk
        with pytest.raises(ValueError):
            Order(ticker=bad, side="buy", quantity=1)
    raw = Order.model_construct(ticker="АCME", side="buy", quantity=1, limit_price=None, as_of=D("2025-03-04"))
    assert any("plain ASCII" in p for p in check_mandate(raw, CAP, store))


# (c) the server sets as_of ---------------------------------------------------------------------------------

def test_the_agent_cannot_choose_the_decision_date(make_gateway):
    gw = make_gateway([TRUE], CAP)
    gw.propose("ACME had revenue of $5.0 billion in fiscal 2024.", dict(ORDER, quantity=10, as_of="2023-01-01"))
    assert gw.last.as_of == date(2025, 3, 4)


def test_the_mcp_tools_offer_no_date_and_ignore_one_sent_anyway(make_gateway, tmp_path):
    gw = make_gateway([TRUE], CAP, db=str(tmp_path / "og.db"))
    server = mcp_server.build(gw)

    async def go():
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            tools = {t.name: t.inputSchema for t in (await client.list_tools()).tools}
            res = await client.call_tool("propose_order", {"research": "ACME had revenue of $5.0 billion in fiscal 2024.",
                                                           "order": dict(ORDER, quantity=10, as_of="2023-01-01")})
            await client.call_tool("check_memo", {"research": "ACME had revenue of $5.0 billion in fiscal 2024.", "ticker": "ACME", "as_of": "2023-01-01"})
            return tools, res
    tools, _ = anyio.run(go)
    assert "as_of" not in json.dumps(tools["propose_order"]) and "as_of" not in json.dumps(tools["check_memo"])
    assert gw.last.as_of == date(2025, 3, 4)


# (d) an empty memo is rejected, not held ------------------------------------------------------------------

@pytest.mark.parametrize("memo", ["", "   \n\t "])
def test_an_empty_memo_is_rejected_cleanly_and_never_held(make_gateway, memo):
    gw = make_gateway([], CAP)
    reply = gw.propose(memo, ORDER)
    assert reply["status"] == "rejected" and "empty" in reply["reasons"][0]
    assert gw.pending() == [] and gw.runs.all_runs() == []


def test_a_model_outage_does_not_flood_the_reviewer_with_claimless_held_orders(make_pack):
    def down(system, user, **kw):
        raise RuntimeError("model unavailable")
    gw = Gateway(make_pack(CAP), ask=down, db_path=":memory:", clock=lambda: date(2025, 3, 4))
    reply = gw.propose(MEMO, dict(ORDER, quantity=10))
    assert reply["status"] == "rejected" and gw.pending() == []


# (e) on-demand fetch and refresh for tickers outside the shipped set ----------------------------------------

FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "accn": "0001-25-000001", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"}]}}}}}
FACTS2 = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2024-01-01", "end": "2024-12-31", "val": 1000, "accn": "0001-25-000001", "fy": 2024, "fp": "FY", "form": "10-K", "filed": "2025-02-01"},
    {"start": "2025-01-01", "end": "2025-12-31", "val": 1200, "accn": "0001-26-000001", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-01"}]}}}}}


@pytest.fixture
def sec(monkeypatch, tmp_path):
    state = {"facts": FACTS, "calls": []}

    def handler(request):
        state["calls"].append(str(request.url))
        if "company_tickers" in str(request.url):
            return httpx.Response(200, json={"0": {"cik_str": 999, "ticker": "NEWCO", "title": "NewCo"}})
        return httpx.Response(200, json=state["facts"])
    real = httpx.Client
    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sources, "VAR", tmp_path)
    monkeypatch.setattr(sources, "PAUSE", 0)
    return state


def test_refresh_works_for_a_ticker_that_is_not_in_the_shipped_set(sec):
    store = TruthStore(":memory:")
    sources.ensure(store, "NEWCO")
    assert [r.period for r in store.versions("NEWCO", "revenue", "FY2025", D("2026-06-01"))] == []
    sec["facts"] = FACTS2
    edgar.refresh(store, "NEWCO")                 # used to raise KeyError (swallowed) because NEWCO is not in companies.json
    assert [r.value for r in store.versions("NEWCO", "revenue", "FY2025", D("2026-06-01"))] == [1200.0]


def test_the_gateway_refreshes_and_rechecks_a_ticker_outside_the_shipped_set(sec):
    store = TruthStore(":memory:")
    store.add(snap("NEWCO", "price", None, 10.0, "2026-03-02", claim_type="price", duration=None))
    pack = FinancePack(store, Mandate(allowed_tickers=["NEWCO"], max_order_notional=1e9), refresh_fn=sources.refresh, on_demand=True)
    claim = {"text": "latest year revenue of $1,200", "type": "fundamental", "ticker": "NEWCO", "metric": "revenue", "period": "latest_fy", "value": 1200.0, "unit": "USD", "main_reason": True}
    sec["facts"] = FACTS2
    gw = Gateway(pack, ask=scripted([claim]), db_path=":memory:", clock=lambda: date(2026, 3, 3))
    reply = gw.propose("NEWCO latest year revenue of $1,200.", {"ticker": "NEWCO", "side": "buy", "quantity": 1})
    assert reply["status"] == "cleared" and any("companyfacts" in c for c in sec["calls"])


def test_sec_requests_are_spaced_to_stay_under_ten_a_second(monkeypatch):
    waits, now = [], [100.0]
    monkeypatch.setattr(sources.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(sources.time, "sleep", lambda s: (waits.append(s), now.__setitem__(0, now[0] + s)))
    monkeypatch.setattr(sources, "PAUSE", 0.15)
    sources._last[0] = 0.0
    for _ in range(4):
        sources._throttle()
    assert waits and all(abs(w - 0.15) < 1e-9 for w in waits) and 1 / sources.PAUSE < 10
