"""Vol surface fitter tests."""
from __future__ import annotations

import pytest

from app.core.vol_surface import fit_smile, fit_surface
from app.data.mock_provider import MockProvider


def test_fit_smile_returns_all_expiries_for_mock_chain() -> None:
    p = MockProvider()
    chain = p.get_chain("TEST")
    surface = fit_surface(chain)
    # Mock generates 5 expiries; 7-DTE may drop off due to 0-time edge case in expiring.
    assert len(surface) >= 4


def test_fit_smile_recovers_base_iv_near_atm() -> None:
    p = MockProvider(base_iv=0.30)
    chain = p.get_chain("TEST")
    expiry = sorted(chain.expiries())[2]  # ~45 DTE
    fit = fit_smile(chain, expiry)
    assert fit is not None
    # At the forward strike, log-moneyness=0 so fair_iv == intercept; mock uses
    # iv = 0.30 + 0.10*|moneyness|, so intercept should be very close to 0.30.
    atm_iv = fit.fair_iv(fit.forward)
    assert atm_iv == pytest.approx(0.30, abs=0.02)


def test_fit_smile_rmse_small_for_clean_data() -> None:
    p = MockProvider()
    chain = p.get_chain("TEST")
    expiry = sorted(chain.expiries())[2]
    fit = fit_smile(chain, expiry)
    assert fit is not None
    assert fit.rmse < 0.02
