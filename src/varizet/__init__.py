"""Varizet (واریزت) Python SDK: the public ``/v1`` API, webhook verification and sandbox helpers.

Money is ``int`` rial everywhere; timestamps are aware UTC ``datetime`` objects.
"""

from ._base import API_VERSION, DEFAULT_BASE_URL
from ._client import AsyncVarizet, Varizet
from ._errors import (
    APIConnectionError,
    APIError,
    APIServerError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    VarizetError,
)
from ._models import (
    ORDER_STATUSES,
    WEBHOOK_EVENT_TYPES,
    ApiKeyIdentity,
    CreatedWebhookEndpoint,
    Customer,
    Deleted,
    Deposit,
    EventResent,
    Order,
    OrderDestination,
    OrderMatch,
    Page,
    Refund,
    RotatedSecret,
    StoreRef,
    WebhookEndpoint,
    WebhookEvent,
    WebhookPingResult,
)
from ._version import __version__
from .formatting import format_rial, to_persian_digits
from .webhooks import (
    SIGNATURE_HEADER,
    WebhookSignatureError,
    construct_event,
    verify_signature,
)

__all__ = [
    "API_VERSION",
    "DEFAULT_BASE_URL",
    "ORDER_STATUSES",
    "SIGNATURE_HEADER",
    "WEBHOOK_EVENT_TYPES",
    "APIConnectionError",
    "APIError",
    "APIServerError",
    "APITimeoutError",
    "ApiKeyIdentity",
    "AsyncVarizet",
    "AuthenticationError",
    "ConflictError",
    "CreatedWebhookEndpoint",
    "Customer",
    "Deleted",
    "Deposit",
    "EventResent",
    "InvalidRequestError",
    "NotFoundError",
    "Order",
    "OrderDestination",
    "OrderMatch",
    "Page",
    "PermissionDeniedError",
    "RateLimitError",
    "Refund",
    "RotatedSecret",
    "StoreRef",
    "ValidationError",
    "Varizet",
    "VarizetError",
    "WebhookEndpoint",
    "WebhookEvent",
    "WebhookPingResult",
    "WebhookSignatureError",
    "__version__",
    "construct_event",
    "format_rial",
    "to_persian_digits",
    "verify_signature",
]
