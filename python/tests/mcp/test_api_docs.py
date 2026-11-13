"""docs/openapi.json and docs/API.md must match the FastAPI app, and every curl example in them must be a valid request.

If this fails after an app change: `python scripts/gen_api_docs.py` and commit docs/openapi.json and docs/API.md.
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "gen_api_docs.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_generated_api_docs_are_current():
    r = _run("--check")
    assert r.returncode == 0, r.stderr or r.stdout


def test_generation_is_deterministic(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gen_api_docs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a, b = mod.build(), mod.build()
    assert a == b
    assert str(Path.home()) not in a[0] + a[1] and "/Users/" not in a[1]


def test_docs_describe_every_endpoint_and_examples_are_valid_requests(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from orderguard_app.app import create_app
    monkeypatch.setenv("OG_SPEND_FILE", str(tmp_path / "spend.jsonl"))
    monkeypatch.delenv("ORDERGUARD_APP_TOKEN", raising=False)
    monkeypatch.delenv("ORDERGUARD_RECEIVER_URL", raising=False)
    md = (ROOT / "docs" / "API.md").read_text()
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text())
    client = TestClient(create_app(), raise_server_exceptions=False)
    live = create_app().openapi()
    assert set(spec["paths"]) == set(live["paths"])
    for path, item in spec["paths"].items():
        for method in item:
            assert f"### {method.upper()} {path}" in md
    blocks = re.findall(r"```sh\ncurl -s http://127\.0\.0\.1:8600(/\S+) \\\n  -H \"Authorization: Bearer \$ORDERGUARD_APP_TOKEN\"(.*?)\n```", md, re.S)
    assert len(blocks) == sum(len(i) for i in spec["paths"].values())
    posted = 0
    for path, rest in blocks:
        m = re.search(r"-d '(.*)'", rest)
        r = client.post(path, json=json.loads(m.group(1))) if m else client.get(path)
        assert r.status_code == 200, f"example for {path} returned {r.status_code}: {r.text[:200]}"
        posted += bool(m)
    assert posted >= 4
    assert "ORDERGUARD_APP_TOKEN" in md and "127.0.0.1:8600" in md
