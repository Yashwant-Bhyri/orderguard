"""Policy packs: unsigned Mandate templates a person can list, read and sign with their own key.

A template is the Mandate JSON shape with `ttlHours` in place of `expiresAt` (resolved when it is signed) and an `_about` note. Signing
runs the same `Mandate.validate` the gate uses, plus `Mandate.check_coherent`, so a template whose per-order cap exceeds its daily cap (and
the like) is refused. Nothing here widens a mandate; `--symbols` only replaces the allow-list.

Templates live in `policies/` at the repo root and, in an installed wheel, in `orderguard_guard/policies/` (see pyproject force-include).
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from . import gate as G

TEMPLATE_ONLY = {"_about", "ttlHours"}


def packs_dir() -> Path:
    here = Path(__file__).resolve().parent
    for d in (here / "policies", here.parents[1] / "policies"):
        if d.is_dir() and any(d.glob("*.json")):
            return d
    raise G.MandateInvalid("the policy templates were not found; reinstall orderguard or run from a source checkout")


def names() -> list[str]:
    return sorted(p.stem for p in packs_dir().glob("*.json"))


def load(name: str) -> dict:
    if not isinstance(name, str) or not name.replace("-", "").isalnum():
        raise G.MandateInvalid(f"{name!r} is not a policy name; run `orderguard policy list`")
    path = packs_dir() / f"{name}.json"
    if not path.is_file():
        raise G.MandateInvalid(f"there is no policy named {name!r}; run `orderguard policy list` (available: {', '.join(names())})")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise G.MandateInvalid(f"the policy template {name!r} is not a JSON object")
    return data


def build_mandate(name: str, symbols: list[str] | None = None, now: dt.datetime | None = None) -> G.Mandate:
    """Resolve a template into an unsigned, validated Mandate expiring `ttlHours` after `now`."""
    t = load(name)
    unknown = set(t) - set(G.Mandate.__dataclass_fields__) - TEMPLATE_ONLY
    if unknown:
        raise G.MandateInvalid(f"the template {name!r} has unsupported fields: {', '.join(sorted(unknown))}")
    ttl = t.get("ttlHours")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0 < ttl <= 24 * 366:
        raise G.MandateInvalid(f"the template {name!r} needs ttlHours, a positive number of hours up to one year")
    if "expiresAt" in t or "signature" in t or "signerPublicKey" in t:
        raise G.MandateInvalid(f"the template {name!r} must be unsigned and use ttlHours, not expiresAt")
    body = {k: v for k, v in t.items() if k not in TEMPLATE_ONLY}
    if symbols:
        norm = []
        for raw in symbols:
            s, problem = G.normalise_ticker(raw)
            if problem:
                raise G.MandateInvalid(problem)
            if s not in norm:
                norm.append(s)
        body["symbols"] = norm
    now = now or dt.datetime.now(dt.timezone.utc)
    body["expiresAt"] = (now + dt.timedelta(hours=ttl)).replace(microsecond=0).astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    m = G.Mandate.from_dict(body)
    m.check_coherent()
    return m


def summary(name: str) -> str:
    t = load(name)
    return f"{name:24} ttl {t.get('ttlHours')}h  per-order ${t['maxOrderNotionalUsd']:,.0f}  daily ${t['maxDailyNotionalUsd']:,.0f}  " \
           f"band {t['priceBandPct']:g}%  symbols {len(t['symbols'])}"
