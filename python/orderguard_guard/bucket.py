"""L3 risk bucket: new information that repeats or depends on a quarantined item is quarantined too.

Code first: two items are related when they share the same ticker plus a distinctive number or a distinctive entity, or
when they come from the same source. A model is asked only when code is unsure (same ticker, nothing concrete shared).
Each entry keeps provenance: source, time, reason, and the index of the entry it repeats.

Measured motivation (lab/legacy/attack-lab-2026-11-06/README.md, round 3): a third wire repeating a quarantined "$400 Apple
takeover" was caught as "repeats a quarantined claim"; the echo-amplification family (F4: 8 headlines from 5 sources) is
exactly this pattern.
"""
from __future__ import annotations

import json
import re
import time
from typing import Iterable

from .llm import as_llm, parse_json

_NUM = re.compile(r"(?<![\w.])[$€£]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[$€£]?\d+(?:\.\d+)?(?:\s?%|-for-\d+|x)?(?![\w])")
_ENTITY = re.compile(r"\b[A-Z][a-z]{3,}(?:\s[A-Z][a-z]{3,})*\b|\b[A-Z]{3,6}\b")
STOP_ENTITIES = {
    "The", "This", "That", "These", "Those", "There", "Company", "Note", "Notes", "Item", "Form", "Total", "Fiscal", "Year",
    "Shares", "Share", "Revenue", "Sales", "Income", "Statement", "Statements", "Consolidated", "Quarter", "Annual", "Report",
    "Today", "Market", "Markets", "Analysts", "Analyst", "Investors", "Investor", "Price", "Prices", "Stock", "Stocks", "Inc",
    "USD", "SEC", "EPS", "CEO", "CFO", "NASDAQ", "NYSE", "AAPL", "MSFT", "Apple", "Microsoft", "Breaking", "Update", "Updated",
}
COMPANY_NAMES = {"AAPL": {"Apple"}, "MSFT": {"Microsoft"}, "GOOGL": {"Alphabet", "Google"}, "AMZN": {"Amazon"}, "NVDA": {"Nvidia"}}

SAME = (
    "You compare a NEW item of market information with a list of EARLIER items that an input screen quarantined as suspicious. "
    'Reply JSON only: {"repeats": true|false, "which": <index of the earlier item or null>, "why": "<one sentence>"}. '
    "'repeats' is true only if the new item makes the same claim as, or depends on, one of the earlier items."
)


def numbers_in(text: str) -> list[str]:
    """Distinctive numbers in text, normalised: '$431,035' -> '431035', '7.38' -> '7.38', '10-for-1' -> '10-for-1'."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).strip()
        tok = raw.lstrip("$€£").replace(",", "").replace(" ", "")
        core = re.sub(r"[%x]$", "", tok)
        if re.fullmatch(r"\d+(\.\d+)?", core):
            try:
                v = float(core)
            except ValueError:
                continue
            if 1900 <= v <= 2100 and float(v).is_integer():   # years are not distinctive
                continue
            if v < 10 and "." not in core:                     # small integers are not distinctive
                continue
            if core == tok:                                    # plain number: one spelling per value ('400.00' and '$400' match)
                tok = format(v, "f").rstrip("0").rstrip(".") if "." in core else str(int(v))
        if tok not in out:
            out.append(tok)
    return out


def entities_in(text: str, ticker: str | None = None) -> set[str]:
    """Capitalised words and acronyms that may name an entity, minus stopwords and the company itself."""
    skip = set(STOP_ENTITIES)
    if ticker:
        skip.add(ticker.upper())
        skip |= COMPANY_NAMES.get(ticker.upper(), set())
    return {e for e in _ENTITY.findall(text or "") if e not in skip and e.split()[0] not in skip}


def _text_of(item: dict) -> str:
    t = item.get("text")
    if isinstance(t, str):
        return t
    return json.dumps(t if t is not None else {k: v for k, v in item.items() if k not in ("numbers",)}, ensure_ascii=False)


class RiskBucket:
    """`add(item)` quarantines an item; `related(item)` returns the quarantined entry it repeats, or None.

    item = {"source", "ticker", "text", "numbers": [...], "kind"}; numbers are extracted from text when absent.
    """

    def __init__(self, model=None, *, use_model_when_unsure: bool = True):
        self.items: list[dict] = []
        self.llm = as_llm(model) if model is not None else None
        self.use_model = use_model_when_unsure and self.llm is not None
        self.model_calls = 0

    def __len__(self) -> int:
        return len(self.items)

    # ---- writing --------------------------------------------------------------------------------

    def add(self, item: dict, reason: str = "flagged by the input screen", related_to: int | None = None) -> dict:
        entry = {
            "source": item.get("source"), "ticker": (item.get("ticker") or "").upper() or None, "kind": item.get("kind"),
            "text": _text_of(item)[:600], "numbers": list(item.get("numbers") or numbers_in(_text_of(item))),
            "entities": sorted(entities_in(_text_of(item), item.get("ticker"))),
            "time": item.get("time") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason, "related_to": related_to, "index": len(self.items),
        }
        self.items.append(entry)
        return entry

    # ---- reading --------------------------------------------------------------------------------

    def related(self, item: dict) -> dict | None:
        """Code-first relation test; model check only when code is unsure. Returns the matching entry plus a 'match' reason."""
        if not self.items:
            return None
        text = _text_of(item)
        ticker = (item.get("ticker") or "").upper() or None
        nums = set(item.get("numbers") or numbers_in(text))
        ents = entities_in(text, ticker)
        source = item.get("source")
        unsure: list[dict] = []
        for q in self.items:
            same_ticker = ticker and q["ticker"] and ticker == q["ticker"]
            shared_nums = nums & set(q["numbers"])
            shared_ents = ents & set(q["entities"])
            if same_ticker and shared_nums:
                return dict(q, match=f"same ticker {ticker} and shares the number {sorted(shared_nums)[0]} with a quarantined item from {q['source']}")
            if same_ticker and shared_ents:
                return dict(q, match=f"same ticker {ticker} and names {sorted(shared_ents)[0]} like a quarantined item from {q['source']}")
            if source and q["source"] and source == q["source"] and q.get("kind") not in ("doc",):
                return dict(q, match=f"same source {source} as a quarantined item")
            if same_ticker and q.get("kind") != "doc":
                unsure.append(q)
        if unsure and self.use_model:
            return self._ask_model(item, text, unsure)
        return None

    def admit(self, item: dict) -> tuple[bool, dict | None]:
        """Admit an item unless it repeats a quarantined claim; if it does, quarantine it too. Returns (admitted, entry)."""
        r = self.related(item)
        if r is None:
            return True, None
        entry = self.add(item, reason=f"repeats a quarantined claim: {r['match']}", related_to=r["index"])
        return False, entry

    def _ask_model(self, item: dict, text: str, candidates: list[dict]) -> dict | None:
        self.model_calls += 1
        payload = {"new": {"source": item.get("source"), "ticker": item.get("ticker"), "text": text[:1500]},
                   "earlier": [{"index": i, "source": q["source"], "text": q["text"][:400], "reason": q["reason"]} for i, q in enumerate(candidates)]}
        try:
            resp = self.llm.chat([{"role": "system", "content": SAME}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], max_tokens=300)
            d = parse_json(resp["choices"][0]["message"].get("content") or "")
        except Exception:
            return None                      # unsure and the model failed: let the item through; L5 still stands behind it
        if d.get("repeats") and isinstance(d.get("which"), int) and 0 <= d["which"] < len(candidates):
            q = candidates[d["which"]]
            return dict(q, match=f"the model judged it repeats a quarantined item from {q['source']}: {str(d.get('why', ''))[:120]}")
        return None

    def summary(self) -> list[dict]:
        return [{k: v for k, v in e.items() if k != "entities"} for e in self.items]

    def quarantined_sources(self) -> set[str]:
        return {e["source"] for e in self.items if e.get("source")}

    def filter_events(self, events: Iterable[dict]) -> list[dict]:
        """Events not from a quarantined source and not marked quarantined. Used by the trigger graph."""
        bad = self.quarantined_sources()
        return [e for e in events if not e.get("quarantined") and e.get("src", e.get("source")) not in bad]
