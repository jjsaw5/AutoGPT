"""yfinance-backed DataProvider for local development.

yfinance returns delayed / end-of-day data and is rate-limited without notice.
It is suitable for experimenting; use a paid provider (Polygon, Tradier) before
relying on any output. See ``options-tool/backend/app/data/README.md`` for cost
notes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app.core.models import OptionChain, OptionContract, OptionRight
from app.data.base import DataProvider, IntradayBar, IVHistoryPoint, PriceBar
from app.data.cache import ChainCache


class YFinanceProvider:
    """Wraps yfinance. Caches chain + history calls through ChainCache."""

    name = "yfinance"

    def __init__(self, cache: ChainCache | None = None):
        import yfinance  # deferred import so tests don't need the dep loaded

        self._yf = yfinance
        self._cache = cache or ChainCache()

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get_chain(self, ticker: str, expiry: date | None = None) -> OptionChain:
        cached = self._cache.get(self.name, "chain", ticker, str(expiry or "all"))
        if cached is not None:
            return OptionChain.model_validate(cached)

        tkr = self._yf.Ticker(ticker)
        info = tkr.fast_info
        spot = float(info.last_price or info.regular_market_previous_close)
        expiries = [datetime.strptime(d, "%Y-%m-%d").date() for d in tkr.options]
        if expiry is not None:
            expiries = [e for e in expiries if e == expiry]

        contracts: list[OptionContract] = []
        as_of = self.now()
        for exp in expiries:
            opt = tkr.option_chain(exp.strftime("%Y-%m-%d"))
            contracts.extend(self._rows_to_contracts(opt.calls, ticker, exp, OptionRight.CALL, as_of))
            contracts.extend(self._rows_to_contracts(opt.puts, ticker, exp, OptionRight.PUT, as_of))

        chain = OptionChain(
            underlying=ticker.upper(),
            spot=spot,
            as_of=as_of,
            contracts=contracts,
        )
        self._cache.set(self.name, "chain", ticker, chain.model_dump(mode="json"), str(expiry or "all"))
        return chain

    @staticmethod
    def _rows_to_contracts(
        df: pd.DataFrame,
        ticker: str,
        expiry: date,
        right: OptionRight,
        as_of: datetime,
    ) -> list[OptionContract]:
        out: list[OptionContract] = []
        for _, row in df.iterrows():
            out.append(
                OptionContract(
                    symbol=str(row.get("contractSymbol", "")),
                    underlying=ticker.upper(),
                    expiry=expiry,
                    strike=float(row["strike"]),
                    right=right,
                    bid=float(row.get("bid") or 0.0),
                    ask=float(row.get("ask") or 0.0),
                    last=float(row.get("lastPrice") or 0.0) or None,
                    volume=int(row.get("volume") or 0),
                    open_interest=int(row.get("openInterest") or 0),
                    implied_vol=float(row.get("impliedVolatility") or 0.0) or None,
                    as_of=as_of,
                )
            )
        return out

    def get_history(self, ticker: str, lookback_days: int) -> list[PriceBar]:
        cached = self._cache.get(self.name, "history", ticker, str(lookback_days))
        if cached is not None:
            return [PriceBar.model_validate(p) for p in cached]

        df: pd.DataFrame = self._yf.Ticker(ticker).history(period=f"{lookback_days}d")
        bars = [
            PriceBar(
                date=idx.date(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=int(row["Volume"]),
            )
            for idx, row in df.iterrows()
        ]
        self._cache.set(
            self.name, "history", ticker, [b.model_dump(mode="json") for b in bars], str(lookback_days)
        )
        return bars

    def get_intraday_bars(
        self, ticker: str, session_date: date, interval_minutes: int = 1
    ) -> list[IntradayBar]:
        """yfinance exposes intraday bars via ``history(interval=...)`` but the
        lookback window on free tiers is 7 days. Anything older returns empty.
        """
        interval = f"{interval_minutes}m"
        df: pd.DataFrame = self._yf.Ticker(ticker).history(
            start=session_date.isoformat(),
            end=(session_date.fromordinal(session_date.toordinal() + 1)).isoformat(),
            interval=interval,
        )
        bars: list[IntradayBar] = []
        for idx, row in df.iterrows():
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            bars.append(
                IntradayBar(
                    timestamp=ts,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )
        return bars

    def get_iv_history(self, ticker: str, lookback_days: int = 252) -> list[IVHistoryPoint]:
        """yfinance has no IV history endpoint. Approximate with realized vol.

        This is a dev-only fallback; Polygon's ``/v3/snapshot/options`` or a
        dedicated vol surface service is what you want in production.
        """
        cached = self._cache.get(self.name, "iv_history", ticker, str(lookback_days))
        if cached is not None:
            return [IVHistoryPoint.model_validate(p) for p in cached]

        bars = self.get_history(ticker, lookback_days + 30)
        closes = np.array([b.close for b in bars], dtype=float)
        if closes.size < 22:
            return []
        log_returns = np.diff(np.log(closes))
        # 21-day rolling realized vol, annualised (252 trading days).
        window = 21
        realized: list[float] = []
        for i in range(window, len(log_returns) + 1):
            realized.append(float(np.std(log_returns[i - window : i], ddof=1) * np.sqrt(252)))
        dates = [b.date for b in bars[window + 1 :]]
        history = [
            IVHistoryPoint(date=d, atm_iv=max(v, 0.0)) for d, v in zip(dates, realized, strict=False)
        ]
        self._cache.set(
            self.name,
            "iv_history",
            ticker,
            [p.model_dump(mode="json") for p in history],
            str(lookback_days),
        )
        return history


_: DataProvider = YFinanceProvider.__new__(YFinanceProvider)
del _
