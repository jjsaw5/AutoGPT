"""Financial Modeling Prep (FMP) options-chain and quote client.

FMP's option-chain response schema was **not verified against live API
docs during this implementation** (the docs site blocked automated
access) -- verify the ALIAS maps below against a real response from your
FMP plan before trusting these numbers, and adjust as needed. This client
was written defensively: it checks a handful of plausible field-name
variants per logical field, and raises a clear ``ValueError`` (rather than
silently defaulting to 0) if none of them are present, because a silently
wrong strike/OI/IV would corrupt the downstream GEX math invisibly.

Only stdlib is used (``urllib`` for HTTP, ``json`` for parsing) -- no
``requests`` dependency, to keep this package dependency-free.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from ..gex import OptionContract

Transport = Callable[[str], Any]

DEFAULT_TIMEOUT_SECONDS = 15

# Plausible field-name variants per logical field, in preference order.
# ADJUST THESE against a real FMP response before relying on this client.
_STRIKE_ALIASES = ("strike", "strikePrice")
_OPTION_TYPE_ALIASES = ("optionType", "type", "contractType")
_OPEN_INTEREST_ALIASES = ("openInterest", "open_interest")
_VOLUME_ALIASES = ("volume", "totalVolume")
_IMPLIED_VOL_ALIASES = ("impliedVolatility", "iv")
_EXPIRATION_ALIASES = ("expirationDate", "expiration")
_PRICE_ALIASES = ("price", "lastPrice", "close")

_CALL_VALUES = {"call", "c"}
_PUT_VALUES = {"put", "p"}


class FmpApiError(RuntimeError):
    """Raised when the FMP transport returns a non-200/malformed response."""


def _default_transport(url: str) -> Any:
    """Default stdlib transport: urlopen + json.loads, 15s timeout.

    Raises FmpApiError on HTTP errors, network errors, or invalid JSON --
    callers relying on the default transport never get a silent failure.
    """
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise FmpApiError(f"FMP request to {url!r} returned HTTP {status}")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        raise FmpApiError(f"FMP request to {url!r} failed: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise FmpApiError(f"FMP request to {url!r} failed: {exc.reason}") from exc

    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FmpApiError(f"FMP response for {url!r} was not valid JSON: {exc}") from exc


def _resolve_alias(record: dict, aliases: tuple[str, ...], label: str, record_repr: str) -> Any:
    for key in aliases:
        if key in record and record[key] is not None:
            return record[key]
    raise ValueError(
        f"Option chain record {record_repr} is missing required field {label!r} "
        f"(checked aliases: {', '.join(aliases)}). Refusing to default to 0, as that "
        f"would silently corrupt GEX math -- verify the FMP response schema against "
        f"voldesk/voldesk/sources/fmp.py's ALIAS lists."
    )


def _normalize_option_type_value(raw: Any, record_repr: str) -> str:
    lowered = str(raw).strip().lower()
    if lowered in _CALL_VALUES:
        return "call"
    if lowered in _PUT_VALUES:
        return "put"
    raise ValueError(
        f"Option chain record {record_repr} has an unrecognized option type {raw!r}"
    )


def _record_to_contract(record: dict) -> OptionContract:
    record_repr = repr(record)[:200]

    strike = _resolve_alias(record, _STRIKE_ALIASES, "strike", record_repr)
    raw_option_type = _resolve_alias(record, _OPTION_TYPE_ALIASES, "option_type", record_repr)
    open_interest = _resolve_alias(record, _OPEN_INTEREST_ALIASES, "open_interest", record_repr)
    implied_vol = _resolve_alias(
        record, _IMPLIED_VOL_ALIASES, "implied_volatility", record_repr
    )
    expiration = _resolve_alias(record, _EXPIRATION_ALIASES, "expiration", record_repr)

    # Volume is treated as optional-with-default-0: a contract that simply
    # hasn't traded today legitimately has volume 0, unlike a missing
    # strike/OI/IV/expiration which would indicate a schema mismatch.
    volume = 0.0
    for key in _VOLUME_ALIASES:
        if key in record and record[key] is not None:
            volume = float(record[key])
            break

    return OptionContract(
        strike=float(strike),
        expiration=str(expiration),
        option_type=_normalize_option_type_value(raw_option_type, record_repr),
        open_interest=float(open_interest),
        volume=volume,
        implied_volatility=float(implied_vol),
        greeks=None,
    )


class FmpClient:
    """Thin client for FMP's options-chain and quote endpoints.

    ``transport`` is injectable so tests can supply a fake that returns
    canned JSON without making real network calls. It defaults to a small
    stdlib ``urllib.request.urlopen`` + ``json.loads`` wrapper.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://financialmodelingprep.com/stable",
        transport: Optional[Transport] = None,
    ) -> None:
        if not api_key:
            raise ValueError("FmpClient requires a non-empty api_key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport: Transport = transport or _default_transport

    def _build_url(self, path: str, params: dict) -> str:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        return f"{self.base_url}/{path.lstrip('/')}?{query}"

    def get_option_chain(
        self, symbol: str, expiration: Optional[str] = None
    ) -> list[OptionContract]:
        """Fetch and normalize the options chain for ``symbol``.

        NOTE: the endpoint path ("options-chain") and the exact response
        field names below were not verified against live FMP docs -- see
        the module docstring. Adjust the ALIAS lists in this file if a
        real response uses different field names.
        """
        url = self._build_url(
            "options-chain",
            {"symbol": symbol, "apikey": self.api_key, "expiration": expiration},
        )
        data = self.transport(url)

        if isinstance(data, dict):
            # Some FMP endpoints wrap the array in a top-level key. Try a
            # couple of plausible variants before giving up.
            for key in ("optionsChain", "data", "results"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                raise FmpApiError(
                    f"Unexpected FMP option chain response shape for {symbol!r}: {data!r}"
                )

        if not isinstance(data, list):
            raise FmpApiError(
                f"Unexpected FMP option chain response shape for {symbol!r}: {data!r}"
            )

        return [_record_to_contract(record) for record in data]

    def get_quote(self, symbol: str) -> dict:
        """Fetch a simple quote for ``symbol`` (used for the spot price)."""
        url = self._build_url("quote", {"symbol": symbol, "apikey": self.api_key})
        data = self.transport(url)

        if isinstance(data, list):
            if not data:
                raise FmpApiError(f"FMP quote response for {symbol!r} was an empty list")
            data = data[0]

        if not isinstance(data, dict):
            raise FmpApiError(f"Unexpected FMP quote response shape for {symbol!r}: {data!r}")

        record_repr = repr(data)[:200]
        # Validate the price field is resolvable up front so callers get a
        # clear error immediately rather than a confusing KeyError later.
        _resolve_alias(data, _PRICE_ALIASES, "price", record_repr)
        return data

    def get_quote_price(self, symbol: str) -> float:
        """Convenience wrapper: fetch a quote and return just the price."""
        data = self.get_quote(symbol)
        record_repr = repr(data)[:200]
        price = _resolve_alias(data, _PRICE_ALIASES, "price", record_repr)
        return float(price)
