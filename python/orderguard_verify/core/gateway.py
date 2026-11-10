"""Gateway core: the one place a checked request is let through.

check()    any text + what it is about -> pass / revise / block / escalate, saved to the decision log. No request involved.
propose()  an outside agent's text + request -> the same check, then the pack decides what the request does:
           cleared (pass), returned for fixes (revise), blocked, or held for a human (escalate).
review()   a human approves or rejects a held request after reading its evidence card.

The agent only ever sees the short reply from propose(). It never sees the mandate, and violations of it are reported
to the agent in general terms only. This prototype sends nothing anywhere: "cleared" is a record, not an order."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from ..paths import DB
from .llm import ask_json
from .pack import Pack
from .pipeline import Result, check
from .runs import RunStore
from .trace import Trace


class Gateway:
    def __init__(self, pack: Pack, *, ask: Callable = ask_json, db_path: str | Path = DB, clock: Callable[[], date] = date.today):
        self.pack, self.ask, self.db_path, self.clock = pack, ask, str(db_path), clock
        self.runs = RunStore(self.db_path)
        self.last: Result | None = None   # the most recent check, with its model calls (the eval reads cost and latency here)

    def _trace(self) -> Trace:
        return Trace(db_path=None if self.db_path == ":memory:" else self.db_path)

    # --- checking any text -----------------------------------------------------------------------

    def check(self, text: str, context: dict | Any) -> dict:
        try:
            c = context if isinstance(context, self.pack.Context) else self.pack.Context(**context)
        except ValidationError as e:
            return {"status": "rejected", "action": "escalate", "reasons": [f"invalid input: {e.errors()[0]['msg']}"]}
        r = check(text, c, self.pack, ask=self.ask, trace=self._trace())
        self.last = r
        self.runs.save(r, "checked", text)
        return self._reply(r, "checked", [])

    # --- agent-facing ----------------------------------------------------------------------------

    def propose(self, text: str, proposal: dict | Any) -> dict:
        try:
            p = proposal if isinstance(proposal, self.pack.Proposal) else self.pack.Proposal(**proposal)
        except ValidationError as e:
            return {"status": "rejected", "action": "block", "reasons": [f"invalid request: {e.errors()[0]['msg']}"]}
        if not isinstance(text, str) or not text.strip():
            return {"status": "rejected", "action": "block", "reasons": ["the memo is empty: a request needs the memo it rests on"]}
        p = p.model_copy(update={"as_of": self.clock()})      # the decision date is the server's, never the agent's
        r = check(text, p, self.pack, ask=self.ask, trace=self._trace())
        self.last = r
        status, extra = self.pack.step(r.decision, self.pack.violations(p))
        if r.error and status == "held":    # the check could not run (no claims found, source or model down): nothing for a human to review
            status = "rejected"
        self.runs.save(r, status, text, extra)
        return self._reply(r, status, extra)

    # --- human-facing ----------------------------------------------------------------------------

    def review(self, run_id: str, approve: bool, reviewer: str = "human") -> dict:
        _, row = self.runs.get(run_id)
        if row["status"] != "held":
            return {"status": row["status"], "message": "only held requests can be reviewed"}
        status = "approved_cleared" if approve else "rejected"
        self.runs.update_review(run_id, status, {"reviewer": reviewer, "approved": approve, "at": time.time()})
        return {"run_id": run_id, "status": status}

    def pending(self) -> list[str]:
        return self.runs.pending()

    def get(self, run_id: str):
        return self.runs.get(run_id)

    @staticmethod
    def _reply(r: Result, status: str, extra: list[str]) -> dict:
        reasons = list(dict.fromkeys(["the request is outside the signed mandate" if x.startswith("outside the mandate") else x
                                      for x in extra + r.decision.reasons]))
        fix = [{"claim": c.text} for c in r.claims if c.id in r.decision.fix]
        return {"run_id": r.run_id, "status": status, "action": r.decision.action, "reasons": reasons, "fix": fix, "coverage": r.coverage}
