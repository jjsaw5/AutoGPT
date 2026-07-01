"""Vol Desk: a deterministic, pure-Python rule engine for a mechanical
options swing-trading strategy based on dealer gamma/delta positioning.

This package does NOT connect to any brokerage, fetch live market data, or
place trades. It only classifies structured input (gamma screen CSV rows,
plain price/candle values) into decisions for a human to act on manually.
"""

__version__ = "0.1.0"
