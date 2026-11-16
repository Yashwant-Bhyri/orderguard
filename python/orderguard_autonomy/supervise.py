"""The continuous feedback loop (design section 3D).

An agent is a process, not a request: observe actions, market and portfolio; evaluate authority, risk, evidence and drift;
control; reconcile; observe again. Authority is leased: it expires unless renewed under current state, and an epoch number lets
one revocation invalidate a whole chain of spawned agents within one lease length. Semantic checks supervise; they never authorize.

What is deterministic here and what is a model:

    deterministic (may refuse)   lease validity and epochs; whether an order matches the typed intent record it claims; whether
                                 cited evidence exists with that content hash
    statistical (may only hold)  drift (Bernoulli CUSUM on off-objective actions, style distance), herding (behavioural flow
                                 similarity), loops, pacing, the judgement model
"""
from __future__ import annotations

import itertools
import math
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Protocol

from ._crypto import sha256_hex


class Control(str, Enum):
    CONTINUE = "continue"
    TIGHTEN = "tighten"                       # smaller limits for this agent or coalition
    REVIEW = "review"                         # a person decides the next action
    SUSPEND_NEW_RISK = "suspend_new_risk"     # no new exposure; cancels and risk-reducing orders still allowed


CONTROL_ORDER = [Control.CONTINUE, Control.TIGHTEN, Control.REVIEW, Control.SUSPEND_NEW_RISK]


def stricter(a: Control, b: Control) -> Control:
    return max(a, b, key=CONTROL_ORDER.index)


# ---------------------------------------------------------------------------------------------------------------------
# Leases with epochs
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Lease:
    agent: str
    contract_id: str
    epoch: int
    expires_at: float
    parent_agent: str | None = None
    lease_id: str = ""
    lineage: str = ""                 # the root agent of this delegation chain
    depth: int = 0
    parent_lease_id: str | None = None


class LeaseError(Exception):
    pass


class LeaseAuthority:
    """Grants, renews and revokes leases. Revoking an epoch invalidates every lease issued under it, including spawned agents.

    Epochs are kept per (contract, lineage), where a lineage is the root agent of a delegation chain, so quarantining one agent and
    everything it spawned does not stop its siblings. `revoke_epoch(contract_id, epoch)` without a lineage revokes every lineage of
    that contract (the firm-wide kill). A revoked lineage is not re-granted until `restore` is called by a person."""

    def __init__(self, clock: Callable[[], float] = time.time, lease_seconds: float = 300.0, max_depth: int = 3):
        self.clock, self.lease_seconds, self.max_depth = clock, float(lease_seconds), int(max_depth)
        self._epoch: dict[tuple[str, str], int] = {}
        self._revoked: dict[tuple[str, str], int] = {}
        self._contract_revoked: dict[str, int] = {}
        self._quarantined: set[tuple[str, str]] = set()
        self._leases: dict[str, Lease] = {}
        self._snapshot: dict[str, int] = {}
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def current_epoch(self, contract_id: str, lineage: str) -> int:
        return max(self._epoch.get((contract_id, lineage), 0), self._contract_revoked.get(contract_id, -1) + 1)

    def observe_snapshot(self, contract_id: str, snapshot: int) -> None:
        """The latest state snapshot for a contract. A renewal must be made against at least this state."""
        self._snapshot[contract_id] = max(self._snapshot.get(contract_id, 0), int(snapshot))

    def grant(self, agent: str, contract_id: str, parent: Lease | None = None) -> Lease:
        now = self.clock()
        with self._lock:
            if parent is not None:
                why = self._check(parent, now)
                if why:
                    raise LeaseError(f"parent lease is not valid: {why}")
                if parent.contract_id != contract_id:
                    raise LeaseError("a child lease must be under the parent's contract (attenuate the contract first)")
                if parent.depth + 1 > self.max_depth:
                    raise LeaseError("delegation is too deep")
                lineage, epoch, depth = parent.lineage, parent.epoch, parent.depth + 1
                expires = min(now + self.lease_seconds, parent.expires_at)
            else:
                lineage, depth = agent, 0
                if (contract_id, lineage) in self._quarantined:
                    raise LeaseError(f"{agent} is quarantined under {contract_id}; a person must restore it")
                epoch = self.current_epoch(contract_id, lineage)
                expires = now + self.lease_seconds
            lease = Lease(agent, contract_id, epoch, expires, parent.agent if parent else None, f"lease-{next(self._seq)}", lineage,
                          depth, parent.lease_id if parent else None)
            self._leases[lease.lease_id] = lease
            return lease

    def renew(self, lease: Lease, state_snapshot: int) -> Lease:
        """Extend a live lease, only against current state: an agent working from an old snapshot must re-read first."""
        now = self.clock()
        with self._lock:
            why = self._check(lease, now)
            if why:
                raise LeaseError(why)
            if int(state_snapshot) < self._snapshot.get(lease.contract_id, 0):
                raise LeaseError("renewal against stale state: re-read the portfolio first")
            cap = math.inf
            if lease.parent_lease_id is not None:
                cap = self._leases[lease.parent_lease_id].expires_at
            new = replace(lease, expires_at=min(now + self.lease_seconds, cap), lease_id=f"lease-{next(self._seq)}")
            self._leases[new.lease_id] = new
            return new

    def revoke_epoch(self, contract_id: str, epoch: int, lineage: str | None = None, *, quarantine: bool = True) -> None:
        with self._lock:
            if lineage is None:
                self._contract_revoked[contract_id] = max(self._contract_revoked.get(contract_id, -1), int(epoch))
                return
            key = (contract_id, lineage)
            self._revoked[key] = max(self._revoked.get(key, -1), int(epoch))
            self._epoch[key] = max(self._epoch.get(key, 0), int(epoch) + 1)
            if quarantine:
                self._quarantined.add(key)

    def revoke_all(self, contract_id: str) -> int:
        """The firm-wide kill: every lease issued under the contract, in every lineage, stops being valid at once."""
        with self._lock:
            top = max([l.epoch for l in self._leases.values() if l.contract_id == contract_id] + [self._contract_revoked.get(contract_id, -1)])
            self._contract_revoked[contract_id] = top
            return top

    def restore(self, contract_id: str, lineage: str) -> None:
        with self._lock:
            self._quarantined.discard((contract_id, lineage))

    def _check(self, lease: Lease, now: float) -> str | None:
        known = self._leases.get(lease.lease_id)
        if known is None or known != lease:
            return "unknown or altered lease"
        if now > lease.expires_at:
            return "lease expired"
        if lease.epoch <= self._revoked.get((lease.contract_id, lease.lineage), -1):
            return f"epoch {lease.epoch} of {lease.lineage} was revoked"
        if lease.epoch <= self._contract_revoked.get(lease.contract_id, -1):
            return f"epoch {lease.epoch} of {lease.contract_id} was revoked"
        if lease.parent_lease_id is not None:
            parent = self._leases.get(lease.parent_lease_id)
            if parent is None:
                return "parent lease unknown"
            why = self._check(parent, now)
            if why:
                return f"parent: {why}"
        return None

    def check(self, lease: Lease | None, now: float | None = None) -> str | None:
        """None if the lease is live; otherwise the reason it is not. Deterministic: a hard check."""
        if lease is None:
            return "no lease"
        with self._lock:
            return self._check(lease, self.clock() if now is None else now)


# ---------------------------------------------------------------------------------------------------------------------
# Typed intent records
# ---------------------------------------------------------------------------------------------------------------------

ACTIONS = ("open", "add", "reduce", "exit", "hedge", "rebalance")
KINDS = ("news", "fundamental", "momentum", "rebalance", "hedge", "income")


@dataclass(frozen=True)
class Claim:
    """A factual claim an agent relies on. A figure must carry a unit and cite evidence by content hash."""
    text: str
    value: float | None = None
    unit: str | None = None
    evidence_sha256: str | None = None


@dataclass(frozen=True)
class IntentRecord:
    """What an agent says it is doing, in typed fields, before an order is admitted. It is compared with the order and the signed
    objective by plain code. An agent's own explanation is not evidence of its reasoning; this record exists so the comparison can
    be made at all."""
    agent: str
    contract_id: str
    objective_id: str
    action: str
    kind: str
    symbol: str
    side: str
    quantity: float
    thesis: str
    horizon_days: float
    evidence: tuple[str, ...] = ()              # content hashes
    claims: tuple[Claim, ...] = ()
    intent_id: str = ""

    def sha256(self) -> str:
        return sha256_hex({"agent": self.agent, "contract_id": self.contract_id, "objective_id": self.objective_id, "action": self.action,
                           "kind": self.kind, "symbol": self.symbol, "side": self.side, "quantity": self.quantity, "thesis": self.thesis,
                           "horizon_days": self.horizon_days, "evidence": list(self.evidence),
                           "claims": [[c.text, c.value, c.unit, c.evidence_sha256] for c in self.claims]})


def intent_problems(rec: IntentRecord | None, order: dict, objective_id: str, position_qty: float = 0.0) -> list[str]:
    """Deterministic mismatches between an order and the intent record it claims. Any one is a hard refusal: an order that does not
    match its own intent was changed after the agent decided (a compromised tool) or was never decided by the agent."""
    if rec is None:
        return ["no intent record"]
    out = []
    if rec.objective_id != objective_id:
        out.append("intent names a different objective than the signed contract")
    if rec.action not in ACTIONS or rec.kind not in KINDS:
        out.append("intent has an unknown action or kind")
    if rec.symbol != order.get("symbol"):
        out.append(f"order symbol {order.get('symbol')} differs from intent {rec.symbol}")
    if rec.side != order.get("side"):
        out.append(f"order side {order.get('side')} differs from intent {rec.side}")
    if float(order.get("quantity", 0)) > float(rec.quantity) + 1e-9:
        out.append(f"order quantity {order.get('quantity')} exceeds the intended {rec.quantity}")
    if rec.action in ("reduce", "exit") and ((rec.side == "sell") != (position_qty > 0)):
        out.append("a reduce or exit intent must trade against the current position")
    if rec.action in ("open", "add") and not rec.evidence:
        out.append("an open or add intent cites no evidence")
    return out


VAGUE = re.compile(r"\b(huge|massive|soar\w*|skyrocket\w*|guarantee\w*|sure thing|can't lose|cannot lose|to the moon|explod\w*|"
                   r"insane|enormous|record\W*breaking|100%|risk.free)\b", re.I)


def claim_flags(rec: IntentRecord, known_hashes: set[str]) -> list[str]:
    """Statistical-free but judgement-adjacent flags on claims: figures without units or sources, claims citing evidence that
    does not exist, and vague promotional language. These only ever produce a hold."""
    out = []
    for c in rec.claims:
        if c.value is not None and not c.unit:
            out.append(f"figure without a unit: {c.text[:60]}")
        if c.evidence_sha256 is None:
            out.append(f"undeclared source for claim: {c.text[:60]}")
        elif c.evidence_sha256 not in known_hashes:
            out.append(f"claim cites evidence that does not exist: {c.text[:60]}")
        if VAGUE.search(c.text):
            out.append(f"vague figure: {c.text[:60]}")
    if VAGUE.search(rec.thesis):
        out.append("vague thesis language")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Evidence provenance
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceItem:
    sha256: str
    source_id: str
    origin: str
    observed_at: float
    text: str
    derived_from: tuple[str, ...] = ()
    trusted_feed: bool = False


@dataclass(frozen=True)
class Provenance:
    ok: bool
    independent_origins: int
    problems: tuple[str, ...]
    roots: tuple[str, ...] = ()


def _shingles(text: str, k: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9%$.]+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(1, len(words) - k + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


class EvidenceStore:
    """Evidence by content hash. Independence is judged by behaviour, not by the outlet's name: reposts that follow `derived_from`
    to one root count once, and texts that are near-copies (word 4-gram Jaccard >= `copy_threshold`) count once even when they
    claim different origins."""

    def __init__(self, copy_threshold: float = 0.5):
        self.items: dict[str, EvidenceItem] = {}
        self.copy_threshold = copy_threshold
        self._sh: dict[str, set[str]] = {}

    def register(self, source_id: str, text: str, observed_at: float, *, origin: str | None = None,
                 derived_from: tuple[str, ...] = (), trusted_feed: bool = False) -> EvidenceItem:
        h = sha256_hex(f"{source_id}\n{observed_at}\n{text}")
        item = EvidenceItem(h, source_id, origin or source_id, float(observed_at), text, tuple(derived_from), trusted_feed)
        self.items[h] = item
        self._sh[h] = _shingles(text)
        return item

    def known(self) -> set[str]:
        return set(self.items)

    def _roots(self, h: str, seen: set[str] | None = None) -> set[str]:
        seen = seen or set()
        if h in seen or h not in self.items:
            return set()
        seen.add(h)
        it = self.items[h]
        if not it.derived_from:
            return {h}
        out: set[str] = set()
        for p in it.derived_from:
            out |= self._roots(p, seen)
        return out or {h}

    def assess(self, refs: tuple[str, ...] | list[str], now: float, max_age_s: float, min_sources: int = 1) -> Provenance:
        problems = []
        live = []
        for h in refs:
            it = self.items.get(h)
            if it is None:
                problems.append(f"evidence {h[:12]} is not on record (fabricated or altered)")
                continue
            if now - it.observed_at > max_age_s:
                problems.append(f"evidence from {it.source_id} is {now - it.observed_at:.0f}s old")
                continue
            live.append(h)
        roots: set[str] = set()
        for h in live:
            roots |= self._roots(h)
        clusters: list[set[str]] = []                         # union near-copies
        for r in sorted(roots):
            merged = [c for c in clusters if any(self.items[r].origin == self.items[x].origin or
                                                 jaccard(self._sh[r], self._sh[x]) >= self.copy_threshold for x in c)]
            new = {r}.union(*merged) if merged else {r}
            clusters = [c for c in clusters if c not in merged] + [new]
        n = len(clusters)
        if n < min_sources:
            problems.append(f"{n} independent origin(s); the contract asks for {min_sources}")
        return Provenance(not problems, n, tuple(problems), tuple(sorted(roots)))


# ---------------------------------------------------------------------------------------------------------------------
# Drift: sequential change detection
# ---------------------------------------------------------------------------------------------------------------------

class ChangeDetector(Protocol):
    """Sequential change detection (CUSUM or SPRT) over one agent's behaviour statistics."""
    def update(self, value: float) -> bool: ...


@dataclass
class CUSUM:
    """One-sided upper CUSUM on a real-valued statistic: S = max(0, S + x - target - k); alarm when S > h (Page 1954)."""
    target: float
    k: float
    h: float
    s: float = 0.0

    def update(self, value: float) -> bool:
        self.s = max(0.0, self.s + float(value) - self.target - self.k)
        return self.s > self.h

    def reset(self) -> None:
        self.s = 0.0


@dataclass
class BernoulliCUSUM:
    """CUSUM on the log-likelihood ratio of a Bernoulli stream, p0 (in control) against p1 (drifted). Minimax-optimal detection delay
    for a given false-alarm rate (Lorden; Moustakides). h = log(1/false-alarm budget) is a conservative threshold."""
    p0: float
    p1: float
    h: float
    s: float = 0.0
    n: int = 0

    def __post_init__(self):
        if not 0 < self.p0 < self.p1 < 1:
            raise ValueError("need 0 < p0 < p1 < 1")
        self._up = math.log(self.p1 / self.p0)
        self._down = math.log((1 - self.p1) / (1 - self.p0))

    def update(self, value: float) -> bool:
        self.n += 1
        self.s = max(0.0, self.s + (self._up if value else self._down))
        return self.s > self.h


@dataclass
class SPRT:
    """Wald's sequential probability ratio test for a Bernoulli rate: returns 'h1', 'h0' or None (keep sampling)."""
    p0: float
    p1: float
    alpha: float = 0.01
    beta: float = 0.05
    llr: float = 0.0

    def update(self, value: float) -> str | None:
        self.llr += math.log(self.p1 / self.p0) if value else math.log((1 - self.p1) / (1 - self.p0))
        if self.llr >= math.log((1 - self.beta) / self.alpha):
            return "h1"
        if self.llr <= math.log(self.beta / (1 - self.alpha)):
            return "h0"
        return None


def style_distance(weights: dict[str, float], target: dict[str, float]) -> float:
    """Total-variation distance between two sector mixes (0 = identical, 1 = disjoint)."""
    tw, tt = sum(abs(v) for v in weights.values()), sum(target.values())
    if tw <= 0 or tt <= 0:
        return 0.0
    keys = set(weights) | set(target)
    return 0.5 * sum(abs(abs(weights.get(k, 0.0)) / tw - target.get(k, 0.0) / tt) for k in keys)


@dataclass
class DriftMonitor:
    """Is one agent still doing what the signed objective says? Two statistics, both on what the agent did, not what it said:

    1. A Bernoulli CUSUM on "this risk-adding order is off-objective" (its sector has less than `min_weight` in the objective's
       signed style). In control the rate is at most `p0` (the objective tolerates some tactical trades); drift is a rate of `p1`.
    2. The style distance of the agent's own book from the signed mix, once it holds enough to measure.

    Either alarm asks for review. Neither can approve anything."""
    style: dict[str, float]
    sectors: dict[str, str]
    p0: float = 0.15
    p1: float = 0.45
    h: float = 6.0              # measured: about 1.4% false alarms per 300 in-control orders, median delay 20 orders at rate 0.45
    min_weight: float = 0.05
    max_style_distance: float = 0.6
    min_book_usd: float = 0.0
    detectors: dict = field(default_factory=dict)
    alarmed: dict = field(default_factory=dict)

    def off_objective(self, symbol: str) -> bool:
        return self.style.get(self.sectors.get(symbol, "?"), 0.0) < self.min_weight

    def update(self, agent: str, symbol: str, adds_risk: bool, step: int | None = None) -> bool:
        if not adds_risk:
            return agent in self.alarmed
        det = self.detectors.setdefault(agent, BernoulliCUSUM(self.p0, self.p1, self.h))
        if det.update(1.0 if self.off_objective(symbol) else 0.0) and agent not in self.alarmed:
            self.alarmed[agent] = step
        return agent in self.alarmed

    def book_distance(self, book_usd: dict[str, float]) -> float:
        by_sector: dict[str, float] = defaultdict(float)
        for s, v in book_usd.items():
            by_sector[self.sectors.get(s, "?")] += abs(v)
        return style_distance(by_sector, self.style)

    def check(self, agent: str, book_usd: dict[str, float]) -> list[str]:
        out = []
        if agent in self.alarmed:
            out.append("drift: off-objective trading rate has shifted (CUSUM alarm)")
        gross = sum(abs(v) for v in book_usd.values())
        if gross > self.min_book_usd and gross > 0:
            d = self.book_distance(book_usd)
            if d > self.max_style_distance:
                out.append(f"drift: the agent's book is {d:.2f} from the signed style (limit {self.max_style_distance:.2f})")
        return out


# ---------------------------------------------------------------------------------------------------------------------
# Herding, loops, pacing
# ---------------------------------------------------------------------------------------------------------------------

def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def flow_vectors(orders: list[dict]) -> dict[str, dict[str, float]]:
    flows: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for o in orders:
        flows[o["agent"]][o["symbol"]] += (1 if o["side"] == "buy" else -1) * float(o["notional"])
    return {a: dict(v) for a, v in flows.items()}


def herding_clusters(orders: list[dict], min_similarity: float = 0.8, min_size: int = 3) -> list[set[str]]:
    """Groups of agents whose recent signed order flow points the same way (cosine >= min_similarity), as connected components.
    Keyed only on behaviour: an agent's declared identity, book or strategy label plays no part."""
    flows = flow_vectors(orders)
    agents = sorted(flows)
    parent = {a: a for a in agents}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, a in enumerate(agents):
        for b in agents[i + 1:]:
            if _cos(flows[a], flows[b]) >= min_similarity:
                parent[find(a)] = find(b)
    groups: dict[str, set[str]] = defaultdict(set)
    for a in agents:
        groups[find(a)].add(a)
    return [g for g in groups.values() if len(g) >= min_size]


def herding_signal(orders: list[dict], evidence: dict[str, list[str]]) -> float:
    """How much supposedly independent agents are trading together and on the same sources, in [0, 1].

    For the largest-flow behavioural cluster: its share of all order flow, times the mean pairwise flow similarity inside it, scaled
    up when its members cite the same evidence roots (shared sources make co-movement a correlation signal, not independent
    opinions). 0 when no cluster of three or more agents exists."""
    clusters = herding_clusters(orders)
    if not clusters:
        return 0.0
    flows = flow_vectors(orders)
    total = sum(sum(abs(v) for v in f.values()) for f in flows.values()) or 1.0
    best = 0.0
    for g in clusters:
        share = sum(sum(abs(v) for v in flows[a].values()) for a in g) / total
        pairs = list(itertools.combinations(sorted(g), 2))
        sim = sum(_cos(flows[a], flows[b]) for a, b in pairs) / len(pairs)
        ev = [set(evidence.get(a, [])) for a in g]
        overlap = sum(jaccard(x, y) for x, y in itertools.combinations(ev, 2)) / len(pairs) if pairs else 0.0
        best = max(best, min(1.0, share * sim * (0.5 + 0.5 * overlap)))
    return best


class HerdingMonitor:
    """Caps the combined new exposure of a behavioural cluster. Clusters are re-derived from the last `window` orders every
    `refresh` orders. An order from a cluster member that would take the cluster's net buying in one symbol group (sector) past
    `cluster_cap_usd` is held. Tighten only."""

    def __init__(self, sectors: dict[str, str], cluster_cap_usd: float, *, window: int = 400, refresh: int = 25,
                 min_similarity: float = 0.8, min_size: int = 3):
        self.sectors, self.cap = sectors, float(cluster_cap_usd)
        self.recent: deque = deque(maxlen=window)
        self.refresh, self.min_similarity, self.min_size = refresh, min_similarity, min_size
        self.clusters: list[set[str]] = []
        self._member: dict[str, int] = {}
        self._n = 0
        self.net: dict[tuple[int, str], float] = defaultdict(float)
        self._agent_net: dict[tuple[str, str], float] = defaultdict(float)

    def observe(self, agent: str, symbol: str, side: str, notional: float) -> None:
        self.recent.append({"agent": agent, "symbol": symbol, "side": side, "notional": notional})
        sec = self.sectors.get(symbol, "?")
        self._agent_net[(agent, sec)] += (1 if side == "buy" else -1) * notional
        self._n += 1
        if self._n % self.refresh == 0:
            self.clusters = herding_clusters(list(self.recent), self.min_similarity, self.min_size)
            self._member = {a: i for i, g in enumerate(self.clusters) for a in g}

    def cluster_of(self, agent: str) -> set[str] | None:
        i = self._member.get(agent)
        return self.clusters[i] if i is not None else None

    def check(self, agent: str, symbol: str, side: str, notional: float) -> str | None:
        g = self.cluster_of(agent)
        if g is None or side != "buy":
            return None
        sec = self.sectors.get(symbol, "?")
        net = sum(self._agent_net[(a, sec)] for a in g)
        if net + notional > self.cap:
            return f"herding: {len(g)} agents trading together already hold ${net:,.0f} net in {sec}; cluster cap ${self.cap:,.0f}"
        return None


def _shape(args: str) -> str:
    return re.sub(r"\d+(\.\d+)?", lambda m: f"{float(m.group(0)):.2g}", args)


def loop_signal(actions: list[tuple[str, str]]) -> float:
    """Repetition in an agent's (tool, arguments) sequence, rising with frequency: 1 - distinct/len over the window, with numbers
    rounded to two significant figures so near-identical calls count as repeats. 0 for fewer than 4 actions."""
    if len(actions) < 4:
        return 0.0
    shapes = [(t, _shape(a)) for t, a in actions]
    return 1.0 - len(set(shapes)) / len(shapes)


@dataclass
class PacingController:
    """Spend of a day's budget treated as a control problem. By step t of T, an agent may have used at most
    share x budget x min(1, (t + 1) / T x (1 + slack)) + floor. It never loosens anything signed; it only holds orders that would
    run ahead of plan, so one fast agent or coalition cannot starve the rest."""
    budget_usd: float
    steps: int
    agents: tuple[str, ...]
    slack: float = 0.5
    floor_usd: float = 0.0
    spent: dict = field(default_factory=lambda: defaultdict(float))

    def allowance(self, agent: str, step: int) -> float:
        share = 1.0 / max(1, len(self.agents))
        return share * self.budget_usd * min(1.0, (step + 1) / self.steps * (1 + self.slack)) + self.floor_usd

    def check(self, agent: str, step: int, notional: float) -> str | None:
        allow = self.allowance(agent, step)
        if self.spent[agent] + notional > allow + 1e-6:
            return f"pacing: ${self.spent[agent] + notional:,.0f} would run ahead of this agent's ${allow:,.0f} plan so far"
        return None

    def record(self, agent: str, notional: float) -> None:
        self.spent[agent] += float(notional)


# ---------------------------------------------------------------------------------------------------------------------
# One turn of the loop
# ---------------------------------------------------------------------------------------------------------------------

THRESHOLDS = {"loop_tighten": 0.5, "loop_suspend": 0.8, "herding_tighten": 0.35, "judgement_review": 0.5}


def step(observation: dict) -> Control:
    """One turn of the loop: what to do with this agent or coalition now.

    observation keys (all optional): lease_problem (str), intent_mismatch (bool), tool_compromise (bool), drift_alarm (bool),
    provenance_problems (list), claim_flags (list), herding (float or str), loop (float), pacing (str), judgement_p (float)."""
    if not isinstance(observation, dict):
        raise TypeError("observation must be a dict")
    c = Control.CONTINUE
    loop = float(observation.get("loop", 0.0) or 0.0)
    if observation.get("lease_problem") or observation.get("intent_mismatch") or observation.get("tool_compromise") \
            or loop >= THRESHOLDS["loop_suspend"]:
        return Control.SUSPEND_NEW_RISK
    if observation.get("drift_alarm") or observation.get("provenance_problems") or observation.get("claim_flags") \
            or float(observation.get("judgement_p", 0.0) or 0.0) >= THRESHOLDS["judgement_review"]:
        c = stricter(c, Control.REVIEW)
    h = observation.get("herding", 0.0)
    if (isinstance(h, str) and h) or (isinstance(h, (int, float)) and h >= THRESHOLDS["herding_tighten"]) \
            or observation.get("pacing") or loop >= THRESHOLDS["loop_tighten"]:
        c = stricter(c, Control.TIGHTEN)
    return c
