"""The logic behind the endpoints. Everything here reuses the guard, lab and verify packages; nothing re-implements a layer."""
from __future__ import annotations

import importlib
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from orderguard_guard import gate as G
from orderguard_guard import graph as GR
from orderguard_guard import llm as LLM_MOD
from orderguard_guard import normalise
from orderguard_guard.market import SimMarket
from orderguard_guard.screen import Screen

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv("OG_MODEL") or "deepseek/deepseek-v4.1-flash-1017"
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


# ---- overview ------------------------------------------------------------------------------------------------------

def _mandate_summary(m: dict, verdict: dict) -> dict:
    keys = ("symbols", "sides", "maxOrderNotionalUsd", "maxDailyNotionalUsd", "priceBandPct", "stepUpAboveUsd", "expiresAt")
    return {**{k: m.get(k) for k in keys}, **verdict}


def configured_mandate() -> dict:
    """Summary of mandate.json in the config directory (ORDERGUARD_HOME), with its signature checked against signing.pub.
    Never reads signing.key and never returns a path outside the configured directory name."""
    from orderguard_guard import init_cmd
    d = init_cmd.default_dir()
    mp, pp = d / init_cmd.MANDATE_FILE, d / init_cmd.PUB_FILE
    if not mp.exists():
        return {"present": False, "hint": "run `orderguard init` to create a signed mandate"}
    try:
        m = G.Mandate.load(mp)
    except Exception:
        return {"present": True, "valid": False, "problem": "mandate.json could not be read as a mandate"}
    verdict: dict[str, Any] = {"present": True, "id": m.id, "signed": bool(m.signature)}
    if not pp.exists():
        return {**_mandate_summary(m.to_dict(), verdict), "valid": False, "problem": "signing.pub is missing, so the signature cannot be checked"}
    try:
        m.verify(G.public_key_from_b64(pp.read_text().strip()))
        verdict.update(valid=True, problem=None)
    except G.MandateInvalid as e:
        verdict.update(valid=False, problem=str(e))
    except Exception:
        verdict.update(valid=False, problem="the mandate could not be verified")
    return _mandate_summary(m.to_dict(), verdict)


def overview(state: State) -> dict:
    mode, key = LLM_MOD.default_mode(), LLM_MOD.api_key() is not None
    receiver = bool(os.getenv("ORDERGUARD_RECEIVER_URL"))
    clf = classifier_module() is not None
    if mode == "replay":
        l2 = ("configured", "replay mode: recorded verdicts only, no model call")
    elif key:
        l2 = ("configured", f"live screen model, budget US${LLM_MOD.SPEND.budget_usd}")
    else:
        l2 = ("off", f"no API key for provider {LLM_MOD.provider()}; chunks that need the model screen come back unavailable")
    layers = [
        ("L1", "Normalise", "available", "Strips hidden characters and flags look-alike tickers in code."),
        ("L2", "Model screen", *l2),
        ("L3", "Risk bucket", "available", "Quarantines repeats of a quarantined claim (agent loop)."),
        ("L4", "Data marking", "available", "Wraps tool output in data tags (agent loop)."),
        ("L5", "Order gate", "available", "Signed mandate, trusted price, caps, band, step-up."),
        ("L6", "Figure check", "available", "Cited figures checked against SEC filings (local truth store)."),
        ("L7", "Trigger graph", "available", "Standing rules need two independent sources."),
        ("L8", "Receiver", "configured" if receiver else "off",
         "Final authority and ledger." if receiver else "Not connected: orders use the in-process local ledger. Set ORDERGUARD_RECEIVER_URL."),
    ]
    return {
        "layers": [{"id": i, "name": n, "status": s, "detail": d} for i, n, s, d in layers],
        "classifier": {"status": "available" if clf else "off", "detail": "Local attack classifier alongside L2." if clf else "Not installed."},
        "demo_mandate": _mandate_summary(state.mandate, {"present": True, "signed": True, "valid": True, "problem": None, "id": state.mandate.get("id")}),
        "configured_mandate": configured_mandate(),
        "receiver": {"configured": receiver},
        "model": {"provider": LLM_MOD.provider(), "model": DEFAULT_MODEL, "mode": mode, "key_configured": key,
                  "budget_usd": LLM_MOD.SPEND.budget_usd, "spent_usd": round(LLM_MOD.SPEND.spent_usd, 6)},
    }


# ---- L1 + L2 -------------------------------------------------------------------------------------------------------

def screen_text(state: State, text: str, kind: str) -> dict:
    cleaned, findings = normalise.clean(text)
    severe = normalise.severe(findings)
    out: dict[str, Any] = {"l1": {"changed": cleaned != text, "findings": findings, "severe": severe, "clean_text": cleaned[:2000]}}
    t0 = time.perf_counter()
    out["reveal"] = reveal(text)
    out["l1"]["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    mode = LLM_MOD.default_mode()
    if mode != "replay" and LLM_MOD.api_key() is None:
        out["l2"] = {"status": "unavailable", "reason": f"no API key is configured and OG_LLM={mode}; set OG_LLM=replay to use recordings only"}
    else:
        scr = state.screen()
        t0 = time.perf_counter()
        v = scr.check(cleaned, kind)
        took = round((time.perf_counter() - t0) * 1000, 1)
        if v.get("category") == "error":
            why = "no recorded response for this text (OG_LLM=replay)" if mode == "replay" else "the screen model could not be reached or the budget is spent"
            out["l2"] = {"status": "unavailable", "reason": why}
        else:
            out["l2"] = {"status": "ok", **{k: v[k] for k in ("flag", "category", "why", "cached") if k in v}}
            if not v.get("cached"):
                out["l2"]["latency_ms"] = took          # a replayed or cached answer has no meaningful latency
    out["fast"] = _fast_screen(state, cleaned, kind)
    out["classifier"] = _classify(cleaned)
    l2 = out["l2"]
    if severe or (l2["status"] == "ok" and l2["flag"]):
        out["verdict"] = "quarantine"
    elif l2["status"] == "ok":
        out["verdict"] = "clean"
    else:
        out["verdict"] = "unknown"
    out["decided_by"] = "L1" if severe else "L2" if l2["status"] == "ok" else None
    return out


def _fast_screen(state: State, text: str, kind: str) -> dict:
    """The optional fast-model stage of the cascade. Reported as off unless the screen was built with one."""
    fast = getattr(state._screen, "_fast", None)
    if fast is None:
        return {"status": "off", "reason": "no fast model is configured (set OG_SCREEN_FAST_MODEL and OG_SCREEN_CASCADE to add one)"}
    try:
        t0 = time.perf_counter()
        v = fast.check(text, kind)
        if v.get("category") == "error":
            return {"status": "unavailable", "reason": "the fast model could not be reached or has no recording for this text"}
        return {"status": "ok", "model": getattr(fast, "model_name", None), "flag": bool(v.get("flag")), "category": v.get("category"),
                "why": v.get("why"), "latency_ms": None if v.get("cached") else round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"status": "error", "reason": type(e).__name__}


def _classify(text: str) -> dict | None:
    """Wraps orderguard_guard.classifier.score. Tolerates missing or extra fields; adds the threshold, latency and character offsets
    of the top features so the page can highlight them."""
    mod = classifier_module()
    if mod is None or not hasattr(mod, "score"):
        return None
    try:
        t0 = time.perf_counter()
        r = mod.score(text)
        took = round((time.perf_counter() - t0) * 1000, 2)
        out: dict[str, Any] = {"status": "ok", "p_attack": float(r["p_attack"]), "label": str(r["label"]),
               "latency_ms": float(r["latency_ms"]) if isinstance(r.get("latency_ms"), (int, float)) else took}
        thr = r.get("threshold")
        if thr is None:
            try:
                thr = mod.get().threshold
            except Exception:
                thr = None
        out["threshold"] = float(thr) if isinstance(thr, (int, float)) else 0.5
        feats = []
        for f in (r.get("top_features") or [])[:8]:
            if not isinstance(f, dict) or "feature" not in f:
                continue
            name = str(f["feature"])
            w = f.get("weight")
            feats.append({"feature": name, "weight": float(w) if isinstance(w, (int, float)) else None, "spans": _spans(text, name)})
        out["top_features"] = feats
        if isinstance(r.get("line"), str):
            out["line"] = r["line"][:200]
        return out
    except Exception as e:
        return {"status": "error", "reason": type(e).__name__}


def _spans(text: str, feature: str, limit: int = 3) -> list[list[int]]:
    """Where a feature shows up in the text, as [start, end) offsets. Character n-gram features carry a leading ~; features are lower-cased."""
    needle = feature[1:] if feature.startswith("~") else feature
    needle = needle.strip().lower()
    if len(needle) < 2 or len(text) > 20000:
        return []
    hay, out, i = text.lower(), [], 0
    if len(hay) != len(text):
        return []                                  # lower-casing changed the length; offsets would drift
    while len(out) < limit:
        i = hay.find(needle, i)
        if i < 0:
            break
        out.append([i, i + len(needle)])
        i += len(needle)
    return out


# ---- revealed text (what L1 sees) ----------------------------------------------------------------------------------

_SHORT = {"ZERO WIDTH SPACE": "ZWSP", "ZERO WIDTH NON-JOINER": "ZWNJ", "ZERO WIDTH JOINER": "ZWJ", "WORD JOINER": "WJ",
          "ZERO WIDTH NO-BREAK SPACE": "BOM", "SOFT HYPHEN": "SHY", "LEFT-TO-RIGHT MARK": "LRM", "RIGHT-TO-LEFT MARK": "RLM",
          "MONGOLIAN VOWEL SEPARATOR": "MVS", "ARABIC LETTER MARK": "ALM"}
REVEAL_MAX = 20000


def reveal(text: str) -> dict:
    """The input as an ordered list of segments so a page can draw what L1 found, without re-implementing L1.
    Segment kinds: text, hidden (tag or zero-width run), mixed (mixed-script token with its folded spelling), b64 (long run with decoded payload)."""
    truncated = len(text) > REVEAL_MAX
    text = text[:REVEAL_MAX]
    vis, vmap = [], []                                   # visible characters and their index in the original
    hidden_at: dict[int, tuple[str, str, str]] = {}   # index -> (chip label, long name, decoded character)
    for i, ch in enumerate(text):
        cp = ord(ch)
        if normalise.TAG_LO <= cp <= normalise.TAG_HI:
            hidden_at[i] = ("TAG", "Unicode tag character", chr(cp - normalise.TAG_LO) if 0x20 <= cp - normalise.TAG_LO < 0x7F else "")
        elif ch in normalise.ZERO_WIDTH:
            name = normalise.ZERO_WIDTH[ch]
            hidden_at[i] = (_SHORT.get(name) or ("VS" if name.startswith("VARIATION") else name if len(name) <= 6 else f"U+{cp:04X}"), name, "")
        else:
            vis.append(ch)
            vmap.append(i)
    vtext = "".join(vis)
    marks: list[tuple[int, int, dict]] = []              # (start, end) in original indexes
    for tok, scripts in normalise.mixed_script_tokens(vtext):
        for m in re.finditer(re.escape(tok), vtext):
            marks.append((vmap[m.start()], vmap[m.end() - 1] + 1, {"kind": "mixed", "text": tok, "scripts": scripts, "folded": normalise.fold_confusables(tok)}))
    for m in normalise._B64.finditer(vtext):
        dec = normalise._decode_b64(m.group(0))
        if dec is not None:
            marks.append((vmap[m.start()], vmap[m.end() - 1] + 1, {"kind": "b64", "text": m.group(0)[:200], "chars": len(m.group(0)), "decoded": dec[:400]}))
    marks.sort(key=lambda x: x[0])
    segs: list[dict] = []
    buf: list[str] = []

    def flush():
        if buf:
            segs.append({"kind": "text", "text": "".join(buf)})
            buf.clear()

    def emit_hidden(a: int, b: int):
        j = a
        while j < b:
            if j not in hidden_at:
                buf.append(text[j])
                j += 1
                continue
            label = hidden_at[j][0]
            k = j
            while k < b and k in hidden_at and hidden_at[k][0] == label:
                k += 1
            flush()
            seg = {"kind": "hidden", "label": label, "count": k - j, "name": hidden_at[j][1]}
            if label == "TAG":
                seg["decoded"] = "".join(hidden_at[x][2] for x in range(j, k))[:400]
            segs.append(seg)
            j = k

    pos = 0
    for a, b, seg in marks:
        if a < pos or any(x in hidden_at for x in range(a, b)):
            continue                                     # overlapping marks, or a hidden character inside the span: show those as plain text and chips
        emit_hidden(pos, a)
        flush()
        segs.append(seg)
        pos = b
    emit_hidden(pos, len(text))
    flush()
    return {"segments": segs, "truncated": truncated, "hidden_count": len(hidden_at)}


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
    except (G.MandateInvalid, TypeError, ValueError):
        raise AppError(422, "the mandate is missing required fields (symbols, sides, maxOrderNotionalUsd, maxDailyNotionalUsd, priceBandPct, expiresAt)") from None
    if not m.signature and source == "uploaded":
        pub = None
    market = SimMarket({k: v for k, v in (prices or demo_prices()).items()}, as_of=f"{as_of}T15:05:00Z")
    checker = _Recording(G.default_figure_checker())
    gate = G.OrderGate(m, market, checker, public_key=pub, require_figures=require_figures)
    try:
        res = gate.evaluate(order, {"daily_total_usd": daily_total, "as_of": as_of})
    except Exception as e:                                           # fail closed, without a stack trace
        res = {"decision": "refuse", "reasons": [f"The order could not be evaluated ({type(e).__name__}), so it is refused."], "checks": {}}
        return {**res, **_order_extras(res, order, m, daily_total, checker), "mandate": _mandate_info(m, source, pub), "prices": market.prices, "as_of": as_of}
    return {**res, **_order_extras(res, order, m, daily_total, checker), "mandate": _mandate_info(m, source, pub), "prices": market.prices, "as_of": as_of}


class _Recording:
    """Wraps the figure checker to keep its raw rows (source form and filed date, reason) which the gate does not copy into `checks`."""

    def __init__(self, inner):
        self.inner, self.rows = inner, []

    def __call__(self, ticker, as_of, figures):
        rows = self.inner(ticker, as_of, figures)
        self.rows = list(rows or [])
        return rows


def _figure_rows(checker: _Recording) -> list[dict]:
    out = []
    for r in checker.rows:
        if not isinstance(r, dict):
            continue
        src = r.get("source")
        src = {k: str(v) for k, v in src.items() if k in ("form", "filed", "accession")} if isinstance(src, dict) else (str(src) if src else None)
        out.append({"figure": r.get("figure"), "status": r.get("status"), "truth": r.get("truth"), "unit": r.get("unit"),
                    "reason": str(r.get("reason") or "")[:300] or None, "source": src})
    return out


def _reason_layer(text: str) -> str:
    """L6 owns the sentences about cited figures; every other gate sentence is L5."""
    return "L6" if text.startswith(("The cited figure", "The order cites no reported")) else "L5"


def _is_hold(text: str) -> bool:
    """The gate's holds (a human must approve; a figure could not be verified) versus its refusals."""
    return "step-up threshold" in text or ("could not be verified" in text and "cited figure" in text) or "no figure checker is configured" in text


def layer_verdicts(reasons: list[str]) -> dict[str, str]:
    """{layer: 'refuse' | 'hold'} for the layers that spoke. A layer that only held says hold even when another layer refused."""
    out: dict[str, str] = {}
    for r in reasons:
        lid = _reason_layer(r)
        out[lid] = "hold" if _is_hold(r) and out.get(lid) != "refuse" else "refuse" if not _is_hold(r) else out[lid]
    return out


def layer_path(decision: str, reasons: list[str], checks: dict, *, figures_checked: bool | None = None) -> list[dict]:
    """The eight stations for one order check: which layers passed, which acted (and with what verdict), which were never reached.
    Station: {id, state: idle|passed|acted|not_reached, verdict?, note}."""
    spoke = layer_verdicts(reasons)
    early = checks.get("mandate") == "invalid" or checks.get("kind") == "money_movement" or not checks
    if early:
        spoke.pop("L6", None)
    cited = bool(checks.get("figures")) if figures_checked is None else figures_checked
    out = []
    for i in range(1, 9):
        lid = f"L{i}"
        if lid in ("L5", "L6"):
            if lid in spoke:
                st = {"id": lid, "state": "acted", "verdict": spoke[lid], "note": "held the order for a human" if spoke[lid] == "hold" else "refused the order"}
            elif lid == "L6" and early and decision != "allow":
                st = {"id": lid, "state": "not_reached", "note": "the order was stopped before the figures were checked"}
            elif lid == "L6" and not cited:
                st = {"id": lid, "state": "idle", "note": "no figures were cited, so there was nothing to check"}
            else:
                st = {"id": lid, "state": "passed", "note": "every check passed"}
        elif i < 5:
            st = {"id": lid, "state": "idle", "note": "reads untrusted text; not part of an order check"}
        else:
            st = {"id": lid, "state": "idle", "note": "not exercised by an order check"}
        out.append(st)
    if decision != "allow":
        for st in out[6:]:
            st.update(state="not_reached", note="the order does not get this far")
    return out


def _order_extras(res: dict, order: dict, m: G.Mandate, daily_total: float, checker: _Recording) -> dict:
    """Fields the dashboard draws from: layer attribution, the claimed-versus-trusted numbers and the meters. Added next to the gate's own output."""
    reasons, checks = res.get("reasons") or [], res.get("checks") or {}
    rl = [_reason_layer(r) for r in reasons]
    sp = layer_verdicts(reasons)
    decided = next((k for k in ("L5", "L6") if sp.get(k) == "refuse"), None) or next((k for k in ("L5", "L6") if k in sp), None)
    claimed_limit = order.get("limit_price") if isinstance(order.get("limit_price"), (int, float)) else None
    qty = order.get("quantity") if isinstance(order.get("quantity"), (int, float)) else None
    figs = _figure_rows(checker)
    return {
        "reason_layers": rl, "decided_by": decided if res.get("decision") != "allow" else None,
        "path": layer_path(res.get("decision", "refuse"), reasons, checks),
        "claimed": {"ticker": order.get("ticker"), "side": order.get("side"), "quantity": qty, "limit_price": claimed_limit},
        "meters": {"notional_usd": checks.get("notional_usd"), "limit_notional_usd": checks.get("limit_notional_usd"),
                   "trusted_price": checks.get("trusted_price"), "limit_vs_trusted_pct": checks.get("limit_vs_trusted_pct"),
                   "per_order_cap_usd": m.maxOrderNotionalUsd, "daily_cap_usd": m.maxDailyNotionalUsd, "daily_before_usd": daily_total,
                   "daily_after_usd": checks.get("daily_total_after_usd"), "price_band_pct": m.priceBandPct, "step_up_usd": m.stepUpAboveUsd},
        "figure_rows": figs,
    }


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



def _source_rows(events: list[dict], quarantined: set) -> list[dict]:
    """One row per source and subject: price moves (venues) and claims (wires), with the independence group.
    Syndicated wire text shares the `origin` of the claim, so three wires echoing one claim show as one group."""
    rows, seen = [], {}
    for e in events[:400]:
        src = GR.source_of(e)
        if not src:
            continue
        kind = "price" if e.get("type") == "quote_change" else "claim"
        subject = str(e.get("ticker") or e.get("origin") or "")
        key = (src, kind, subject, str(e.get("pct") if kind == "price" else e.get("text")))
        if key in seen:
            continue
        seen[key] = 1
        row = {"source": str(src), "kind": kind, "subject": subject, "group": str(e.get("origin") or src), "quarantined": src in quarantined}
        if kind == "price":
            row["pct"] = e.get("pct")
        else:
            row["text"] = str(e.get("text", ""))[:200]
        rows.append(row)
    return rows


def _threshold_label(rule: GR.Rule, spec: dict | None) -> str:
    if spec is not None and spec.get("kind") == "pct_change":
        t = float(spec["threshold"])
        return f"median {'at or below' if t < 0 else 'at or above'} {t:+g}%"
    if spec is not None:
        return "a matching claim is confirmed"
    return {"R1": "basket mean at or below -40%", "R2": "a takeover claim above the market price is confirmed", "R3": "median at or below -15%"}.get(rule.id, "see the rule text")


def _rule_details(g: GR.TriggerGraph, rule_objs: list[GR.Rule], usable: list[dict], guarded: list[dict], specs) -> list[dict]:
    """Per rule: its threshold, each input's median and source count, and the outcome in words ("needs 2 independent sources, has 1")."""
    spec_by_id = {str(sp.get("id")): sp for sp in (specs or [])}
    out = []
    for r, res in zip(rule_objs, guarded):
        ins = g.read_inputs(usable, r)
        inputs = [{"name": k, "median": v["value"], "sources": len(v["sources"]), "needs": g.min_sources,
                   "by_source": {str(a): b for a, b in v["by_source"].items()}} for k, v in ins.items()]
        thin = [i for i in inputs if i["sources"] < g.min_sources]
        if res["fires"]:
            outcome = "fires"
        elif res["held_reason"]:
            outcome = "held"
        else:
            outcome = "quiet"
        need = (f"needs {g.min_sources} independent sources, has {min(i['sources'] for i in thin)}" if thin and outcome == "held" else None)
        out.append({"id": r.id, "text": r.text, "side": r.side, "notional": r.notional, "threshold": _threshold_label(r, spec_by_id.get(r.id)),
                    "inputs": inputs, "outcome": outcome, "held_reason": res["held_reason"], "need": need})
    return out


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
    bad = set(quarantined_sources)
    usable = [e for e in events if GR.source_of(e) not in bad]
    return {
        "sources": _source_rows(events, bad),
        "rule_details": _rule_details(g, rule_objs, usable, guarded, rules),
        "min_sources": g.min_sources,
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
    tl = timeline(compact)
    return {"scenario": scenario, "ok": not err, **meta, "run_path": _run_path(meta.get("arm"), tl), "layers": layers, "judged": judged, "error": _client_error(err),
            "replay_miss": bool(err and "ReplayMiss" in err), "timeline": tl, "final": compact.get("final", ""),
            "quarantined": compact.get("quarantined", [])}


_ARM_LAYERS = {"naive": set(), "gate_only": {"L5", "L6"}, "full": {"L1", "L2", "L3", "L4", "L5", "L6", "L7"}}


def _run_path(arm: str | None, steps: list[dict]) -> list[dict]:
    """The whole run on one rail. off = the arm does not run that layer; acted = it stopped, held or quarantined something at least once
    (the strongest verdict wins); passed = it ran and found nothing; idle = it never had anything to judge."""
    on = _ARM_LAYERS.get(arm or "full", _ARM_LAYERS["full"])
    rank = {"refuse": 3, "quarantine": 2, "hold": 1}
    best: dict[str, str] = {}
    touched: set[str] = set()
    for s_ in steps:
        for st in s_.get("path") or []:
            if st["state"] == "acted":
                v = st.get("verdict") or "refuse"
                if rank.get(v, 0) >= rank.get(best.get(st["id"], ""), -1):
                    best[st["id"]] = v
            elif st["state"] == "passed":
                touched.add(st["id"])
    out = []
    for i in range(1, 9):
        lid = f"L{i}"
        if lid in best:
            out.append({"id": lid, "state": "acted", "verdict": best[lid], "note": "acted in this run"})
        elif lid not in on:
            out.append({"id": lid, "state": "off", "note": f"the {arm or 'full'} arm does not run this layer" if lid != "L8" else "not part of the lab arms"})
        elif lid in touched:
            out.append({"id": lid, "state": "passed", "note": "everything it saw passed"})
        else:
            out.append({"id": lid, "state": "idle", "note": "nothing for this layer to judge in this run"})
    return out


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
        gate = g and {"decision": g.get("decision"), "layer": g.get("layer") or "L5/L6", "reasons": g.get("reasons"),
                      "figures": (g.get("checks") or {}).get("figures") if "checks" in g else g.get("figures")}
        step = {"step": i, "tool": name, "args": c.get("args"), "result": c.get("result"), "quarantined": attach, "gate": gate}
        step["path"] = _step_path(attach, gate)
        steps.append(step)
    placed = {id(q) for s in steps for q in s["quarantined"]}
    rest = [q for q in qs if id(q) not in placed]
    if rest:
        steps.append({"step": len(steps) + 1, "tool": None, "args": None, "result": None, "quarantined": rest, "gate": None, "path": _step_path(rest, None)})
    return steps


def _base_path(note: str = "") -> list[dict]:
    return [{"id": f"L{i}", "state": "idle", "note": note} for i in range(1, 9)]


def _step_path(quarantined: list[dict], gate: dict | None) -> list[dict] | None:
    """Compact rail for one agent step: the layers that acted on it. A read tool that was quarantined stops at its layer;
    an order or unknown-tool call is judged at L5 or L6. Steps no layer touched have no path."""
    if quarantined:
        acted = {str(q.get("layer") or "L2") for q in quarantined}
        out = _base_path("not involved in this step")
        for st in out:
            if st["id"] in acted:
                st.update(state="acted", verdict="quarantine", note="quarantined text that looked like an instruction")
            elif int(st["id"][1]) < max(int(a[1]) for a in acted) and int(st["id"][1]) <= 4:
                st.update(state="passed", note="passed")
            elif int(st["id"][1]) <= 4:
                st.update(state="not_reached", note="the text was stopped before this layer")
        return out
    if gate:
        decision = gate.get("decision") or "refuse"
        reasons = gate.get("reasons") or []
        figs = gate.get("figures") or []
        return layer_path(decision, reasons, {"figures": figs, "x": 1}, figures_checked=bool(figs))
    return None


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


_CELL = re.compile(r"^(\d+)/(\d+) \((\d+(?:\.\d+)?)%, (\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)$")
ARMS = ("naive", "gate_only", "full")


def _cell(text: str) -> dict | None:
    """'3/18 (17%, 6-39)' -> {k, n, rate, lo, hi} (percent). Cells that are '-' or free text give None."""
    m = _CELL.match(str(text).strip())
    if not m:
        return None
    return {"k": int(m.group(1)), "n": int(m.group(2)), "rate": float(m.group(3)), "lo": float(m.group(4)), "hi": float(m.group(5))}


def _pooled(cells: list[dict]) -> dict | None:
    from orderguard_lab.tables import wilson
    k, n = sum(c["k"] for c in cells), sum(c["n"] for c in cells)
    if not n:
        return None
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": round(100 * k / n, 1), "lo": round(100 * lo, 1), "hi": round(100 * hi, 1)}


def results_charts(sections: list[dict]) -> list[dict]:
    """Structured data for the chart and tiles, read from the parsed per-model tables: per family and arm, attack success and executed
    harm with the report's own Wilson 95% intervals; utility on clean controls."""
    out = []
    for sec in sections:
        t = sec["tables"][0] if sec["tables"] else None
        if not t or [h.lower() for h in t["headers"][:2]] != ["family", "arm"] or not {"attack succeeded", "executed"} <= set(t["headers"]):
            continue
        ix = {h: i for i, h in enumerate(t["headers"])}
        fam: dict[str, dict] = {}
        for row in t["rows"]:
            if len(row) < len(t["headers"]):
                continue
            letter, _, name = row[ix["family"]].partition(" ")
            f = fam.setdefault(letter, {"id": letter, "name": name, "arms": {}, "executed": {}})
            f["arms"][row[ix["arm"]]] = _cell(row[ix["attack succeeded"]])
            f["executed"][row[ix["arm"]]] = _cell(row[ix["executed"]])
        util = {}
        for ut in sec["tables"][1:]:
            if [h.lower() for h in ut["headers"][:1]] == ["arm"] and "utility" in ut["headers"]:
                for row in ut["rows"]:
                    util[row[0]] = _cell(row[ut["headers"].index("utility")])
        m = re.match(r"^(.*?)\s*\((live|offline)\),\s*(\d+) runs", sec["title"])
        errors = 0
        for line in sec["text"]:
            error_count = re.match(r"^Runs that ended in an error \(excluded above\): (\d+)", line)
            if error_count:
                errors = int(error_count.group(1))
                break
        out.append({"title": sec["title"], "model": m.group(1) if m else sec["title"], "kind": m.group(2) if m else "unknown",
                    "runs": int(m.group(3)) if m else None, "errors": errors, "families": list(fam.values()), "utility": util})
    return out


def _is_dos(f: dict) -> bool:
    return f.get("id") == "E" or "denial of service" in str(f.get("name") or "").lower()


def results_headline(charts: list[dict], sections: list[dict]) -> dict:
    """Pool live fixed-case outcomes and read the separate lab spend total."""
    live = [c for c in charts if c["kind"] == "live"]
    families = [f for chart in live for f in chart["families"]]
    attack_families = [f for f in families if f["id"] in {"A", "B", "C", "D"}]
    dos_families = [f for f in families if _is_dos(f)]

    def pool_families(group, metric, arm):
        return _pooled([cell for f in group if (cell := f[metric].get(arm))])

    def pool_utility(arm):
        return _pooled([cell for chart in live if (cell := chart["utility"].get(arm))])

    spend = None
    for sec in sections:
        if sec["title"] != "Spend":
            continue
        for line in sec["text"]:
            m = re.match(r"^Total US\$(\d+(?:\.\d+)?)", line)
            if m:
                spend = float(m.group(1))

    return {
        "models": [c["model"] for c in live],
        "live_runs": sum(c["runs"] or 0 for c in live),
        "live_errors": sum(c.get("errors", 0) for c in live),
        "executed_full": pool_families(attack_families, "executed", "full"),
        "executed_naive": pool_families(attack_families, "executed", "naive"),
        "dos_full": pool_families(dos_families, "arms", "full"),
        "naive_success": pool_families(families, "arms", "naive"),
        "naive_success_ad": pool_families(attack_families, "arms", "naive"),
        "full_success_ad": pool_families(attack_families, "arms", "full"),
        "utility_full": pool_utility("full"),
        "utility_naive": pool_utility("naive"),
        "spend_usd": spend,
    }


def results() -> dict:
    p = ROOT / "docs" / "RESULTS.md"
    if not p.exists():
        raise AppError(404, "no results are available: docs/RESULTS.md does not exist")
    runs = ROOT / "results" / "runs"
    sections = parse_results(p.read_text(encoding="utf-8"))
    charts = results_charts(sections)
    return {"source": "docs/RESULTS.md", "sections": sections, "charts": charts, "headline": results_headline(charts, sections),
            "run_files": len(list(runs.glob("*.jsonl"))) if runs.exists() else 0}
