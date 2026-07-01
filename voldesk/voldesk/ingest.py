"""CSV ingestion for the vendor's nightly gamma screen export."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional, Union

from .models import GammaScreenRow

REQUIRED_COLUMNS = [
    "symbol",
    "spot",
    "db",
    "db_change",
    "grade",
    "p_trans",
    "n_trans",
    "plus_gex",
    "cotmp",
]

OPTIONAL_BOOL_COLUMNS = ["grade_11_deep", "spike_crash_pattern"]
OPTIONAL_FLOAT_COLUMNS = [
    "db_prior_2_sessions",
    "minervini_score",
    "oi_depth",
    "zero_gex",
    "plus_gex_next",
    "cotmc",
]

TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}


def _parse_bool(value: Optional[str], column: str) -> bool:
    if value is None or value.strip() == "":
        return False
    lowered = value.strip().lower()
    if lowered in TRUE_VALUES:
        return True
    if lowered in FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean value {value!r} in column {column!r}")


def _parse_optional_float(value: Optional[str]) -> Optional[float]:
    if value is None or value.strip() == "":
        return None
    return float(value)


def load_gamma_screen(path: Union[str, Path]) -> list[GammaScreenRow]:
    """Load a gamma screen CSV export and return a list of GammaScreenRow.

    Raises ValueError with a clear message if a required column is missing.
    """
    path = Path(path)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in fieldnames]
        if missing:
            raise ValueError(
                f"Gamma screen CSV is missing required column(s): {', '.join(missing)}"
            )

        rows: list[GammaScreenRow] = []
        for line_num, record in enumerate(reader, start=2):
            try:
                row = GammaScreenRow(
                    symbol=record["symbol"],
                    spot=float(record["spot"]),
                    dealer_delta_balance=float(record["db"]),
                    db_change=float(record["db_change"]),
                    grade=int(record["grade"]),
                    p_trans=float(record["p_trans"]),
                    n_trans=float(record["n_trans"]),
                    plus_gex=float(record["plus_gex"]),
                    cotmp=float(record["cotmp"]),
                    grade_11_deep=_parse_bool(record.get("grade_11_deep"), "grade_11_deep"),
                    db_prior_2_sessions=_parse_optional_float(record.get("db_prior_2_sessions")),
                    minervini_score=_parse_optional_float(record.get("minervini_score")),
                    oi_depth=_parse_optional_float(record.get("oi_depth")),
                    zero_gex=_parse_optional_float(record.get("zero_gex")),
                    plus_gex_next=_parse_optional_float(record.get("plus_gex_next")),
                    cotmc=_parse_optional_float(record.get("cotmc")),
                    spike_crash_pattern=_parse_bool(
                        record.get("spike_crash_pattern"), "spike_crash_pattern"
                    ),
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Error parsing gamma screen CSV row {line_num}: {exc}") from exc
            rows.append(row)

    return rows


def filter_p2p_candidates(rows: list[GammaScreenRow]) -> list[GammaScreenRow]:
    """Return the subset of rows where spot has already crossed above pTrans."""
    return [row for row in rows if row.spot >= row.p_trans]
