"""HTTP client — rate-limit retry/backoff."""

from __future__ import annotations

import pytest

from options_scanner.clients.base import BaseHTTPClient, HTTPError


class _Resp:
    def __init__(self, status, body=None, retry_after=None):
        self.status_code = status
        self._body = body if body is not None else {"data": [1, 2, 3]}
        self.headers = {"Content-Type": "application/json"}
        if retry_after is not None:
            self.headers["Retry-After"] = str(retry_after)
        self.text = "err"

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _client(responses):
    slept = []
    c = BaseHTTPClient("http://x", backoff_base=0.01, sleep=lambda s: slept.append(s))
    c._session = _Session(responses)
    return c, slept


def test_retries_then_succeeds():
    c, slept = _client([_Resp(429), _Resp(429), _Resp(200, {"data": "ok"})])
    out = c.get("/thing", use_cache=False)
    assert out == {"data": "ok"}
    assert c._session.calls == 3
    assert len(slept) == 2  # backed off twice before the 200


def test_gives_up_after_max_retries():
    c, slept = _client([_Resp(429)] * 5)
    with pytest.raises(HTTPError):
        c.get("/thing", use_cache=False)
    assert c._session.calls == 4  # 1 + 3 retries


def test_respects_retry_after_header():
    c, slept = _client([_Resp(429, retry_after=7), _Resp(200)])
    c.get("/thing", use_cache=False)
    assert slept == [7.0]


def test_no_retry_on_success():
    c, slept = _client([_Resp(200)])
    c.get("/thing", use_cache=False)
    assert c._session.calls == 1 and slept == []
