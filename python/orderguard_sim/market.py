"""A small, explicit multi-symbol market with decaying square-root impact.

The market has no directional alpha. Exogenous returns are correlated Student-t
innovations with a persistent GARCH-style volatility state. Authorized flow adds
temporary impact to log prices:

    I[t] = decay * I[t-1] + eta * sigma[t] * sign(Q[t]) * sqrt(|Q[t]| / ADV)

`Q` is net authorized dollar flow per symbol during a step. ADV is daily dollar
volume, `sigma` is one-step volatility, `eta` is dimensionless. The update is
simple enough to audit and deliberately does not model an order book.

Calibration uses the included recorded Binance feed for symbols it contains and
scales its roughly one-second realized volatility by sqrt(simulation seconds).
Missing symbols use documented stylized defaults (equities 0.0015, crypto
0.0030 one-step volatility; 0.30 common factor correlation; $50m / $150m ADV).
The feed is a short, one-second, single-exchange recording, so these estimates
are shape seeds, not exchange-grade estimates.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from orderguard_arena.feeds import DEFAULT_SYMBOLS

DEFAULT_RECORDING = Path(__file__).resolve().parents[2] / "data" / "arena" / "feeds" / "binance-public-20261111T000117Z.jsonl"
DEFAULT_ADV_EQUITY = 50_000_000.0
DEFAULT_ADV_CRYPTO = 150_000_000.0
DEFAULT_SIGMA_EQUITY = 0.0015
DEFAULT_SIGMA_CRYPTO = 0.0030
DEFAULT_CORRELATION = 0.30


def _is_crypto(symbol: str) -> bool:
    return symbol.endswith(("-USD", "USDT"))


def _corr_psd(corr: np.ndarray) -> np.ndarray:
    """Clip tiny negative eigenvalues and renormalize to a correlation matrix."""
    vals, vecs = np.linalg.eigh((corr + corr.T) * 0.5)
    fixed = (vecs * np.maximum(vals, 1e-8)) @ vecs.T
    scale = np.sqrt(np.maximum(np.diag(fixed), 1e-12))
    fixed = fixed / scale[:, None] / scale[None, :]
    np.fill_diagonal(fixed, 1.0)
    return fixed


def calibrate_recording(path: str | Path, symbols: list[str]) -> dict:
    """Estimate per-step vol and pair correlation for symbols in a recorded feed."""
    prices: dict[str, list[float]] = {s: [] for s in symbols}
    aliases = {"BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "SOL-USD": "SOLUSDT"}
    try:
        with Path(path).open(encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("type") != "tick":
                    continue
                for sym in symbols:
                    q = row.get("quotes", {}).get(sym) or row.get("quotes", {}).get(aliases.get(sym, ""))
                    if q and float(q.get("last", 0.0)) > 0:
                        prices[sym].append(float(q["last"]))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {"sigma": {}, "correlation": {}}
    rets = {}
    sigmas = {}
    for sym, px in prices.items():
        p = np.asarray(px, dtype=np.float64)
        r = np.diff(np.log(p)) if len(p) > 1 else np.array([], dtype=np.float64)
        if len(r) >= 8 and float(np.std(r)) > 1e-8:
            sigmas[sym] = float(np.clip(np.std(r, ddof=1), 2e-5, 0.008))
            rets[sym] = r
    correlations: dict[tuple[str, str], float] = {}
    for i, a in enumerate(rets):
        for b in list(rets)[i + 1:]:
            n = min(len(rets[a]), len(rets[b]))
            if n >= 8:
                value = float(np.corrcoef(rets[a][-n:], rets[b][-n:])[0, 1])
                if math.isfinite(value):
                    # Shrink a short recording toward the stylized common-factor prior.
                    correlations[(a, b)] = float(np.clip(0.75 * value + 0.25 * DEFAULT_CORRELATION, -0.8, 0.95))
    return {"sigma": sigmas, "correlation": correlations}


class ImpactMarket:
    """Seeded price process; callers provide only the authorized net flow."""

    def __init__(self, symbols: list[str] | None = None, seed: int = 0, *, initial_prices: dict[str, float] | None = None,
                 sigma: dict[str, float] | None = None, adv: dict[str, float] | None = None,
                 correlation: np.ndarray | None = None, correlation_pairs: dict | None = None,
                 impact_eta: float = 1.0, impact_decay: float = 0.82, garch_alpha: float = 0.08,
                 garch_beta: float = 0.90, student_df: float = 5.0):
        self.symbols = list(symbols or DEFAULT_SYMBOLS)
        self.index = {s: i for i, s in enumerate(self.symbols)}
        n = len(self.symbols)
        if not n or len(self.index) != n:
            raise ValueError("symbols must be a non-empty list without duplicates")
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.initial_prices = np.array([float((initial_prices or {}).get(s, 250.0 if not _is_crypto(s) else 100.0)) for s in self.symbols])
        if np.any(~np.isfinite(self.initial_prices)) or np.any(self.initial_prices <= 0):
            raise ValueError("initial prices must be finite and positive")
        default_sigma = {s: DEFAULT_SIGMA_CRYPTO if _is_crypto(s) else DEFAULT_SIGMA_EQUITY for s in self.symbols}
        self.sigma = np.array([float((sigma or {}).get(s, default_sigma[s])) for s in self.symbols], dtype=np.float64)
        self.adv = np.array([float((adv or {}).get(s, DEFAULT_ADV_CRYPTO if _is_crypto(s) else DEFAULT_ADV_EQUITY)) for s in self.symbols], dtype=np.float64)
        if np.any(~np.isfinite(self.sigma)) or np.any(self.sigma <= 0) or np.any(~np.isfinite(self.adv)) or np.any(self.adv <= 0):
            raise ValueError("volatilities and ADV must be finite and positive")
        if correlation is None:
            corr = np.full((n, n), DEFAULT_CORRELATION, dtype=np.float64)
            np.fill_diagonal(corr, 1.0)
            for (a, b), rho in (correlation_pairs or {}).items():
                if a in self.index and b in self.index:
                    i, j = self.index[a], self.index[b]
                    corr[i, j] = corr[j, i] = float(rho)
            # Different sleeves have a smaller shared factor by construction.
            for i, a in enumerate(self.symbols):
                for j, b in enumerate(self.symbols[:i]):
                    if _is_crypto(a) != _is_crypto(b) and (a, b) not in (correlation_pairs or {}) and (b, a) not in (correlation_pairs or {}):
                        corr[i, j] = corr[j, i] = 0.12
        else:
            corr = np.asarray(correlation, dtype=np.float64)
            if corr.shape != (n, n):
                raise ValueError("correlation matrix shape must match symbols")
        self.correlation = _corr_psd(corr)
        self.cholesky = np.linalg.cholesky(self.correlation)
        self.impact_eta, self.impact_decay = float(impact_eta), float(impact_decay)
        self.garch_alpha, self.garch_beta, self.student_df = float(garch_alpha), float(garch_beta), float(student_df)
        if not (0 <= self.impact_decay < 1 and self.garch_alpha >= 0 and self.garch_beta >= 0 and
                self.garch_alpha + self.garch_beta < 1 and self.student_df > 2):
            raise ValueError("invalid impact decay or volatility parameters")
        self.mid = self.initial_prices.copy()
        self.impact_state = np.zeros(n, dtype=np.float64)
        self.variance_state = np.ones(n, dtype=np.float64)
        self.step_index = 0
        self.prices = [self.mid.copy()]
        self.returns: list[np.ndarray] = []
        self.impacts: list[np.ndarray] = []

    @classmethod
    def from_recording(cls, symbols: list[str] | None = None, seed: int = 0, recording: str | Path = DEFAULT_RECORDING,
                       *, simulation_step_seconds: float = 1.0, **kwargs) -> "ImpactMarket":
        symbols = list(symbols or DEFAULT_SYMBOLS)
        cal = calibrate_recording(recording, symbols)
        scale = math.sqrt(max(float(simulation_step_seconds), 1.0))
        scaled_sigma = {s: min(0.008, v * scale) for s, v in cal["sigma"].items()}
        return cls(symbols, seed, sigma=scaled_sigma, correlation_pairs=cal["correlation"], **kwargs)

    def quote(self, symbol: str, *, lag: int = 0) -> float:
        i = self.index[symbol]
        j = max(0, min(self.step_index - int(lag), len(self.prices) - 1))
        return float(self.prices[j][i])

    def slippage_fraction(self, symbol: str, cumulative_abs_usd: float) -> float:
        i = self.index[symbol]
        impact = self.impact_eta * self.sigma[i] * math.sqrt(max(cumulative_abs_usd, 0.0) / self.adv[i])
        return max(0.00002, 0.5 * 0.0002 + impact)

    def impact_fraction(self, symbol: str, notional_usd: float) -> float:
        """Instantaneous square-root impact magnitude for a dollar clip (useful for sizing and tests)."""
        i = self.index[symbol]
        return self.impact_eta * self.sigma[i] * math.sqrt(abs(float(notional_usd)) / self.adv[i])

    def step(self, net_flow_usd: dict[str, float] | np.ndarray | None = None,
             exogenous_log_return: dict[str, float] | np.ndarray | None = None) -> np.ndarray:
        """Advance one step. Only this input flow can create order-driven price impact."""
        n = len(self.symbols)
        flow = np.zeros(n, dtype=np.float64)
        if isinstance(net_flow_usd, dict):
            for s, v in net_flow_usd.items():
                if s in self.index:
                    flow[self.index[s]] = float(v)
        elif net_flow_usd is not None:
            flow = np.asarray(net_flow_usd, dtype=np.float64).copy()
            if flow.shape != (n,):
                raise ValueError("net flow vector shape must match symbols")
        z = self.cholesky @ self.rng.standard_normal(n)
        chi = self.rng.chisquare(self.student_df)
        t = z / math.sqrt(chi / self.student_df) * math.sqrt((self.student_df - 2.0) / self.student_df)
        base_ret = self.sigma * np.sqrt(self.variance_state) * t
        if isinstance(exogenous_log_return, dict):
            for s, v in exogenous_log_return.items():
                if s in self.index:
                    base_ret[self.index[s]] += float(v)
        elif exogenous_log_return is not None:
            shock = np.asarray(exogenous_log_return, dtype=np.float64)
            if shock.shape != (n,):
                raise ValueError("exogenous return vector shape must match symbols")
            base_ret += shock
        signed_impact = self.impact_eta * self.sigma * np.sqrt(np.abs(flow) / self.adv) * np.sign(flow)
        self.impact_state = self.impact_decay * self.impact_state + signed_impact
        ret = base_ret + self.impact_state
        self.mid *= np.exp(ret)
        standardized = base_ret / self.sigma
        self.variance_state = (1.0 - self.garch_alpha - self.garch_beta) + self.garch_alpha * standardized**2 + self.garch_beta * self.variance_state
        self.returns.append(ret.copy())
        self.impacts.append(signed_impact.copy())
        self.prices.append(self.mid.copy())
        self.step_index += 1
        return ret

