"""L7 trigger graph: standing rules fire only on inputs confirmed by enough independent, unquarantined sources.

A rule has inputs, a threshold function over the input values, a notional and a side. `evaluate(events)`:
  - drops events that are marked quarantined or come from a quarantined source (L3);
  - reads each input as the MEDIAN across sources (venues), so one liar cannot move it;
  - lets a rule fire only if every input has at least `min_sources` independent sources.
`blast_radius(source, lies)` simulates one lying source and reports what a naive rule and the guarded graph would each do.

Measured motivation (lab/legacy/attack-lab-2026-11-06/bucket_graph.py): with one venue printing a -48% crash on a three-name basket, a
rule that trusts any single print sold $30,000; the guarded graph held (median of three venues -1.2%), and a REAL -45% crash on
all three venues still fired.

Events: {"src"|"source"|"venue": name, "type": "quote_change", "ticker", "pct"} and text events
{"src", "type": "headline"|"notice", "ticker", "text"}. Named non-ticker inputs (e.g. "AAPL_takeover") are read with a matcher.
"""
from __future__ import annotations

import copy
import math
import statistics
from dataclasses import dataclass, field
from typing import Callable


def source_of(e: dict) -> str | None:
    if not isinstance(e, dict):
        return None
    src = e.get("src") or e.get("source") or e.get("venue")
    return src if src is None or isinstance(src, str) else str(src)      # a list or dict as a source name must not break hashing


def _pct(e: dict) -> float | None:
    """The move an event reports, or None when it is missing, boolean, NaN, infinite or not a number: such a reading counts as no source."""
    v = e.get("pct") if isinstance(e, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except (ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _match(rule: "Rule", name: str, e: dict) -> bool:
    try:
        return bool(rule.matchers[name](e))
    except Exception:      # noqa: BLE001  an event the matcher cannot read is not evidence
        return False


def _safe_fires(rule: "Rule", values: dict) -> bool:
    try:
        return bool(rule.fires(values))
    except Exception:      # noqa: BLE001  a rule that cannot be evaluated does not fire
        return False


@dataclass
class Rule:
    id: str
    text: str
    inputs: list[str]
    fires: Callable[[dict], bool]          # values {input: float} -> bool
    notional: float
    side: str
    matchers: dict = field(default_factory=dict)   # input name -> predicate(event) -> bool, for non-price inputs
    tickers: list[str] = field(default_factory=list)   # tickers of the orders this rule places (default: its price inputs)

    def fulfilled_by(self, ticker: str, side: str) -> bool:
        """Would an order for `ticker` on `side` carry out this rule?"""
        names = self.tickers or [i for i in self.inputs if i not in self.matchers]
        return str(side).lower() == self.side and str(ticker).upper() in {n.upper() for n in names}


def basket_mean_fall(inputs: list[str], pct: float) -> Callable[[dict], bool]:
    return lambda v: sum(v[i] for i in inputs) / len(inputs) <= pct


def _says_takeover_400(e: dict) -> bool:
    return e.get("type") in ("headline", "notice") and "$400" in str(e.get("text", ""))


ROBOTICS = ["ISRG", "ROK", "TER"]


def robotics_basket_rule() -> Rule:
    return Rule("R1", "Sell the robotics basket (ISRG, ROK, TER) if the basket falls more than 40% today", list(ROBOTICS),
                basket_mean_fall(ROBOTICS, -40), 30000, "sell")


def takeover_rule() -> Rule:
    return Rule("R2", "Buy $10,000 of AAPL if a takeover offer above the market price is confirmed", ["AAPL_takeover"],
                lambda v: v["AAPL_takeover"] > 0, 10000, "buy", matchers={"AAPL_takeover": _says_takeover_400}, tickers=["AAPL"])


def msft_rule() -> Rule:
    return Rule("R3", "Sell all MSFT if MSFT falls more than 15% today", ["MSFT"], lambda v: v["MSFT"] <= -15, 42018, "sell")


def graph_events(events: list[dict]) -> list[dict]:
    """Group syndicated wire text by its `origin` tag, so one claim echoed by many wires counts as one source."""
    return [({**e, "source": e["origin"], "src": e["origin"]} if e.get("origin") and e.get("type") in ("headline", "notice") else e) for e in events]


def standing_rules() -> list[Rule]:
    """The three prototype rules: robotics basket, takeover, MSFT."""
    return [robotics_basket_rule(), takeover_rule(), msft_rule()]


def honest_events() -> list[dict]:
    """The prototype's quiet morning: two honest venues on every name."""
    base = {"ISRG": (-1.2, -1.1), "ROK": (-0.8, -0.9), "TER": (-2.0, -2.1), "MSFT": (0.4, 0.5)}
    return [{"src": v, "type": "quote_change", "ticker": t, "pct": p} for t, ps in base.items() for v, p in zip(("VenueA", "VenueB"), ps)]


def single_venue_crash_events() -> list[dict]:
    """Prototype poison 1: VenueC alone prints a crash for the whole robotics basket."""
    return honest_events() + [{"src": "VenueC", "type": "quote_change", "ticker": t, "pct": p} for t, p in zip(ROBOTICS, (-48.0, -46.5, -51.0))]


def real_crash_events(pct: float = -45.0) -> list[dict]:
    """A REAL crash: every venue agrees. The guarded rule must still fire."""
    return [{"src": v, "type": "quote_change", "ticker": t, "pct": pct} for v in ("VenueA", "VenueB", "VenueC") for t in ROBOTICS] + \
           [e for e in honest_events() if e["ticker"] == "MSFT"]


def takeover_echo_events() -> list[dict]:
    """Prototype poison 2: a fake takeover repeated by three wires."""
    return honest_events() + [
        {"src": "FlashWire", "type": "headline", "ticker": "AAPL", "text": "Apple in talks to be taken private at $400 a share - sources"},
        {"src": "MarketPulse", "type": "headline", "ticker": "AAPL", "text": "Consortium bid of $400/share for Apple said to be fully financed"},
        {"src": "StreetTicker", "type": "headline", "ticker": "AAPL", "text": "Arbitrage desks pile into AAPL on reported $400 buyout bid"}]


class TriggerGraph:
    def __init__(self, rules: list[Rule] | None = None, min_sources: int = 2, *, groups: dict | None = None,
                 baseline: list[dict] | None = None):
        self.rules = list(rules if rules is not None else standing_rules())
        self.min_sources = max(1, int(min_sources))     # zero would let a rule fire on no evidence at all
        self.groups = dict(groups or {})        # source -> owner; two wires with one owner count as one source
        self.baseline = list(baseline if baseline is not None else honest_events())

    # ---- reading inputs ------------------------------------------------------------------------------------
    def _group(self, src):
        return self.groups.get(src, src)

    def _usable(self, events: list[dict]) -> list[dict]:
        return [e for e in events if isinstance(e, dict) and not e.get("quarantined")]

    def read_inputs(self, events: list[dict], rule: Rule) -> dict:
        """{input: {"value": median or None, "sources": set, "by_source": {src: value}}}"""
        out = {}
        for name in rule.inputs:
            if name in rule.matchers:
                hits = [e for e in events if _match(rule, name, e)]
                srcs = {self._group(source_of(e)) for e in hits if source_of(e)}
                out[name] = {"value": 1.0 if hits else 0.0, "sources": srcs, "by_source": {source_of(e): 1.0 for e in hits}}
                continue
            by_src: dict = {}
            for e in events:
                if e.get("type") == "quote_change" and str(e.get("ticker", "")).upper() == name.upper() and source_of(e) and _pct(e) is not None:
                    by_src.setdefault(source_of(e), []).append(_pct(e))
            latest = {s: v[-1] for s, v in by_src.items()}
            vals = list(latest.values())
            # median_low and median_high differ only for an even number of sources; a rule must fire under both, so one liar among two
            # cannot drag the median across the threshold
            out[name] = {"value": statistics.median(vals) if vals else None, "sources": {self._group(s) for s in latest}, "by_source": latest,
                         "low": statistics.median_low(vals) if vals else None, "high": statistics.median_high(vals) if vals else None}
        return out

    # ---- evaluation ------------------------------------------------------------------------------------------
    def evaluate(self, events: list[dict], *, quarantined_sources: set | None = None) -> list[dict]:
        bad = {str(b) for b in (quarantined_sources or ())}
        events = [e for e in events] if isinstance(events, (list, tuple)) else []
        usable = [e for e in self._usable(events) if source_of(e) not in bad]
        results = []
        for r in self.rules:
            ins = self.read_inputs(usable, r)
            values = {k: (v["value"] if v["value"] is not None else 0.0) for k, v in ins.items()}
            low = {k: (v.get("low", v["value"]) if v.get("low", v["value"]) is not None else 0.0) for k, v in ins.items()}
            high = {k: (v.get("high", v["value"]) if v.get("high", v["value"]) is not None else 0.0) for k, v in ins.items()}
            fires = _safe_fires(r, values) and _safe_fires(r, low) and _safe_fires(r, high)
            thin = [k for k, v in ins.items() if len(v["sources"]) < self.min_sources]
            held = None
            if fires and thin:
                held = (f"{r.id} would fire, but {', '.join(thin)} has fewer than {self.min_sources} independent sources "
                        f"({'; '.join(f'{k}: {len(ins[k]['sources'])}' for k in thin)}), so it is held")
                fires = False
            elif not fires:
                # does any single source alone cross the threshold? then say a lone voice was outvoted
                for name, v in ins.items():
                    for s, val in v["by_source"].items():
                        alone = dict(values)
                        alone[name] = val
                        if name not in r.matchers and len(r.inputs) == 1 and _safe_fires(r, alone):
                            held = f"{s} alone reports {val:g} for {name}, but the median across {len(v['by_source'])} sources is {v['value']:g}, so {r.id} is held"
                            break
                        if name not in r.matchers and len(r.inputs) > 1:
                            alone_all = {k: (x["by_source"].get(s, x["value"] or 0.0)) for k, x in ins.items()}
                            if _safe_fires(r, alone_all):
                                held = (f"{s} alone reports a move that would fire {r.id}, but the median across "
                                        f"{len(v['by_source'])} sources does not, so it is held")
                                break
                    if held:
                        break
            results.append({"rule": r.id, "fires": fires, "held_reason": held, "notional": r.notional if fires else 0, "side": r.side,
                            "values": values})
        return results

    @staticmethod
    def naive(rules: list[Rule], events: list[dict], matchers_from: list[Rule] | None = None) -> list[dict]:
        """The baseline: latest print wins, any single source counts, nothing is screened."""
        g = TriggerGraph(rules, min_sources=1)
        out = []
        for r in rules:
            ins = {}
            for name in r.inputs:
                if name in r.matchers:
                    hits = [e for e in events if isinstance(e, dict) and _match(r, name, e)]
                    ins[name] = 1.0 if hits else 0.0
                else:
                    xs = [_pct(e) for e in events if isinstance(e, dict) and e.get("type") == "quote_change" and str(e.get("ticker", "")).upper() == name.upper() and _pct(e) is not None]
                    ins[name] = xs[-1] if xs else 0.0
            f = _safe_fires(r, ins)
            out.append({"rule": r.id, "fires": f, "notional": r.notional if f else 0, "side": r.side})
        return out

    # ---- blast radius ------------------------------------------------------------------------------------------
    def blast_radius(self, source: str, lies: list[float], events: list[dict] | None = None) -> list[dict]:
        """If `source` lies by each value in `lies` (a pct move) on every price input, which rules fire and for how much?

        Starts from `events` (default: the honest baseline plus `source` as a third venue reporting the truth).
        """
        base = copy.deepcopy(self.baseline if events is None else events)
        tickers = sorted({i for r in self.rules for i in r.inputs if i not in r.matchers})
        base = [e for e in base if source_of(e) != source]
        # the liar is one of the venues: it would otherwise report roughly what the others report
        honest = {}
        for e in base:
            if isinstance(e, dict) and e.get("type") == "quote_change" and _pct(e) is not None:
                honest.setdefault(str(e.get("ticker")).upper(), []).append(_pct(e))
        report = []
        for lie in lies:
            fake = base + [{"src": source, "type": "quote_change", "ticker": t, "pct": lie} for t in tickers]
            guarded = self.evaluate(fake)
            naive = self.naive(self.rules, fake)
            report.append({"source": source, "lie_pct": lie,
                           "naive_fires": [x["rule"] for x in naive if x["fires"]], "naive_notional": sum(x["notional"] for x in naive),
                           "guarded_fires": [x["rule"] for x in guarded if x["fires"]], "guarded_notional": sum(x["notional"] for x in guarded),
                           "guarded": guarded})
        return report
