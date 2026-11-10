"""Decision log: every check with its claims, verdicts, decision, evidence and what happened next. Written by the gateway,
read by the review page and `og log`."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

from .models import Claim, Decision, Verdict
from .pipeline import Result

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, ts REAL, status TEXT, as_of TEXT, context_json TEXT, text TEXT, claims TEXT, verdicts TEXT,
    decision TEXT, dropped TEXT, step_reasons TEXT, review TEXT, cost_usd REAL, seconds REAL, summary TEXT, coverage TEXT, error TEXT
);
"""


class RunStore:
    def __init__(self, path: str | Path, read_only: bool = False):
        if str(path) != ":memory:" and not read_only:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        uri = f"file:{path}?mode=ro" if read_only else str(path)
        self.db = sqlite3.connect(uri, uri=read_only, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        if not read_only:
            cols = [r[1] for r in self.db.execute("PRAGMA table_info(runs)")]
            if cols and "context_json" not in cols:      # a log written by an older version: keep it aside, start a new one
                self.db.execute("ALTER TABLE runs RENAME TO runs_legacy")
            self.db.executescript(SCHEMA)

    def pending(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT run_id FROM runs WHERE status='held' ORDER BY ts")]

    def all_runs(self) -> list[dict]:
        rows = self.db.execute("SELECT run_id,status,as_of,summary,decision,ts,coverage,step_reasons FROM runs ORDER BY ts DESC").fetchall()
        return [{"run_id": r[0], "status": r[1], "as_of": r[2], "summary": r[3], "decision": json.loads(r[4]), "ts": r[5],
                 "coverage": r[6], "step_reasons": json.loads(r[7] or "[]")} for r in rows]

    def get(self, run_id: str) -> tuple[Result, dict]:
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        row = dict(row)
        claims = [Claim(**c) for c in json.loads(row["claims"])]
        r = Result(run_id, json.loads(row["context_json"]), date.fromisoformat(row["as_of"]), claims,
                   [Verdict(**v) for v in json.loads(row["verdicts"])], Decision(**json.loads(row["decision"])),
                   row["summary"] or "", json.loads(row["dropped"]), [], row["seconds"], error=row["error"] or "",
                   saved_coverage=row["coverage"] or "")
        return r, row

    def save(self, r: Result, status: str, text: str, step_reasons: list[str] | None = None) -> None:
        ctx = r.context.model_dump_json() if hasattr(r.context, "model_dump_json") else json.dumps(r.context, default=str)
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.run_id, time.time(), status, r.as_of.isoformat(), ctx, text,
            json.dumps([c.model_dump(mode="json") for c in r.claims]), json.dumps([v.model_dump(mode="json") for v in r.verdicts]),
            r.decision.model_dump_json(), json.dumps(r.dropped, default=str), json.dumps(step_reasons or []), None,
            r.cost_usd, r.seconds, r.summary, r.coverage, r.error))
        self.db.commit()

    def update_review(self, run_id: str, status: str, review: dict) -> None:
        self.db.execute("UPDATE runs SET status=?, review=? WHERE run_id=?", (status, json.dumps(review), run_id))
        self.db.commit()
