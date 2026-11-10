"""Where the lab reads and writes. Everything is relative to the repository root; no absolute paths are stored anywhere."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_LAB = ROOT / "data" / "lab"
REPLAY = ROOT / "data" / "replay"
RESULTS = Path(os.getenv("OG_RESULTS", ROOT / "results"))
RUNS = RESULTS / "runs"
ADAPTIVE = RESULTS / "adaptive"
DETECT = RESULTS / "detect"
SWEEPS = RESULTS / "sweeps"
SPEND = RESULTS / "spend.jsonl"
DOCS = ROOT / "docs"
RESULTS_MD = DOCS / "RESULTS.md"
