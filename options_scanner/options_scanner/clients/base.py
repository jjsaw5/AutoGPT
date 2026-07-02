"""Shared HTTP client with a simple per-scan TTL cache.

Spec §2: "Cache per-ticker per-scan; never duplicate calls." The cache key is
the full (method, url, sorted-params) tuple, so repeated identical requests
inside one scan hit the cache instead of the wire.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

try:
    import requests
except ImportError:  # pragma: no cover - requests is a hard runtime dep
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class HTTPError(RuntimeError):
    """Raised when an HTTP request fails after the client's own handling."""


class BaseHTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        default_headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        cache_ttl: float = 300.0,
    ) -> None:
        if requests is None:  # pragma: no cover
            raise RuntimeError("The 'requests' package is required to make HTTP calls.")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._session = requests.Session()
        if default_headers:
            self._session.headers.update(default_headers)
        # cache: key -> (expires_at, payload)
        self._cache: dict[str, tuple[float, Any]] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _cache_key(self, method: str, url: str, params: dict[str, Any] | None) -> str:
        query = urlencode(sorted((params or {}).items()))
        return f"{method.upper()} {url}?{query}"

    def clear_cache(self) -> None:
        """Drop cached responses. Call at the start of each fresh scan."""
        self._cache.clear()

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        key = self._cache_key("GET", url, params)

        if use_cache and key in self._cache:
            expires_at, payload = self._cache[key]
            if expires_at > self._now():
                return payload
            del self._cache[key]

        try:
            resp = self._session.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
        except Exception as exc:  # network-level failure
            raise HTTPError(f"GET {url} failed: {exc}") from exc

        if resp.status_code >= 400:
            raise HTTPError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")

        payload = _parse_body(resp)
        if use_cache:
            self._cache[key] = (self._now() + self.cache_ttl, payload)
        return payload


def _parse_body(resp: Any) -> Any:
    content_type = resp.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return resp.json()
    # UW can return text/plain Markdown; try JSON first, fall back to text.
    try:
        return resp.json()
    except ValueError:
        return resp.text
