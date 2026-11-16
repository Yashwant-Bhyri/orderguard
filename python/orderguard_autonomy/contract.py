"""The signed specification (design section 3A).

Three objects are never merged: what the owner said (Intent), what a model proposed (ProposedPolicy) and what the owner signed
(AutonomyContract). A model may propose numbers; only a signature makes them binding, and the diff between the two is kept.
Delegation is by attenuation: a child contract may only be narrower than its parent.

A contract has three signed sections. Every key is listed in SCHEMA with the rule that decides whether a child value is narrower:

    trading     symbols, sides, allow_short, max_leverage, max_order_usd, price_band_pct
    portfolio   capital_usd, max_gross_usd, max_issuer_weight, max_sector_weight, sectors, scenarios, max_scenario_loss_usd,
                risk_budget_usd, es_alpha
    autonomy    objective, lease_seconds, max_orders_per_minute, review_above_usd, max_state_age_s, max_evidence_age_s,
                min_independent_sources, expires_at

`compile_predicates` turns a signed contract into the checks the admission controller runs. Predicates marked `hard` are arithmetic
on signed inputs and the projected state; the two that are not (`risk_budget`, `portfolio_es`) depend on an estimated covariance
and can only hold.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol

from ._crypto import canonical_json, flatten_sections, public_b64, sha256_hex, sign_b64, verify_b64
from .risk import Scenario, declared_scenario_loss


@dataclass(frozen=True)
class Intent:
    """The owner's words, kept verbatim. Never enforced directly."""
    text: str
    owner: str


@dataclass(frozen=True)
class ProposedPolicy:
    """Numbers a model suggests for an Intent, with the scenario consequences shown to the owner before signing."""
    intent: Intent
    limits: dict
    consequences: dict = field(default_factory=dict)     # declared scenario -> projected loss under these limits
    proposer: str = ""


@dataclass(frozen=True)
class AutonomyContract:
    """What the owner signed. Trading permissions, portfolio constraints and autonomy terms, plus the signature over all of them."""
    contract_id: str
    principal: str
    authorized_agents: tuple[str, ...]
    trading: dict             # allowed assets, sides, leverage, largest single order
    portfolio: dict           # issuer and sector weights, factor exposure, declared-scenario loss, turnover
    autonomy: dict            # lease length, order rate per agent, when a person reviews, state freshness
    parent_id: str | None = None
    signature: str = ""
    signer_public_key: str = ""
    version: int = 1

    def payload(self) -> dict:
        """Everything the signature covers (all fields except the signature and the key)."""
        return {"contract_id": self.contract_id, "principal": self.principal, "authorized_agents": sorted(self.authorized_agents),
                "trading": self.trading, "portfolio": self.portfolio, "autonomy": self.autonomy, "parent_id": self.parent_id,
                "version": int(self.version)}

    def sha256(self) -> str:
        return sha256_hex(canonical_json(self.payload()))

    def flat(self) -> dict:
        return flatten_sections({"trading": self.trading, "portfolio": self.portfolio, "autonomy": self.autonomy})

    def scenarios(self) -> list[Scenario]:
        return [Scenario.from_dict(s) for s in self.portfolio.get("scenarios", [])]


class ContractInvalid(Exception):
    pass


class PolicyProposer(Protocol):
    """Turns an Intent into a ProposedPolicy. A proposal, never an authorization."""
    def propose(self, intent: Intent) -> ProposedPolicy: ...


# ---------------------------------------------------------------------------------------------------------------------
# Schema: every signed key and how a child value compares to its parent's
# ---------------------------------------------------------------------------------------------------------------------

# rule: "subset" child set within parent set; "le" child <= parent; "ge" child >= parent; "implies" child True only if parent True;
# "sectors" child agrees with parent on every child symbol; "scenarios" child keeps every parent scenario unchanged (may add);
# "equal" must be identical.
SCHEMA: dict[str, str] = {
    "trading.symbols": "subset", "trading.sides": "subset", "trading.allow_short": "implies", "trading.max_leverage": "le",
    "trading.max_order_usd": "le", "trading.price_band_pct": "le",
    "portfolio.capital_usd": "le", "portfolio.max_gross_usd": "le", "portfolio.max_issuer_weight": "le",
    "portfolio.max_sector_weight": "le", "portfolio.sectors": "sectors", "portfolio.scenarios": "scenarios",
    "portfolio.max_scenario_loss_usd": "le", "portfolio.risk_budget_usd": "le", "portfolio.es_alpha": "ge",
    "autonomy.objective": "equal", "autonomy.lease_seconds": "le", "autonomy.max_orders_per_minute": "le",
    "autonomy.review_above_usd": "le", "autonomy.max_state_age_s": "le", "autonomy.max_evidence_age_s": "le",
    "autonomy.min_independent_sources": "ge", "autonomy.expires_at": "le",
}
NUMERIC = {k for k, r in SCHEMA.items() if r in ("le", "ge")}


def validate(c: AutonomyContract) -> list[str]:
    """Structural problems with a contract's signed sections (empty list = well formed)."""
    problems = []
    flat = c.flat()
    for key in SCHEMA:
        if key not in flat:
            problems.append(f"missing {key}")
    for key in flat:
        if key not in SCHEMA:
            problems.append(f"unknown key {key}")
    for key in NUMERIC & flat.keys():
        v = flat[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or float(v) < 0:
            problems.append(f"{key} must be a finite number >= 0")
    if problems:
        return problems
    t, p = c.trading, c.portfolio
    if not t["symbols"] or len(set(t["symbols"])) != len(t["symbols"]):
        problems.append("trading.symbols must be a non-empty list without duplicates")
    if not set(t["sides"]) <= {"buy", "sell"} or not t["sides"]:
        problems.append("trading.sides must be a non-empty subset of buy, sell")
    for w in ("max_issuer_weight", "max_sector_weight"):
        if not 0 < float(p[w]) <= 1:
            problems.append(f"portfolio.{w} must be in (0, 1]")
    missing = [s for s in t["symbols"] if s not in p["sectors"]]
    if missing:
        problems.append(f"portfolio.sectors has no sector for {', '.join(missing)}")
    if not 0.5 <= float(p["es_alpha"]) < 1:
        problems.append("portfolio.es_alpha must be in [0.5, 1)")
    for s in p["scenarios"]:
        try:
            scn = Scenario.from_dict(s)
        except (KeyError, TypeError, ValueError):
            problems.append("a scenario is malformed")
            continue
        if any(not math.isfinite(v) or v < -1.0 or v > 10.0 for v in scn.shocks.values()):
            problems.append(f"scenario {scn.name} has a shock outside [-100%, +1000%]")
    obj = c.autonomy["objective"]
    if not isinstance(obj, dict) or not obj.get("id"):
        problems.append("autonomy.objective must have an id")
    if not c.authorized_agents:
        problems.append("authorized_agents is empty")
    return problems


def sign_contract(c: AutonomyContract, private_key) -> AutonomyContract:
    """The owner (or, for a child, the delegating agent) signs the payload. Refuses to sign a malformed contract."""
    problems = validate(c)
    if problems:
        raise ContractInvalid("; ".join(problems))
    return replace(c, signature=sign_b64(private_key, c.payload()), signer_public_key=public_b64(private_key))


def verify_contract(c: AutonomyContract, trusted_keys: set[str] | frozenset[str] | None = None) -> list[str]:
    """Problems with a signed contract: shape, signature, and (if given) whether the signer is a trusted key."""
    problems = validate(c)
    if not c.signature or not verify_b64(c.signer_public_key, c.signature, c.payload()):
        problems.append("signature does not verify")
    if trusted_keys is not None and c.signer_public_key not in trusted_keys:
        problems.append("signer is not a trusted key")
    return problems


# ---------------------------------------------------------------------------------------------------------------------
# Attenuated delegation
# ---------------------------------------------------------------------------------------------------------------------

def _scn_map(v) -> dict[str, dict]:
    return {s["name"]: dict(sorted((k, float(x)) for k, x in s["shocks"].items())) for s in v}


def _narrower(rule: str, parent, child, child_symbols: set[str]) -> bool:
    if rule == "subset":
        return set(child) <= set(parent)
    if rule == "le":
        return float(child) <= float(parent)
    if rule == "ge":
        return float(child) >= float(parent)
    if rule == "implies":
        return (not bool(child)) or bool(parent)
    if rule == "sectors":
        return all(s in parent and s in child and parent[s] == child[s] for s in child_symbols)
    if rule == "scenarios":
        pm, cm = _scn_map(parent), _scn_map(child)
        return all(name in cm and cm[name] == shocks for name, shocks in pm.items())
    if rule == "equal":
        return canonical_json(parent) == canonical_json(child)
    raise ValueError(rule)


def attenuation_problems(parent: AutonomyContract, child: AutonomyContract) -> list[str]:
    """Every way `child` is not inside `parent` (empty list = a valid attenuation)."""
    problems = []
    if child.parent_id != parent.contract_id:
        problems.append("child does not name this parent")
    if child.principal != parent.principal:
        problems.append("child has a different principal")
    pf, cf = parent.flat(), child.flat()
    syms = set(cf.get("trading.symbols", []))
    for key, rule in SCHEMA.items():
        if key not in pf:
            continue                                          # nothing to compare against; validate() reports it
        if key not in cf:
            problems.append(f"{key} is missing in the child (unbounded is wider)")
            continue
        try:
            ok = _narrower(rule, pf[key], cf[key], syms)
        except (TypeError, ValueError, KeyError):
            ok = False
        if not ok:
            problems.append(f"{key} is wider in the child")
    for key in cf.keys() - SCHEMA.keys():
        problems.append(f"{key} is not a known limit")
    return problems


def is_attenuation(parent: AutonomyContract, child: AutonomyContract) -> bool:
    """True only if every permission and limit of `child` is inside `parent`. Delegation that widens authority is refused."""
    return not attenuation_problems(parent, child)


def verify_chain(chain: list[AutonomyContract], trusted_root_keys: set[str]) -> list[str]:
    """A delegation chain, root first. The root is signed by a trusted owner key; every link verifies and narrows its parent.

    A child may be signed by the delegating agent rather than the owner: attenuation, not the signer, is what bounds it."""
    if not chain:
        return ["empty chain"]
    problems = [f"root: {p}" for p in verify_contract(chain[0], trusted_root_keys)]
    for i in range(1, len(chain)):
        problems += [f"link {i}: {p}" for p in verify_contract(chain[i])]
        problems += [f"link {i}: {p}" for p in attenuation_problems(chain[i - 1], chain[i])]
    return problems


# ---------------------------------------------------------------------------------------------------------------------
# From intent to a signed contract
# ---------------------------------------------------------------------------------------------------------------------

DEFAULT_SCENARIOS = (
    {"name": "market_down_20", "shocks": {"*": -0.20}},
    {"name": "tech_down_30", "shocks": {"*": -0.05, "sector:tech": -0.30}},
    {"name": "crypto_down_50", "shocks": {"sector:crypto": -0.50}},
    {"name": "rates_shock", "shocks": {"*": -0.08, "sector:financials": -0.15, "sector:energy": 0.05}},
)


def worst_fill_loss(limits: dict, scenario: Scenario, sectors: dict[str, str]) -> float:
    """Largest loss a long-only book can reach in `scenario` while staying inside the proposed issuer, sector and gross caps.

    Greedy by loss per dollar is optimal here: the caps are nested (issuer inside sector inside gross), a laminar family, and a
    linear objective over such constraints is maximised greedily."""
    cap = float(limits["portfolio.capital_usd"])
    issuer_cap = float(limits["portfolio.max_issuer_weight"]) * cap
    sector_cap = float(limits["portfolio.max_sector_weight"]) * cap
    gross_left = min(float(limits["portfolio.max_gross_usd"]), cap * float(limits["trading.max_leverage"]))
    sector_left: dict[str, float] = {}
    loss = 0.0
    for sym in sorted(limits["trading.symbols"], key=lambda s: scenario.shock_for(s, sectors)):
        per_dollar = -scenario.shock_for(sym, sectors)
        if per_dollar <= 0 or gross_left <= 0:
            continue
        sec = sectors[sym]
        room = min(issuer_cap, sector_left.setdefault(sec, sector_cap), gross_left)
        loss += room * per_dollar
        sector_left[sec] -= room
        gross_left -= room
    return loss


@dataclass
class RuleProposer:
    """A deterministic stand-in for the model that drafts limits from an owner's words.

    It reads a few plain phrases (amount, "diversified", "not too aggressive", "no crypto", "income") and fills the rest from house
    defaults. It is deliberately simple: the point is the flow (propose, show consequences, sign, keep the diff), not the parser.
    A language model can replace it behind the same PolicyProposer protocol without changing anything that enforces."""
    symbols: tuple[str, ...]
    sectors: dict[str, str]
    name: str = "rule-proposer-v1"

    def propose(self, intent: Intent) -> ProposedPolicy:
        text = intent.text.lower()
        m = re.search(r"\$\s*([\d,.]+)\s*(k|m|thousand|million)?", text)
        capital = 100_000.0
        if m:
            capital = float(m.group(1).replace(",", ""))
            capital *= {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}.get(m.group(2) or "", 1.0)
        careful = any(w in text for w in ("not too aggressive", "conservative", "careful", "cautious", "safe"))
        diversified = any(w in text for w in ("diversif", "one theme", "one sector", "everything on"))
        symbols = [s for s in self.symbols if not ("no crypto" in text and self.sectors.get(s) == "crypto")]
        income = any(w in text for w in ("income", "dividend", "defensive"))
        style = {"staples": 0.25, "healthcare": 0.25, "financials": 0.2, "energy": 0.15, "index": 0.15} if income else \
                {"index": 0.4, "tech": 0.3, "healthcare": 0.1, "financials": 0.1, "staples": 0.1}
        limits = {
            "trading.symbols": symbols, "trading.sides": ["buy", "sell"], "trading.allow_short": False, "trading.max_leverage": 1.0,
            "trading.max_order_usd": round(capital * (0.05 if careful else 0.10), 2), "trading.price_band_pct": 2.0,
            "portfolio.capital_usd": capital, "portfolio.max_gross_usd": capital,
            "portfolio.max_issuer_weight": 0.10 if diversified or careful else 0.20,
            "portfolio.max_sector_weight": 0.35 if diversified else 0.50,
            "portfolio.sectors": {s: self.sectors[s] for s in symbols},
            "portfolio.scenarios": [dict(s) for s in DEFAULT_SCENARIOS],
            "portfolio.max_scenario_loss_usd": round(capital * (0.10 if careful else 0.18), 2),
            "portfolio.risk_budget_usd": round(capital * (0.03 if careful else 0.06), 2), "portfolio.es_alpha": 0.975,
            "autonomy.objective": {"id": "obj-" + sha256_hex(intent.text)[:10], "statement": intent.text, "style": style,
                                   "max_style_distance": 0.6},
            "autonomy.lease_seconds": 300, "autonomy.max_orders_per_minute": 30, "autonomy.review_above_usd": round(capital * 0.08, 2),
            "autonomy.max_state_age_s": 5.0, "autonomy.max_evidence_age_s": 3600.0, "autonomy.min_independent_sources": 2,
            "autonomy.expires_at": 4_102_444_800.0,
        }
        consequences = consequences_of(limits)
        return ProposedPolicy(intent, limits, consequences, self.name)


def consequences_of(limits: dict) -> dict:
    """What a set of limits would allow in each declared scenario, in dollars: the number shown to the owner before signing."""
    sectors = limits["portfolio.sectors"]
    out = {}
    for s in limits["portfolio.scenarios"]:
        scn = Scenario.from_dict(s)
        out[scn.name] = round(worst_fill_loss(limits, scn, sectors), 2)
    out["_worst_allowed_by_scenario_cap"] = float(limits["portfolio.max_scenario_loss_usd"])
    return out


def contract_from_limits(limits: dict, *, contract_id: str, principal: str, agents: tuple[str, ...], parent_id: str | None = None,
                         version: int = 1) -> AutonomyContract:
    sections: dict[str, dict] = {"trading": {}, "portfolio": {}, "autonomy": {}}
    for key, v in limits.items():
        sec, name = key.split(".", 1)
        sections[sec][name] = v
    return AutonomyContract(contract_id, principal, tuple(agents), sections["trading"], sections["portfolio"], sections["autonomy"],
                            parent_id=parent_id, version=version)


def signed_diff(proposed: ProposedPolicy, signed: AutonomyContract) -> dict:
    """What the owner changed between the model's proposal and what they signed. Recorded with the contract."""
    p, s = proposed.limits, signed.flat()
    changed = {}
    for key in sorted(p.keys() & s.keys()):
        if canonical_json(p[key]) == canonical_json(s[key]):
            continue
        rule = SCHEMA.get(key)
        direction = "different"
        if rule:
            try:
                tighter = _narrower(rule, p[key], s[key], set(signed.trading.get("symbols", [])))
                looser = _narrower(rule, s[key], p[key], set(p.get("trading.symbols", [])))
                direction = "tighter" if tighter and not looser else "looser" if looser and not tighter else "different"
            except (TypeError, ValueError, KeyError):
                pass
        changed[key] = {"proposed": p[key], "signed": s[key], "direction": direction}
    return {"proposer": proposed.proposer, "intent_sha256": sha256_hex(proposed.intent.text), "changed": changed,
            "added": {k: s[k] for k in sorted(s.keys() - p.keys())}, "removed": sorted(p.keys() - s.keys()),
            "consequences_shown": proposed.consequences}


# ---------------------------------------------------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderContext:
    """Everything a predicate needs, computed by the admission controller from the signed contract and the projected state.

    `*_before` / `*_after` are conservative projections (filled positions, plus every working order that would add to the measure,
    without and with this order). A predicate fails only when the order makes its measure worse AND the result is over the limit,
    so an order that reduces risk is never blocked by a cap the book already exceeds."""
    agent: str
    symbol: str
    side: str
    quantity: float
    limit_price: float
    mark: float | None
    notional: float
    now: float
    lease_problem: str | None = None
    orders_last_minute: int = 0
    issuer_before: float = 0.0
    issuer_after: float = 0.0
    sector_before: float = 0.0
    sector_after: float = 0.0
    gross_before: float = 0.0
    gross_after: float = 0.0
    short_after: float = 0.0                    # the lowest the position can go (negative = short)
    scenario_before: dict = field(default_factory=dict)
    scenario_after: dict = field(default_factory=dict)
    state_age_s: float = 0.0
    risk_units: float = 0.0
    risk_available: float = math.inf
    es_before: float = 0.0
    es_after: float = 0.0


@dataclass(frozen=True)
class Predicate:
    """One enforceable condition compiled from a contract, e.g. projected issuer weight <= 0.15. `hard` predicates can refuse.

    `check(ctx)` returns None when the condition holds, else a plain reason. `on_fail` is "refuse" or "hold"."""
    name: str
    hard: bool
    description: str
    on_fail: str = "refuse"
    check: Callable[[OrderContext], str | None] | None = field(default=None, compare=False, repr=False)


EPS = 1e-6


def _worse_and_over(before: float, after: float, limit: float) -> bool:
    return after > limit + EPS and after > before + EPS


def compile_predicates(contract: AutonomyContract) -> list[Predicate]:
    """Compile a signed contract into the predicates the admission controller evaluates."""
    t, p, a = contract.trading, contract.portfolio, contract.autonomy
    symbols, sides = frozenset(t["symbols"]), frozenset(t["sides"])
    agents = frozenset(contract.authorized_agents)
    cap = float(p["capital_usd"])
    issuer_cap = float(p["max_issuer_weight"]) * cap
    sector_cap = float(p["max_sector_weight"]) * cap
    gross_cap = min(float(p["max_gross_usd"]), cap * float(t["max_leverage"]))
    loss_cap = float(p["max_scenario_loss_usd"])
    band = float(t["price_band_pct"]) / 100.0
    max_order = float(t["max_order_usd"])
    rate = int(a["max_orders_per_minute"])
    review = float(a["review_above_usd"])
    fresh = float(a["max_state_age_s"])
    expires = float(a["expires_at"])
    budget = float(p["risk_budget_usd"])
    allow_short = bool(t["allow_short"])

    def scen(ctx: OrderContext) -> str | None:
        bad = [n for n, v in ctx.scenario_after.items() if _worse_and_over(ctx.scenario_before.get(n, 0.0), v, loss_cap)]
        return f"declared scenario {bad[0]} would lose ${ctx.scenario_after[bad[0]]:,.0f}, over the signed ${loss_cap:,.0f}" if bad else None

    P = Predicate
    return [
        P("contract_live", True, "the contract has not expired",
          check=lambda c: None if c.now <= expires else "the contract has expired"),
        P("agent_authorized", True, "the agent is named in the contract",
          check=lambda c: None if c.agent in agents else f"agent {c.agent} is not authorized by this contract"),
        P("lease_valid", True, "the agent holds a live lease in an unrevoked epoch",
          check=lambda c: None if c.lease_problem is None else c.lease_problem),
        P("symbol_permitted", True, "the symbol is in the signed list",
          check=lambda c: None if c.symbol in symbols else f"{c.symbol} is not a permitted symbol"),
        P("side_permitted", True, "the side is permitted",
          check=lambda c: None if c.side in sides else f"{c.side} is not a permitted side"),
        P("trusted_mark", True, "a trusted price exists for the symbol",
          check=lambda c: None if c.mark and c.mark > 0 else "no trusted price for this symbol"),
        P("max_order_usd", True, f"one order is at most ${max_order:,.0f} at the trusted price",
          check=lambda c: None if c.notional <= max_order + EPS else f"order ${c.notional:,.0f} is over the signed ${max_order:,.0f} per order"),
        P("price_band", True, f"limit price within {band:.1%} of the trusted price",
          check=lambda c: None if c.mark and abs(c.limit_price / c.mark - 1) <= band + 1e-12 else "limit price is outside the signed band"),
        P("no_short", True, "the position can never go below zero" if not allow_short else "shorting permitted",
          check=lambda c: None if allow_short or c.short_after >= -EPS else "the order could leave a short position"),
        P("gross_exposure", True, f"projected gross exposure at most ${gross_cap:,.0f}",
          check=lambda c: f"projected gross ${c.gross_after:,.0f} is over ${gross_cap:,.0f}" if _worse_and_over(c.gross_before, c.gross_after, gross_cap) else None),
        P("issuer_cap", True, f"projected exposure to one issuer at most ${issuer_cap:,.0f}",
          check=lambda c: f"projected {c.symbol} exposure ${c.issuer_after:,.0f} is over ${issuer_cap:,.0f}" if _worse_and_over(c.issuer_before, c.issuer_after, issuer_cap) else None),
        P("sector_cap", True, f"projected exposure to one sector at most ${sector_cap:,.0f}",
          check=lambda c: f"projected sector exposure ${c.sector_after:,.0f} is over ${sector_cap:,.0f}" if _worse_and_over(c.sector_before, c.sector_after, sector_cap) else None),
        P("declared_scenario_loss", True, f"loss in each declared scenario at most ${loss_cap:,.0f} (those scenarios only)", check=scen),
        P("order_rate", True, f"at most {rate} orders per minute per agent",
          check=lambda c: None if c.orders_last_minute < rate else f"agent is at its signed {rate} orders per minute"),
        P("state_fresh", True, f"portfolio state no older than {fresh:g}s", on_fail="hold",
          check=lambda c: None if c.state_age_s <= fresh else f"portfolio state is {c.state_age_s:.1f}s old; decisions wait for fresh state"),
        P("review_above", True, f"a person reviews orders above ${review:,.0f}", on_fail="hold",
          check=lambda c: None if c.notional <= review + EPS else f"order ${c.notional:,.0f} is above the signed review threshold"),
        P("risk_budget", False, "the order's standalone ES fits the agent's remaining risk budget", on_fail="hold",
          check=lambda c: None if c.risk_units <= c.risk_available + EPS else f"order needs ${c.risk_units:,.0f} of risk budget, ${c.risk_available:,.0f} left"),
        P("portfolio_es", False, f"estimated portfolio ES at most ${budget:,.0f}", on_fail="hold",
          check=lambda c: f"estimated ES would be ${c.es_after:,.0f}, over the ${budget:,.0f} budget" if _worse_and_over(c.es_before, c.es_after, budget) else None),
    ]


def scenario_losses_for(contract: AutonomyContract, exposures: dict[str, float]) -> dict[str, float]:
    return declared_scenario_loss(exposures, contract.scenarios(), contract.portfolio["sectors"])
