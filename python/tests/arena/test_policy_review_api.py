import datetime as dt

from fastapi.testclient import TestClient

from orderguard_app.app import create_app
from orderguard_guard.gate import Mandate, generate_keypair, public_key_to_b64, sign_mandate


def test_fit_forecast_and_exact_simulation_are_distinct(monkeypatch):
    monkeypatch.setenv("OG_LLM", "replay")
    with TestClient(create_app(token="test")) as c:
        path = "/api/arena/policy"
        assert c.get(path).status_code == 401
        c.headers["Authorization"] = "Bearer test"
        parent = c.get(path).json()
        draft = parent["suggested_draft"]
        assert "signature" not in draft and "signerPublicKey" not in parent["parent"]
        bad = draft | {"maxDailyNotionalUsd": parent["parent"]["maxDailyNotionalUsd"] + 1}
        refused = c.post(path, json={"draft": bad, "mode": "simulate"}).json()
        assert refused["fit"]["violations"][0]["code"] == "daily_cap"
        assert refused["simulation"] is None and refused["estimate"] is None

        forecast = c.post(path, json={"draft": draft, "mode": "estimate"}).json()
        assert forecast["fit"]["fits"] and forecast["simulation"] is None
        assert forecast["estimate"]["status"] in ("experimental", "validated_for_triage")
        for values in forecast["estimate"]["outcomes"].values():
            assert 0 <= values["lower"] <= values["estimate"] <= values["upper"]
        outside = c.post(path, json={"draft": draft, "mode": "estimate", "agents": 1100}).json()
        assert outside["estimate"]["status"] == "outside_training_domain"

        measured = c.post(path, json={"draft": draft, "mode": "simulate", "agents": 120, "steps": 160,
                                     "regime": "collusion", "limits": {"bad_allowed_usd_per_day": 0}}).json()
        assert measured["fit"]["parent_id"] == parent["parent_id"]
        assert measured["estimate"] is None and measured["simulation"]["limits"]["met"] is False
        assert measured["simulation"]["results"]["draft"]["proposals"] > 0


def test_configured_policy_requires_pinned_owner_and_respects_revocation(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path))
    with TestClient(create_app(token="")) as c:
        path = "/api/arena/policy?source=configured"
        assert c.get(path).status_code == 409
        key, pub = generate_keypair()
        end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
        body = c.get("/api/arena/policy").json()["parent"] | {"expiresAt": end.isoformat()}
        signed = sign_mandate(body, key)
        (tmp_path / "mandate.json").write_text(json.dumps(signed))
        (tmp_path / "signing.pub").write_text(public_key_to_b64(pub))
        assert c.get(path).status_code == 200
        batch = c.post("/api/arena/policy/search", json={"source": "configured", "mode": "rank"}).json()
        assert batch["parent_id"] == Mandate.from_dict(signed).id
        assert batch["simulated"] == 0 and batch["selected_rank"] is None
        assert all(x["draft"]["expiresAt"] == body["expiresAt"] and "signature" not in x["draft"]
                   for x in batch["candidates"])
        (tmp_path / "revoked-mandates.json").write_text(json.dumps([Mandate.from_dict(signed).id]))
        assert c.get(path).status_code == 409
        assert c.post("/api/arena/policy/search", json={"source": "configured", "mode": "rank"}).status_code == 409


def test_search_checks_every_draft_and_selects_the_measured_match_with_highest_fill_value():
    with TestClient(create_app(token="")) as client:
        search_path = "/api/arena/policy/search"
        scenario = {"agents": 50, "steps": 120, "seed": 7, "regime": "normal"}
        payload = scenario | {"limits": {"bad_allowed_usd_per_day": 100_000, "false_refusal_rate": 0.8, "holds_per_day": 50}}
        ranked = client.post(search_path, json=payload | {"mode": "rank"}).json()
        assert ranked["ranking"]["method"] == "point_forecast"
        assert ranked["selected_rank"] is None and all(c["simulation"] is None for c in ranked["candidates"])
        measured = client.post(search_path, json=payload).json()
        assert measured["simulated"] == len(ranked["candidates"]) == 8
        matches = [c for c in measured["candidates"] if c["simulation"]["limits"]["met"]]
        assert measured["match_count"] == len(matches) > 1
        selected = next(c for c in matches if c["rank"] == measured["selected_rank"])
        observed = selected["simulation"]["metrics"]
        assert observed["legitimate_filled_usd_per_day"] == max(c["simulation"]["metrics"]["legitimate_filled_usd_per_day"] for c in matches)
        paired = client.post("/api/arena/policy", json=payload | {"mode": "simulate", "draft": selected["draft"]}).json()
        assert paired["fit"]["fits"] and paired["simulation"]["results"]["draft"] == observed


def test_calibrated_warning_names_a_measured_violation_without_authorizing_the_draft():
    with TestClient(create_app(token="")) as client:
        policy = "/api/arena/policy"
        search = f"{policy}/search"
        scenario = {"agents": 150, "steps": 400, "seed": 7, "regime": "poisoned"}
        params = scenario | {"limits": {"holds_per_day": 0}}
        preview = client.post(search, json=params | {"mode": "rank"}).json()
        warned = next(draft for draft in preview["candidates"] if "warning" in draft)
        assert preview["simulated"] == 0 and preview["selected_rank"] is None
        draft = warned["draft"]
        estimate = client.post(policy, json=params | {"mode": "estimate", "draft": draft}).json()
        warning = estimate["estimate"]["warning"]
        assert warning == warned["warning"] and warning["metric"] == "holds_per_day"
        assert warning["lower_estimate"] > warning["limit"] == 0
        assert estimate["simulation"] is None and "signature" not in draft
        measured = client.post(search, json=params).json()
        assert measured["simulated"] == len(preview["candidates"]) == 8
        actual = next(candidate for candidate in measured["candidates"] if candidate["draft"] == draft)
        assert "warning" not in actual
        check = actual["simulation"]["limits"]["checks"][warning["metric"]]
        assert check["observed"] >= warning["lower_estimate"] and not check["met"]
        unbounded = client.post(search, json=scenario | {"mode": "rank"}).json()
        assert all("warning" not in draft for draft in unbounded["candidates"])
        outside = client.post(policy, json=params | {"mode": "estimate", "draft": draft, "agents": 1100}).json()
        assert outside["estimate"]["status"] == "outside_training_domain" and "warning" not in outside["estimate"]


def test_malformed_forecast_does_not_disable_exact_comparison(tmp_path, monkeypatch):
    from orderguard_arena import mandate_model

    artifact = tmp_path / "invalid-model.json"
    artifact.write_text("[]")
    monkeypatch.setattr(mandate_model, "ARTIFACT", artifact)
    mandate_model.load_model.cache_clear()
    with TestClient(create_app(token="")) as client:
        params = {"agents": 50, "steps": 120, "limits": {"bad_allowed_usd_per_day": 100_000}}
        result = client.post("/api/arena/policy/search", json=params).json()
        assert result["ranking"] == {"method": "generated_order", "reason": "model_unavailable"}
        assert result["simulated"] == 8 and result["selected_rank"] is not None
        draft = result["candidates"][0]["draft"]
        estimate = client.post("/api/arena/policy", json=params | {"draft": draft, "mode": "estimate"}).json()
        assert estimate["estimate"]["status"] == "model_unavailable"


def test_qualifying_starter_drafts_with_no_legitimate_fills_are_not_selected(tmp_path, monkeypatch):
    from orderguard_guard.init_cmd import init

    init(tmp_path)
    monkeypatch.setenv("ORDERGUARD_HOME", str(tmp_path))
    with TestClient(create_app(token="")) as client:
        result = client.post("/api/arena/policy/search", json={"source": "configured", "limits": {
            "bad_allowed_usd_per_day": 2_500, "false_refusal_rate": 1, "holds_per_day": 1_000}}).json()
        assert result["match_count"] == result["simulated"] == 8
        assert all(c["simulation"]["metrics"]["legitimate_fills"] == 0 for c in result["candidates"])
        assert result["selected_rank"] is None
