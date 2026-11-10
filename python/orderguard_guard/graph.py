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
import statistics
from dataclasses import dataclass, field
from typing import Callable


def source_of(e: dict) -> str | None:
    return e.get("src") or e.get("source") or e.get("venue")


@dataclass
class Rule:
    id: str
    text: str
    inputs: list[str]
    fires: Callable[[dict], bool]          # values {input: float} -> bool
    notional: float
    side: str
    matchers: dict = field(default_factory=dict)   # input name -> predicate(event) -> bool, for non-price inputs


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
                lambda v: v["AAPL_takeover"] > 0, 10000, "buy", matchers={"AAPL_takeover": _says_takeover_400})


def msft_rule() -> Rule:
    return Rule("R3", "Sell all MSFT if MSFT falls more than 15% today", ["MSFT"], lambda v: v["MSFT"] <= -15, 42018, "sell")


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
        self.min_sources = min_sources
        self.groups = dict(groups or {})        # source -> owner; two wires with one owner count as one source
        self.baseline = list(baseline if baseline is not None else honest_events())

    # ---- reading inputs ------------------------------------------------------------------------------------
    def _group(self, src):
        return self.groups.get(src, src)

    def _usable(self, events: list[dict]) -> list[dict]:
        return [e for e in events if not e.get("quarantined")]

    def read_inputs(self, events: list[dict], rule: Rule) -> dict:
        """{input: {"value": median or None, "sources": set, "by_source": {src: value}}}"""
        out = {}
        for name in rule.inputs:
            if name in rule.matchers:
                hits = [e for e in events if rule.matchers[name](e)]
                srcs = {self._group(source_of(e)) for e in hits if source_of(e)}
                out[name] = {"value": 1.0 if hits else 0.0, "sources": srcs, "by_source": {source_of(e): 1.0 for e in hits}}
                continue
            by_src: dict = {}
            for e in events:
                if e.get("type") == "quote_change" and str(e.get("ticker", "")).upper() == name.upper() and source_of(e) and "pct" in e:
                    by_src.setdefault(source_of(e), []).append(float(e["pct"]))
            latest = {s: v[-1] for s, v in by_src.items()}
            vals = list(latest.values())
            out[name] = {"value": statistics.median(vals) if vals else None, "sources": {self._group(s) for s in latest}, "by_source": latest}
        return out

    # ---- evaluation ------------------------------------------------------------------------------------------
    def evaluate(self, events: list[dict], *, quarantined_sources: set | None = None) -> list[dict]:
        bad = set(quarantined_sources or ())
        usable = [e for e in self._usable(events) if source_of(e) not in bad]
        results = []
        for r in self.rules:
            ins = self.read_inputs(usable, r)
            values = {k: (v["value"] if v["value"] is not None else 0.0) for k, v in ins.items()}
            fires = bool(r.fires(values))
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
                        if name not in r.matchers and len(r.inputs) == 1 and r.fires(alone):
                            held = f"{s} alone reports {val:g} for {name}, but the median across {len(v['by_source'])} sources is {v['value']:g}, so {r.id} is held"
                            break
                        if name not in r.matchers and len(r.inputs) > 1:
                            alone_all = {k: (x["by_source"].get(s, x["value"] or 0.0)) for k, x in ins.items()}
                            if r.fires(alone_all):
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
                    hits = [e for e in events if r.matchers[name](e)]
                    ins[name] = 1.0 if hits else 0.0
                else:
                    xs = [float(e["pct"]) for e in events if e.get("type") == "quote_change" and str(e.get("ticker", "")).upper() == name.upper() and "pct" in e]
                    ins[name] = xs[-1] if xs else 0.0
            f = bool(r.fires(ins))
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
            if e.get("type") == "quote_change":
                honest.setdefault(str(e["ticker"]).upper(), []).append(float(e["pct"]))
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
