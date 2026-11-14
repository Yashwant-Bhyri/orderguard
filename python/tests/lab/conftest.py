import os

import pytest

os.environ.setdefault("OG_LAB_L6", "facts")          # never reach the network for figure checks
os.environ.setdefault("OG_LLM", "replay")


@pytest.fixture
def res(tmp_path, monkeypatch):
    """Redirect every results directory the lab writes or reads into tmp_path."""
    from orderguard_lab import adaptive, cli, detect, runner, tables
    from orderguard_lab.sandbox import sweep
    d = {"RUNS": tmp_path / "runs", "ADAPTIVE": tmp_path / "adaptive", "DETECT": tmp_path / "detect", "SWEEPS": tmp_path / "sweeps"}
    for mod in (tables, runner, adaptive, detect, sweep):
        for k, v in d.items():
            if hasattr(mod, k):
                monkeypatch.setattr(mod, k, v)
    monkeypatch.setattr(tables, "SPEND", tmp_path / "spend.jsonl")
    monkeypatch.setattr(tables, "RESULTS_MD", tmp_path / "RESULTS.md")
    from orderguard_lab.sandbox import manifest
    monkeypatch.setattr(manifest, "SANDBOX_MD", tmp_path / "SANDBOX.md")
    return tmp_path


@pytest.fixture(autouse=True)
def _strict_replay(monkeypatch):
    """In the lab suite a missing recording must stop the run, never become an excluded error row."""
    monkeypatch.setenv("OG_REPLAY_STRICT", "1")
