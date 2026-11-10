"""OrderGuard guard: layers L1-L5 and L7, the hardened agent loop, the LLM client, the receiver client and the CLI.

AI trading agents will believe fake information. OrderGuard decides what they may do using numbers they
cannot touch, and checks the facts their orders rely on. See docs/ARCHITECTURE.md for the layer map.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repository root (python/orderguard_guard/__init__.py -> ../..)
DATA = ROOT / "data"
REPLAY_DIR = Path(os.getenv("OG_REPLAY_DIR", DATA / "replay"))
RESULTS_DIR = Path(os.getenv("OG_RESULTS_DIR", ROOT / "results"))
DEFAULT_MODEL = os.getenv("OG_MODEL", "deepseek/deepseek-v4.1-flash")

__all__ = ["ROOT", "DATA", "REPLAY_DIR", "RESULTS_DIR", "DEFAULT_MODEL"]
