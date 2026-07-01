"""JSON-file-backed persistence for tracked positions. No database involved."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Optional, Union

from .models import Position, PositionStatus


def _position_to_dict(position: Position) -> dict:
    return {
        "symbol": position.symbol,
        "entry_price": position.entry_price,
        "entry_date": position.entry_date.isoformat(),
        "p_trans": position.p_trans,
        "n_trans": position.n_trans,
        "t1_target": position.t1_target,
        "t2_target": position.t2_target,
        "t1_hit": position.t1_hit,
        "stop_locked_to_entry": position.stop_locked_to_entry,
        "status": position.status.value
        if isinstance(position.status, PositionStatus)
        else position.status,
        "daily_closes": [
            [d.isoformat(), price] for d, price in position.daily_closes
        ],
        "close_reason": position.close_reason,
    }


def _position_from_dict(data: dict) -> Position:
    return Position(
        symbol=data["symbol"],
        entry_price=data["entry_price"],
        entry_date=date.fromisoformat(data["entry_date"]),
        p_trans=data["p_trans"],
        n_trans=data["n_trans"],
        t1_target=data["t1_target"],
        t2_target=data.get("t2_target"),
        t1_hit=data.get("t1_hit", False),
        stop_locked_to_entry=data.get("stop_locked_to_entry", False),
        status=PositionStatus(data.get("status", PositionStatus.CONFIRMED.value)),
        daily_closes=[
            (date.fromisoformat(d), price) for d, price in data.get("daily_closes", [])
        ],
        close_reason=data.get("close_reason"),
    )


class PositionLedger:
    """Simple JSON-file-backed store for open/closed positions, keyed by symbol."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self._positions: dict[str, Position] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._positions = {}
            return
        with self.path.open() as f:
            raw = json.load(f)
        self._positions = {
            symbol: _position_from_dict(data) for symbol, data in raw.items()
        }

    def save(self) -> None:
        data = {
            symbol: _position_to_dict(position)
            for symbol, position in self._positions.items()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            json.dump(data, f, indent=2)

    def open_position(self, position: Position) -> None:
        self._positions[position.symbol] = position
        self.save()

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def update_daily_close(self, symbol: str, close_date: date, price: float) -> None:
        position = self._positions.get(symbol)
        if position is None:
            raise KeyError(f"No position found for symbol {symbol!r}")
        position.daily_closes.append((close_date, price))
        self.save()

    def close_position(self, symbol: str, reason: str) -> None:
        position = self._positions.get(symbol)
        if position is None:
            raise KeyError(f"No position found for symbol {symbol!r}")
        position.status = PositionStatus.CLOSED
        position.close_reason = reason
        self.save()

    def all_open(self) -> list[Position]:
        return [
            p for p in self._positions.values() if p.status != PositionStatus.CLOSED
        ]
