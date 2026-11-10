"""The core must not know what an order, a filing or a market price is: those belong in orderguard_verify/finance."""
import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "orderguard_verify" / "core"
FORBIDDEN = r"\b(ticker|tickers|orders|filing|filings|edgar|10-k|shares|price|prices|revenue|eps|broker|ledger|trade|trading|stock|equity|fiscal|paper)\b"
ALLOWED_LINES = ()


def test_core_imports_nothing_from_finance():
    for f in CORE.glob("*.py"):
        assert "finance" not in re.findall(r"from \.\.?(\w+)", f.read_text()) and "orderguard_verify.finance" not in f.read_text(), f.name


def test_core_uses_no_finance_vocabulary():
    hits = []
    for f in CORE.glob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            low = line.lower()
            if any(a in low for a in ALLOWED_LINES):
                continue
            if re.search(FORBIDDEN, low):
                hits.append(f"{f.name}:{n}: {line.strip()[:90]}")
    assert not hits, "\n".join(hits)
