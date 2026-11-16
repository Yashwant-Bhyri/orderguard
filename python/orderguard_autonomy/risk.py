"""Counterfactual portfolio risk (design section 3C).

The question is not "is this order too large" but "how does it change the risk of the portfolio as it will be".
sigma_p = sqrt(w' Sigma w); ES_a(L) = E[L | L >= VaR_a(L)]; the order's incremental risk is ES(w + d) - ES(w).

Because sigma_p is a norm of Sigma^(1/2) w and ES is coherent, both are subadditive: rho(w + d1 + d2) <= rho(w) + rho(d1) + rho(d2).
So risk budget can be reserved per order like dollars, and the sum of reservations soundly bounds the total without searching the
2^n fill combinations of working orders. Euler allocation returns the diversification benefit at reconciliation.

Two classes, kept apart: loss under *declared* scenarios is arithmetic on signed inputs and may refuse; statistical estimates
(covariance, ES, liquidity, regime) may only hold or tighten.

Units: exposures are signed US dollars. A covariance model returns the covariance of simple returns over its stated horizon, so
sigma and ES come out in dollars over that horizon. ES here is parametric (elliptical: Gaussian or Student-t scaled to unit
variance), which is what makes it a norm and therefore subadditive under one covariance. Under a *different* covariance (a regime
change) reserved amounts are recomputed at reconciliation; subadditivity is a property of one model, not across models.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Protocol, Sequence

import numpy as np


class CovarianceModel(Protocol):
    """A factor model with shrinkage toward a structured target, plus a stressed variant for crisis correlations."""
    def covariance(self, symbols: Sequence[str], *, stressed: bool = False): ...


# ---------------------------------------------------------------------------------------------------------------------
# Declared scenarios: deterministic, may refuse
# ---------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    """A declared, signed stress scenario: a shock per symbol or factor. Loss under it is deterministic.

    Keys of `shocks`: a symbol ("NVDA"), a sector ("sector:tech") or the whole market ("*"). The most specific key wins.
    A shock is a simple return, so -0.2 means the price falls 20%.
    """
    name: str
    shocks: dict[str, float]

    def shock_for(self, symbol: str, sectors: dict[str, str] | None = None) -> float:
        if symbol in self.shocks:
            return float(self.shocks[symbol])
        sec = (sectors or {}).get(symbol)
        if sec is not None and f"sector:{sec}" in self.shocks:
            return float(self.shocks[f"sector:{sec}"])
        return float(self.shocks.get("*", 0.0))

    def as_dict(self) -> dict:
        return {"name": self.name, "shocks": dict(sorted(self.shocks.items()))}

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        return cls(str(d["name"]), {str(k): float(v) for k, v in d["shocks"].items()})


def _loss(exposures: dict[str, float], scn: Scenario, sectors: dict[str, str] | None) -> float:
    return -sum(float(e) * scn.shock_for(s, sectors) for s, e in exposures.items())


def declared_scenario_loss(exposures: dict[str, float], scenarios: Sequence[Scenario],
                           sectors: dict[str, str] | None = None) -> dict[str, float]:
    """Loss in each declared scenario (positive = money lost). Bounds loss in those scenarios only, never real-world loss."""
    return {scn.name: _loss(exposures, scn, sectors) for scn in scenarios}


def worst_case_scenario_loss(base: dict[str, float], pending: Iterable[dict[str, float]], scenarios: Sequence[Scenario],
                             sectors: dict[str, str] | None = None) -> dict[str, float]:
    """Worst loss in each scenario over every way the pending orders could (partly) fill.

    Loss is linear in each order's fill fraction f in [0, 1], so the maximum over all fills is the base loss plus the positive part
    of each pending order's own loss. Exact, and linear in the number of orders: no 2^n search.
    """
    pending = list(pending)
    out = {}
    for scn in scenarios:
        out[scn.name] = _loss(base, scn, sectors) + sum(max(0.0, _loss(d, scn, sectors)) for d in pending)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Distribution helpers (no scipy in the base install)
# ---------------------------------------------------------------------------------------------------------------------

def norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, refined by one Newton step; |error| < 1e-12)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    lo, hi = 0.02425, 1 - 0.02425
    if p < lo:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= hi:
        q = p - 0.5
        r = q*q
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def _t_pdf(x: np.ndarray | float, df: float):
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    return c * (1 + np.asarray(x, dtype=np.float64) ** 2 / df) ** (-(df + 1) / 2)


@lru_cache(maxsize=64)
def _t_ppf(p: float, df: float) -> float:
    """Student-t quantile by bisection on a numerically integrated CDF (deterministic; fine for df > 2 and p up to 0.9999)."""
    hi = 60.0
    grid = np.linspace(0.0, hi, 600_001)
    pdf = _t_pdf(grid, df)
    cdf = 0.5 + np.concatenate(([0.0], np.cumsum((pdf[1:] + pdf[:-1]) * 0.5 * (grid[1] - grid[0]))))
    i = int(np.searchsorted(cdf, p))
    i = min(max(i, 1), len(grid) - 1)
    x0, x1, c0, c1 = grid[i - 1], grid[i], cdf[i - 1], cdf[i]
    return float(x0 + (p - c0) * (x1 - x0) / max(c1 - c0, 1e-300))


@lru_cache(maxsize=64)
def es_factor(alpha: float = 0.975, df: float | None = None) -> float:
    """ES of a unit-variance loss at level alpha. Gaussian: phi(z)/(1-alpha) (2.338 at 97.5%). Student-t(df) scaled to unit variance."""
    if not 0.5 <= alpha < 1.0:
        raise ValueError("alpha must be in [0.5, 1)")
    if df is None:
        z = norm_ppf(alpha)
        return math.exp(-z * z / 2) / math.sqrt(2 * math.pi) / (1 - alpha)
    if df <= 2:
        raise ValueError("df must be > 2 for a finite variance")
    q = _t_ppf(alpha, float(df))
    es_std_t = float(_t_pdf(q, df)) / (1 - alpha) * (df + q * q) / (df - 1)
    return es_std_t * math.sqrt((df - 2) / df)


@lru_cache(maxsize=64)
def var_factor(alpha: float = 0.975, df: float | None = None) -> float:
    if df is None:
        return norm_ppf(alpha)
    return _t_ppf(alpha, float(df)) * math.sqrt((df - 2) / df)


# ---------------------------------------------------------------------------------------------------------------------
# Covariance models: estimated, may only tighten
# ---------------------------------------------------------------------------------------------------------------------

def stress_correlation(cov: np.ndarray, *, vol_mult: float = 2.0, corr_floor: float = 0.6) -> np.ndarray:
    """A stressed covariance: volatilities times `vol_mult`, correlations pulled toward one (R' = (1-s) R + s 11').

    A convex combination of two correlation matrices is a correlation matrix, so the result stays positive semi-definite.
    """
    sd = np.sqrt(np.maximum(np.diag(cov), 0.0))
    safe = np.where(sd > 0, sd, 1.0)
    corr = cov / safe[:, None] / safe[None, :]
    np.fill_diagonal(corr, 1.0)
    s = float(np.clip(corr_floor, 0.0, 1.0))
    corr_s = (1 - s) * corr + s * np.ones_like(corr)
    sd_s = sd * float(vol_mult)
    return corr_s * sd_s[:, None] * sd_s[None, :]


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit and Wolf (2004) shrinkage of the sample covariance toward the constant-correlation target.

    `returns` is T x N. Returns (shrunk covariance, shrinkage intensity in [0, 1]).
    """
    x = np.asarray(returns, dtype=np.float64)
    t, n = x.shape
    if t < 2:
        raise ValueError("need at least two observations")
    x = x - x.mean(axis=0)
    sample = x.T @ x / t
    var = np.diag(sample).copy()
    sd = np.sqrt(np.maximum(var, 1e-30))
    if n == 1:
        return sample, 0.0
    corr = sample / sd[:, None] / sd[None, :]
    rbar = (corr.sum() - n) / (n * (n - 1))
    target = rbar * sd[:, None] * sd[None, :]
    np.fill_diagonal(target, var)
    y = x ** 2
    phi_mat = y.T @ y / t - sample ** 2
    phi = phi_mat.sum()
    term1 = ((x ** 3).T @ x) / t
    help_ = x.T @ x / t
    term2 = np.diag(help_)[:, None] * sample
    theta = term1 - term2
    np.fill_diagonal(theta, 0.0)
    rho = np.diag(phi_mat).sum() + rbar * ((1 / sd)[:, None] * sd[None, :] * theta).sum()
    gamma = np.linalg.norm(sample - target, "fro") ** 2
    kappa = (phi - rho) / gamma if gamma > 0 else 0.0
    delta = float(np.clip(kappa / t, 0.0, 1.0))
    return delta * target + (1 - delta) * sample, delta


@dataclass
class StaticCovariance:
    """A fixed covariance over a stated horizon, with a stressed variant. Used for tests and as the declared prior."""
    symbols: list[str]
    cov: np.ndarray
    stress_vol_mult: float = 2.0
    stress_corr_floor: float = 0.6

    def __post_init__(self):
        self.cov = np.asarray(self.cov, dtype=np.float64)
        self.index = {s: i for i, s in enumerate(self.symbols)}
        if self.cov.shape != (len(self.symbols), len(self.symbols)):
            raise ValueError("covariance shape must match symbols")
        if np.min(np.linalg.eigvalsh((self.cov + self.cov.T) / 2)) < -1e-12:
            raise ValueError("covariance must be positive semi-definite")
        self._stressed = stress_correlation(self.cov, vol_mult=self.stress_vol_mult, corr_floor=self.stress_corr_floor)

    def covariance(self, symbols: Sequence[str], *, stressed: bool = False) -> np.ndarray:
        idx = [self.index[s] for s in symbols]
        m = self._stressed if stressed else self.cov
        return m[np.ix_(idx, idx)]


def factor_covariance(returns: np.ndarray, symbols: Sequence[str], sectors: dict[str, str]) -> np.ndarray:
    """Market plus sector factor model: Sigma = B Sigma_F B' + D, loadings by least squares, residual variances on the diagonal.

    Factors are the equal-weight market return and each sector's equal-weight return net of the market. With few observations this
    is far more stable than the sample covariance, because only (1 + sectors) factor variances and N residuals are estimated.
    """
    x = np.asarray(returns, dtype=np.float64)
    t, n = x.shape
    mkt = x.mean(axis=1)
    names = sorted({sectors.get(s, "other") for s in symbols})
    f_cols = [mkt]
    for sec in names:
        members = [i for i, s in enumerate(symbols) if sectors.get(s, "other") == sec]
        if len(members) >= 2:
            f_cols.append(x[:, members].mean(axis=1) - mkt)
    f = np.column_stack(f_cols)
    f_c = f - f.mean(axis=0)
    x_c = x - x.mean(axis=0)
    beta, *_ = np.linalg.lstsq(f_c, x_c, rcond=None)              # k x n
    resid = x_c - f_c @ beta
    d = np.maximum(resid.var(axis=0, ddof=min(1, t - 1)), 1e-12)
    sf = np.atleast_2d(np.cov(f_c, rowvar=False, ddof=min(1, t - 1)))
    return beta.T @ sf @ beta + np.diag(d)


@dataclass
class RollingCovariance:
    """The model the admission controller uses in the benchmark: covariance of trusted returns seen so far, shrunk (Ledoit-Wolf,
    constant correlation) and blended with a declared prior while history is short. Horizon: `horizon_steps` simulation steps."""
    symbols: list[str]
    prior: np.ndarray                         # per-step covariance prior (declared)
    window: int = 120
    min_obs: int = 30
    horizon_steps: int = 1
    stress_vol_mult: float = 2.0
    stress_corr_floor: float = 0.6
    _rets: list = field(default_factory=list)
    _cache: dict = field(default_factory=dict)

    def __post_init__(self):
        self.index = {s: i for i, s in enumerate(self.symbols)}
        self.prior = np.asarray(self.prior, dtype=np.float64)

    def observe(self, step_returns: np.ndarray) -> None:
        self._rets.append(np.asarray(step_returns, dtype=np.float64))
        if len(self._rets) > self.window:
            self._rets.pop(0)
        self._cache.clear()

    def _per_step(self) -> np.ndarray:
        n = len(self._rets)
        if n < self.min_obs:
            return self.prior
        est, _ = ledoit_wolf_constant_correlation(np.vstack(self._rets))
        w = min(1.0, (n - self.min_obs + 1) / max(1, self.window - self.min_obs + 1))
        return w * est + (1 - w) * self.prior

    def covariance(self, symbols: Sequence[str], *, stressed: bool = False) -> np.ndarray:
        key = bool(stressed)
        if key not in self._cache:
            base = self._per_step() * self.horizon_steps
            self._cache[key] = stress_correlation(base, vol_mult=self.stress_vol_mult, corr_floor=self.stress_corr_floor) if stressed else base
        m = self._cache[key]
        idx = [self.index[s] for s in symbols]
        return m[np.ix_(idx, idx)]


# ---------------------------------------------------------------------------------------------------------------------
# Portfolio risk, incremental risk, reservable risk and Euler allocation
# ---------------------------------------------------------------------------------------------------------------------

def portfolio_sigma(model: CovarianceModel, exposures: dict[str, float], *, stressed: bool = False) -> float:
    syms = sorted(s for s, v in exposures.items() if v)
    if not syms:
        return 0.0
    w = np.array([float(exposures[s]) for s in syms])
    cov = model.covariance(syms, stressed=stressed)
    return float(math.sqrt(max(0.0, float(w @ cov @ w))))


def expected_shortfall(model: CovarianceModel, exposures: dict[str, float], alpha: float = 0.975, *,
                       df: float | None = None, stressed: bool = False) -> float:
    """Parametric ES (elliptical): es_factor(alpha, df) x sigma_p. A norm of the exposure vector, hence subadditive."""
    return es_factor(alpha, df) * portfolio_sigma(model, exposures, stressed=stressed)


def _add(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    out = dict(a)
    for s, v in b.items():
        out[s] = out.get(s, 0.0) + float(v)
    return out


def incremental_es(model: CovarianceModel, exposures: dict[str, float], order: dict[str, float], alpha: float = 0.975, *,
                   df: float | None = None, stressed: bool = False) -> float:
    """Estimated Delta ES of adding `order` to `exposures`. Model-dependent: may tighten, never approve."""
    return (expected_shortfall(model, _add(exposures, order), alpha, df=df, stressed=stressed)
            - expected_shortfall(model, exposures, alpha, df=df, stressed=stressed))


def reservable_risk(model: CovarianceModel, order: dict[str, float], alpha: float = 0.975, *, df: float | None = None,
                    stressed: bool = False) -> float:
    """Standalone risk of an order, the amount reserved against a subadditive risk budget.

    Soundness: for positions w and working orders d_1..d_n, ES(w + sum of any fill fractions f_i d_i) <= ES(w) + sum ES(d_i),
    because ES here is a norm (triangle inequality and absolute homogeneity with f_i in [0, 1])."""
    return expected_shortfall(model, order, alpha, df=df, stressed=stressed)


def euler_contributions(model: CovarianceModel, exposures: dict[str, float], alpha: float = 0.975, *,
                        df: float | None = None, stressed: bool = False) -> dict[str, float]:
    """Each position's share of portfolio ES, summing exactly to the total (Euler: w_i dES/dw_i = k w_i (Sigma w)_i / sigma_p).

    Contributions can be negative for a hedge. Used at reconciliation to return the diversification benefit that per-order
    standalone reservations over-count."""
    syms = sorted(s for s, v in exposures.items() if v)
    if not syms:
        return {}
    w = np.array([float(exposures[s]) for s in syms])
    cov = model.covariance(syms, stressed=stressed)
    var = float(w @ cov @ w)
    if var <= 0:
        return {s: 0.0 for s in syms}
    sig = math.sqrt(var)
    k = es_factor(alpha, df)
    contrib = k * w * (cov @ w) / sig
    return {s: float(c) for s, c in zip(syms, contrib)}


def group_euler(model: CovarianceModel, books: dict[str, dict[str, float]], alpha: float = 0.975, *, df: float | None = None,
                stressed: bool = False) -> dict[str, float]:
    """Euler contribution of each sub-book (an agent's own positions) to the ES of the combined book. Sums to the total."""
    total: dict[str, float] = {}
    for b in books.values():
        total = _add(total, b)
    syms = sorted(s for s, v in total.items() if v)
    if not syms:
        return {k: 0.0 for k in books}
    w = np.array([total[s] for s in syms])
    cov = model.covariance(syms, stressed=stressed)
    var = float(w @ cov @ w)
    if var <= 0:
        return {k: 0.0 for k in books}
    grad = es_factor(alpha, df) * (cov @ w) / math.sqrt(var)
    return {k: float(np.dot(np.array([b.get(s, 0.0) for s in syms]), grad)) for k, b in books.items()}


def liquidity_cost(notional_usd: float, adv_usd: float, sigma: float, eta: float = 1.0) -> float:
    """Expected cost of exiting a position, square-root impact (the same law the simulator uses): |N| x eta x sigma x sqrt(|N| / ADV)."""
    n = abs(float(notional_usd))
    if adv_usd <= 0:
        return float("inf") if n else 0.0
    return n * eta * float(sigma) * math.sqrt(n / float(adv_usd))


# ---------------------------------------------------------------------------------------------------------------------
# Regime detection and backtests
# ---------------------------------------------------------------------------------------------------------------------

@dataclass
class RegimeDetector:
    """Volatility regime from the ratio of a fast to a slow EWMA of squared market returns, with hysteresis.

    Model-dependent: a 'stressed' verdict switches the risk check to the stressed covariance (stricter), never the other way."""
    fast_halflife: float = 5.0
    slow_halflife: float = 60.0
    enter: float = 2.0
    leave: float = 1.4
    warmup: int = 20
    _fast: float = 0.0
    _slow: float = 0.0
    _n: int = 0
    stressed: bool = False

    def update(self, market_return: float) -> bool:
        r2 = float(market_return) ** 2
        af = 1 - 0.5 ** (1 / self.fast_halflife)
        as_ = 1 - 0.5 ** (1 / self.slow_halflife)
        if self._n == 0:
            self._fast = self._slow = r2
        else:
            self._fast += af * (r2 - self._fast)
            self._slow += as_ * (r2 - self._slow)
        self._n += 1
        if self._n < self.warmup or self._slow <= 0:
            return self.stressed
        ratio = math.sqrt(self._fast / self._slow)
        if not self.stressed and ratio >= self.enter:
            self.stressed = True
        elif self.stressed and ratio <= self.leave:
            self.stressed = False
        return self.stressed


def backtest_var_es(losses: Sequence[float], var: Sequence[float], es: Sequence[float], alpha: float = 0.975) -> dict:
    """Joint VaR and ES backtest. Kupiec's unconditional-coverage test on VaR exceptions, and Acerbi and Szekely's Z2 for ES
    (about 0 when ES is right, positive when ES understates the tail). Tail backtests have low power: report, don't certify."""
    L, V, E = (np.asarray(x, dtype=np.float64) for x in (losses, var, es))
    t = len(L)
    if t == 0:
        return {"n": 0}
    hits = L > V
    x = int(hits.sum())
    p = 1 - alpha
    phat = x / t
    if 0 < x < t:
        lr = -2 * ((t - x) * math.log(1 - p) + x * math.log(p) - (t - x) * math.log(1 - phat) - x * math.log(phat))
    elif x == 0:
        lr = -2 * t * math.log(1 - p)
    else:
        lr = -2 * t * math.log(p)
    kupiec_p = math.erfc(math.sqrt(max(lr, 0.0) / 2))
    safe_e = np.where(E > 0, E, np.inf)
    z2 = float(np.sum(L * hits / safe_e) / (t * p) - 1)
    return {"n": t, "exceptions": x, "expected_exceptions": round(t * p, 2), "kupiec_p": kupiec_p, "acerbi_szekely_z2": z2}
