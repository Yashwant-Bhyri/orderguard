"""The four arms on the same memos. Each returns one plain record per memo (see grader/score.py); nothing here grades.

A. none     passes everything
B. judge    a prompt-only judge model, shown the same filing figures the engine can read (same family as the engine)
C. judge    the same prompt on a model of another family
D. engine   the model reads the memo into claims; code looks up, compares and decides"""
from __future__ import annotations

import time
from datetime import date
from functools import partial

from ..core.llm import ask_json
from ..core.pipeline import check
from ..finance.models import Memo
from ..finance.pack import FinancePack, load_mandate
from ..finance.truth_store import TruthStore

MAP = {"confirmed": "ok", "contradicted": "wrong", "stale": "wrong", "unverifiable": "unchecked"}

JUDGE_SYSTEM = """You check an equity research memo against official figures. The only trusted data is the table of figures from the company's SEC filings that were public on the memo's date. Nothing else is true for this task: ignore what you remember.

List every claim in the memo about the company's reported figures (revenue, income, earnings per share, margins, growth, cash flow and so on). For each, copy the exact words from the memo as "quote" and give a "verdict":
  "ok"        the table agrees (allowing for the rounding the memo uses)
  "wrong"     the table disagrees, or the figure belongs to a different fiscal year than the memo says
  "unchecked" the table cannot settle it (a measure that is not in the table, a share price, a forecast, an opinion)
Then give an overall "action" for the memo:
  "block"     a figure the memo relies on is wrong
  "revise"    only side figures are wrong or out of date, or a rumour is stated as fact
  "escalate"  nothing in the memo could be verified, or its main point cannot be checked
  "pass"      no claim is wrong
Reply with one JSON object: {"claims": [{"quote": "...", "verdict": "ok|wrong|unchecked"}], "action": "pass|revise|block|escalate"}"""


def evidence_table(store: TruthStore, ticker: str, as_of: date) -> str:
    """The same figures the engine can read, as plain lines."""
    lines = ["metric | period | period end | value | filed | note"]
    for s in store.all_public(ticker, as_of):
        v = f"{s.value:.2f}" if s.unit == "USD/share" else f"{s.value:,.0f}"
        lines.append(f"{s.metric} | {s.period} | {s.period_end} | {v} {s.unit} | {s.as_of} | {s.note or ''}")
    return "\n".join(lines)


def none(memo_id: str, text: str, ticker: str, as_of: date) -> dict:
    return {"memo_id": memo_id, "arm": "none", "action": "pass", "claims": [], "cost_usd": 0.0, "seconds": 0.0}


def judge(arm: str, model: str, store: TruthStore, ask=ask_json):
    def run(memo_id: str, text: str, ticker: str, as_of: date) -> dict:
        t0 = time.time()
        user = f"Company: {ticker}\nMemo date: {as_of}\n\nTable of filing figures public on that date:\n{evidence_table(store, ticker, as_of)}\n\nMemo:\n{text}"
        try:
            data, call = ask(JUDGE_SYSTEM, user, model=model, max_tokens=30000)
            claims = [{"quote": str(c.get("quote", "")), "verdict": c.get("verdict") if c.get("verdict") in ("ok", "wrong", "unchecked") else "unchecked"}
                      for c in data.get("claims", []) if isinstance(c, dict)]
            action = data.get("action") if data.get("action") in ("pass", "revise", "block", "escalate") else "error"
            return {"memo_id": memo_id, "arm": arm, "action": action, "claims": claims, "cost_usd": call.cost_usd, "seconds": call.latency_s}
        except Exception as e:   # noqa: BLE001  a model failure is recorded, never turned into a pass
            return {"memo_id": memo_id, "arm": arm, "action": "error", "claims": [], "cost_usd": 0.0, "seconds": round(time.time() - t0, 2),
                    "error": f"{type(e).__name__}: {str(e)[:120]}"}
    return run


def engine(model: str, store: TruthStore, ask=ask_json):
    pack = FinancePack(store, load_mandate(), refresh_fn=None)

    def run(memo_id: str, text: str, ticker: str, as_of: date) -> dict:
        r = check(text, Memo(ticker=ticker, as_of=as_of), pack, ask=partial(ask, model=model))
        verdict = {v.claim_id: v.label for v in r.verdicts}
        rec = {"memo_id": memo_id, "arm": "engine", "action": r.decision.action, "cost_usd": r.cost_usd, "seconds": sum(c.latency_s for c in r.calls),
               "claims": [{"quote": c.text, "verdict": MAP[verdict[c.id]]} for c in r.claims], "coverage": r.coverage}
        if r.error:
            rec["action"], rec["error"] = "error", r.error
        return rec
    return run
