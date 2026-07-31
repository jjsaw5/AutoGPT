"""A gated, rules-based process for intraday 0DTE SPY/QQQ directional trades.

The engine never places an order. It produces a signal with every gate's
reasoning attached, and a plan whose size is derived from fixed dollar risk.
"""

from .config import DEFAULT_CONFIG, StrategyConfig
from .models import Decision, Regime, Signal
from .regime import score_regime
from .signal import evaluate

__all__ = [
    "DEFAULT_CONFIG",
    "StrategyConfig",
    "Decision",
    "Regime",
    "Signal",
    "score_regime",
    "evaluate",
]
