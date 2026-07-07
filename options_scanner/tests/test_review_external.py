"""Review-an-external-play tool — framework critique of a posted book."""

from __future__ import annotations

import datetime

from options_scanner.review_external import (
    ExternalPosition,
    review_book,
    render_review,
)

_NOW = datetime.datetime(2026, 7, 6, 12, 0)


def _semi_book():
    # The posted screenshot: all long calls, all semi/semicap, near-dated.
    S = "semiconductors"
    return [
        ExternalPosition("ALAB", "call", 430, "2026-07-10", 1, "long", 15.83, S),
        ExternalPosition("AMAT", "call", 650, "2026-07-10", 1, "long", 13.18, S),
        ExternalPosition("LRCX", "call", 420, "2026-07-10", 1, "long", 1.85, S),
        ExternalPosition("LRCX", "call", 400, "2026-07-10", 2, "long", 3.78, S),
        ExternalPosition("AMAT", "call", 820, "2026-07-17", 5, "long", 2.60, S),
        ExternalPosition("LRCX", "call", 450, "2026-07-17", 1, "long", 2.65, S),
        ExternalPosition("UCTT", "call", 150, "2026-07-17", 6, "long", 0.73, S),
    ]


def test_all_bullish_all_long_premium_flagged():
    r = review_book(_semi_book(), now=_NOW)
    joined = " ".join(r.findings)
    assert "one-directional (all bullish)" in joined
    assert "long premium" in joined and "IV" in joined     # vol-blind flag


def test_correlation_cluster_flagged():
    r = review_book(_semi_book(), now=_NOW)
    joined = " ".join(r.findings)
    assert "semiconductors" in joined and "G12" in joined
    # verdict should push to restructure/pass given the concentration
    assert "PASS" in r.verdict or "restructure" in r.verdict.lower()


def test_naked_and_near_dated_flags():
    r = review_book(_semi_book(), now=_NOW)
    # every position is a naked long call
    assert all(p.structure == "naked_long_call" for p in r.positions)
    # 7/10 legs are ~4 DTE -> near-dated
    near = [p for p in r.positions if p.dte is not None and p.dte <= 7]
    assert near and any("near-dated" in " ".join(p.flags) for p in near)


def test_lottery_ticket_flag_with_spot():
    pos = [ExternalPosition("AMAT", "call", 820, "2026-07-17", 5, "long", 2.60,
                            "semiconductors", underlying_price=650.0)]
    r = review_book(pos, now=_NOW)
    assert any("lottery" in " ".join(p.flags) for p in r.positions)


def test_vertical_spread_detected_and_not_naked():
    # a defined-risk debit spread should NOT be flagged as naked
    pos = [
        ExternalPosition("BAC", "call", 60, "2026-07-17", 1, "long", 1.28),
        ExternalPosition("BAC", "call", 62.5, "2026-07-17", 1, "short", 0.40),
    ]
    r = review_book(pos, now=_NOW)
    assert any(p.structure == "call_vertical" for p in r.positions)
    assert not any(p.structure.startswith("naked") for p in r.positions)


def test_render_contains_verdict_and_positions():
    out = render_review(review_book(_semi_book(), now=_NOW))
    assert "EXTERNAL PLAY REVIEW" in out and "VERDICT" in out
    assert "AMAT" in out and "semiconductors" in out
