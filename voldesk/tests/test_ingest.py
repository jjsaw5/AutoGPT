"""Tests for gamma screen CSV ingestion."""

from __future__ import annotations

import pytest

from voldesk.ingest import filter_p2p_candidates, load_gamma_screen

REQUIRED_HEADER = "symbol,spot,db,db_change,grade,p_trans,n_trans,plus_gex,cotmp"


def write_csv(tmp_path, content: str):
    path = tmp_path / "gamma_screen.csv"
    path.write_text(content)
    return path


def test_load_minimal_required_columns(tmp_path):
    content = REQUIRED_HEADER + "\n" + "AAPL,101.0,0.8,0.6,9,100.0,90.0,110.0,98.0\n"
    path = write_csv(tmp_path, content)
    rows = load_gamma_screen(path)
    assert len(rows) == 1
    row = rows[0]
    assert row.symbol == "AAPL"
    assert row.spot == 101.0
    assert row.dealer_delta_balance == 0.8
    assert row.grade == 9
    assert row.grade_11_deep is False
    assert row.db_prior_2_sessions is None
    assert row.spike_crash_pattern is False


def test_missing_required_column_raises_value_error(tmp_path):
    # Missing "cotmp" column.
    header = "symbol,spot,db,db_change,grade,p_trans,n_trans,plus_gex"
    content = header + "\n" + "AAPL,101.0,0.8,0.6,9,100.0,90.0,110.0\n"
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="cotmp"):
        load_gamma_screen(path)


def test_optional_columns_with_defaults(tmp_path):
    header = REQUIRED_HEADER + ",grade_11_deep,db_prior_2_sessions,spike_crash_pattern"
    content = (
        header
        + "\n"
        + "TSLA,101.0,1.0,0.05,11,100.0,90.0,110.0,98.0,true,1.00,false\n"
    )
    path = write_csv(tmp_path, content)
    rows = load_gamma_screen(path)
    row = rows[0]
    assert row.grade_11_deep is True
    assert row.db_prior_2_sessions == 1.00
    assert row.spike_crash_pattern is False


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("Yes", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("", False),
    ],
)
def test_boolean_parsing_case_insensitive(tmp_path, value, expected):
    header = REQUIRED_HEADER + ",spike_crash_pattern"
    content = header + "\n" + f"MSFT,101.0,0.8,0.6,9,100.0,90.0,110.0,98.0,{value}\n"
    path = write_csv(tmp_path, content)
    rows = load_gamma_screen(path)
    assert rows[0].spike_crash_pattern is expected


def test_invalid_boolean_raises(tmp_path):
    header = REQUIRED_HEADER + ",spike_crash_pattern"
    content = header + "\n" + "MSFT,101.0,0.8,0.6,9,100.0,90.0,110.0,98.0,maybe\n"
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError):
        load_gamma_screen(path)


def test_multiple_rows(tmp_path):
    content = (
        REQUIRED_HEADER
        + "\n"
        + "AAPL,101.0,0.8,0.6,9,100.0,90.0,110.0,98.0\n"
        + "MSFT,50.0,0.5,0.2,5,55.0,45.0,60.0,48.0\n"
    )
    path = write_csv(tmp_path, content)
    rows = load_gamma_screen(path)
    assert len(rows) == 2
    assert [r.symbol for r in rows] == ["AAPL", "MSFT"]


def test_filter_p2p_candidates_returns_rows_with_spot_above_p_trans(tmp_path):
    content = (
        REQUIRED_HEADER
        + "\n"
        + "AAPL,101.0,0.8,0.6,9,100.0,90.0,110.0,98.0\n"  # spot >= p_trans
        + "MSFT,50.0,0.5,0.2,5,55.0,45.0,60.0,48.0\n"  # spot < p_trans
        + "NFLX,60.0,0.5,0.2,5,60.0,45.0,70.0,48.0\n"  # spot == p_trans
    )
    path = write_csv(tmp_path, content)
    rows = load_gamma_screen(path)
    p2p = filter_p2p_candidates(rows)
    symbols = {r.symbol for r in p2p}
    assert symbols == {"AAPL", "NFLX"}
