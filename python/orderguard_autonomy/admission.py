"""The admission controller (design section 2).

Order of evaluation, and the rule that binds it: hard predicates from the signed contract decide first and can refuse; model-based
checks (incremental risk, drift, herding, evidence quality, the judgement model) run after and can only hold or tighten. Nothing a
model returns can turn a refusal into an allowance.

One `admit` call, all under the ledger's single-writer lock so admission is linearizable:

    1. idempotency      a repeated idempotency key never creates a second order or reservation
    2. authority        contract signature and version, agent named, lease live, intent record matches the order
    3. hard predicates  compiled from the contract and evaluated on the conservative projection (filled + working + this order):
                        permissions, per-order size, price band, no short, gross, issuer, sector, declared-scenario loss, rate,
                        state freshness, review threshold
    4. escrow           the agent's node in the firm -> book -> agent escrow must be able to hold the order's dollars
    5. model checks     risk budget (standalone ES reserved per order), estimated portfolio ES, evidence provenance, claim flags,
                        drift, herding, pacing, loops, an optional judgement model: each can only hold (or, for an agent the
                        supervisor has suspended, refuse new risk)
    6. combine          the stricter of hard and model; ALLOW and HOLD reserve capacity, ALLOW gets a signed certificate
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from . import contract as C
from . import risk as R
from .certificate import DecisionCertificate, EvidenceRef, issue
from .state import (EscrowExhausted, EscrowNode, L, Lifecycle, ReservationLedger, WORKING, WorkingOrder, order_dict,
                    reconcile_events)
from .supervise import (Control, DriftMonitor, EvidenceStore, HerdingMonitor, IntentRecord, LeaseAuthority, Lease, PacingController,
                        claim_flags, intent_problems, loop_signal, step as supervise_step)


class Decision(str, Enum):
    ALLOW = "allow"
    HOLD = "hold"
    REFUSE = "refuse"


@dataclass(frozen=True)
class Admission:
    decision: Decision
    hard_reasons: tuple[str, ...]
    model_reasons: tuple[str, ...]
    reservation_id: str | None
    order_id: str | None = None
    certificate: DecisionCertificate | None = None
    control: str = "continue"
    latency_us: float = 0.0


def combine(hard: Decision, model: Decision) -> Decision:
    """The tighten-only rule: the stricter of the two, and a hard refusal always stands."""
    order = [Decision.ALLOW, Decision.HOLD, Decision.REFUSE]
    return max(hard, model, key=order.index)


@dataclass(frozen=True)
class ActionRequest:
    """What an agent asks for: one order, its idempotency key, the typed intent it claims, and the lease it holds."""
    agent: str
    symbol: str
    side: str
    quantity: float
    limit_price: float
    idempotency_key: str
    intent: IntentRecord | None = None
    lease: Lease | None = None
    venue: str = "default"
    strategy_version: str = "v1"

    def order(self) -> dict:
        return {"symbol": self.symbol, "side": self.side, "quantity": float(self.quantity), "limit_price": float(self.limit_price)}


def _bounds_all(state) -> dict[str, tuple[float, float]]:
    buys: dict[str, float] = defaultdict(float)
    sells: dict[str, float] = defaultdict(float)
    for o in state.working.values():
        if o.state in WORKING:
            (buys if o.side == "buy" else sells)[o.symbol] += o.remaining
    out = {}
    for s in set(state.positions) | set(buys) | set(sells):
        p = float(state.positions.get(s, 0.0))
        out[s] = (p - sells.get(s, 0.0), p + buys.get(s, 0.0))
    return out


def _mag(b: tuple[float, float]) -> float:
    return max(abs(b[0]), abs(b[1]))


@dataclass
class SupervisionConfig:
    """Which supervision checks run. All of them can only hold or tighten."""
    risk_budget: bool = True
    portfolio_es: bool = True
    provenance: bool = True
    claims: bool = True
    drift: bool = True
    herding: bool = True
    pacing: bool = True
    loops: bool = True
    judgement: bool = True


class AdmissionController:
    def __init__(self, contract: C.AutonomyContract, ledger: ReservationLedger, agent_nodes: dict[str, EscrowNode], *,
                 risk_model: R.CovarianceModel | None = None, trusted_owner_keys: set[str] | None = None,
                 leases: LeaseAuthority | None = None, evidence: EvidenceStore | None = None, drift: DriftMonitor | None = None,
                 herding: HerdingMonitor | None = None, pacing: PacingController | None = None, judgement=None,
                 judgement_hold_at: float = 0.5, regime: R.RegimeDetector | None = None, issuer_key=None,
                 clock: Callable[[], float] = time.time, step_clock: Callable[[], int] | None = None, require_intent: bool = True,
                 supervision: SupervisionConfig | None = None, es_df: float | None = 5.0):
        self.contract, self.ledger, self.nodes = contract, ledger, agent_nodes
        self.risk_model, self.leases, self.evidence = risk_model, leases, evidence
        self.drift, self.herding, self.pacing, self.judgement = drift, herding, pacing, judgement
        self.judgement_hold_at = judgement_hold_at
        self.regime, self.issuer_key, self.clock = regime, issuer_key, clock
        self.step_clock = step_clock or (lambda: 0)
        self.require_intent = require_intent
        self.sup = supervision or SupervisionConfig()
        self.es_df = es_df
        self.trusted_owner_keys = trusted_owner_keys
        self.predicates = C.compile_predicates(contract)
        self.alpha = float(contract.portfolio["es_alpha"])
        self._contract_ok: dict[str, list[str]] = {}
        self._recent: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._actions: dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._res_of: dict[str, tuple[str, EscrowNode, float, float]] = {}
        self.held: dict[str, ActionRequest] = {}
        self._seq = 0
        self.suspended: set[str] = set()
        self.sectors = contract.portfolio["sectors"]
        if ledger.state.policy_versions.get(contract.contract_id) != contract.version:
            ledger.set_policy(contract.contract_id, contract.version)

    # ---- helpers ---------------------------------------------------------------------------------------------------
    def _contract_problems(self, c: C.AutonomyContract) -> list[str]:
        h = c.sha256() + c.signature
        if h not in self._contract_ok:
            self._contract_ok[h] = C.verify_contract(c, self.trusted_owner_keys)
        return self._contract_ok[h]

    def _adds_risk(self, state, req: ActionRequest) -> bool:
        pos = float(state.positions.get(req.symbol, 0.0))
        signed = req.quantity if req.side == "buy" else -req.quantity
        return not (pos * signed < 0 and abs(signed) <= abs(pos) + 1e-9)

    def _agent_book(self, state, agent: str) -> dict[str, float]:
        return {s: q * state.marks.get(s, 0.0) for s, q in state.agent_positions.get(agent, {}).items() if q}

    def context(self, req: ActionRequest, state, now: float) -> C.OrderContext:
        """The conservative projection the predicates are evaluated on."""
        mark = state.marks.get(req.symbol)
        sign = 1.0 if req.side == "buy" else -1.0
        q = float(req.quantity)
        notional = q * float(mark) if mark else q * float(req.limit_price)
        bounds = _bounds_all(state)
        b0 = bounds.get(req.symbol, (0.0, 0.0))
        b1 = (b0[0] + min(sign * q, 0.0), b0[1] + max(sign * q, 0.0))
        m = float(mark or req.limit_price)
        issuer_before, issuer_after = _mag(b0) * m, _mag(b1) * m
        sec = self.sectors.get(req.symbol, "?")
        sector_before = sum(_mag(b) * state.marks.get(s, 0.0) for s, b in bounds.items() if self.sectors.get(s) == sec)
        gross_before = sum(_mag(b) * state.marks.get(s, 0.0) for s, b in bounds.items())
        delta = issuer_after - issuer_before
        base_usd = {s: p * state.marks.get(s, 0.0) for s, p in state.positions.items() if p}
        pending = [{o.symbol: o.sign * o.remaining * state.marks.get(o.symbol, o.limit_price)} for o in state.working.values() if o.state in WORKING]
        scns = self.contract.scenarios()
        scen_before = R.worst_case_scenario_loss(base_usd, pending, scns, self.sectors)
        scen_after = R.worst_case_scenario_loss(base_usd, pending + [{req.symbol: sign * notional}], scns, self.sectors)
        risk_units, risk_available, es_b, es_a = 0.0, float("inf"), 0.0, 0.0
        stressed = bool(self.regime and self.regime.stressed)
        if self.risk_model is not None and mark:
            order_vec = {req.symbol: sign * notional}
            risk_units = R.reservable_risk(self.risk_model, order_vec, self.alpha, df=self.es_df, stressed=stressed)
            node = self.nodes.get(req.agent)
            if node is not None:
                risk_available = node.obtainable()[1]        # read-only: capacity moves down only when an order is reserved
            proj = dict(base_usd)
            for d in pending:
                for s, v in d.items():
                    proj[s] = proj.get(s, 0.0) + v
            es_b = R.expected_shortfall(self.risk_model, proj, self.alpha, df=self.es_df, stressed=stressed)
            proj[req.symbol] = proj.get(req.symbol, 0.0) + sign * notional
            es_a = R.expected_shortfall(self.risk_model, proj, self.alpha, df=self.es_df, stressed=stressed)
        recent = self._recent[req.agent]
        while recent and now - recent[0] > 60.0:
            recent.popleft()
        lease_problem = None
        if self.leases is not None:
            lease_problem = self.leases.check(req.lease, now)
            if lease_problem is None and req.lease is not None and (req.lease.agent != req.agent or req.lease.contract_id != self.contract.contract_id):
                lease_problem = "lease belongs to a different agent or contract"
        return C.OrderContext(
            agent=req.agent, symbol=req.symbol, side=req.side, quantity=q, limit_price=float(req.limit_price), mark=mark,
            notional=notional, now=now, lease_problem=lease_problem, orders_last_minute=len(recent),
            issuer_before=issuer_before, issuer_after=issuer_after, sector_before=sector_before, sector_after=sector_before + delta,
            gross_before=gross_before, gross_after=gross_before + delta, short_after=b1[0], scenario_before=scen_before,
            scenario_after=scen_after, state_age_s=max(0.0, now - state.marks_as_of), risk_units=risk_units,
            risk_available=risk_available, es_before=es_b, es_after=es_a)

    # ---- admit -----------------------------------------------------------------------------------------------------
    def admit(self, request: ActionRequest, contract: C.AutonomyContract | None = None, state=None) -> Admission:
        """Evaluate one proposed action against the signed contract and the projected portfolio state."""
        t0 = time.perf_counter()
        contract = contract or self.contract
        with self.ledger.lock:
            state = self.ledger.state
            now = self.clock()
            if request.idempotency_key in state.by_key:
                oid = state.by_key[request.idempotency_key]
                return Admission(Decision.REFUSE, (f"duplicate idempotency key: already order {oid}",), (), None, oid,
                                 latency_us=(time.perf_counter() - t0) * 1e6)
            hard: list[str] = []
            hard_hold: list[str] = []
            model: list[str] = []
            if contract.contract_id != self.contract.contract_id:
                hard.append("request names a contract this controller does not enforce")
            hard += [f"contract: {p}" for p in self._contract_problems(contract)]
            if state.policy_versions.get(contract.contract_id) != contract.version:
                hard.append(f"contract version {contract.version} is not the version on the ledger")
            adds_risk = self._adds_risk(state, request)
            ctx = self.context(request, state, now)
            for p in self.predicates:
                if not p.hard or p.check is None:
                    continue
                why = p.check(ctx)
                if why:
                    (hard if p.on_fail == "refuse" else hard_hold).append(why)
            pos = float(state.positions.get(request.symbol, 0.0))
            mismatch = []
            if self.require_intent:
                mismatch = intent_problems(request.intent, {**request.order()}, contract.autonomy["objective"]["id"], pos)
                if request.intent is not None and (request.intent.agent != request.agent or request.intent.contract_id != contract.contract_id):
                    mismatch.append("intent record belongs to a different agent or contract")
                hard += [f"intent: {m}" for m in mismatch]
            node = self.nodes.get(request.agent)
            reserve_usd = max(ctx.notional, float(request.quantity) * float(request.limit_price))
            if node is None:
                hard.append(f"agent {request.agent} has no escrow allocation")
            elif adds_risk and not hard and node.obtainable()[0] + 1e-6 < reserve_usd:
                hard.append(f"escrow: {node.path} cannot obtain ${reserve_usd:,.0f} of capacity from its book or firm")
            hard_decision = Decision.REFUSE if hard else Decision.HOLD if hard_hold else Decision.ALLOW

            model_decision, control = Decision.ALLOW, Control.CONTINUE
            if hard_decision != Decision.REFUSE:
                model_decision, control, model = self._model_checks(request, ctx, state, now, adds_risk, bool(mismatch))
            final = combine(hard_decision, model_decision)
            if mismatch:
                self.quarantine(request.agent, reason="order does not match its intent record")
            if final == Decision.REFUSE:
                return Admission(final, tuple(hard), tuple(model), None, control=control.value,
                                 latency_us=(time.perf_counter() - t0) * 1e6)
            # reserve: ALLOW and HOLD both hold capacity, so an approval later cannot oversubscribe
            self._seq += 1
            oid = f"{request.agent}-{self._seq}"
            wo = WorkingOrder(oid, request.agent, contract.contract_id, request.symbol, request.side, float(request.quantity), 0.0,
                              float(request.limit_price), L.RISK_RESERVED, request.idempotency_key, request.venue)
            usd = reserve_usd if adds_risk else 0.0
            risk = ctx.risk_units if adds_risk else 0.0
            if final == Decision.HOLD:
                # A model-based shortfall must stay a hold, never become a refusal: a held order reserves its dollars (a hard
                # resource) and only the risk budget that is actually available. A person approving it decides about the rest.
                risk = min(risk, node.obtainable()[1])
            try:
                res = node.reserve(wo, usd, risk)
            except EscrowExhausted as e:
                return Admission(Decision.REFUSE, tuple(hard) + (f"escrow: {e}",), tuple(model), None, control=control.value,
                                 latency_us=(time.perf_counter() - t0) * 1e6)
            self.ledger.append({"kind": "reserve", "order": order_dict(wo),
                                "reservation": {"reservation_id": res.reservation_id, "order_id": oid, "domain": res.domain,
                                                "notional_usd": res.notional_usd, "risk_units": res.risk_units}})
            self._res_of[oid] = (res.reservation_id, node, res.notional_usd, res.risk_units)
            self._recent[request.agent].append(now)
            cert = None
            if final == Decision.ALLOW:
                self._observe_allowed(request, ctx)
                cert = self._certificate(request, contract, oid, res.reservation_id, now)
            else:
                self.held[oid] = request
            return Admission(final, tuple(hard + hard_hold), tuple(model), res.reservation_id, oid, cert, control.value,
                             (time.perf_counter() - t0) * 1e6)

    def _model_checks(self, req: ActionRequest, ctx: C.OrderContext, state, now: float, adds_risk: bool,
                      mismatch: bool) -> tuple[Decision, Control, list[str]]:
        reasons: list[str] = []
        obs: dict = {"intent_mismatch": mismatch}
        if adds_risk:
            for p in self.predicates:
                if p.hard or p.check is None:
                    continue
                if (p.name == "risk_budget" and not self.sup.risk_budget) or (p.name == "portfolio_es" and not self.sup.portfolio_es):
                    continue
                why = p.check(ctx)
                if why:
                    reasons.append(why)
        if req.agent in self.suspended:
            obs["tool_compromise"] = True
            reasons.append("agent is suspended from new risk pending review")
        rec = req.intent
        if rec is not None and self.evidence is not None:
            if self.sup.provenance and adds_risk:
                need = int(self.contract.autonomy["min_independent_sources"]) if rec.kind == "news" else 1
                prov = self.evidence.assess(rec.evidence, now, float(self.contract.autonomy["max_evidence_age_s"]), need)
                if not prov.ok:
                    obs["provenance_problems"] = list(prov.problems)
                    reasons += [f"evidence: {p}" for p in prov.problems]
            if self.sup.claims:
                flags = claim_flags(rec, self.evidence.known())
                if flags:
                    obs["claim_flags"] = flags
                    reasons += [f"claims: {f}" for f in flags]
        if self.drift is not None and self.sup.drift:
            self.drift.update(req.agent, req.symbol, adds_risk, self.step_clock())
            if adds_risk:
                d = self.drift.check(req.agent, self._agent_book(state, req.agent))
                if d:
                    obs["drift_alarm"] = True
                    reasons += d
        if self.herding is not None and self.sup.herding and adds_risk:
            h = self.herding.check(req.agent, req.symbol, req.side, ctx.notional)
            if h:
                obs["herding"] = h
                reasons.append(h)
        if self.pacing is not None and self.sup.pacing and adds_risk:
            p = self.pacing.check(req.agent, self.step_clock(), ctx.notional)
            if p:
                obs["pacing"] = p
                reasons.append(p)
        if self.sup.loops:
            acts = self._actions[req.agent]
            acts.append(("order", f"{req.symbol} {req.side} {req.quantity} {req.limit_price}"))
            lp = loop_signal(list(acts))
            obs["loop"] = lp
            if lp >= 0.5:
                reasons.append(f"loop: {lp:.0%} of this agent's recent orders repeat")
        if self.judgement is not None and self.sup.judgement and rec is not None:
            try:
                p, why = self.judgement.score_request(req, state, self.contract, self.evidence)
            except Exception as e:                           # a failing model degrades to no advice; it never blocks or allows
                p, why = 0.0, f"judgement unavailable: {type(e).__name__}"
            obs["judgement_p"] = p
            if p >= self.judgement_hold_at:
                reasons.append(f"judgement: {why} (p={p:.2f})")
        control = supervise_step(obs)
        if any(r.startswith(("order needs", "estimated ES")) for r in reasons):
            control = max(control, Control.TIGHTEN, key=[Control.CONTINUE, Control.TIGHTEN, Control.REVIEW, Control.SUSPEND_NEW_RISK].index)
        if control == Control.SUSPEND_NEW_RISK:
            return (Decision.REFUSE if adds_risk else Decision.ALLOW), control, reasons
        if control in (Control.REVIEW, Control.TIGHTEN) and adds_risk:
            return Decision.HOLD, control, reasons
        return Decision.ALLOW, control, reasons

    def _observe_allowed(self, req: ActionRequest, ctx: C.OrderContext) -> None:
        if self.herding is not None:
            self.herding.observe(req.agent, req.symbol, req.side, ctx.notional)
        if self.pacing is not None and self._adds_risk(self.ledger.state, req):
            self.pacing.record(req.agent, ctx.notional)

    def _certificate(self, req: ActionRequest, contract: C.AutonomyContract, oid: str, rid: str, now: float) -> DecisionCertificate | None:
        if self.issuer_key is None:
            return None
        ev = ()
        if req.intent is not None and self.evidence is not None:
            ev = tuple(EvidenceRef(self.evidence.items[h].source_id, h, self.evidence.items[h].observed_at)
                       for h in req.intent.evidence if h in self.evidence.items)
        lease = req.lease
        cert = DecisionCertificate(order=req.order(), agent_id=req.agent, strategy_version=req.strategy_version,
                                   contract_id=contract.contract_id, policy_version=contract.version,
                                   objective_id=contract.autonomy["objective"]["id"], evidence=ev,
                                   portfolio_snapshot=self.ledger.state.snapshot, reservation_id=rid, contract_sha256=contract.sha256(),
                                   intent_sha256=req.intent.sha256() if req.intent else "", lease_id=lease.lease_id if lease else "",
                                   lease_epoch=lease.epoch if lease else 0, lineage=lease.lineage if lease else "", order_id=oid,
                                   issued_at=now, decision="allow")
        return issue(cert, self.issuer_key)

    # ---- human review ----------------------------------------------------------------------------------------------
    def resolve_hold(self, order_id: str, approve: bool) -> DecisionCertificate | None:
        """A person decides a held order. Approval uses the capacity reserved when it was held; denial releases it."""
        with self.ledger.lock:
            req = self.held.pop(order_id)
            if not approve:
                self.on_terminal(order_id, Lifecycle.CANCELED, 0.0)
                return None
            ctx = self.context(req, self.ledger.state, self.clock())
            self._observe_allowed(req, ctx)
            return self._certificate(req, self.contract, order_id, self._res_of[order_id][0], self.clock())

    # ---- lifecycle from the broker ---------------------------------------------------------------------------------
    def on_status(self, order_id: str, to: Lifecycle, filled: float | None = None) -> None:
        with self.ledger.lock:
            wo = self.ledger.state.working[order_id]
            if to in (L.FILLED, L.CANCELED, L.REJECTED):
                self.on_terminal(order_id, to, wo.filled if filled is None else filled)
            else:
                self.ledger.transition(order_id, to, filled)

    def on_terminal(self, order_id: str, to: Lifecycle, filled: float) -> None:
        with self.ledger.lock:
            wo = self.ledger.state.working[order_id]
            if wo.state == L.RISK_RESERVED and to in (L.FILLED,):
                self.ledger.transition(order_id, L.SUBMITTED)
            self.ledger.transition(order_id, to, filled)
            entry = self._res_of.pop(order_id, None)
            if entry is not None:
                rid, node, usd, risk = entry
                frac = (float(filled) / wo.quantity) if wo.quantity else 0.0
                node.settle(rid, usd * frac, risk * frac)
                self.ledger.append({"kind": "release", "reservation_id": rid})

    def reconcile(self, broker_orders: list[dict], broker_positions: dict[str, float] | None, *, complete: bool = False) -> list[dict]:
        """Bring the ledger in line with the broker, settle the escrow, and re-measure filled risk with Euler allocation."""
        with self.ledger.lock:
            events = reconcile_events(self.ledger.state, broker_orders, broker_positions, complete=complete)
            for ev in events:
                if ev["kind"] == "transition" and Lifecycle(ev["to"]) in (L.FILLED, L.CANCELED, L.REJECTED):
                    self.on_terminal(ev["order_id"], Lifecycle(ev["to"]), float(ev.get("filled", self.ledger.state.working[ev["order_id"]].filled)))
                elif ev["kind"] == "release":
                    continue                                   # on_terminal released it
                else:
                    self.ledger.append(ev)
            self.rebase()
            return events

    def rebase(self) -> None:
        """Re-measure every agent's filled exposure: gross dollars at marks, and its Euler share of the book's ES."""
        state = self.ledger.state
        books = {a: self._agent_book(state, a) for a in self.nodes}
        risk = {a: 0.0 for a in self.nodes}
        if self.risk_model is not None:
            stressed = bool(self.regime and self.regime.stressed)
            risk = R.group_euler(self.risk_model, books, self.alpha, df=self.es_df, stressed=stressed)
        for a, node in self.nodes.items():
            node.rebase_filled(sum(abs(v) for v in books[a].values()), max(0.0, risk.get(a, 0.0)))

    # ---- authority -------------------------------------------------------------------------------------------------
    def quarantine(self, agent: str, reason: str = "") -> None:
        """Suspend new risk for an agent and revoke its lineage's epoch, which ends every lease it spawned at once."""
        self.suspended.add(agent)
        if self.leases is not None:
            ep = self.leases.current_epoch(self.contract.contract_id, agent)
            self.leases.revoke_epoch(self.contract.contract_id, ep, lineage=agent)
            self.ledger.append({"kind": "revoke_epoch", "contract_id": f"{self.contract.contract_id}/{agent}", "epoch": ep,
                                "reason": reason})

    def set_marks(self, marks: dict[str, float], as_of: float) -> None:
        self.ledger.set_marks(marks, as_of)
        if self.leases is not None:
            self.leases.observe_snapshot(self.contract.contract_id, self.ledger.state.snapshot)
