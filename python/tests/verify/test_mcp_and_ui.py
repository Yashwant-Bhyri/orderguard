"""Slice 5: the MCP tool and the review page, end to end and in-process (no network ports)."""
import json

import anyio
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from orderguard_verify.core import mcp_server
from orderguard_verify.core.review_ui import make_app

FALSE = {"text": "revenue of $6.5 billion", "type": "fundamental", "ticker": "ACME", "metric": "revenue", "period": "FY2024", "value": 6.5e9, "unit": "USD"}
RUMOUR = {"text": "ACME is in talks to buy a rival", "type": "rumour", "ticker": "ACME", "key": True, "main_reason": True}
TRUE = dict(FALSE, text="revenue of $5.0 billion", value=5.0e9)
ORDER = {"ticker": "ACME", "side": "buy", "quantity": 500, "as_of": "2025-03-04"}


def test_external_mcp_client_gets_blocked_on_a_false_figure(make_gateway, tmp_path):
    server = mcp_server.build(make_gateway([FALSE], db=str(tmp_path / "og.db")))

    async def go():
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            names = [t.name for t in (await client.list_tools()).tools]
            res = await client.call_tool("propose_order", {"research": "ACME had revenue of $6.5 billion.", "order": ORDER})
            return names, res.structuredContent or json.loads(res.content[0].text)

    names, reply = anyio.run(go)
    assert "propose_order" in names
    assert reply["status"] == "blocked" and "contradicted" in reply["reasons"][0]


def test_review_page_shows_evidence_and_a_held_order_can_be_approved(make_gateway, tmp_path):
    db = str(tmp_path / "og.db")
    gw = make_gateway([TRUE, RUMOUR], db=db)
    reply = gw.propose("ACME had revenue of $5.0 billion. ACME is in talks to buy a rival.", ORDER)
    assert reply["status"] == "held"
    page = TestClient(make_app(db)).get("/").text
    assert "Approve" in page and "https://example.test/filing" in page and "unverifiable" in page
    assert gw.review(reply["run_id"], approve=True)["status"] == "approved_cleared"
    assert "Approve" not in TestClient(make_app(db)).get("/").text


def test_review_page_has_a_paste_box_and_the_gateway_checks_pasted_text(make_gateway, tmp_path):
    gw = make_gateway([FALSE], db=str(tmp_path / "og.db"))
    page = TestClient(make_app(str(tmp_path / "og.db"), '<input name="ticker">', "hint")).get("/").text
    assert "<textarea" in page and 'name="ticker"' in page
    app = mcp_server.build(gw).streamable_http_app()
    r = TestClient(app).post("/admin/check", headers={"x-admin-token": mcp_server.admin_token()},
                             json={"text": "ACME had revenue of $6.5 billion.", "context": {"ticker": "ACME", "as_of": "2025-03-04"}})
    assert r.status_code == 200 and r.json()["action"] == "block"
    assert "BLOCK" in TestClient(make_app(str(tmp_path / "og.db"))).get("/").text


def test_review_endpoint_rejects_a_missing_admin_token(make_gateway, tmp_path):
    app = mcp_server.build(make_gateway([TRUE], db=str(tmp_path / "og.db"))).streamable_http_app()
    assert TestClient(app).post("/admin/review", json={"run_id": "x", "approve": True}).status_code == 403
