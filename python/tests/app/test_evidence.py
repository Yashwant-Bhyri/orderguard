"""The public /evidence/<path> endpoint: an allow-list over committed results/ and docs/ files, never a general file server."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from orderguard_app import evidence as E
from orderguard_app.app import create_app

REAL = "results/arena/arena-s7-k1000-t2000.summary.json"
TOKEN = "evidence-test-token"


@pytest.fixture()
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture()
def tokened(monkeypatch):
    monkeypatch.setenv("ORDERGUARD_APP_TOKEN", TOKEN)
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    """A throw-away repository root with public and private files, so symlink and size cases can be built."""
    for d in ("results/sub", "docs", "var", "secret_outside"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "results/ok.json").write_text('{"b": 2, "a": [1, 2]}')
    (tmp_path / "results/sub/note.md").write_text("# hello <script>alert(1)</script>")
    (tmp_path / "docs/page.txt").write_text("plain")
    (tmp_path / "results/spend.jsonl").write_text("{}")
    (tmp_path / "results/signing.key.json").write_text("{}")
    (tmp_path / "results/.hidden.json").write_text("{}")
    (tmp_path / "results/data.bin").write_bytes(b"\0")
    (tmp_path / "var/ledger.json").write_text("{}")
    (tmp_path / "secret_outside/x.json").write_text('{"leak": true}')
    (tmp_path / "top.json").write_text("{}")
    os.symlink(tmp_path / "secret_outside/x.json", tmp_path / "results/link.json")           # file symlink out of the tree
    os.symlink(tmp_path / "secret_outside", tmp_path / "results/linkdir")                    # directory symlink out of the tree
    os.symlink(tmp_path / "results/ok.json", tmp_path / "results/inside_link.json")          # even a link that stays inside is refused
    monkeypatch.setattr(E, "ROOT", tmp_path)
    return TestClient(create_app(), raise_server_exceptions=False)


def test_serves_a_real_result_file_as_a_readable_page_and_raw(client):
    r = client.get("/evidence/" + REAL)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "sha256" in r.text and "?raw=1" in r.text and "&quot;proposals&quot;: 20503" in r.text      # pretty-printed and escaped
    assert r.headers["x-content-type-options"] == "nosniff" and "default-src 'self'" in r.headers["content-security-policy"]
    raw = client.get("/evidence/" + REAL + "?raw=1")
    assert raw.status_code == 200 and raw.headers["content-type"] == "application/json" and raw.json()["proposals"] == 20503
    assert raw.content == (E.ROOT / REAL).read_bytes()
    md = client.get("/evidence/docs/REVIEW.md?raw=1")
    assert md.status_code == 200 and md.headers["content-type"] == "text/plain; charset=utf-8"


def test_json_is_pretty_printed_and_html_is_escaped(tree):
    page = tree.get("/evidence/results/ok.json").text
    assert '&quot;a&quot;: [\n    1,' in page
    md = tree.get("/evidence/results/sub/note.md").text
    assert "<script>alert(1)" not in md and "&lt;script&gt;" in md


def test_works_without_auth_even_with_a_token_set_and_api_stays_protected(tokened):
    for p in ("/evidence/" + REAL, "/evidence/" + REAL + "?raw=1", "/evidence/docs/APP.md"):
        assert tokened.get(p).status_code == 200, p
    assert tokened.get("/api/theater/source?id=summary").status_code == 401
    assert tokened.get("/evidence/docs/APP.md", headers={"Authorization": "Bearer wrong"}).status_code == 200   # a bad header is simply ignored here
    assert TOKEN not in tokened.get("/evidence/docs/APP.md").text


@pytest.mark.parametrize("path", [
    "../pyproject.toml", "results/../pyproject.toml", "docs/../../etc/passwd", "results/%2e%2e/pyproject.toml", "%2e%2e/%2e%2e/etc/passwd",
    "results/%2E%2E/%2e%2e/x.json", "results/..%2fpyproject.toml", "results%2f..%2f..%2fetc%2fpasswd", "docs/%2e%2e%2f%2e%2e%2fsecret.json",
    "/etc/passwd", "//etc/passwd", "%2fetc%2fpasswd", "results//ok.json", "results\\ok.json", "results/ok.json%00.md",
    "docs/..\\x.md", "results/%252e%252e/x.json",
])
def test_traversal_and_absolute_paths_are_refused(tree, client, path):
    for c in (tree, client):
        r = c.get("/evidence/" + path)
        assert r.status_code == 404 and "leak" not in r.text and "root:" not in r.text, path


def test_traversal_resolver_level(tree):
    for rel in ("../top.json", "results/../top.json", "/etc/passwd", "results/", "results", "", "docs", "results/sub", "results/sub/",
                "results/./ok.json", "results/ok.json\n", "results/ok.json\x00.md", "results\\ok.json", "results//ok.json", "results/ok.json/"):
        assert E.resolve(rel) is None, rel
    resolved = E.resolve("results/ok.json")
    assert resolved == (E.ROOT / "results/ok.json").resolve()
    assert resolved.is_file() and not resolved.is_symlink()


def test_symlinks_are_never_followed(tree):
    for p in ("results/link.json", "results/linkdir/x.json", "results/inside_link.json"):
        assert tree.get("/evidence/" + p).status_code == 404, p
        assert tree.get("/evidence/" + p + "?raw=1").status_code == 404, p
    assert tree.get("/evidence/results/ok.json").status_code == 200


def test_allow_list_prefix_extension_and_names(tree):
    assert tree.get("/evidence/results/ok.json").status_code == 200
    assert tree.get("/evidence/docs/page.txt?raw=1").text == "plain"
    for p in ("top.json", "var/ledger.json", "secret_outside/x.json", "python/orderguard_app/app.py", "pyproject.toml", ".env", "data/models/order_risk.json",
              "results/spend.jsonl", "results/signing.key.json", "results/.hidden.json", "results/data.bin", "docs/page.exe", ".git/config", "var/spend.jsonl"):
        assert tree.get("/evidence/" + p).status_code == 404, p


def test_real_repo_private_things_are_not_reachable(client):
    for p in ("results/spend.jsonl", "var/spend.jsonl", "var/ledger.sqlite", ".env", ".env.example", "pyproject.toml", "python/orderguard_app/app.py",
              "data/models/order_risk.json", "results/runs", "results", "docs", "docs/", "nope/x.md", "docs/none.md", "results/none.json"):
        assert client.get("/evidence/" + p).status_code == 404, p
    r = client.get("/evidence/results/none.json")
    assert r.status_code == 404 and r.json() == {"error": "no such evidence file"}


def test_size_caps(tree, monkeypatch):
    big = tree.get("/evidence/results/ok.json")
    assert big.status_code == 200
    monkeypatch.setattr(E, "MAX_RENDER", 5)
    page = tree.get("/evidence/results/ok.json")
    assert page.status_code == 200 and "too large to show here" in page.text and "&quot;a&quot;" not in page.text
    assert tree.get("/evidence/results/ok.json?raw=1").status_code == 200
    monkeypatch.setattr(E, "MAX_RAW", 5)
    assert tree.get("/evidence/results/ok.json?raw=1").status_code == 413
    assert tree.get("/evidence/results/ok.json").status_code == 413
    assert tree.get("/evidence/results/" + "a" * 300 + ".json").status_code == 404


def test_committed_stream_fits_the_raw_cap(client):
    r = client.get("/evidence/results/arena/arena-s7-k1000-t2000.jsonl")
    assert r.status_code == 200 and "too large to show here" in r.text           # readable page points at the raw file
    assert client.get("/evidence/results/arena/arena-s7-k1000-t2000.jsonl?raw=1").status_code == 200


def test_read_only_and_every_linked_source_resolves(client):
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/evidence/" + REAL).status_code == 405
    html = (E.ROOT / "python/orderguard_app/static/index.html").read_text()
    import re
    links = re.findall(r'href="(/evidence/[^"]+)"', html)
    assert len(links) == 2
    for l in links:
        assert client.get(l).status_code == 200, l
    from orderguard_app import theater as T
    for sid, (rel, _) in T.SOURCES.items():
        public = rel.startswith(("results/", "docs/"))
        assert (client.get("/evidence/" + rel).status_code == 200) == public, rel
