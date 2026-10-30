"""One function per API operation: builds the request and names the parser. The sync and async
resources only differ in how they execute a :class:`Spec`."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from ._base import segment
from ._models import (
    ApiKeyIdentity,
    CreatedWebhookEndpoint,
    Customer,
    Deleted,
    Deposit,
    EventResent,
    Json,
    Order,
    Page,
    Refund,
    RotatedSecret,
    ShapeError,
    WebhookEndpoint,
    WebhookEvent,
    WebhookPingResult,
    format_datetime,
)

T = TypeVar("T")


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


#: "Leave this field as it is" for PATCH arguments where ``None`` means "clear it".
UNSET: Any = _Unset()


@dataclass(frozen=True)
class Spec(Generic[T]):
    method: Literal["GET", "POST", "PATCH", "DELETE"]
    path: str
    parse: Callable[[Json], T]
    params: Mapping[str, str | None] | None = None
    body: Any = None
    idempotency_key: str | None = None


def as_json(data: Any) -> Json:
    if not isinstance(data, Mapping):
        raise ShapeError("expected a JSON object")
    return data


def rial(name: str, value: int, *, minimum: int = 0) -> int:
    """Money is an ``int`` number of rial (never float, never toman)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int number of rial, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be ≥ {minimum} rial")
    return value


def _limit(limit: int | None) -> str | None:
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an int between 1 and 100")
    return str(limit)


def _time(value: datetime | str | None) -> str | None:
    return None if value is None else format_datetime(value)


def _drop_none(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# --- /v1/me ---------------------------------------------------------------------------------------


def me() -> Spec[ApiKeyIdentity]:
    return Spec("GET", "/v1/me", ApiKeyIdentity.from_dict)


# --- /v1/orders -----------------------------------------------------------------------------------


def create_order(
    *,
    amount: int,
    merchant_order_id: str | None,
    description: str | None,
    customer: Customer | Mapping[str, str | None] | None,
    expires_in: int | None,
    unique_mode: Literal["increase", "decrease"] | None,
    card_id: str | None,
    return_url: str | None,
    metadata: Mapping[str, str] | None,
    payer_last4: str | None,
    idempotency_key: str | None,
) -> Spec[Order]:
    if isinstance(customer, Customer):
        customer = {"name": customer.name, "phone": customer.phone, "email": customer.email}
    body = _drop_none(
        {
            "amount": rial("amount", amount),
            "merchant_order_id": merchant_order_id,
            "description": description,
            "customer": _drop_none(customer) if customer is not None else None,
            "expires_in": expires_in,
            "unique_mode": unique_mode,
            "card_id": card_id,
            "return_url": return_url,
            "metadata": dict(metadata) if metadata is not None else None,
            "payer_last4": payer_last4,
        }
    )
    return Spec("POST", "/v1/orders", Order.from_dict, body=body, idempotency_key=idempotency_key)


def get_order(id_or_code: str) -> Spec[Order]:
    return Spec("GET", f"/v1/orders/{segment(id_or_code)}", Order.from_dict)


def list_orders(
    *,
    status: str | None,
    merchant_order_id: str | None,
    customer_phone: str | None,
    created_gte: datetime | str | None,
    created_lte: datetime | str | None,
    limit: int | None,
    starting_after: str | None,
) -> Spec[Page[Order]]:
    params = {
        "status": status,
        "merchant_order_id": merchant_order_id,
        "customer_phone": customer_phone,
        "created[gte]": _time(created_gte),
        "created[lte]": _time(created_lte),
        "limit": _limit(limit),
        "starting_after": starting_after,
    }
    return Spec("GET", "/v1/orders", lambda d: Page.parse(d, Order.from_dict), params=params)


def cancel_order(id_or_code: str, idempotency_key: str | None) -> Spec[Order]:
    return Spec(
        "POST", f"/v1/orders/{segment(id_or_code)}/cancel", Order.from_dict, idempotency_key=idempotency_key
    )


# --- /v1/refunds ----------------------------------------------------------------------------------


def create_refund(
    *,
    order_id: str,
    amount: int,
    method: Literal["card", "iban"],
    reference: str | None,
    reason: str | None,
    idempotency_key: str | None,
) -> Spec[Refund]:
    body = _drop_none(
        {
            "order_id": order_id,
            "amount": rial("amount", amount, minimum=1),
            "method": method,
            "reference": reference,
            "reason": reason,
        }
    )
    return Spec("POST", "/v1/refunds", Refund.from_dict, body=body, idempotency_key=idempotency_key)


def get_refund(refund_id: str) -> Spec[Refund]:
    return Spec("GET", f"/v1/refunds/{segment(refund_id)}", Refund.from_dict)


def list_refunds(*, order: str | None, limit: int | None, starting_after: str | None) -> Spec[Page[Refund]]:
    return Spec(
        "GET",
        "/v1/refunds",
        lambda d: Page.parse(d, Refund.from_dict),
        params={"order": order, "limit": _limit(limit), "starting_after": starting_after},
    )


# --- /v1/webhook_endpoints, /v1/events -------------------------------------------------------------


def create_endpoint(
    *, url: str, events: Sequence[str], description: str | None, idempotency_key: str | None
) -> Spec[CreatedWebhookEndpoint]:
    body = _drop_none({"url": url, "events": list(events), "description": description})
    return Spec(
        "POST",
        "/v1/webhook_endpoints",
        CreatedWebhookEndpoint.from_dict,
        body=body,
        idempotency_key=idempotency_key,
    )


def list_endpoints(*, limit: int | None, starting_after: str | None) -> Spec[Page[WebhookEndpoint]]:
    return Spec(
        "GET",
        "/v1/webhook_endpoints",
        lambda d: Page.parse(d, WebhookEndpoint.from_dict),
        params={"limit": _limit(limit), "starting_after": starting_after},
    )


def get_endpoint(endpoint_id: str) -> Spec[WebhookEndpoint]:
    return Spec("GET", f"/v1/webhook_endpoints/{segment(endpoint_id)}", WebhookEndpoint.from_dict)


def update_endpoint(
    endpoint_id: str,
    *,
    url: str | None,
    events: Sequence[str] | None,
    description: str | None,
    status: Literal["enabled", "disabled"] | None,
) -> Spec[WebhookEndpoint]:
    body: dict[str, Any] = _drop_none(
        {"url": url, "events": list(events) if events is not None else None, "status": status}
    )
    if description is not UNSET:
        body["description"] = description
    if not body:
        raise ValueError("nothing to update")
    return Spec(
        "PATCH", f"/v1/webhook_endpoints/{segment(endpoint_id)}", WebhookEndpoint.from_dict, body=body
    )


def delete_endpoint(endpoint_id: str) -> Spec[Deleted]:
    return Spec("DELETE", f"/v1/webhook_endpoints/{segment(endpoint_id)}", Deleted.from_dict)


def rotate_secret(endpoint_id: str, idempotency_key: str | None) -> Spec[RotatedSecret]:
    return Spec(
        "POST",
        f"/v1/webhook_endpoints/{segment(endpoint_id)}/rotate_secret",
        RotatedSecret.from_dict,
        idempotency_key=idempotency_key,
    )


def ping_endpoint(endpoint_id: str) -> Spec[WebhookPingResult]:
    return Spec("POST", f"/v1/webhook_endpoints/{segment(endpoint_id)}/ping", WebhookPingResult.from_dict)


def list_events(
    *, type: str | None, limit: int | None, starting_after: str | None
) -> Spec[Page[WebhookEvent]]:
    return Spec(
        "GET",
        "/v1/events",
        lambda d: Page.parse(d, WebhookEvent.from_dict),
        params={"type": type, "limit": _limit(limit), "starting_after": starting_after},
    )


def resend_event(event_id: str, idempotency_key: str | None) -> Spec[EventResent]:
    return Spec(
        "POST",
        f"/v1/events/{segment(event_id)}/resend",
        EventResent.from_dict,
        idempotency_key=idempotency_key,
    )


# --- /v1/test -------------------------------------------------------------------------------------


def simulate_deposit(
    *,
    amount: int,
    card_id: str | None,
    payer_last4: str | None,
    bank: str | None,
    idempotency_key: str | None,
) -> Spec[Deposit]:
    body = _drop_none(
        {
            "amount": rial("amount", amount, minimum=1),
            "card_id": card_id,
            "payer_last4": payer_last4,
            "bank": bank,
        }
    )
    return Spec("POST", "/v1/test/deposits", Deposit.from_dict, body=body, idempotency_key=idempotency_key)
