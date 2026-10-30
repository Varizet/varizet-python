"""Typed errors built from the API error shape (docs/05 §2).

Every failed call raises a subclass of :class:`VarizetError`. HTTP errors carry the stable English
``code`` and the Persian, user-facing ``message`` exactly as the API sent them.
"""

from __future__ import annotations

from typing import Any


class VarizetError(Exception):
    """Base class of every error raised by this package."""


class APIConnectionError(VarizetError):
    """No usable answer: network failure, timeout, or a body that is not the documented shape."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class APITimeoutError(APIConnectionError):
    """The request did not finish within the client's timeout."""


class APIError(VarizetError):
    """The API answered with ``{"error": {type, code, message, param, request_id}}``."""

    def __init__(
        self,
        *,
        status: int,
        type: str,
        code: str,
        message: str,
        param: str | None = None,
        request_id: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.type = type
        self.code = code
        self.message = message
        self.param = param
        self.request_id = request_id
        self.body = body

    def __str__(self) -> str:
        suffix = f" (request_id={self.request_id})" if self.request_id else ""
        return f"[{self.status} {self.code}] {self.message}{suffix}"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status={self.status}, code={self.code!r}, request_id={self.request_id!r})"
        )


class InvalidRequestError(APIError):
    """400 ``invalid_request`` (``amount_too_small``, ``invalid_parameter``…)."""


class AuthenticationError(APIError):
    """401 ``authentication_error`` (``invalid_api_key``, ``key_revoked``)."""


class PermissionDeniedError(APIError):
    """403 ``permission_error`` (``scope_missing``, ``testmode_required``, ``plan_limit_reached``…)."""


class NotFoundError(APIError):
    """404 ``not_found`` (``order_not_found``, ``resource_not_found``…)."""


class ConflictError(APIError):
    """409 ``conflict`` (``idempotency_mismatch``, ``order_not_cancelable``…)."""


class ValidationError(APIError):
    """422 ``validation_error`` (``merchant_order_id_duplicate``…)."""


class RateLimitError(APIError):
    """429 ``rate_limited``; ``retry_after`` is the server's ``Retry-After`` in seconds, when sent."""

    def __init__(self, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.retry_after = retry_after


class APIServerError(APIError):
    """5xx ``api_error``: report ``request_id`` to support."""


_BY_STATUS: dict[int, type[APIError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}

_BY_TYPE: dict[str, type[APIError]] = {
    "invalid_request": InvalidRequestError,
    "authentication_error": AuthenticationError,
    "permission_error": PermissionDeniedError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "validation_error": ValidationError,
    "rate_limited": RateLimitError,
    "api_error": APIServerError,
}


def error_class(status: int, error_type: str | None) -> type[APIError]:
    """The error class for an HTTP status, falling back to the body's ``type``."""
    if status >= 500:
        return APIServerError
    return _BY_STATUS.get(status) or (_BY_TYPE.get(error_type or "") or APIError)
