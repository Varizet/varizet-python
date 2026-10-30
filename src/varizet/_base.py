"""Request building, retries and error mapping shared by the sync and async clients."""

from __future__ import annotations

import json
import os
import random
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from ._errors import APIConnectionError, APIError, RateLimitError, error_class
from ._version import __version__

API_VERSION = "2026-10-01"
DEFAULT_BASE_URL = "https://api.varizet.ir"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
#: Answers worth one more try (the request is safe to repeat: GET, or a POST with its key).
RETRY_STATUSES = frozenset({500, 502, 503, 504})
_KEY = re.compile(r"vz_(live|test)_[0-9A-Za-z]+")


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    path: str
    params: Mapping[str, str] | None
    body: bytes | None
    headers: Mapping[str, str]


def segment(value: str) -> str:
    """One path segment (ids, codes), percent-encoded."""
    if not value:
        raise ValueError("an id is required")
    return quote(value, safe="")


class BaseClient:
    def __init__(
        self,
        api_key: str | None,
        *,
        base_url: str | None,
        timeout: float,
        max_retries: int,
        app_info: str | None,
    ) -> None:
        key = api_key or os.environ.get("VARIZET_API_KEY")
        if not key or not _KEY.fullmatch(key):
            raise ValueError("api_key must be a vz_live_… or vz_test_… key (or set VARIZET_API_KEY)")
        self._api_key = key
        self.base_url = (base_url or os.environ.get("VARIZET_API_BASE") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._user_agent = f"varizet-python/{__version__}" + (f" {app_info}" if app_info else "")

    @property
    def livemode(self) -> bool:
        return self._api_key.startswith("vz_live_")

    def __repr__(self) -> str:
        mode = "live" if self.livemode else "test"
        return f"{type(self).__name__}(base_url={self.base_url!r}, mode={mode!r})"

    def _prepare(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | None] | None = None,
        body: Any = None,
        idempotency_key: str | None = None,
    ) -> PreparedRequest:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "Varizet-Version": API_VERSION,
            "User-Agent": self._user_agent,
        }
        if method == "POST":
            # every POST carries a key, so a retry after a lost answer can never act twice
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        raw: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        return PreparedRequest(method, path, clean or None, raw, headers)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = _retry_after(response)
        if retry_after is not None:
            return min(retry_after, 30.0)
        return min(0.5 * 2.0**attempt, 8.0) * (0.75 + random.random() / 2)  # noqa: S311 (jitter)

    def _should_retry_status(self, attempt: int, response: httpx.Response) -> bool:
        return attempt < self.max_retries and response.status_code in RETRY_STATUSES

    def _parse(self, response: httpx.Response) -> Any:
        try:
            data = response.json() if response.content else None
        except ValueError:
            data = None
        if response.is_success:
            if data is None and response.content:
                raise APIConnectionError(f"Varizet answered {response.status_code} with a non-JSON body")
            return data
        raise _api_error(response, data)


def _retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    value = response.headers.get("retry-after")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def _api_error(response: httpx.Response, data: Any) -> APIError:
    error = data.get("error") if isinstance(data, Mapping) else None
    status = response.status_code
    request_id = response.headers.get("x-request-id")
    if isinstance(error, Mapping) and isinstance(error.get("code"), str):
        kwargs: dict[str, Any] = {
            "status": status,
            "type": str(error.get("type") or ""),
            "code": str(error["code"]),
            "message": str(error.get("message") or ""),
            "param": error.get("param") if isinstance(error.get("param"), str) else None,
            "request_id": error.get("request_id") if isinstance(error.get("request_id"), str) else request_id,
            "body": data,
        }
    else:
        kwargs = {
            "status": status,
            "type": "api_error" if status >= 500 else "invalid_request",
            "code": f"http_{status}",
            "message": f"HTTP {status}",
            "request_id": request_id,
            "body": data,
        }
    cls = error_class(status, kwargs["type"])
    if cls is RateLimitError:
        return RateLimitError(retry_after=_retry_after(response), **kwargs)
    return cls(**kwargs)
