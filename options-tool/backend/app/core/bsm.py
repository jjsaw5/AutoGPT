"""Black–Scholes–Merton pricing and Greeks.

No dividend yield; risk-free rate is passed in per call. Kept dependency-free
(no ``py_vollib``) so tests stay fast and the mock provider can share the same
math as the Thorp strategist.

Reference: Hull, *Options, Futures, and Other Derivatives* (10th ed.), ch. 15.
"""
from __future__ import annotations

import math

from app.core.models import OptionRight

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1_d2(spot: float, strike: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return d1, d2


def price(
    spot: float, strike: float, t: float, r: float, sigma: float, right: OptionRight
) -> float:
    """BSM price. Falls back to intrinsic at/after expiry."""
    if t <= 0 or sigma <= 0:
        intrinsic = (
            max(spot - strike, 0.0) if right is OptionRight.CALL else max(strike - spot, 0.0)
        )
        return intrinsic
    d1, d2 = _d1_d2(spot, strike, t, r, sigma)
    if right is OptionRight.CALL:
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def delta(
    spot: float, strike: float, t: float, r: float, sigma: float, right: OptionRight
) -> float:
    if t <= 0 or sigma <= 0:
        if right is OptionRight.CALL:
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    d1, _ = _d1_d2(spot, strike, t, r, sigma)
    return _norm_cdf(d1) if right is OptionRight.CALL else _norm_cdf(d1) - 1.0


def vega(spot: float, strike: float, t: float, r: float, sigma: float) -> float:
    """Per 1.0 change in vol (i.e., per 100 vol points). Divide by 100 for per-point."""
    if t <= 0 or sigma <= 0:
        return 0.0
    d1, _ = _d1_d2(spot, strike, t, r, sigma)
    return spot * _norm_pdf(d1) * math.sqrt(t)


def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    t: float,
    r: float,
    right: OptionRight,
    tol: float = 1e-5,
    max_iter: int = 80,
) -> float | None:
    """Newton–Raphson implied-vol solver with a bisection safety net.

    Returns None if the target price is outside BSM's reachable range (e.g.
    below intrinsic), which shields callers from having to handle NaNs.
    """
    if t <= 0 or market_price <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = (
        max(spot - strike, 0.0) if right is OptionRight.CALL else max(strike - spot, 0.0)
    )
    if market_price < intrinsic - 1e-8:
        return None

    lo, hi = 1e-4, 5.0
    sigma = 0.3
    for _ in range(max_iter):
        p = price(spot, strike, t, r, sigma, right)
        diff = p - market_price
        if abs(diff) < tol:
            return sigma
        v = vega(spot, strike, t, r, sigma)
        if v < 1e-8:
            break
        sigma -= diff / v
        if sigma <= lo or sigma >= hi:
            break
    # Fallback: bisection between lo and hi.
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        p = price(spot, strike, t, r, mid, right)
        if abs(p - market_price) < tol:
            return mid
        if p < market_price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def pop_between(lower: float, upper: float, spot: float, t: float, sigma: float, r: float = 0.0) -> float:
    """Risk-neutral probability the underlying finishes in [lower, upper] at T.

    Uses the lognormal density implied by BSM (drift = r - 0.5σ²). This is the
    standard textbook POP used for defined-risk structures and matches what
    Tastytrade calls "probability of profit" up to a discounting adjustment.
    """
    if t <= 0 or sigma <= 0 or spot <= 0 or lower >= upper:
        return 0.0
    mu = math.log(spot) + (r - 0.5 * sigma * sigma) * t
    sd = sigma * math.sqrt(t)
    # P(lower <= S_T <= upper) = Φ((ln upper - μ)/σ√T) − Φ((ln lower - μ)/σ√T)
    if lower <= 0:
        lo_term = 0.0
    else:
        lo_term = _norm_cdf((math.log(lower) - mu) / sd)
    hi_term = _norm_cdf((math.log(upper) - mu) / sd)
    return max(0.0, min(1.0, hi_term - lo_term))


def prob_touch(
    barrier: float, spot: float, t: float, sigma: float, r: float = 0.0
) -> float:
    """Probability that GBM touches ``barrier`` during [0, t].

    Derived from the first-passage density for Brownian motion with drift
    (Shreve, *Stochastic Calculus for Finance II*, Theorem 7.2.1):

        m       = ln(B/S)
        α       = r − σ²/2
        P(hit)  = Φ( (α t − |m|) / σ√t ) + (B/S)^(2α/σ²) · Φ( (−α t − |m|) / σ√t )

    The formula is symmetric in the sign of m — ``|m|`` is what matters for
    first passage, and the multiplier term uses signed ``m`` via the exponent.
    """
    if t <= 0 or sigma <= 0 or spot <= 0 or barrier <= 0 or barrier == spot:
        return 0.0
    sd = sigma * math.sqrt(t)
    alpha = r - 0.5 * sigma * sigma
    m = math.log(barrier / spot)
    abs_m = abs(m)
    term_a = _norm_cdf((alpha * t - abs_m) / sd)
    multiplier = float((barrier / spot) ** (2.0 * alpha / (sigma * sigma)))
    term_b = multiplier * _norm_cdf((-alpha * t - abs_m) / sd)
    return max(0.0, min(1.0, term_a + term_b))
