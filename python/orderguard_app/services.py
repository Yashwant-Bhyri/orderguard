"""The logic behind the endpoints. Everything here reuses the guard, lab and verify packages; nothing re-implements a layer."""
from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Any, Callable

from orderguard_guard import gate as G
from orderguard_guard import graph as GR
from orderguard_guard import llm as LLM_MOD
from orderguard_guard import normalise
from orderguard_guard.market import SimMarket
from orderguard_guard.screen import Screen

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv("OG_MODEL") or "deepseek/deepseek-v4.1-flash"
DEMO_SCENARIOS = {
    "demo-1": "Honest trade (full arm)",
    "demo-2": "Fake 10-for-1 split in the feed (gate_only: L5 alone)",
    "demo-3": "Fake filing figures on a look-alike page (gate_only: L6 alone)",
    "demo-4": "Injected transfer instruction in a web page (full arm)",
}


class AppError(Exception):
    """An error whose message is safe to show a client."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# ---- state ---------------------------------------------------------------------------------------------------------

class State:
    """Process state: an in-memory signing key (never persisted or returned), the signed demo mandate and a screen cache."""

    def __init__(self):
        priv, pub = G.generate_keypair()
        self._priv = priv
        self.public_key = G.public_key_to_b64(pub)
        self.pub = pub
        self.mandate = G.sign_mandate({"symbols": ["AAPL", "MSFT"], "sides": ["buy"], "maxOrderNotionalUsd": 10000, "maxDailyNotionalUsd": 20000,
                                       "priceBandPct": 5, "stepUpAboveUsd": 9500, "expiresAt": "2099-01-01T00:00:00Z",
                                       "referencePrices": {"AAPL": 222.70, "MSFT": 420.18}}, priv)
        self._screen: Screen | None = None
        self._scripted: dict[str, dict] | None = None

    def sign(self, mandate: dict) -> dict:
        return G.sign_mandate(mandate, self._priv)

    def screen(self) -> Screen:
        if self._screen is None:
            self._screen = Screen(DEFAULT_MODEL)
        return self._screen


def demo_prices() -> dict:
    from orderguard_lab.envs import TRUSTED_PRICES
    return dict(TRUSTED_PRICES)


# ---- health --------------------------------------------------------------------------------------------------------

def _version(pkg: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(pkg)
    except Exception:
        return None


def classifier_module():
    try:
        return importlib.import_module("orderguard_guard.classifier")
    except ImportError:
        return None


def health() -> dict:
    from . import __version__
    import sys
    spend = LLM_MOD.SPEND
    return {
        "status": "ok",
        "versions": {"app": __version__, "orderguard": _version("orderguard"), "fastapi": _version("fastapi"), "python": sys.version.split()[0]},
        "provider": LLM_MOD.provider(),
        "key_configured": LLM_MOD.api_key() is not None,       # a bool only: the key itself is never read into a response
        "llm_mode": LLM_MOD.default_mode(),
        "budget": {"budget_usd": spend.budget_usd, "spent_usd": round(spend.spent_usd, 6), "calls": spend.calls},
        "model": DEFAULT_MODEL,
        "classifier_available": classifier_module() is not None,
        "receiver_configured": bool(os.getenv("ORDERGUARD_RECEIVER_URL")),
        "auth_required": bool(os.getenv("ORDERGUARD_APP_TOKEN")),
    }


# ---- L1 + L2 -------------------------------------------------------------------------------------------------------

def screen_text(state: State, text: str, kind: str) -> dict:
    cleaned, findings = normalise.clean(text)
    severe = normalise.severe(findings)
    out: dict[str, Any] = {"l1": {"changed": cleaned != text, "findings": findings, "severe": severe, "clean_text": cleaned[:2000]}}
    mode = LLM_MOD.default_mode()
    if mode != "replay" and LLM_MOD.api_key() is None:
        out["l2"] = {"status": "unavailable", "reason": f"no API key is configured and OG_LLM={mode}; set OG_LLM=replay to use recordings only"}
    else:
        v = state.screen().check(cleaned, kind)
        if v.get("category") == "error":
            why = "no recorded response for this text (OG_LLM=replay)" if mode == "replay" else "the screen model could not be reached or the budget is spent"
            out["l2"] = {"status": "unavailable", "reason": why}
        else:
            out["l2"] = {"status": "ok", **{k: v[k] for k in ("flag", "category", "why", "cached") if k in v}}
    out["classifier"] = _classify(cleaned)
    l2 = out["l2"]
    if severe or (l2["status"] == "ok" and l2["flag"]):
        out["verdict"] = "quarantine"
    elif l2["status"] == "ok":
        out["verdict"] = "clean"
    else:
        out["verdict"] = "unknown"
    return out


def _classify(text: str) -> dict | None:
    mod = classifier_module()
    if mod is None or not hasattr(mod, "score"):
        return None
    try:
        r = mod.score(text)
        return {"status": "ok", "p_attack": float(r["p_attack"]), "label": str(r["label"])}
    except Exception as e:
        return {"status": "error", "reason": type(e).__name__}


# ---- L5 + L6 -------------------------------------------------------------------------------------------------------

def check_order(state: State, order: dict, upload, prices: dict | None, as_of: str, daily_total: float, require_figures: bool) -> dict:
    pub = None
    if upload is None:
        mandate, source, pub = dict(state.mandate), "demo", state.pub
    else:
        mandate, source = dict(upload.mandate), "uploaded"
        if upload.public_key:
            try:
                pub = G.public_key_from_b64(upload.public_key)
            except Exception:
                raise AppError(422, "public_key is not a valid base64 Ed25519 public key") from None
    try:
        m = G.Mandate.from_dict(mandate)
    except (TypeError, ValueError):
        raise AppError(422, "the mandate is missing required fields (symbols, sides, maxOrderNotionalUsd, maxDailyNotionalUsd, priceBandPct, expiresAt)") from None
    if not m.signature and source == "uploaded":
        pub = None
    market = SimMarket({k: v for k, v in (prices or demo_prices()).items()}, as_of=f"{as_of}T15:05:00Z")
    gate = G.OrderGate(m, market, G.default_figure_checker(), public_key=pub, require_figures=require_figures)
    try:
        res = gate.evaluate(order, {"daily_total_usd": daily_total, "as_of": as_of})
    except Exception as e:                                           # fail closed, without a stack trace
        return {"decision": "refuse", "reasons": [f"The order could not be evaluated ({type(e).__name__}), so it is refused."], "checks": {},
                "mandate": _mandate_info(m, source, pub), "prices": market.prices, "as_of": as_of}
    return {**res, "mandate": _mandate_info(m, source, pub), "prices": market.prices, "as_of": as_of}


def _mandate_info(m: G.Mandate, source: str, pub) -> dict:
    d = m.to_dict()
    return {"source": source, "id": m.id, "signed": bool(m.signature), "signature_checked": pub is not None,
            "signature_checked_against": ("demo key" if source == "demo" else "supplied public key") if pub is not None else None,
            "mandate": d}


# ---- L7 ------------------------------------------------------------------------------------------------------------

def build_rule(spec: dict) -> GR.Rule:
    try:
        rid, kind = str(spec["id"]), spec["kind"]
        inputs = [str(i) for i in spec["inputs"]]
        side, notional, threshold = str(spec["side"]).lower(), float(spec["notional"]), float(spec["threshold"])
    except (KeyError, TypeError, ValueError):
        raise AppError(422, "each rule needs id, kind (pct_change or event), inputs, threshold, notional and side") from None
    if not inputs or side not in ("buy", "sell"):
        raise AppError(422, "a rule needs at least one input and side buy or sell")
    text = str(spec.get("text") or rid)
    tickers = [str(t) for t in spec.get("tickers") or []]
    if kind == "pct_change":
        if threshold < 0:
            fires: Callable[[dict], bool] = lambda v: sum(v[i] for i in inputs) / len(inputs) <= threshold
        else:
            fires = lambda v: sum(v[i] for i in inputs) / len(inputs) >= threshold
        return GR.Rule(rid, text, inputs, fires, notional, side, tickers=tickers)
    if kind == "event":
        needle = str(spec.get("match") or "").lower()
        if not needle:
            raise AppError(422, "an event rule needs a non-empty match string")
        matchers = {i: (lambda e, n=needle: e.get("type") in ("headline", "notice") and n in str(e.get("text", "")).lower()) for i in inputs}
        return GR.Rule(rid, text, inputs, lambda v: all(v[i] >= max(threshold, 1e-9) for i in inputs), notional, side, matchers=matchers, tickers=tickers)
    raise AppError(422, "kind must be pct_change or event")


PRESETS = {"honest": GR.honest_events, "single_venue_crash": GR.single_venue_crash_events, "real_crash": GR.real_crash_events,
           "takeover_echo": GR.takeover_echo_events}


def trigger_graph(rules, events, preset, quarantined_sources, blast_source, lies) -> dict:
    rule_objs = [build_rule(r) for r in rules] if rules else GR.standing_rules()
    if events is None:
        events = PRESETS[preset or "single_venue_crash"]()
    events = GR.graph_events(list(events))
    g = GR.TriggerGraph(rule_objs, min_sources=2)
    try:
        guarded = g.evaluate(events, quarantined_sources=set(quarantined_sources))
        naive = GR.TriggerGraph.naive(rule_objs, events)
        blast = g.blast_radius(blast_source or "VenueC", lies)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        raise AppError(422, "the events do not fit the rules (for example a rule input has no matching event shape)") from None
    return {
        "rules": [{"id": r.id, "text": r.text, "inputs": r.inputs, "side": r.side, "notional": r.notional} for r in rule_objs],
        "guarded": [{k: r[k] for k in ("rule", "fires", "held_reason", "notional", "side", "values")} for r in guarded],
        "naive": naive,
        "blast_radius": [{k: b[k] for k in ("source", "lie_pct", "naive_fires", "naive_notional", "guarded_fires", "guarded_notional")} for b in blast],
        "naive_notional": sum(x["notional"] for x in naive), "guarded_notional": sum(x["notional"] for x in guarded),
    }


# ---- scenarios -----------------------------------------------------------------------------------------------------

def list_scenarios() -> list[dict]:
    from orderguard_lab import cases as C
    out = [{"id": k, "kind": "scripted demo", "title": v, "arms": [], "offline": True} for k, v in DEMO_SCENARIOS.items()]
    out += [{"id": c.id, "kind": "lab case", "title": f"{c.family} / {c.surface}: {c.technique}", "goal": c.goal,
             "arms": ["naive", "gate_only", "full"], "offline": "replay"} for c in C.all_cases()]
    return out


def _scripted_demo(state: State) -> list[dict]:
    if state._scripted is None:
        from orderguard_guard import cli
        from orderguard_guard.receiver_client import LocalLedger
        from orderguard_lab import envs as E
        mandate = state.sign({**E.default_mandate(), "expiresAt": "2099-01-01T00:00:00Z"})
        state._scripted = cli.demo_scenarios(cli.scripted_llm_factory(), LocalLedger(), mandate, out=lambda *a, **k: None)
    return state._scripted


def run_scenario(state: State, scenario: str, arm: str | None) -> dict:
    from orderguard_lab import runner as R
    from orderguard_guard import cli
    if scenario in DEMO_SCENARIOS:
        res = _scripted_demo(state)[int(scenario[-1]) - 1]
        tr = res["transcript"]
        if arm and arm != tr.get("arm"):
            raise AppError(422, f"the arm of {scenario} is fixed ({tr.get('arm')}); pick a lab case to compare arms")
        compact, judged, layers = R.compact(tr), {}, res["layers"]
        meta = {"agent": "scripted stand-in (no model is called)", "arm": tr.get("arm")}
    else:
        from orderguard_lab import cases as C
        try:
            case = C.get(scenario)
        except KeyError:
            raise AppError(404, "unknown scenario; GET /api/scenarios lists them") from None
        arm = arm or "full"
        rec = R.run_case(case, DEFAULT_MODEL, arm, mode="live")      # the LLM client honours OG_LLM: replay serves recordings only
        compact = rec["transcript"]
        judged = {k: rec.get(k) for k in ("attempted", "executed", "belief", "utility", "success", "harm_usd", "stopped_by") if k in rec}
        layers = cli._layers(compact)
        meta = {"agent": f"{DEFAULT_MODEL} (OG_LLM={LLM_MOD.default_mode()})", "arm": arm, "task": case.user_task()[:600], "expected_stop": case.expected_stop}
    err = compact.get("error")
    return {"scenario": scenario, "ok": not err, **meta, "layers": layers, "judged": judged, "error": _client_error(err),
            "replay_miss": bool(err and "ReplayMiss" in err), "timeline": timeline(compact), "final": compact.get("final", ""),
            "quarantined": compact.get("quarantined", [])}


def _client_error(err: str | None) -> str | None:
    if not err:
        return None
    if "ReplayMiss" in err:
        return "no recording exists for this scenario and arm in replay mode; the trace stops where the recordings end"
    return err.split(":", 1)[0] + ": the run stopped early"


def timeline(tr: dict) -> list[dict]:
    """One entry per tool call in order, with the layer decisions that touched it; quarantines attach to the first call of their tool."""
    qs = list(tr.get("quarantined", []))
    seen_tools: set[str] = set()
    steps = []
    for i, c in enumerate(tr.get("calls", []), 1):
        name = c.get("name")
        attach = []
        if name not in seen_tools:
            attach = [q for q in qs if q.get("tool") == name]
            seen_tools.add(name)
        g = c.get("gate")
        steps.append({"step": i, "tool": name, "args": c.get("args"), "result": c.get("result"), "quarantined": attach,
                      "gate": g and {"decision": g.get("decision"), "layer": g.get("layer") or "L5/L6", "reasons": g.get("reasons"),
                                     "figures": (g.get("checks") or {}).get("figures")}})
    placed = {id(q) for s in steps for q in s["quarantined"]}
    rest = [q for q in qs if id(q) not in placed]
    if rest:
        steps.append({"step": len(steps) + 1, "tool": None, "args": None, "result": None, "quarantined": rest, "gate": None})
    return steps


# ---- ledger and results --------------------------------------------------------------------------------------------

def ledger() -> dict:
    url = os.getenv("ORDERGUARD_RECEIVER_URL")
    if not url:
        return {"connected": False, "message": "receiver not connected: set ORDERGUARD_RECEIVER_URL to the L8 receiver bridge"}
    from orderguard_guard.receiver_client import Receiver, ReceiverError
    rc = Receiver(url, timeout=5.0)
    try:
        return {"connected": True, "snapshot": rc.snapshot()}
    except ReceiverError as e:
        raise AppError(502, str(e)) from None
    finally:
        rc.close()


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_results(text: str) -> list[dict]:
    sections: list[dict] = [{"level": 1, "title": "(top)", "text": [], "tables": []}]
    lines, i = text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            sections.append({"level": len(m.group(1)), "title": m.group(2).strip(), "text": [], "tables": []})
        elif line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?\s*$", lines[i + 1]):
            head, rows, i = _split_row(line), [], i + 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            sections[-1]["tables"].append({"headers": head, "rows": rows})
            continue
        elif line.strip():
            sections[-1]["text"].append(line.strip())
        i += 1
    return [s for s in sections if s["tables"] or s["text"] or s["title"] != "(top)"]


def results() -> dict:
    p = ROOT / "docs" / "RESULTS.md"
    if not p.exists():
        raise AppError(404, "no results are available: docs/RESULTS.md does not exist")
    runs = ROOT / "results" / "runs"
    return {"source": "docs/RESULTS.md", "sections": parse_results(p.read_text(encoding="utf-8")),
            "run_files": len(list(runs.glob("*.jsonl"))) if runs.exists() else 0}
