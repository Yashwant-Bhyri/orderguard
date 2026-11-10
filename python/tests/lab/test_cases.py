import re

from orderguard_lab import cases as C


def test_registry_size_and_unique_ids():
    cs = C.all_cases()
    assert len(cs) >= 60
    assert len({c.id for c in cs}) == len(cs)
    assert len([c for c in cs if not c.control]) >= 60


def test_every_family_covered():
    fam = C.counts()
    for f in C.FAMILIES:
        assert fam.get(f, 0) >= 5, (f, fam)


def test_one_control_per_surface():
    ctl = {c.surface for c in C.all_cases() if c.control}
    assert ctl == set(C.SURFACES)


def test_every_case_has_predicate_stop_source_and_env():
    for c in C.all_cases():
        assert c.has_predicate(), c.id
        assert c.expected_stop in C.STOPS, c.id
        assert c.source_idea.strip(), c.id
        assert c.goal in C.GOALS, c.id
        assert c.surface in C.SURFACES, c.id
        env = c.build_env()
        assert env.tool_names("naive") != env.tool_names("full")          # transfer only in the naive arm
        assert "transfer_funds" in env.tool_names("naive") and "transfer_funds" not in env.tool_names("full")
        assert c.user_task().startswith("Today is 2024-11-06")


def test_legacy_ports_keep_their_ids():
    legacy = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "W0", "W1", "W2", "W3", "W4", "F0", "F1", "F2", "F3", "F4"]
    for l in legacy:
        assert C.get(l).legacy == l
    assert len([c for c in C.all_cases() if c.legacy]) == 19        # 16 attacks + 3 surface controls


def test_required_variants_present():
    squash = lambda x: re.sub(r"[^a-z0-9]", "", x.lower())          # noqa: E731
    ids = squash(" ".join(c.technique + " " + c.id + " " + c.description for c in C.all_cases()))
    for needle in ["zero-width", "html comment", "fake tool-result", "tool-description", "zh-hant", "zh-hans", "cantonese", "base64", "reverse split", "special dividend",
                   "symbol change", "halt", "margin call", "risk-engine", "mandate update", "quarterly", "wrong year", "billions and millions", "guidance", "look-alike",
                   "homoglyph", "consensus", "wire", "replay", "echo", "single venue", "tampered", "duplicate", "lot size", "price band"]:
        assert squash(needle) in ids, needle


def test_no_paths_or_emails_in_case_text():
    for c in C.all_cases():
        blob = repr(c.description) + repr(c.source_idea) + repr(c.user_task())
        assert ("/Us" + "ers/") not in blob and not re.search(r"\b[\w.]+@[\w.]+\.\w+\b", blob), c.id


def test_select():
    assert len(C.select("A")) == C.counts()["A"]
    assert C.select("D1")[0].id == "A-D1"
    assert all(c.surface == "feed" for c in C.select("feed"))
