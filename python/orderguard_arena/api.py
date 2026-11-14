"""FastAPI router for the dashboard. Mount it with `app.include_router(orderguard_arena.api.router)`.

  GET /api/arena/run        seeded or recorded-feed run (agents <= 5,000, agents x steps <= 2.5M): summary, a downsampled event stream,
                            latency samples and per-envelope collusion markers
  GET /api/arena/feeds      recorded market-data feeds available for replay (data/arena/feeds)
  GET /api/arena/frontier   envelope frontier over a seeded or recorded-feed stream: frontier points, baseline, recommendation (advice only)
  GET /api/arena/envelopes  the default signed envelopes (metadata, limits) and, with ticker/side/quantity/limit_price, which of them fit an order
  POST /api/arena/policy/search   generate, rank and optionally simulate drafts under a signed parent
Everything is simulated and offline; nothing here signs a mandate or talks to a broker.
"""
from __future__ import annotations

import random
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .arena import ArenaConfig, run_arena
from .envelopes import default_envelopes
from .feeds import DEFAULT_SYMBOLS, FeedError, RecordedFeed, ReplayFeed
from .frontier import run_frontier
from .policy_candidates import ParentPolicyError
from .policy_review import load_parent, parent_for_review, review_policy
from .policy_search import search_policies
from .policy_sim import PolicyScenario

router = APIRouter(prefix="/api/arena", tags=["arena"])
MAX_AGENTS, MAX_STEPS, MAX_WORK, MAX_EVENTS, DEFAULT_STEPS = 5000, 2000, 2_500_000, 400, 400
FEEDS = Path(__file__).resolve().parents[2] / "data" / "arena" / "feeds"


class PolicyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    bad_allowed_usd_per_day: float | None = Field(default=None, ge=0)
    false_refusal_rate: float | None = Field(default=None, ge=0, le=1)
    holds_per_day: float | None = Field(default=None, ge=0)


class PolicyScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["demo", "configured"] = "demo"
    seed: int = Field(default=7, ge=0, lt=2**32, strict=True)
    agents: int = Field(default=150, ge=1, le=MAX_AGENTS, strict=True)
    steps: int = Field(default=400, ge=1, le=MAX_STEPS, strict=True)
    regime: Literal["normal", "volatile", "poisoned", "collusion"] = "normal"
    feed: str | None = Field(default=None, max_length=128)
    limits: PolicyLimits | None = None


class PolicyRequest(PolicyScenarioRequest):
    draft: dict
    mode: Literal["fit", "estimate", "simulate"] = "fit"


class PolicySearchRequest(PolicyScenarioRequest):
    mode: Literal["rank", "simulate"] = "simulate"


@router.get("/policy")
def policy_parent(source: Literal["demo", "configured"] = "demo") -> dict:
    """Read the signed parent limits and an editable starting draft."""
    try:
        return parent_for_review(source)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/policy")
def policy_assessment(body: PolicyRequest) -> dict:
    """Check containment and optionally estimate or simulate the draft in a paper swarm."""
    try:
        parent, key, revoked = load_parent(body.source)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    try:
        scenario = PolicyScenario(body.seed, body.agents, body.steps, body.regime)
        limits = body.limits.model_dump(exclude_none=True) if body.limits else None
        return review_policy(parent, key, revoked, body.draft, scenario, mode=body.mode,
                             feed=_recording(body.feed), limits=limits)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/policy/search")
def policy_search(body: PolicySearchRequest) -> dict:
    """Generate contained drafts and optionally compare their measured outcomes."""
    try:
        parent, key, revoked = load_parent(body.source)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    try:
        scenario = PolicyScenario(body.seed, body.agents, body.steps, body.regime)
        limits = body.limits.model_dump(exclude_none=True) if body.limits else None
        return search_policies(parent, key, revoked, scenario, mode=body.mode, feed=_recording(body.feed), limits=limits)
    except ParentPolicyError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _int_param(name: str, raw, lo: int, hi: int | None = None) -> int:
    """A whole number in [lo, hi]. Anything else is a 422 that names the field; nothing is silently corrected."""
    try:
        if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
            raise ValueError
        text = str(raw).strip()
        if not re.fullmatch(r"[+-]?\d+", text):
            raise ValueError
        v = int(text)
    except ValueError:
        raise HTTPException(422, f"{name} must be a whole number" + (f" from {lo:,} to {hi:,}" if hi is not None else f" of at least {lo:,}") + f" (got {str(raw)[:40]!r})") from None
    if v < lo or (hi is not None and v > hi):
        raise HTTPException(422, f"{name} must be " + (f"from {lo:,} to {hi:,}" if hi is not None else f"at least {lo:,}") + f" (got {v:,})")
    return v


def _clamp(agents, steps, seed=7) -> tuple[int, int]:
    """Validate the request, then apply the one documented adjustment: steps are cut so agents x steps stays within MAX_WORK (a few seconds per request)."""
    _int_param("seed", seed, 0, 2 ** 32 - 1)
    a = _int_param("agents", agents, 1, MAX_AGENTS)
    s = _int_param("steps", steps, 1, MAX_STEPS)
    return a, min(s, max(MAX_WORK // a, 1))


def _feed_path(feed: str | None) -> Path | None:
    if not feed or feed == "synthetic":
        return None
    if Path(feed).name == feed and Path(feed).suffix == ".jsonl":   # names only: no paths, no traversal
        try:
            p = (FEEDS / feed).resolve()
            if p.parent == FEEDS.resolve() and p.suffix == ".jsonl" and p.is_file():
                return p
        except (OSError, RuntimeError, ValueError):
            pass
    raise HTTPException(404, f"no recorded feed named {feed!r}; GET /api/arena/feeds lists them")


@lru_cache(maxsize=8)
def _load_recording(path: Path, _version: tuple[int, int, int, int]) -> RecordedFeed:
    return RecordedFeed(path)


def _recording(feed: str | None) -> RecordedFeed | None:
    path = _feed_path(feed)
    if path is None:
        return None
    try:
        stat = path.stat()
        return _load_recording(path, (stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
    except FileNotFoundError:
        raise HTTPException(404, f"no recorded feed named {feed!r}; GET /api/arena/feeds lists them") from None
    except OSError:
        raise HTTPException(422, f"could not read recorded feed {feed!r}") from None
    except FeedError as exc:
        raise HTTPException(422, f"invalid recorded feed {feed!r}: {exc}") from None


@lru_cache(maxsize=8)
def _run(seed: int, agents: int, steps: int, routing: str, agent_share: float | None, feed: RecordedFeed | None = None):
    if feed is None:
        return run_arena(ArenaConfig(seed=seed, agents=agents, steps=steps, steps_per_day=max(steps // 4, 1), routing=routing, agent_share=agent_share),
                         attach_receiver=False)
    return run_arena(ArenaConfig(seed=seed, agents=agents, steps=len(feed), steps_per_day=feed.steps_per_day, routing=routing, agent_share=agent_share,
                                 name=f"replay-{feed.path.stem}"), feed=feed, attach_receiver=False)


def collusion_markers(events: list[dict], envelopes: list[dict], steps_per_day: int) -> list[dict]:
    """Per envelope and simulated day: the first step at which budget committed to colluding agents (allowed or held) passed half the daily cap."""
    caps = {e["name"]: float(e.get("daily") or e.get("daily_usd") or 0) for e in envelopes}
    spent: dict[tuple[str, int], float] = {}
    out, seen = [], set()
    for e in events:
        if e.get("label") not in ("collusion", "colluding") or e.get("d") not in ("allow", "hold") or not e.get("env"):
            continue
        day = int(e.get("step", 0)) // max(steps_per_day, 1)
        k = (e["env"], day)
        spent[k] = spent.get(k, 0.0) + float(e.get("risk") or 0.0)
        cap = caps.get(e["env"]) or 0.0
        if cap and k not in seen and spent[k] >= 0.5 * cap:
            seen.add(k)
            out.append({"envelope": e["env"], "day": day, "step": e.get("step"), "colluding_usd": round(spent[k], 2), "cap_usd": cap})
    return out


def latency_samples(r, n: int = 600) -> list[float]:
    lat = getattr(r.authority, "_lat", None) or []
    if not lat:
        return []
    rng = random.Random(0)
    pick = lat if len(lat) <= n else rng.sample(lat, n)
    return sorted(round(x / 1000.0, 3) for x in pick)


def _risk(events: list[dict], envelopes: list[dict], spd: int) -> dict | None:
    """The tighten-only order-risk layer replayed over this run's decisions (python/orderguard_risk). None if the model is absent."""
    try:
        from orderguard_risk.cli import replay_events
        res = replay_events(events, envelopes, spd)
    except (FileNotFoundError, ImportError, ValueError):
        return None
    keep = ("leak_before_usd", "leak_after_usd", "bad_stopped_share", "bad_held_usd", "bad_refused_usd", "honest_allowed", "honest_held",
            "honest_refused", "honest_tightened_rate", "latency_us", "caveat", "by_label")
    return {k: res.get(k) for k in keep}


@router.get("/feeds")
def arena_feeds() -> dict:
    items = []
    for p in sorted(FEEDS.glob("*.jsonl")) if FEEDS.exists() else []:
        try:
            recording = _recording(p.name)
        except HTTPException:
            continue
        source = recording.meta.get("source")
        items.append({"name": p.name, "ticks": len(recording), "source": source if isinstance(source, str) and source else "recorded"})
    return {"feeds": items, "default_steps": DEFAULT_STEPS, "limits": {"agents": MAX_AGENTS, "steps": MAX_STEPS, "agents_x_steps": MAX_WORK}}


def downsample(events: list[dict], limit: int = MAX_EVENTS) -> list[dict]:
    """Keep every non-allow decision of a bad proposal first (they are the interesting ones), then a uniform sample of the rest."""
    keep = [e for e in events if e["label"] != "legit"]
    rest = [e for e in events if e["label"] == "legit"]
    room = max(limit - len(keep), 0)
    if len(keep) > limit:
        step = len(keep) / limit
        keep = [keep[int(i * step)] for i in range(limit)]
    if rest and room:
        step = max(len(rest) / room, 1.0)
        keep += [rest[int(i * step)] for i in range(min(room, len(rest)))]
    return sorted(keep, key=lambda e: e["i"])


@router.get("/run")
def arena_run(seed: str = "7", agents: str = "150", steps: str = str(DEFAULT_STEPS), routing: str = Query("pinned", pattern="^(pinned|tightest_fit)$"),
              agent_share: float | None = Query(None, gt=0, le=1), feed: str | None = None) -> dict:
    a, s = _clamp(agents, steps, seed)
    seed = int(seed)
    recording = _recording(feed)
    r = _run(seed, a, len(recording) if recording else s, routing, agent_share, recording)
    summ = {k: v for k, v in r.summary.items() if k != "utilisation_series"}
    spd = int((r.summary.get("config") or {}).get("steps_per_day") or max(s // 4, 1))
    return {"summary": summ, "utilisation": r.summary["utilisation_series"], "events": downsample(r.events),
            "events_total": len(r.events), "latency_us_samples": latency_samples(r),
            "collusion_markers": collusion_markers(r.events, r.summary.get("envelopes") or [], spd),
            "risk": _risk(r.events, r.summary.get("envelopes") or [], spd),
            "requested": {"agents": int(agents), "steps": int(steps)}, "ran": {"agents": a, "steps": int((r.summary.get("config") or {}).get("steps") or s), "feed": feed or "synthetic"},
            "note": "simulated agents and fills; events are downsampled (every bad proposal kept first)"}


@router.get("/frontier")
def arena_frontier(seed: str = "7", agents: str = "150", steps: str = str(DEFAULT_STEPS), samples: int = Query(40, ge=8, le=120), max_leak: float | None = None,
                   max_approvals: float | None = None, max_false_refusal: float | None = 0.05, feed: str | None = None) -> dict:
    a, s = _clamp(agents, steps, seed)
    seed = int(seed)
    recording = _recording(feed)
    r = _run(seed, a, len(recording) if recording else s, "pinned", None, recording)
    if not any(e["label"] == "legit" and not e["replay"] and e["risk"] > 0 for e in r.events):
        raise HTTPException(422, "this arena run produced no legitimate orders to evaluate in the envelope lab")
    cfg = r.summary["config"]
    meta = {"config": cfg, "envelopes": r.summary["envelopes"]}
    f = run_frontier(r.events, meta, samples=samples, max_leak_per_day=max_leak, max_approvals_per_day=max_approvals, max_false_refusal=max_false_refusal,
                     with_monotonicity=False)
    keep = ("label", "per_order", "daily", "band_pct", "breadth", "step_up", "agent_share", "utility_per_day_usd", "leaked_per_day_usd",
            "false_refusal_rate", "approvals_per_day", "utility_share", "blocked_share")
    f["candidates"] = [{k: c.get(k) for k in keep} for c in f.pop("all", None) or []]   # every candidate, so the lab can re-pick client-side
    f["ran"] = {"feed": feed or "synthetic", "agents": cfg["agents"], "steps": cfg["steps"], "steps_per_day": cfg["steps_per_day"]}
    return f


@router.get("/envelopes")
def arena_envelopes(agents: str = "150", ticker: str | None = None, side: str = "buy", quantity: int = 10, limit_price: float | None = None, price: float | None = None) -> dict:
    book = default_envelopes(DEFAULT_SYMBOLS, _int_param("agents", agents, 1, MAX_AGENTS))
    out = {"owner": "owner-1", "note": "simulated owner key; signatures are verified once when the envelope is loaded",
           "envelopes": [{"id": e.id, "name": e.name, "purpose": e.purpose, "symbols": sorted(e.allowed), "per_order_usd": e.max_order, "daily_usd": e.budget.cap,
                          "band_pct": e.m.priceBandPct, "step_up_usd": e.stepup, "signed": bool(e.m.signature)} for e in book.envelopes()]}
    if ticker:
        px = price if price is not None else ReplayFeed(7, steps=1).trusted_first().get(ticker.upper())
        order = {"ticker": ticker, "side": side, "quantity": quantity, "limit_price": limit_price if limit_price is not None else px}
        fits = book.fit(order, px)
        t = book.tightest_fit(order, px)
        out["fit"] = {"order": order, "trusted_price": px, "authorizing": [e.name for e in fits], "tightest": t.name if t else None}
    return out
