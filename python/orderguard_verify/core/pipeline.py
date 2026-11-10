"""The whole check in one function: extract -> verify -> decide (-> refresh and re-check once).

It never raises on bad input or an unavailable model or source: the result is `escalate` with the reason, never a stack
trace and never a silent pass."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .decision import decide
from .extractor import extract
from .llm import LLMCall, ask_json
from .models import Claim, Decision, Verdict
from .pack import Pack, SourceUnavailable
from .trace import Trace


@dataclass
class Result:
    run_id: str
    context: Any                  # the pack's Context while running; a plain dict when reloaded from the run store
    as_of: date
    claims: list[Claim]
    verdicts: list[Verdict]
    decision: Decision
    summary: str = ""             # what the text is about, in one line
    dropped: list[dict] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)
    seconds: float = 0.0
    checkable: int = 0            # claims of a type a source could settle
    checked: int = 0              # ... of which the sources could actually settle (verdict other than unverifiable)
    error: str = ""               # set when the check could not run
    saved_coverage: str = ""      # the coverage line as stored, when a result is reloaded from the decision log

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def coverage(self) -> str:
        if self.saved_coverage:
            return self.saved_coverage
        return f"{self.checked} of {self.checkable} checkable claims could be checked" if self.checkable else "no checkable claims found"


def _failed(run_id, context, as_of, summary, why, calls, t0) -> Result:
    return Result(run_id, context, as_of, [], [], Decision(action="escalate", reasons=[why]), summary, [], calls,
                  round(time.time() - t0, 2), error=why)


def check(text: str, context: Any, pack: Pack, *, ask: Callable = ask_json, trace: Trace | None = None) -> Result:
    t0 = time.time()
    text = text.strip()                      # a trailing newline must not change the recorded-answer key
    trace = trace or Trace(db_path=None)
    as_of, summary = pack.decision_date(context), pack.describe(context)
    calls: list[LLMCall] = []

    def tracing_ask(system: str, user: str, **kw):
        data, call = ask(system, user, **kw)
        calls.append(call)
        return data, call

    if not text.strip():
        return _failed(trace.run_id, context, as_of, summary, "the text is empty: nothing to check", calls, t0)
    try:
        pack.prepare(context)
    except SourceUnavailable as e:
        return _failed(trace.run_id, context, as_of, summary, f"cannot check: {e}", calls, t0)
    try:
        ex = extract(text, context, pack, tracing_ask)
    except Exception as e:   # noqa: BLE001  model down, no key, unreadable reply: say so, do not guess
        return _failed(trace.run_id, context, as_of, summary, f"cannot read the text: the model was unavailable or unusable ({type(e).__name__}: {str(e)[:120]})", calls, t0)
    trace.log("extract", claims=[c.model_dump(mode="json") for c in ex.claims], dropped=ex.dropped)
    if not ex.claims:
        return _failed(trace.run_id, context, as_of, summary, "no checkable claims were found in the text", calls, t0)

    def verify_one(c: Claim) -> Verdict:
        try:
            return pack.verify(c, context, tracing_ask)
        except Exception as e:   # noqa: BLE001  one claim failing to check must not sink or silently pass the text
            return Verdict(claim_id=c.id, label="unverifiable", reason=f"could not be checked ({type(e).__name__})")

    def run_checks() -> tuple[list[Verdict], Decision]:
        verdicts = [verify_one(c) for c in ex.claims]
        return verdicts, decide(pack, ex.claims, verdicts)

    verdicts, decision = run_checks()
    trace.log("decision", verdicts=[v.model_dump(mode="json") for v in verdicts], decision=decision.model_dump(mode="json"))
    if decision.refresh:                      # stale data: re-fetch, then check once more
        for subject in decision.refresh:
            pack.refresh(subject)
        verdicts, decision = run_checks()
        trace.log("decision_after_refresh", verdicts=[v.model_dump(mode="json") for v in verdicts], decision=decision.model_dump(mode="json"))
    checkable = [c for c in ex.claims if c.type in pack.hard_types]
    label = {v.claim_id: v.label for v in verdicts}
    return Result(trace.run_id, context, as_of, ex.claims, verdicts, decision, summary, ex.dropped, calls,
                  round(time.time() - t0, 2), checkable=len(checkable), checked=sum(label[c.id] != "unverifiable" for c in checkable))
