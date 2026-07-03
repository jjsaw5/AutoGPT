"""Per-expiry implied-vol smile fit.

Uses a quadratic in log-moneyness k = ln(K/F), i.e. the "sticky-delta" smile

    σ(k) ≈ a₀ + a₁·k + a₂·k²

which is the textbook polynomial SVI surrogate (Gatheral, *The Volatility
Surface*, ch. 3). Quadratic is enough to model the post-2008 equity smirk
without overfitting 20–40 strike samples.

Strikes are interpolated via the fitted polynomial. Expiries are kept separate
— the Thorp module compares market IV against the *same-expiry* fair value, so
we don't need a full 2-D surface for Phase 2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.core.models import OptionChain, OptionRight


@dataclass
class SmileFit:
    expiry: date
    coeffs: tuple[float, float, float]  # (a0, a1, a2) in ascending degree
    spot: float
    forward: float
    n_points: int
    rmse: float

    def fair_iv(self, strike: float) -> float:
        if strike <= 0:
            return 0.0
        k = math.log(strike / self.forward)
        a0, a1, a2 = self.coeffs
        return max(a0 + a1 * k + a2 * k * k, 1e-4)


def _forward(spot: float, r: float, t: float) -> float:
    return spot * math.exp(r * t)


def fit_smile(chain: OptionChain, expiry: date, min_points: int = 6) -> SmileFit | None:
    """Least-squares quadratic fit of IV vs log-moneyness for one expiry.

    Prefers out-of-the-money legs on each side (OTM calls above spot, OTM puts
    below) because they carry the fattest vol signal; ATM is picked up by the
    fit's intercept.
    """
    today = chain.as_of.date()
    dte = (expiry - today).days
    if dte <= 0:
        return None
    t = dte / 365.0
    fwd = _forward(chain.spot, chain.risk_free_rate, t)

    samples: list[tuple[float, float]] = []  # (log-moneyness, iv)
    for c in chain.by_expiry(expiry):
        if c.implied_vol is None or c.implied_vol <= 0:
            continue
        # Keep OTM only: OTM call if K > spot, OTM put if K < spot.
        is_otm = (c.right is OptionRight.CALL and c.strike > chain.spot) or (
            c.right is OptionRight.PUT and c.strike < chain.spot
        )
        if not is_otm:
            continue
        k = math.log(c.strike / fwd)
        samples.append((k, c.implied_vol))

    if len(samples) < min_points:
        return None

    ks = np.array([s[0] for s in samples], dtype=float)
    ivs = np.array([s[1] for s in samples], dtype=float)
    # np.polyfit returns highest-degree-first; flip to (a0, a1, a2).
    highest_first = np.polyfit(ks, ivs, 2)
    a2, a1, a0 = float(highest_first[0]), float(highest_first[1]), float(highest_first[2])
    fitted = a0 + a1 * ks + a2 * ks**2
    rmse = float(np.sqrt(np.mean((fitted - ivs) ** 2)))
    return SmileFit(
        expiry=expiry, coeffs=(a0, a1, a2), spot=chain.spot, forward=fwd,
        n_points=len(samples), rmse=rmse,
    )


def fit_surface(chain: OptionChain, min_points: int = 6) -> dict[date, SmileFit]:
    """Fit a smile for each expiry that has enough points."""
    out: dict[date, SmileFit] = {}
    for expiry in chain.expiries():
        fit = fit_smile(chain, expiry, min_points=min_points)
        if fit is not None:
            out[expiry] = fit
    return out
