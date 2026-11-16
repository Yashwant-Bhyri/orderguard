"""The launch site (site/): its data is built from the committed results, is current, is deterministic, and is the only source of
the figures the page shows."""
from __future__ import annotations

import importlib.util
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "site"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts" / "build_site_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load_builder()


@pytest.fixture(scope="module")
def built():
    return B.build()


@pytest.fixture(scope="module")
def data():
    return json.loads((SITE / "data.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------- build
def test_the_build_is_deterministic(built):
    doc2, theater2 = B.build()
    assert B.serialise(built[0]) == B.serialise(doc2)
    assert built[1] == theater2


def test_data_json_is_current_with_the_results(built):
    """Fails when a results file, the README or a policy pack changed and the site data was not rebuilt (the og-arena verify idea)."""
    assert (SITE / "data.json").read_text(encoding="utf-8") == B.serialise(built[0]), \
        "site/data.json is stale: run .venv/bin/python scripts/build_site_data.py"
    for name, body in built[1].items():
        assert (SITE / "theater" / name).read_bytes() == body, f"site/theater/{name} is stale: run scripts/build_site_data.py"
    assert B.main(["--check"]) == 0


def test_every_input_is_listed_with_its_hash_and_every_fact_names_an_existing_file(data):
    paths = {i["path"] for i in data["inputs"]}
    assert {"results/bench/summary.json", "results/redteam/campaign.json", "results/review/triage.json", "results/theater/timeline.json", "README.md"} <= paths
    for i in data["inputs"]:
        assert (ROOT / i["path"]).is_file() and re.fullmatch(r"[0-9a-f]{64}", i["sha256"])

    def walk(o):
        if isinstance(o, dict):
            if {"value", "text", "src"} <= set(o):
                yield o
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    facts = list(walk(data))
    assert len(facts) > 40
    for f in facts:
        assert (ROOT / f["src"]).is_file(), f["src"]
    for key in ("src",):
        for o in _dicts(data):
            v = o.get(key)
            for p in ([v] if isinstance(v, str) else v if isinstance(v, list) else []):
                assert (ROOT / p).exists(), p


def _dicts(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _dicts(v)
    elif isinstance(o, list):
        for v in o:
            yield from _dicts(v)


def test_headline_figures_match_their_result_files(data):
    s = json.loads((ROOT / "results/bench/summary.json").read_text())
    assert data["bench"]["facts"]["dps"]["text"] == f"{s['at_scale']['decisions_per_s']:,}"
    camp = json.loads((ROOT / "results/redteam/campaign.json").read_text())
    assert data["redteam"]["facts"]["rounds"]["value"] == camp["summary"]["rounds"]
    assert data["redteam"]["facts"]["hard"]["value"] == camp["summary"]["hard_breach_count"]
    t = json.loads((ROOT / "results/review/triage.json").read_text())
    assert data["review"]["facts"]["model"]["value"] == t["queues"]["model_flagged"]["reviews_to_catch"]["model"]["90%"]
    # the forged-split example is decided by the real gate, not typed in
    assert data["split"]["decision"] == "refuse" and data["split"]["decided_by"] == "L5"
    assert any("per-order cap" in r for r in data["split"]["reasons"])


def test_scope_and_promise_are_copied_from_the_readme(data):
    readme = (ROOT / "README.md").read_text()
    assert f"**{data['readme']['promise']}**" in readme
    for s in data["readme"]["scope"]:
        assert f"**{s['lead']}**" in readme
        assert "".join(x.get("t", "") or x.get("b", "") or x.get("code", "") or x.get("a", "") for x in s["text"]) in readme.replace("`", "")


# ---------------------------------------------------------------------------------------------------------------- the page
class _Text(HTMLParser):
    """Visible text and the readable attributes of index.html, outside <script> and <style>."""

    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self.binds: list[tuple[str, str]] = []
        self.skip = 0
        self.h1 = None
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        for k in ("data-t", "data-f", "data-seg", "data-src", "data-check"):
            if k in a:
                self.binds.append((k, a[k]))
        for k in ("aria-label", "title", "alt", "placeholder"):
            if a.get(k):
                self.out.append(a[k])
        if tag == "h1":
            self._in_h1, self.h1 = True, ""

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if tag == "h1":
            self._in_h1 = False

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)
            if self._in_h1:
                self.h1 += d


PAGES = ("index.html", "evidence.html", "vision.html")


def _page(name="index.html"):
    p = _Text()
    p.feed((SITE / name).read_text(encoding="utf-8"))
    return p


def test_the_html_holds_no_figures_of_its_own():
    """Every number on the page is placed from data.json. The markup may only name the layer codes (L1 to L8)."""
    for name in PAGES:
        text = " ".join(_page(name).out)
        text = re.sub(r"\bL[1-8]\b", "", text)
        assert not re.findall(r"\d", text), f"hand-typed digits in site/{name}: {re.findall(r'.{0,30}\d.{0,30}', text)}"


def test_every_binding_resolves_in_data_json(data):
    page = _page()
    evidence = _page("evidence.html")
    # the demos, the console and the comparison are built from data.json by site.js, so fewer bindings live in the markup
    assert len(page.binds) + len(evidence.binds) > 20
    for kind, path in page.binds + evidence.binds:
        node = data
        for k in path.split("."):
            assert isinstance(node, dict) and k in node, f"{kind}={path!r} does not resolve in site/data.json"
            node = node[k]
        if kind == "data-f":
            assert {"text", "src"} <= set(node)
        if kind == "data-check":
            assert page.h1.strip().rstrip(".") == node.rstrip("."), "the hero headline must be the README's promise, word for word (no trailing period on a headline)"


DATA_LIKE = re.compile(r"\$\s?\d|\d,\d{3}|\d+(?:\.\d+)?\s*(?:%|µs|ms|x\b|M\b|k\b)|\b\d+\s+(?:of|agents|orders|reviews|rounds|processes|steps|seeds|days)\b")


def test_the_script_formats_no_figures_of_its_own():
    """site.js positions marks and places strings from data.json; a string literal that looks like a figure is a hand-typed number."""
    js = (SITE / "site.js").read_text(encoding="utf-8")
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert "`" not in js, "template literals would hide figures from this check"
    bad = [m.group() for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', js) if DATA_LIKE.search(m.group())]
    assert not bad, f"figure-like string literals in site/site.js: {bad}"
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js


def test_static_contract_weight_and_no_external_requests():
    files = [SITE / "index.html", SITE / "evidence.html", SITE / "vision.html", SITE / "site.css", SITE / "site.js"]
    total = sum(p.stat().st_size for p in files)
    assert total < 400_000, f"page weight {total:,} bytes (data.json excluded)"
    for p in files:
        body = p.read_text(encoding="utf-8")
        urls = set(re.findall(r"https?://[^\s\"')]+", body))
        assert urls <= {"http://www.w3.org/2000/svg", "https://github.com/"}, f"{p.name} references {urls - {'http://www.w3.org/2000/svg', 'https://github.com/'}}"
        assert "@import" not in body and "fonts.googleapis" not in body
        assert not re.search(r"/(Users|home)/[a-z]", body), f"{p.name} has an absolute home path"
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", body.replace("@media", "").replace("@import", "")), f"{p.name} has an email address"
    html = (SITE / "index.html").read_text()
    assert re.search(r'<script src="site.js" defer></script>', html) and '<link rel="stylesheet" href="site.css">' in html
    css = (SITE / "site.css").read_text()
    assert "prefers-reduced-motion: reduce" in css and "prefers-color-scheme: dark" in css and ':root[data-theme="dark"]' in css


def test_data_json_has_no_home_paths_or_emails():
    body = (SITE / "data.json").read_text(encoding="utf-8")
    assert not re.search(r"/(Users|home)/[a-z]", body)
    assert not re.search(r"[\w.+-]+@[\w-]+\.(com|org|net|io)\b", body)


def test_the_static_theater_reads_its_files_next_to_it():
    html = (SITE / "theater" / "index.html").read_text()
    assert '<script src="./static-shim.js"></script>\n<script src="./theater.js"></script>' in html
    assert "/static/" not in html
    shim = (SITE / "theater" / "static-shim.js").read_text()
    assert '"/api/theater/timeline": "./timeline.json"' in shim
