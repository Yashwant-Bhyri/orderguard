"""The finance pack: research memos in; trusted sources are SEC EDGAR filings (and a SYNTHETIC quote feed for the
dev-set price cases); the limits are the human's mandate. One small function (`step`) maps the text's decision to what
happens to an order. No real orders, ever: "cleared" is a record in the decision log, nothing is sent anywhere."""
from __future__ import annotations

import json
from datetime import date
from typing import Callable

from ..core.models import Claim, Decision, Verdict
from ..core.pack import SourceUnavailable
from ..paths import DATA, DB, VAR
from . import edgar, extraction, sources, verifier
from .mandate import check_mandate
from .models import AgentOrder, Mandate, Memo, Order
from .truth_store import TruthStore

# How a decision about the text becomes a decision about the order. This table is the whole of it.
STATUS = {"pass": "cleared", "revise": "returned", "block": "blocked", "escalate": "held"}


class FinancePack:
    name = "finance"
    Context = Memo
    Proposal = Order
    hard_types = frozenset({"price", "fundamental"})
    never_key_types = frozenset({"sentiment"})
    unconfirmable_types = frozenset({"rumour"})
    form_fields = ('<input name="ticker" placeholder="Ticker, e.g. AAPL" required size="14">'
                   '<input name="as_of" type="date" title="Date the memo was written (blank = today)">')
    form_hint = "Checks the memo's reported figures against SEC filings public on that date. Nothing is sent anywhere."

    def __init__(self, store: TruthStore, mandate: Mandate, refresh_fn: Callable | None = edgar.refresh, on_demand: bool = False):
        self.store, self.mandate, self.refresh_fn, self.on_demand = store, mandate, refresh_fn, on_demand

    def extraction_prompt(self, text: str, ctx: Memo):
        return extraction.extraction_prompt(text, ctx)

    def claim_from_raw(self, raw: dict, index: int, ctx: Memo) -> Claim:
        return extraction.claim_from_raw(raw, index, ctx)

    def describe(self, ctx: Memo) -> str:
        return f"{ctx.side} {ctx.quantity} {ctx.ticker}" if isinstance(ctx, Order) else f"memo about {ctx.ticker}"

    def decision_date(self, ctx: Memo) -> date:
        return ctx.as_of or date.today()

    def prepare(self, ctx: Memo) -> None:
        """Fetch the company's filings on demand if we do not have them (only when switched on: the eval never touches the network)."""
        if self.on_demand:
            sources.ensure(self.store, ctx.ticker)
        elif ctx.ticker.upper() not in self.store.tickers():
            raise SourceUnavailable(f"{ctx.ticker} is not in the truth store")

    def verify(self, claim: Claim, ctx: Memo, ask: Callable) -> Verdict:
        return verifier.verify(claim, self.decision_date(ctx), self.store, ask)

    def refresh(self, subject: str) -> None:
        """Re-fetch a company's filings. If the network fails the re-check simply sees the same data."""
        if self.refresh_fn:
            try:
                self.refresh_fn(self.store, subject)
            except Exception:   # noqa: BLE001
                pass

    def violations(self, order: Order) -> list[str]:
        return check_mandate(order, self.mandate, self.store)

    def step(self, decision: Decision, violations: list[str]) -> tuple[str, list[str]]:
        """Outside the mandate is always blocked. Otherwise pass -> cleared, revise -> returned, block -> blocked, escalate -> held."""
        if violations:
            return "blocked", [f"outside the mandate: {v}" for v in violations]
        return STATUS[decision.action], []

    def register_tools(self, mcp, gateway, call) -> None:
        @mcp.tool()
        async def propose_order(research: str, order: AgentOrder) -> dict:
            """Submit a research memo and the order it supports. The memo is checked against SEC filings. Returns the
            order status (cleared / returned / held / blocked), the claims to fix if returned, and the reasons. A held
            order waits for a human."""
            return await call(gateway.propose, research, order.model_dump())

        @mcp.tool()
        async def check_memo(research: str, ticker: str) -> dict:
            """Check a research memo against SEC filings without proposing any order. The server decides the date (today);
            you cannot choose it. Returns pass / revise / block / escalate, the claims to fix, and how many claims could be checked."""
            return await call(gateway.check, research, {"ticker": ticker, "as_of": gateway.clock().isoformat()})

        @mcp.tool()
        async def order_status(run_id: str) -> dict:
            """Look up what happened to an earlier proposal (for example a held order a human has since reviewed)."""
            try:
                _, row = gateway.get(run_id)
            except KeyError:
                return {"error": "unknown run_id"}
            return {"run_id": run_id, "status": row["status"]}


def load_mandate(path=None) -> Mandate:
    return Mandate(**json.loads((path or DATA / "mandate.json").read_text()))


def make_pack(store: TruthStore | None = None, mandate: Mandate | None = None, refresh: bool = False, on_demand: bool = False) -> FinancePack:
    """The finance pack wired to the truth store. A working copy of the shipped store lives in var/ so that data fetched on demand
    never touches the committed file."""
    if store is None:
        work = VAR / "truth.db"
        if not work.exists():
            import os
            import shutil
            VAR.mkdir(parents=True, exist_ok=True)
            tmp = work.with_name(f"truth.{os.getpid()}.tmp")
            shutil.copy(DATA / "truth.db", tmp)
            os.replace(tmp, work)           # atomic: two processes starting together never see half a file
        store = TruthStore(work)
    from . import quotes
    if store.quote("AAPL", date.today()) is None and "AAPL" in store.tickers():
        quotes.load(store)
    return FinancePack(store, mandate or load_mandate(), sources.refresh if refresh else None, on_demand)
