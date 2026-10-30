"""Typed models of the public ``/v1`` API (snake_case, ``@varizet/contracts``).

Money is ``int`` rial everywhere. Timestamps are timezone-aware UTC ``datetime`` objects. Every
model keeps the JSON it came from in ``raw``, and unknown fields are ignored, so a newer API never
breaks an older SDK.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

T = TypeVar("T")

ORDER_STATUSES = (
    "awaiting_payment",
    "needs_review",
    "underpaid",
    "paid",
    "expired",
    "canceled",
    "refunded",
    "partially_refunded",
)

WEBHOOK_EVENT_TYPES = (
    "order.created",
    "order.paid",
    "order.needs_review",
    "order.underpaid",
    "order.expired",
    "order.canceled",
    "refund.created",
    "deposit.unmatched",
    "device.offline",
    "device.online",
    "card.cap_reached",
)


class ShapeError(ValueError):
    """A response field is missing or has the wrong type."""


Json = Mapping[str, Any]


def _get(d: Json, key: str) -> Any:
    if key not in d:
        raise ShapeError(f"missing field {key!r}")
    return d[key]


def _str(d: Json, key: str) -> str:
    v = _get(d, key)
    if not isinstance(v, str):
        raise ShapeError(f"{key!r} must be a string")
    return v


def _opt_str(d: Json, key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ShapeError(f"{key!r} must be a string or null")
    return v


def _int(d: Json, key: str) -> int:
    v = _get(d, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ShapeError(f"{key!r} must be an integer")
    return v


def _opt_int(d: Json, key: str) -> int | None:
    return None if d.get(key) is None else _int(d, key)


def _bool(d: Json, key: str, default: bool | None = None) -> bool:
    if key not in d and default is not None:
        return default
    v = _get(d, key)
    if not isinstance(v, bool):
        raise ShapeError(f"{key!r} must be a boolean")
    return v


def _float(d: Json, key: str) -> float:
    v = _get(d, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ShapeError(f"{key!r} must be a number")
    return float(v)


def _obj(d: Json, key: str) -> Json:
    v = _get(d, key)
    if not isinstance(v, Mapping):
        raise ShapeError(f"{key!r} must be an object")
    return v


def _opt_obj(d: Json, key: str) -> Json | None:
    return None if d.get(key) is None else _obj(d, key)


def _str_list(d: Json, key: str) -> list[str]:
    v = _get(d, key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ShapeError(f"{key!r} must be a list of strings")
    return list(v)


def parse_datetime(value: str) -> datetime:
    """ISO-8601 from the API (``2026-10-28T10:34:12.000Z``) → aware UTC ``datetime`` (3.10-safe)."""
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as err:
        raise ShapeError(f"not an ISO-8601 time: {value!r}") from err
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _dt(d: Json, key: str) -> datetime:
    return parse_datetime(_str(d, key))


def _opt_dt(d: Json, key: str) -> datetime | None:
    v = _opt_str(d, key)
    return None if v is None else parse_datetime(v)


def format_datetime(value: datetime | str) -> str:
    """A query/body time: UTC ISO-8601 with ``Z`` (naive datetimes are taken as UTC)."""
    if isinstance(value, str):
        return value
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Customer:
    name: str | None
    phone: str | None
    email: str | None

    @classmethod
    def from_dict(cls, d: Json) -> Customer:
        return cls(name=_opt_str(d, "name"), phone=_opt_str(d, "phone"), email=_opt_str(d, "email"))


@dataclass(frozen=True)
class OrderDestination:
    card_id: str
    bank: str
    last4: str
    owner_name: str

    @classmethod
    def from_dict(cls, d: Json) -> OrderDestination:
        return cls(_str(d, "card_id"), _str(d, "bank"), _str(d, "last4"), _str(d, "owner_name"))


@dataclass(frozen=True)
class OrderMatch:
    score: int
    channel: str
    deposit_id: str
    reasons: list[str]

    @classmethod
    def from_dict(cls, d: Json) -> OrderMatch:
        return cls(_int(d, "score"), _str(d, "channel"), _str(d, "deposit_id"), _str_list(d, "reasons"))


@dataclass(frozen=True)
class Order:
    """``Order`` (docs/05 §3). ``amount`` is what the merchant asked for; ``unique_amount`` is what
    the customer must transfer (both int rial)."""

    id: str
    code: str
    status: str
    amount: int
    unique_amount: int
    unique_mode: str
    currency: str
    payment_url: str
    destination: OrderDestination
    expires_at: datetime
    grace_until: datetime
    paid_at: datetime | None
    paid_amount: int | None
    paid_late: bool
    payer_card_last4: str | None
    match: OrderMatch | None
    merchant_order_id: str | None
    customer: Customer | None
    metadata: dict[str, str]
    livemode: bool
    created_at: datetime
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @classmethod
    def from_dict(cls, d: Json) -> Order:
        payer = _opt_obj(d, "payer")
        match = _opt_obj(d, "match")
        customer = _opt_obj(d, "customer")
        metadata = d.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            raise ShapeError("'metadata' must be an object")
        return cls(
            id=_str(d, "id"),
            code=_str(d, "code"),
            status=_str(d, "status"),
            amount=_int(d, "amount"),
            unique_amount=_int(d, "unique_amount"),
            unique_mode=_str(d, "unique_mode"),
            currency=_str(d, "currency"),
            payment_url=_str(d, "payment_url"),
            destination=OrderDestination.from_dict(_obj(d, "destination")),
            expires_at=_dt(d, "expires_at"),
            grace_until=_dt(d, "grace_until"),
            paid_at=_opt_dt(d, "paid_at"),
            paid_amount=_opt_int(d, "paid_amount"),
            paid_late=_bool(d, "paid_late", default=False),
            payer_card_last4=_opt_str(payer, "card_last4") if payer else None,
            match=OrderMatch.from_dict(match) if match else None,
            merchant_order_id=_opt_str(d, "merchant_order_id"),
            customer=Customer.from_dict(customer) if customer else None,
            metadata={str(k): str(v) for k, v in metadata.items()},
            livemode=_bool(d, "livemode"),
            created_at=_dt(d, "created_at"),
            raw=dict(d),
        )


@dataclass(frozen=True)
class Deposit:
    """A bank credit (or a sandbox one from :meth:`Varizet.test.simulate_deposit`)."""

    id: str
    amount: int
    direction: str
    bank: str
    account_hint: str
    payer_last4: str | None
    tracking_ref: str | None
    occurred_at: datetime
    channel: str
    parse_confidence: float
    match_status: str
    order_id: str | None
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Json) -> Deposit:
        return cls(
            id=_str(d, "id"),
            amount=_int(d, "amount"),
            direction=_str(d, "direction"),
            bank=_str(d, "bank"),
            account_hint=_str(d, "account_hint"),
            payer_last4=_opt_str(d, "payer_last4"),
            tracking_ref=_opt_str(d, "tracking_ref"),
            occurred_at=_dt(d, "occurred_at"),
            channel=_str(d, "channel"),
            parse_confidence=_float(d, "parse_confidence"),
            match_status=_str(d, "match_status"),
            order_id=_opt_str(d, "order_id"),
            raw=dict(d),
        )


@dataclass(frozen=True)
class Refund:
    """A recorded refund (docs/05 §5, also the ``refund.created`` webhook's ``data.object``); the
    money itself is moved by the merchant."""

    id: str
    order_id: str
    amount: int
    method: str
    reference: str | None
    reason: str | None
    created_at: datetime
    currency: str = "IRR"
    livemode: bool = False
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Json) -> Refund:
        return cls(
            id=_str(d, "id"),
            order_id=_str(d, "order_id"),
            amount=_int(d, "amount"),
            method=_str(d, "method"),
            reference=_opt_str(d, "reference"),
            reason=_opt_str(d, "reason"),
            created_at=_dt(d, "created_at"),
            currency=_opt_str(d, "currency") or "IRR",
            livemode=_bool(d, "livemode", False),
            raw=dict(d),
        )


@dataclass(frozen=True)
class WebhookEndpoint:
    id: str
    url: str
    description: str | None
    events: list[str]
    status: str
    api_version: str
    livemode: bool
    #: Set while the previous secret still signs deliveries after a rotation.
    old_secret_expires_at: datetime | None
    created_at: datetime
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Json) -> WebhookEndpoint:
        rotation = _opt_obj(d, "secret_rotation")
        return cls(
            id=_str(d, "id"),
            url=_str(d, "url"),
            description=_opt_str(d, "description"),
            events=_str_list(d, "events"),
            status=_str(d, "status"),
            api_version=_str(d, "api_version"),
            livemode=_bool(d, "livemode"),
            old_secret_expires_at=_dt(rotation, "old_expires_at") if rotation else None,
            created_at=_dt(d, "created_at"),
            raw=dict(d),
        )


@dataclass(frozen=True)
class CreatedWebhookEndpoint:
    """The create answer: the only time the ``whsec_…`` signing secret is shown."""

    endpoint: WebhookEndpoint
    secret: str

    @classmethod
    def from_dict(cls, d: Json) -> CreatedWebhookEndpoint:
        return cls(endpoint=WebhookEndpoint.from_dict(d), secret=_str(d, "secret"))


@dataclass(frozen=True)
class RotatedSecret:
    id: str
    secret: str
    old_expires_at: datetime

    @classmethod
    def from_dict(cls, d: Json) -> RotatedSecret:
        return cls(_str(d, "id"), _str(d, "secret"), _dt(d, "old_expires_at"))


@dataclass(frozen=True)
class Deleted:
    id: str
    deleted: bool

    @classmethod
    def from_dict(cls, d: Json) -> Deleted:
        return cls(_str(d, "id"), _bool(d, "deleted"))


@dataclass(frozen=True)
class WebhookPingResult:
    """``POST /v1/webhook_endpoints/{id}/ping``: what the endpoint answered to a signed ping."""

    id: str
    event_id: str
    ok: bool
    status_code: int | None
    latency_ms: int
    error: str | None

    @classmethod
    def from_dict(cls, d: Json) -> WebhookPingResult:
        return cls(
            id=_str(d, "id"),
            event_id=_str(d, "event_id"),
            ok=_bool(d, "ok"),
            status_code=_opt_int(d, "status_code"),
            latency_ms=_int(d, "latency_ms"),
            error=_opt_str(d, "error"),
        )


@dataclass(frozen=True)
class WebhookEvent:
    """A webhook body (docs/05 §6). ``data["object"]`` is the subject as ``GET`` would return it."""

    id: str
    type: str
    created_at: datetime
    livemode: bool
    data: Json
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @property
    def object(self) -> Json:
        obj = self.data.get("object")
        return obj if isinstance(obj, Mapping) else {}

    def order(self) -> Order:
        """``data.object`` as an :class:`Order` (for ``order.*`` events)."""
        return Order.from_dict(self.object)

    @classmethod
    def from_dict(cls, d: Json) -> WebhookEvent:
        return cls(
            id=_str(d, "id"),
            type=_str(d, "type"),
            created_at=_dt(d, "created_at"),
            livemode=_bool(d, "livemode"),
            data=_obj(d, "data"),
            raw=dict(d),
        )


@dataclass(frozen=True)
class EventResent:
    id: str
    endpoints_queued: int

    @classmethod
    def from_dict(cls, d: Json) -> EventResent:
        return cls(_str(d, "id"), _int(d, "endpoints_queued"))


@dataclass(frozen=True)
class StoreRef:
    id: str
    name: str
    slug: str


@dataclass(frozen=True)
class ApiKeyIdentity:
    """``GET /v1/me``: the key's store, mode and scopes (never the secret)."""

    store: StoreRef
    livemode: bool
    scopes: list[str]
    key_prefix: str
    key_last4: str
    raw: Json = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, d: Json) -> ApiKeyIdentity:
        store = _obj(d, "store")
        key = _obj(d, "key")
        return cls(
            store=StoreRef(_str(store, "id"), _str(store, "name"), _str(store, "slug")),
            livemode=_bool(d, "livemode"),
            scopes=_str_list(d, "scopes"),
            key_prefix=_str(key, "prefix"),
            key_last4=_str(key, "last4"),
            raw=dict(d),
        )


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a cursor list (``{data, has_more, next_cursor}``)."""

    data: list[T]
    has_more: bool
    next_cursor: str | None

    def __iter__(self) -> Iterator[T]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def parse(cls, d: Json, item: Callable[[Json], T]) -> Page[T]:
        rows = _get(d, "data")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise ShapeError("'data' must be a list")
        items = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ShapeError("list items must be objects")
            items.append(item(row))
        return cls(
            data=items, has_more=_bool(d, "has_more", default=False), next_cursor=_opt_str(d, "next_cursor")
        )
