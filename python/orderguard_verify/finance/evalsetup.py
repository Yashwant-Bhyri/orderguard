"""How the finance pack builds an isolated gateway for each eval case. The eval never touches the network."""
from __future__ import annotations

from datetime import date

from ..core.gateway import Gateway
from ..paths import DATA
from .pack import FinancePack, load_mandate
from .truth_store import TruthStore

CASES = DATA / "eval" / "cases.json"


def make_gateway(case: dict, ask) -> Gateway:
    # The eval replays history, so its harness (not an agent) fixes the decision date of each case.
    day = case["proposal"].get("as_of")
    return Gateway(FinancePack(TruthStore(), load_mandate(), refresh_fn=None), ask=ask, db_path=":memory:",
                   clock=(lambda: date.fromisoformat(day)) if day else date.today)
