"""Claim extractor. The only job of the LLM here is to READ the text and list what it asserts.

It never judges whether a claim is true. Code checks the output afterwards: every claim must quote the text, and the
pack normalises each claim (the finance pack, for example, forces facts about the traded company to be key)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from .llm import LLMCall, ask_json
from .models import Claim
from .pack import Pack


@dataclass
class Extraction:
    claims: list[Claim]
    dropped: list[dict]       # model output we refused, with the reason
    call: LLMCall


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def extract(text: str, proposal: Any, pack: Pack, ask: Callable = ask_json) -> Extraction:
    system, user = pack.extraction_prompt(text, proposal)
    data, call = ask(system, user)
    claims: list[Claim] = []
    dropped: list[dict] = []
    text_n = _norm(text)
    for i, raw in enumerate(data.get("claims", []), start=1):
        try:
            c = pack.claim_from_raw(raw, i, proposal)
        except (ValidationError, TypeError, ValueError) as e:
            dropped.append({"raw": raw, "why": f"invalid claim: {str(e)[:120]}"})
            continue
        if _norm(c.text) not in text_n:
            dropped.append({"raw": raw, "why": "quote not found in text"})
            continue
        claims.append(c)
    return Extraction(claims, dropped, call)
