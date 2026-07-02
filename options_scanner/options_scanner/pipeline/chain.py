"""Live option-chain abstraction (Unusual Whales per-contract endpoints).

Turns UW's `option-contracts` (per-strike OI / volume / NBBO / IV) and `greeks`
(per-strike delta) into a single-expiry :class:`OptionChain` so structure
selection can pick *real* strikes and premiums, and gates G1/G2/G9 + POP can be
evaluated on real contracts instead of proxies/placeholders.

Robinhood still confirms live quotes at execution time (spec §2); this makes the
scan itself real rather than sketched.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

_OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")

# Target days-to-expiry by horizon (structure selection picks the nearest
# available expiry to this).
_HORIZON_DTE = {
    "intraday": 0,
    "swing": 14,
    "position": 35,
    "leaps": 270,
}


def parse_occ(symbol: str) -> tuple[str, str, float] | None:
    """Parse an OCC option symbol → (option_type, expiry_iso, strike).

    e.g. ``AAPL260717C00317500`` → ``("call", "2026-07-17", 317.5)``.
    """
    m = _OCC.match(symbol.strip())
    if not m:
        return None
    opt_type = "call" if m.group("cp") == "C" else "put"
    expiry = f"20{m.group('yy')}-{m.group('mm')}-{m.group('dd')}"
    strike = int(m.group("strike")) / 1000.0
    return opt_type, expiry, strike


def _f(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass
class OptionContract:
    option_type: str      # "call" | "put"
    expiry: str           # ISO date
    strike: float
    oi: int = 0
    volume: int = 0
    bid: float | None = None
    ask: float | None = None
    iv: float | None = None
    delta: float | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        if self.ask <= 0:
            return None
        return round((self.bid + self.ask) / 2, 4)

    @property
    def spread_pct(self) -> float | None:
        mid = self.mid
        if not mid or mid <= 0:
            return None
        return (self.ask - self.bid) / mid


@dataclass
class OptionChain:
    """A single-expiry chain (both call and put ladders) for one ticker."""

    ticker: str
    expiry: str
    spot: float
    dte: int
    contracts: list[OptionContract] = field(default_factory=list)

    def _side(self, option_type: str) -> list[OptionContract]:
        return sorted(
            (c for c in self.contracts if c.option_type == option_type),
            key=lambda c: c.strike,
        )

    def strikes(self, option_type: str) -> list[float]:
        return [c.strike for c in self._side(option_type)]

    def at_strike(self, option_type: str, strike: float) -> OptionContract | None:
        side = self._side(option_type)
        if not side:
            return None
        return min(side, key=lambda c: abs(c.strike - strike))

    def atm(self, option_type: str) -> OptionContract | None:
        return self.at_strike(option_type, self.spot)

    def by_delta(self, option_type: str, target: float) -> OptionContract | None:
        side = [c for c in self._side(option_type) if c.delta is not None]
        if not side:
            return None
        return min(side, key=lambda c: abs(abs(c.delta) - abs(target)))

    def offset_strike(
        self, option_type: str, base_strike: float, n: int
    ) -> OptionContract | None:
        """Contract ``n`` strikes above (n>0) / below (n<0) ``base_strike``."""
        side = self._side(option_type)
        strikes = [c.strike for c in side]
        if base_strike not in strikes:
            base = self.at_strike(option_type, base_strike)
            if base is None:
                return None
            base_strike = base.strike
        idx = strikes.index(base_strike) + n
        if 0 <= idx < len(side):
            return side[idx]
        return None


def build_chain(
    uw,
    ticker: str,
    horizon: str,
    spot: float | None,
    *,
    now: datetime | None = None,
) -> OptionChain | None:
    """Fetch and assemble the chain for the expiry nearest this horizon's DTE.

    Returns ``None`` when the chain can't be built (no spot, gated/empty data),
    so callers fall back to the nominal placeholder path.
    """
    if not spot:
        return None
    today = (now or datetime.now(timezone.utc)).date()

    # 1) Discover available expiries from the most-active contracts.
    active = uw.option_contracts(ticker)
    if not active:
        return None
    expiries = _available_expiries(active, today, allow_zero=(horizon == "intraday"))
    if not expiries:
        return None
    target_dte = _HORIZON_DTE.get(horizon, 14)
    chosen_iso, chosen_dte = min(expiries, key=lambda e: abs(e[1] - target_dte))

    # 2) Full ladder + greeks for the chosen expiry.
    ladder = uw.option_contracts(ticker, expiry=chosen_iso)
    grk = uw.greeks(ticker, expiry=chosen_iso)
    if not ladder:
        return None
    delta_by_strike = _delta_index(grk)

    contracts: list[OptionContract] = []
    for row in ladder:
        parsed = parse_occ(str(row.get("option_symbol", "")))
        if not parsed:
            continue
        opt_type, expiry, strike = parsed
        if expiry != chosen_iso:
            continue
        deltas = delta_by_strike.get(strike, {})
        contracts.append(
            OptionContract(
                option_type=opt_type,
                expiry=expiry,
                strike=strike,
                oi=int(row.get("open_interest") or 0),
                volume=int(row.get("volume") or 0),
                bid=_f(row.get("nbbo_bid")),
                ask=_f(row.get("nbbo_ask")),
                iv=_f(row.get("implied_volatility")),
                delta=deltas.get(opt_type),
            )
        )
    if not contracts:
        return None
    return OptionChain(
        ticker=ticker, expiry=chosen_iso, spot=spot, dte=chosen_dte, contracts=contracts
    )


def _available_expiries(
    active: list[dict], today: date, *, allow_zero: bool
) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for row in active:
        parsed = parse_occ(str(row.get("option_symbol", "")))
        if not parsed:
            continue
        _, expiry, _ = parsed
        if expiry in seen:
            continue
        try:
            dte = (datetime.strptime(expiry, "%Y-%m-%d").date() - today).days
        except ValueError:
            continue
        if dte < 0 or (dte == 0 and not allow_zero):
            continue
        seen[expiry] = dte
    return sorted(seen.items(), key=lambda kv: kv[1])


def _delta_index(greeks: list[dict]) -> dict[float, dict[str, float]]:
    """Map strike -> {"call": call_delta, "put": put_delta}."""
    index: dict[float, dict[str, float]] = {}
    for row in greeks:
        strike = _f(row.get("strike"))
        if strike is None:
            continue
        entry: dict[str, float] = {}
        cd = _f(row.get("call_delta"))
        pd = _f(row.get("put_delta"))
        if cd is not None:
            entry["call"] = cd
        if pd is not None:
            entry["put"] = pd
        index[strike] = entry
    return index
