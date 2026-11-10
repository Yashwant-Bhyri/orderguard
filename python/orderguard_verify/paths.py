"""Where things live on disk. OG_VAR moves the working files (decision log, working truth store) elsewhere."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repository root
DATA = ROOT / "data" / "verify"
RESULTS = DATA / "results"
DOCS = ROOT / "docs" / "verify"
VAR = Path(os.getenv("OG_VAR", ROOT / "var" / "verify"))
DB = VAR / "orderguard.db"
