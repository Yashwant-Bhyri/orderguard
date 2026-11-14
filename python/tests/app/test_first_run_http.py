"""A request a first-time curl user gets wrong is explained, not just rejected."""
from fastapi.testclient import TestClient

from orderguard_app.app import create_app

BODY = '{"order": {"ticker": "AAPL", "side": "buy", "quantity": 10, "limit_price": 222.7}}'


def test_form_encoded_body_gets_a_content_type_hint():
    c = TestClient(create_app())
    r = c.post("/api/check-order", content=BODY, headers={"content-type": "application/x-www-form-urlencoded"})   # what `curl -d` sends
    assert r.status_code == 422
    assert "Content-Type: application/json" in r.json()["hint"]


def test_json_body_that_is_wrong_gets_no_misleading_hint_and_a_right_one_works():
    c = TestClient(create_app())
    assert "hint" not in c.post("/api/check-order", json={"order": "nope"}).json()
    ok = c.post("/api/check-order", content=BODY, headers={"content-type": "application/json"})
    assert ok.status_code == 200 and ok.json()["decision"] == "allow"
