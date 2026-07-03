"""0DTE module (Sang Lucci / intraday gamma-flow inspiration).

0DTE is a high-variance regime: gamma explodes near expiry and dealer hedging
flows dominate the tape. The module treats the guardrails as non-negotiable:

- **Universe is restricted to SPY, SPX, QQQ** (equivalent highly-liquid names).
- Expiry must equal today. If no same-day expiry exists on the chain, skip.
- Signal = composite of:
    1. Opening range breakout (ORB) — first 30 minutes define the range,
       a close beyond it votes long or short.
    2. VWAP relationship — price above VWAP confirms longs, below confirms shorts.
    3. Dealer-gamma proxy — sum of ATM chain gamma. Positive gamma = sellers in
       control (mean-reverting), negative = dealers short gamma (trend-amplifying).
- **Every returned setup carries a hard stop-loss** (dollar loss). No exceptions
  — this overrides the high-volume module's no-stop behavior on purpose.
- Session circuit breaker (via ``RiskGuard`` in session mode): halt new entries
  after N consecutive losses or once session drawdown exceeds a % of cash.

Signal output is a compact "signal log" — entry timestamp + thesis + stop — so
the UI can render intraday activity without replaying the raw ticks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Literal

from app.core.models import (
    CONTRACT_MULTIPLIER,
    Account,
    Candidate,
    JournalEntry,
    ManagementAction,
    ManagementVerdict,
    MarketSnapshot,
    OptionChain,
    OptionContract,
    OptionRight,
    Position,
    PositionSize,
    StopLoss,
    TradeLeg,
    TradeSetup,
)
from app.data.base import DataProvider, IntradayBar
from app.risk.guard import RiskCaps, RiskGuard

ALLOWED_UNIVERSE = {"SPY", "SPX", "QQQ", "SPXW", "XSP"}
Direction = Literal["long", "short"]


@dataclass(frozen=True)
class ZeroDTEConfig:
    opening_range_minutes: int = 30
    stop_loss_pct_of_debit: float = 0.40  # hard stop at 40% of the debit paid
    risk_per_trade: float = 0.005  # 0.5% of cash per 0DTE ticket
    min_signal_score: int = 2  # need 2 of {ORB, VWAP, GEX} to fire


@dataclass
class SignalLogEntry:
    timestamp: datetime
    direction: Direction
    orb_vote: bool
    vwap_vote: bool
    gex_vote: bool
    score: int
    thesis: str


class ZeroDTEStrategist:
    name = "zero_dte"

    def __init__(
        self,
        provider: DataProvider,
        journal: Iterable[JournalEntry] | None = None,
        risk_caps: RiskCaps | None = None,
        config: ZeroDTEConfig | None = None,
    ):
        self._provider = provider
        self._journal = list(journal or [])
        self._risk_guard = RiskGuard(caps=risk_caps)
        self._config = config or ZeroDTEConfig()

    @property
    def risk_guard(self) -> RiskGuard:
        return self._risk_guard

    def set_journal(self, journal: Iterable[JournalEntry]) -> None:
        self._journal = list(journal)

    # ------------------------------------------------------------------ screen
    def screen(self, universe: list[str]) -> list[Candidate]:
        out: list[Candidate] = []
        for ticker in universe:
            if ticker.upper() not in ALLOWED_UNIVERSE:
                continue
            try:
                chain = self._provider.get_chain(ticker)
            except Exception:  # pragma: no cover
                continue
            setup = self.analyze(ticker, chain)
            if setup is not None and setup.strategy != "skip":
                out.append(
                    Candidate(
                        ticker=ticker.upper(),
                        reason=setup.thesis,
                        score=setup.expected_value or 0.0,
                    )
                )
        return out

    # ----------------------------------------------------------------- analyze
    def analyze(self, ticker: str, chain: OptionChain) -> TradeSetup | None:
        if ticker.upper() not in ALLOWED_UNIVERSE:
            return self._skip(
                ticker,
                f"0DTE only trades the SPX/SPY/QQQ cluster. {ticker.upper()} rejected.",
            )

        today = self._today(chain.as_of)
        if today not in chain.expiries():
            return self._skip(ticker, "No same-day (0DTE) expiry on the chain.")

        bars = self._provider.get_intraday_bars(ticker, today)
        if len(bars) < self._config.opening_range_minutes + 5:
            return self._skip(ticker, "Not enough intraday data to evaluate ORB yet.")

        # Session circuit breaker — fire before anything else so the module
        # halts cleanly after N losses or drawdown.
        account_probe = Account(cash=100_000)
        circuit = self._risk_guard.check_entry(
            ticker=ticker,
            proposed_contracts=1,
            account=account_probe,
            journal=self._journal,
            as_of=chain.as_of,
            session_only=True,
        )
        if not circuit.allowed:
            return self._skip(ticker, f"Session circuit breaker: {circuit.reason}")

        signal = self._evaluate_signals(bars)
        if signal.score < self._config.min_signal_score:
            return self._skip(
                ticker,
                f"Signal score {signal.score}/3 < min {self._config.min_signal_score}; no trade.",
            )

        # Pick a same-day ATM option on the signal's direction.
        today_legs = chain.by_expiry(today)
        right = OptionRight.CALL if signal.direction == "long" else OptionRight.PUT
        candidate_pool = [c for c in today_legs if c.right is right]
        if not candidate_pool:
            return self._skip(ticker, f"No 0DTE {right.value} contracts available on chain.")
        atm = min(candidate_pool, key=lambda c: abs(c.strike - chain.spot))

        debit = atm.mid
        if debit <= 0:
            return self._skip(ticker, "0DTE contract mid is zero — spread too wide to trade.")

        # Mandatory hard stop — expressed in dollars of loss per contract.
        stop_dollar_loss = debit * self._config.stop_loss_pct_of_debit * CONTRACT_MULTIPLIER
        max_loss = debit  # long option → max loss = premium paid
        max_profit_est = debit * 2.0  # 2R target — conservative
        return TradeSetup(
            ticker=ticker.upper(),
            strategy=f"zero_dte_{signal.direction}_atm",
            thesis=signal.thesis,
            legs=[TradeLeg(contract=atm, quantity=1)],
            net_credit=-debit,
            max_profit=max_profit_est,
            max_loss=max_loss,
            max_theoretical_loss=max_loss,
            breakevens=[atm.strike + debit if signal.direction == "long" else atm.strike - debit],
            pop=None,
            expected_value=None,
            iv_rank=None,
            iv_percentile=None,
            dte=0,
            stop_loss=StopLoss(
                dollar_loss=stop_dollar_loss,
                kind="dollar_loss",
            ),
            notes=[
                f"Signal score {signal.score}/3 (ORB={signal.orb_vote}, "
                f"VWAP={signal.vwap_vote}, GEX={signal.gex_vote}).",
                "MANDATORY HARD STOP: exit at the stop_loss.dollar_loss value. "
                "This overrides any no-stop behavior from the high-volume module.",
                f"Session circuit-breaker caps: {self._risk_guard.caps.session_max_consecutive_losses} "
                f"consecutive losses, {self._risk_guard.caps.session_max_drawdown_pct} drawdown.",
            ],
        )

    # -------------------------------------------------------------------- size
    def size(self, setup: TradeSetup, account: Account) -> PositionSize:
        if setup.max_loss <= 0:
            return PositionSize(
                contracts=0, capital_at_risk=0.0, pct_of_account=0.0,
                rationale="Degenerate payoff.",
            )
        budget = account.cash * self._config.risk_per_trade
        per_contract = setup.max_loss * CONTRACT_MULTIPLIER
        contracts = int(budget // per_contract)
        decision = self._risk_guard.check_entry(
            ticker=setup.ticker,
            proposed_contracts=contracts,
            account=account,
            journal=self._journal,
            as_of=datetime.now(tz=timezone.utc),
            session_only=True,
        )
        if not decision.allowed:
            return PositionSize(
                contracts=0,
                capital_at_risk=0.0,
                pct_of_account=0.0,
                rationale=f"Session circuit breaker: {decision.reason}",
            )
        capital_at_risk = contracts * per_contract
        return PositionSize(
            contracts=contracts,
            capital_at_risk=capital_at_risk,
            pct_of_account=capital_at_risk / account.cash if account.cash > 0 else 0.0,
            rationale=(
                f"0DTE sized to {self._config.risk_per_trade:.2%} of cash with "
                f"hard stop at {self._config.stop_loss_pct_of_debit:.0%} of debit."
            ),
        )

    # ------------------------------------------------------------------ manage
    def manage(self, position: Position, market: MarketSnapshot) -> ManagementAction:
        stop = position.setup.stop_loss
        if stop is None:
            # 0DTE without a stop is an invariant violation. Close immediately.
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_TIME,
                reason="0DTE position is missing its mandatory stop-loss — closing.",
                suggested_action="Close at market and audit where the stop was dropped.",
            )
        stop_dollars = stop.dollar_loss * position.size.contracts
        if position.current_pnl <= -stop_dollars:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_TIME,
                reason=f"Hard stop hit: P/L ${position.current_pnl:,.0f} <= -${stop_dollars:,.0f}.",
                suggested_action="Close at market — no scale-in on 0DTE.",
            )
        target = position.setup.max_profit * CONTRACT_MULTIPLIER * position.size.contracts
        if target > 0 and position.current_pnl >= target:
            return ManagementAction(
                verdict=ManagementVerdict.CLOSE_WINNER,
                reason="Hit 2R profit target on 0DTE.",
            )
        return ManagementAction(verdict=ManagementVerdict.HOLD, reason="Stop and target both untouched.")

    # =================================================================== signals
    def _evaluate_signals(self, bars: list[IntradayBar]) -> SignalLogEntry:
        window = self._config.opening_range_minutes
        or_high = max(b.high for b in bars[:window])
        or_low = min(b.low for b in bars[:window])
        last = bars[-1]

        orb_vote_long = last.close > or_high
        orb_vote_short = last.close < or_low

        vwap = self._vwap(bars)
        vwap_vote_long = last.close > vwap
        vwap_vote_short = last.close < vwap

        gex_proxy = self._gex_proxy(bars)
        # Positive GEX = suppressive (sellers on top), favour mean reversion.
        # Negative GEX = amplifying, favour trend continuation.
        gex_vote_long = (orb_vote_long and gex_proxy < 0) or (
            not orb_vote_long and not orb_vote_short and gex_proxy > 0 and last.close > vwap
        )
        gex_vote_short = (orb_vote_short and gex_proxy < 0) or (
            not orb_vote_long and not orb_vote_short and gex_proxy > 0 and last.close < vwap
        )

        long_score = int(orb_vote_long) + int(vwap_vote_long) + int(gex_vote_long)
        short_score = int(orb_vote_short) + int(vwap_vote_short) + int(gex_vote_short)
        direction: Direction = "long" if long_score >= short_score else "short"
        score = max(long_score, short_score)
        thesis = (
            f"0DTE {direction}: last {last.close:.2f} vs OR[{or_low:.2f}, {or_high:.2f}], "
            f"VWAP {vwap:.2f}, GEX proxy {gex_proxy:+.3f}."
        )
        return SignalLogEntry(
            timestamp=last.timestamp,
            direction=direction,
            orb_vote=orb_vote_long if direction == "long" else orb_vote_short,
            vwap_vote=vwap_vote_long if direction == "long" else vwap_vote_short,
            gex_vote=gex_vote_long if direction == "long" else gex_vote_short,
            score=score,
            thesis=thesis,
        )

    @staticmethod
    def _vwap(bars: list[IntradayBar]) -> float:
        vol_price = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars)
        vol = sum(b.volume for b in bars)
        return vol_price / vol if vol > 0 else bars[-1].close

    @staticmethod
    def _gex_proxy(bars: list[IntradayBar]) -> float:
        """Dealer gamma proxy from intraday realized vol.

        Full dealer GEX needs the entire option chain's gamma × open-interest,
        which is out of scope for the mock. We proxy using the *change* in
        realized vol: rising intraday vol usually tracks dealers getting
        shorter gamma. Returns a small signed number in vol units.
        """
        if len(bars) < 30:
            return 0.0
        closes = [b.close for b in bars]
        first_block = closes[: len(closes) // 2]
        second_block = closes[len(closes) // 2 :]
        rv_first = _std(first_block)
        rv_second = _std(second_block)
        return rv_first - rv_second  # positive = vol *cooling* → positive GEX regime

    # ===================================================================== utils
    @staticmethod
    def _today(as_of: datetime) -> date:
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        return as_of.astimezone(timezone.utc).date()

    def _skip(self, ticker: str, reason: str) -> TradeSetup:
        return TradeSetup(
            ticker=ticker.upper(),
            strategy="skip",
            thesis=reason,
            legs=[],
            net_credit=0.0,
            max_profit=0.0,
            max_loss=0.0,
            breakevens=[],
            dte=0,
            notes=[reason],
        )


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return float((sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5)
