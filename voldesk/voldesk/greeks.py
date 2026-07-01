"""Standard Black-Scholes greeks, computed from scratch with stdlib ``math``.

FMP's options-chain endpoint returns raw contract data (strike, expiration,
type, bid/ask, volume, open interest, implied volatility) but does **not**
return delta/gamma/vanna/charm. This module fills that gap with the
textbook European Black-Scholes closed-form greeks so the GEX layer
(``voldesk.gex``) has something to multiply against open interest.

IMPORTANT CAVEAT: equity and index options traded in the US are
American-style (early exercise is allowed), but this module only
implements the *European* Black-Scholes model. That is a simplifying
approximation:

- Early-exercise value is not modeled at all, so deep ITM puts (and, for
  dividend payers, deep ITM calls held through an ex-dividend date) can
  diverge from a true American price/greeks.
- Short-dated, near-the-money contracts (which is most of what a GEX/dealer-
  positioning screen cares about) are where this approximation is most
  accurate; deep ITM/OTM and long-dated contracts are where it is weakest.

None of the formulas below are novel -- they are the standard closed-form
Black-Scholes greeks (delta, gamma, vanna) and the standard Haug closed-form
for charm, as widely published (e.g. Haug, "The Complete Guide to Option
Pricing Formulas"). Treat this file as a faithful implementation of known
public formulas, not a source of new financial engineering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

OptionType = Literal["call", "put"]


@dataclass
class Greeks:
    """Black-Scholes greeks for a single option contract."""

    delta: float
    gamma: float
    vanna: float
    charm: float


def _norm_cdf(x: float) -> float:
    """Standard normal CDF, N(x), via math.erf (no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF, phi(x)."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(
    spot: float,
    strike: float,
    days_to_expiry: float,
    implied_vol: float,
    option_type: OptionType,
    risk_free_rate: float = 0.05,
    dividend_yield: float = 0.0,
) -> Greeks:
    """Compute European Black-Scholes delta/gamma/vanna/charm.

    Args:
        spot: Underlying spot price, S.
        strike: Contract strike, K.
        days_to_expiry: Calendar days to expiration. Converted to years as
            T = days_to_expiry / 365.
        implied_vol: Implied volatility as a decimal (0.35, not 35).
        option_type: "call" or "put".
        risk_free_rate: r. Default 0.05 is a placeholder -- callers should
            override with a current risk-free rate (e.g. the latest T-bill
            yield) rather than relying on this default for real trading
            decisions.
        dividend_yield: q, continuous dividend yield. Default 0.0.

    Returns:
        A Greeks dataclass with delta, gamma, vanna, charm.

    Notes on scaling:
        - vanna here is raw d(Delta)/d(sigma) for a full 100% (1.00) change
          in implied vol. A caller who wants "delta change per 1 vol point
          (1% IV move)" should multiply this vanna by 0.01.
        - charm here is d(Delta)/dt (per year of calendar time passing,
          i.e. per unit decrease in T). A caller who wants "delta decay per
          calendar day" should divide charm by 365.

    Edge cases:
        If days_to_expiry <= 0 (contract at/after expiry) or implied_vol
        or spot/strike are non-positive, the contract has no meaningful
        time value left. delta collapses to its intrinsic-value indicator
        (1.0/0.0 for calls, 0.0/-1.0 for puts) and gamma/vanna/charm are
        all 0.0, since none of those greeks are defined at T=0.
    """
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    t = days_to_expiry / 365.0

    if t <= 0 or implied_vol <= 0 or spot <= 0 or strike <= 0:
        if option_type == "call":
            delta = 1.0 if spot > strike else 0.0
        else:
            delta = -1.0 if spot < strike else 0.0
        return Greeks(delta=delta, gamma=0.0, vanna=0.0, charm=0.0)

    sigma = implied_vol
    sqrt_t = math.sqrt(t)

    d1 = (math.log(spot / strike) + (risk_free_rate - dividend_yield + 0.5 * sigma * sigma) * t) / (
        sigma * sqrt_t
    )
    d2 = d1 - sigma * sqrt_t

    disc_q = math.exp(-dividend_yield * t)
    pdf_d1 = _norm_pdf(d1)

    if option_type == "call":
        delta = disc_q * _norm_cdf(d1)
    else:
        delta = disc_q * (_norm_cdf(d1) - 1.0)

    # Gamma is identical for calls and puts at the same strike/expiry.
    gamma = disc_q * pdf_d1 / (spot * sigma * sqrt_t)

    # Vanna = d(Delta)/d(sigma), same formula for calls and puts.
    vanna = -disc_q * pdf_d1 * d2 / sigma

    # Charm = d(Delta)/dt, standard Haug closed-form (differs for calls/puts
    # only in the dividend term). Widely reproduced e.g. on Wikipedia's
    # "Greeks (finance)" page and in Haug's option pricing formula reference.
    common_term = pdf_d1 * (2.0 * (risk_free_rate - dividend_yield) * t - d2 * sigma * sqrt_t) / (
        2.0 * t * sigma * sqrt_t
    )
    if option_type == "call":
        charm = -disc_q * (common_term + dividend_yield * _norm_cdf(d1))
    else:
        charm = -disc_q * (common_term - dividend_yield * _norm_cdf(-d1))

    return Greeks(delta=delta, gamma=gamma, vanna=vanna, charm=charm)
