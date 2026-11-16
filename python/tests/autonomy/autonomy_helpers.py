"""Shared builders for the autonomy tests: a small signed contract, a ledger, an escrow tree and a controller."""
import numpy as np

from orderguard_autonomy import contract as C, risk as R, state as S, supervise as V
from orderguard_autonomy._crypto import key_from_label, public_b64
from orderguard_autonomy.admission import ActionRequest, AdmissionController

SECTORS = {"AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "KO": "staples", "JNJ": "healthcare", "SPY": "index", "XOM": "energy"}
OWNER = key_from_label("test-owner")
ADMIT = key_from_label("test-admission")
LEDGER = key_from_label("test-ledger")
RECEIVER = key_from_label("test-receiver")


def base_limits(**over):
    lim = C.RuleProposer(tuple(SECTORS), SECTORS).propose(C.Intent("Grow $100k, diversified", "owner")).limits
    lim.update({"portfolio.max_issuer_weight": 0.20, "portfolio.max_sector_weight": 0.35, "trading.max_order_usd": 10_000.0,
                "autonomy.review_above_usd": 9_000.0, "portfolio.max_scenario_loss_usd": 30_000.0,
                "portfolio.risk_budget_usd": 20_000.0})
    lim.update(over)
    return lim


def make_contract(agents=("a1", "a2", "a3"), cid="c1", **over):
    return C.sign_contract(C.contract_from_limits(base_limits(**over), contract_id=cid, principal="owner", agents=agents), OWNER)


def make_cov(symbols=tuple(SECTORS), vol=0.02, rho=0.3):
    n = len(symbols)
    cov = np.full((n, n), rho * vol * vol)
    np.fill_diagonal(cov, vol * vol)
    return R.StaticCovariance(list(symbols), cov)


class Clock:
    def __init__(self, t=1_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make_controller(contract=None, *, agent_limit=60_000.0, firm=100_000.0, risk_firm=20_000.0, risk_agent=12_000.0, model=True,
                    leases=True, supervision=None, **kw):
    contract = contract or make_contract()
    clock = kw.pop("clock", None) or Clock()
    ledger = S.ReservationLedger(signing_key=LEDGER, checkpoint_every=8)
    root = S.EscrowNode("firm", firm, risk_firm)
    book = S.EscrowNode("book", 0, 0, root, limit_usd=firm, risk_limit=risk_firm)
    nodes = {a: S.EscrowNode(a, 0, 0, book, limit_usd=agent_limit, risk_limit=risk_agent) for a in contract.authorized_agents}
    la = V.LeaseAuthority(clock=clock, lease_seconds=300) if leases else None
    ev = kw.pop("evidence", None) or V.EvidenceStore()
    ctl = AdmissionController(contract, ledger, nodes, risk_model=make_cov() if model else None, trusted_owner_keys={public_b64(OWNER)},
                              leases=la, evidence=ev, issuer_key=ADMIT, clock=clock, supervision=supervision, **kw)
    ctl.set_marks({s: 100.0 for s in SECTORS}, clock())
    ctl.test_clock, ctl.root, ctl.book = clock, root, book
    ctl.test_leases = {a: la.grant(a, contract.contract_id) for a in contract.authorized_agents} if la else {}
    ctl.doc = ev.register("wire", "Quarterly filing shows revenue of 90 billion dollars", clock() - 10, origin="filing")
    return ctl


_seq = [0]


def req(ctl, agent, symbol, side, qty, *, limit=None, key=None, kind="fundamental", action=None, evidence=None, intent=True, **ikw):
    _seq[0] += 1
    limit = 100.0 if limit is None else limit
    action = action or ("add" if side == "buy" else "reduce")
    rec = None
    if intent:
        rec = V.IntentRecord(agent, ctl.contract.contract_id, ctl.contract.autonomy["objective"]["id"], action, kind, symbol, side, qty,
                             ikw.pop("thesis", "position sized to the signed plan"), 30,
                             tuple(evidence if evidence is not None else (ctl.doc.sha256,)), ikw.pop("claims", ()),
                             intent_id=f"i{_seq[0]}")
    return ActionRequest(agent, symbol, side, qty, limit, key or f"k{_seq[0]}", rec, ctl.test_leases.get(agent), **ikw)

