"""Trace log: every step of a run, appended to SQLite so a decision can be replayed and audited."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from ..paths import DB as DEFAULT_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace (
    run_id TEXT NOT NULL, ts REAL NOT NULL, step TEXT NOT NULL, data TEXT NOT NULL
);
"""


class Trace:
    def __init__(self, run_id: str | None = None, db_path: str | Path | None = DEFAULT_DB):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.events: list[dict] = []
        self.db = None
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
            self.db.executescript(SCHEMA)

    def log(self, step: str, **data) -> None:
        self.events.append({"step": step, **data})
        if self.db:
            self.db.execute("INSERT INTO trace VALUES (?,?,?,?)", (self.run_id, time.time(), step, json.dumps(data, default=str)))
            self.db.commit()
