"""Shared pytest fixtures for the voldesk test suite."""

from __future__ import annotations

from voldesk.models import GammaScreenRow


def make_row(**overrides) -> GammaScreenRow:
    """Build a GammaScreenRow that passes all 5 filters by default, with overrides."""
    defaults = dict(
        symbol="TEST",
        spot=101.0,
        dealer_delta_balance=0.80,
        db_change=0.60,
        grade=9,
        p_trans=100.0,
        n_trans=90.0,
        plus_gex=110.0,
        cotmp=98.0,
        grade_11_deep=False,
        db_prior_2_sessions=None,
        spike_crash_pattern=False,
    )
    defaults.update(overrides)
    return GammaScreenRow(**defaults)
