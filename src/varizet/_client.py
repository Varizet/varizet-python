"""``Varizet`` (sync) and ``AsyncVarizet`` clients for the public ``/v1`` API."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import datetime
from types import TracebackType
from typing import Any, Literal, TypeVar

import anyio
import httpx

from . import _specs as specs
from ._base import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT, BaseClient
from ._errors import APIConnectionError, APITimeoutError
from ._models import (
    ApiKeyIdentity,
    CreatedWebhookEndpoint,
    Customer,
    Deleted,
    Deposit,
    EventResent,
    Order,
    Page,
    Refund,
    RotatedSecret,
    ShapeError,
    WebhookEndpoint,
    WebhookEvent,
    WebhookPingResult,
)
from ._specs import UNSET, Spec

T = TypeVar("T")
UniqueMode = Literal["increase", "decrease"]
RefundMethod = Literal["card", "iban"]
EndpointStatus = Literal["enabled", "disabled"]


def _parsed(spec: Spec[T], data: Any) -> T:
    try:
        return spec.parse(specs.as_json(data))
    except ShapeError as err:
        raise APIConnectionError(f"unexpected response shape for {spec.method} {spec.path}: {err}") from err


def _paginate(fetch: Callable[[str | None], Page[T]]) -> Iterator[T]:
    cursor: str | None = None
    while True:
        page = fetch(cursor)
        yield from page.data
        if not page.has_more or not page.next_cursor:
            return
        cursor = page.next_cursor


async def _apaginate(fetch: Callable[[str | None], Awaitable[Page[T]]]) -> AsyncIterator[T]:
    cursor: str | None = None
    while True:
        page = await fetch(cursor)
        for item in page.data:
            yield item
        if not page.has_more or not page.next_cursor:
            return
        cursor = page.next_cursor


# --- sync -----------------------------------------------------------------------------------------


class Varizet(BaseClient):
    """Synchronous client::

        client = Varizet("vz_test_…")
        order = client.orders.create(amount=8_500_000, merchant_order_id="INV-1")

    Every POST carries an ``Idempotency-Key`` (generated unless you pass ``idempotency_key=``), so
    network errors and 5xx answers are retried up to ``max_retries`` times with the same key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        app_info: str | None = None,
        http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key, base_url=base_url, timeout=timeout, max_retries=max_retries, app_info=app_info
        )
        self._http = http_client or httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)
        self._owns_http = http_client is None
        self._sleep: Callable[[float], None] = time.sleep
        self.orders = Orders(self)
        self.refunds = Refunds(self)
        self.webhook_endpoints = WebhookEndpoints(self)
        self.events = Events(self)
        self.test = TestHelpers(self)

    def me(self) -> ApiKeyIdentity:
        """``GET /v1/me``: the key's store, mode and scopes."""
        return self._call(specs.me())

    def _call(self, spec: Spec[T]) -> T:
        req = self._prepare(
            spec.method, spec.path, params=spec.params, body=spec.body, idempotency_key=spec.idempotency_key
        )
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    req.method,
                    self._url(req.path),
                    params=req.params,
                    content=req.body,
                    headers=dict(req.headers),
                    timeout=self.timeout,
                )
            except httpx.TransportError as exc:
                if attempt < self.max_retries:
                    self._sleep(self._retry_delay(attempt, None))
                    attempt += 1
                    continue
                error = APITimeoutError if isinstance(exc, httpx.TimeoutException) else APIConnectionError
                raise error(f"Varizet {req.method} {req.path} failed: {exc}", cause=exc) from exc
            if self._should_retry_status(attempt, response):
                self._sleep(self._retry_delay(attempt, response))
                attempt += 1
                continue
            return _parsed(spec, self._parse(response))

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Varizet:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


class Orders:
    def __init__(self, client: Varizet) -> None:
        self._c = client

    def create(
        self,
        *,
        amount: int,
        merchant_order_id: str | None = None,
        description: str | None = None,
        customer: Customer | Mapping[str, str | None] | None = None,
        expires_in: int | None = None,
        unique_mode: UniqueMode | None = None,
        card_id: str | None = None,
        return_url: str | None = None,
        metadata: Mapping[str, str] | None = None,
        payer_last4: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        """``POST /v1/orders``. ``amount`` is int rial; the customer pays ``order.unique_amount``."""
        return self._c._call(
            specs.create_order(
                amount=amount,
                merchant_order_id=merchant_order_id,
                description=description,
                customer=customer,
                expires_in=expires_in,
                unique_mode=unique_mode,
                card_id=card_id,
                return_url=return_url,
                metadata=metadata,
                payer_last4=payer_last4,
                idempotency_key=idempotency_key,
            )
        )

    def get(self, id_or_code: str) -> Order:
        """``GET /v1/orders/{id}`` with ``ord_…`` or ``VZ-…``."""
        return self._c._call(specs.get_order(id_or_code))

    def list(
        self,
        *,
        status: str | None = None,
        merchant_order_id: str | None = None,
        customer_phone: str | None = None,
        created_gte: datetime | str | None = None,
        created_lte: datetime | str | None = None,
        limit: int | None = None,
        starting_after: str | None = None,
    ) -> Page[Order]:
        """One page, newest first. See :meth:`list_auto_paging` to walk every page."""
        return self._c._call(
            specs.list_orders(
                status=status,
                merchant_order_id=merchant_order_id,
                customer_phone=customer_phone,
                created_gte=created_gte,
                created_lte=created_lte,
                limit=limit,
                starting_after=starting_after,
            )
        )

    def list_auto_paging(
        self,
        *,
        status: str | None = None,
        merchant_order_id: str | None = None,
        customer_phone: str | None = None,
        created_gte: datetime | str | None = None,
        created_lte: datetime | str | None = None,
        page_size: int = 100,
    ) -> Iterator[Order]:
        """Every matching order, following ``next_cursor`` lazily."""
        return _paginate(
            lambda cursor: self.list(
                status=status,
                merchant_order_id=merchant_order_id,
                customer_phone=customer_phone,
                created_gte=created_gte,
                created_lte=created_lte,
                limit=page_size,
                starting_after=cursor,
            )
        )

    def cancel(self, id_or_code: str, *, idempotency_key: str | None = None) -> Order:
        """``POST /v1/orders/{id}/cancel`` (unpaid orders only; else ``ConflictError``)."""
        return self._c._call(specs.cancel_order(id_or_code, idempotency_key))


class Refunds:
    def __init__(self, client: Varizet) -> None:
        self._c = client

    def create(
        self,
        *,
        order_id: str,
        amount: int,
        method: RefundMethod = "card",
        reference: str | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> Refund:
        """``POST /v1/refunds`` (docs/05 §5, ``refunds:write``): records a refund the merchant
        transferred, like the panel; Varizet sends ``refund.created``. ``order_id`` is ``ord_…`` or
        ``VZ-…``; an unpaid order is ``ConflictError``, too much ``ValidationError``."""
        return self._c._call(
            specs.create_refund(
                order_id=order_id,
                amount=amount,
                method=method,
                reference=reference,
                reason=reason,
                idempotency_key=idempotency_key,
            )
        )

    def get(self, refund_id: str) -> Refund:
        """``GET /v1/refunds/{id}`` (``orders:read`` or ``refunds:write``)."""
        return self._c._call(specs.get_refund(refund_id))

    def list(
        self, *, order: str | None = None, limit: int | None = None, starting_after: str | None = None
    ) -> Page[Refund]:
        """One page, newest first; ``order`` narrows to one order."""
        return self._c._call(specs.list_refunds(order=order, limit=limit, starting_after=starting_after))

    def list_auto_paging(self, *, order: str | None = None, page_size: int = 100) -> Iterator[Refund]:
        return _paginate(lambda cursor: self.list(order=order, limit=page_size, starting_after=cursor))


class WebhookEndpoints:
    def __init__(self, client: Varizet) -> None:
        self._c = client

    def create(
        self,
        *,
        url: str,
        events: Sequence[str],
        description: str | None = None,
        idempotency_key: str | None = None,
    ) -> CreatedWebhookEndpoint:
        """``POST /v1/webhook_endpoints``; ``.secret`` is shown only here."""
        return self._c._call(
            specs.create_endpoint(
                url=url, events=events, description=description, idempotency_key=idempotency_key
            )
        )

    def list(self, *, limit: int | None = None, starting_after: str | None = None) -> Page[WebhookEndpoint]:
        return self._c._call(specs.list_endpoints(limit=limit, starting_after=starting_after))

    def list_auto_paging(self, *, page_size: int = 100) -> Iterator[WebhookEndpoint]:
        return _paginate(lambda cursor: self.list(limit=page_size, starting_after=cursor))

    def get(self, endpoint_id: str) -> WebhookEndpoint:
        return self._c._call(specs.get_endpoint(endpoint_id))

    def update(
        self,
        endpoint_id: str,
        *,
        url: str | None = None,
        events: Sequence[str] | None = None,
        description: str | None = UNSET,
        status: EndpointStatus | None = None,
    ) -> WebhookEndpoint:
        """``PATCH``; pass ``description=None`` to clear it."""
        return self._c._call(
            specs.update_endpoint(endpoint_id, url=url, events=events, description=description, status=status)
        )

    def delete(self, endpoint_id: str) -> Deleted:
        return self._c._call(specs.delete_endpoint(endpoint_id))

    def rotate_secret(self, endpoint_id: str, *, idempotency_key: str | None = None) -> RotatedSecret:
        """New secret now; the old one keeps signing for 24 h (two ``v1=`` values)."""
        return self._c._call(specs.rotate_secret(endpoint_id, idempotency_key))

    def ping(self, endpoint_id: str) -> WebhookPingResult:
        """Sends one signed ``webhook.ping`` to the endpoint now and reports its answer."""
        return self._c._call(specs.ping_endpoint(endpoint_id))


class Events:
    def __init__(self, client: Varizet) -> None:
        self._c = client

    def list(
        self, *, type: str | None = None, limit: int | None = None, starting_after: str | None = None
    ) -> Page[WebhookEvent]:
        return self._c._call(specs.list_events(type=type, limit=limit, starting_after=starting_after))

    def list_auto_paging(self, *, type: str | None = None, page_size: int = 100) -> Iterator[WebhookEvent]:
        return _paginate(lambda cursor: self.list(type=type, limit=page_size, starting_after=cursor))

    def resend(self, event_id: str, *, idempotency_key: str | None = None) -> EventResent:
        return self._c._call(specs.resend_event(event_id, idempotency_key))


class TestHelpers:
    """Sandbox helpers; test keys (``vz_test_…``) only, else ``PermissionDeniedError``."""

    __test__ = False  # not a pytest class

    def __init__(self, client: Varizet) -> None:
        self._c = client

    def simulate_deposit(
        self,
        *,
        amount: int,
        card_id: str | None = None,
        payer_last4: str | None = None,
        bank: str | None = None,
        idempotency_key: str | None = None,
    ) -> Deposit:
        """``POST /v1/test/deposits``: a synthetic bank SMS through the real matcher. Pay an order
        by passing its ``unique_amount`` (and ``destination.card_id``)."""
        return self._c._call(
            specs.simulate_deposit(
                amount=amount,
                card_id=card_id,
                payer_last4=payer_last4,
                bank=bank,
                idempotency_key=idempotency_key,
            )
        )


# --- async ----------------------------------------------------------------------------------------


class AsyncVarizet(BaseClient):
    """Asynchronous client (``await client.orders.create(...)``); same surface as :class:`Varizet`."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        app_info: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key, base_url=base_url, timeout=timeout, max_retries=max_retries, app_info=app_info
        )
        self._http = http_client or httpx.AsyncClient(
            transport=transport, timeout=timeout, follow_redirects=False
        )
        self._owns_http = http_client is None
        self._sleep: Callable[[float], Awaitable[None]] = anyio.sleep
        self.orders = AsyncOrders(self)
        self.refunds = AsyncRefunds(self)
        self.webhook_endpoints = AsyncWebhookEndpoints(self)
        self.events = AsyncEvents(self)
        self.test = AsyncTestHelpers(self)

    async def me(self) -> ApiKeyIdentity:
        return await self._call(specs.me())

    async def _call(self, spec: Spec[T]) -> T:
        req = self._prepare(
            spec.method, spec.path, params=spec.params, body=spec.body, idempotency_key=spec.idempotency_key
        )
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    req.method,
                    self._url(req.path),
                    params=req.params,
                    content=req.body,
                    headers=dict(req.headers),
                    timeout=self.timeout,
                )
            except httpx.TransportError as exc:
                if attempt < self.max_retries:
                    await self._sleep(self._retry_delay(attempt, None))
                    attempt += 1
                    continue
                error = APITimeoutError if isinstance(exc, httpx.TimeoutException) else APIConnectionError
                raise error(f"Varizet {req.method} {req.path} failed: {exc}", cause=exc) from exc
            if self._should_retry_status(attempt, response):
                await self._sleep(self._retry_delay(attempt, response))
                attempt += 1
                continue
            return _parsed(spec, self._parse(response))

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncVarizet:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()


class AsyncOrders:
    def __init__(self, client: AsyncVarizet) -> None:
        self._c = client

    async def create(
        self,
        *,
        amount: int,
        merchant_order_id: str | None = None,
        description: str | None = None,
        customer: Customer | Mapping[str, str | None] | None = None,
        expires_in: int | None = None,
        unique_mode: UniqueMode | None = None,
        card_id: str | None = None,
        return_url: str | None = None,
        metadata: Mapping[str, str] | None = None,
        payer_last4: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        return await self._c._call(
            specs.create_order(
                amount=amount,
                merchant_order_id=merchant_order_id,
                description=description,
                customer=customer,
                expires_in=expires_in,
                unique_mode=unique_mode,
                card_id=card_id,
                return_url=return_url,
                metadata=metadata,
                payer_last4=payer_last4,
                idempotency_key=idempotency_key,
            )
        )

    async def get(self, id_or_code: str) -> Order:
        return await self._c._call(specs.get_order(id_or_code))

    async def list(
        self,
        *,
        status: str | None = None,
        merchant_order_id: str | None = None,
        customer_phone: str | None = None,
        created_gte: datetime | str | None = None,
        created_lte: datetime | str | None = None,
        limit: int | None = None,
        starting_after: str | None = None,
    ) -> Page[Order]:
        return await self._c._call(
            specs.list_orders(
                status=status,
                merchant_order_id=merchant_order_id,
                customer_phone=customer_phone,
                created_gte=created_gte,
                created_lte=created_lte,
                limit=limit,
                starting_after=starting_after,
            )
        )

    def list_auto_paging(
        self,
        *,
        status: str | None = None,
        merchant_order_id: str | None = None,
        customer_phone: str | None = None,
        created_gte: datetime | str | None = None,
        created_lte: datetime | str | None = None,
        page_size: int = 100,
    ) -> AsyncIterator[Order]:
        """``async for order in client.orders.list_auto_paging(...)``."""
        return _apaginate(
            lambda cursor: self.list(
                status=status,
                merchant_order_id=merchant_order_id,
                customer_phone=customer_phone,
                created_gte=created_gte,
                created_lte=created_lte,
                limit=page_size,
                starting_after=cursor,
            )
        )

    async def cancel(self, id_or_code: str, *, idempotency_key: str | None = None) -> Order:
        return await self._c._call(specs.cancel_order(id_or_code, idempotency_key))


class AsyncRefunds:
    def __init__(self, client: AsyncVarizet) -> None:
        self._c = client

    async def create(
        self,
        *,
        order_id: str,
        amount: int,
        method: RefundMethod = "card",
        reference: str | None = None,
        reason: str | None = None,
        idempotency_key: str | None = None,
    ) -> Refund:
        """See :meth:`Refunds.create`."""
        return await self._c._call(
            specs.create_refund(
                order_id=order_id,
                amount=amount,
                method=method,
                reference=reference,
                reason=reason,
                idempotency_key=idempotency_key,
            )
        )

    async def get(self, refund_id: str) -> Refund:
        return await self._c._call(specs.get_refund(refund_id))

    async def list(
        self, *, order: str | None = None, limit: int | None = None, starting_after: str | None = None
    ) -> Page[Refund]:
        spec = specs.list_refunds(order=order, limit=limit, starting_after=starting_after)
        return await self._c._call(spec)

    def list_auto_paging(self, *, order: str | None = None, page_size: int = 100) -> AsyncIterator[Refund]:
        return _apaginate(lambda cursor: self.list(order=order, limit=page_size, starting_after=cursor))


class AsyncWebhookEndpoints:
    def __init__(self, client: AsyncVarizet) -> None:
        self._c = client

    async def create(
        self,
        *,
        url: str,
        events: Sequence[str],
        description: str | None = None,
        idempotency_key: str | None = None,
    ) -> CreatedWebhookEndpoint:
        return await self._c._call(
            specs.create_endpoint(
                url=url, events=events, description=description, idempotency_key=idempotency_key
            )
        )

    async def list(
        self, *, limit: int | None = None, starting_after: str | None = None
    ) -> Page[WebhookEndpoint]:
        return await self._c._call(specs.list_endpoints(limit=limit, starting_after=starting_after))

    def list_auto_paging(self, *, page_size: int = 100) -> AsyncIterator[WebhookEndpoint]:
        return _apaginate(lambda cursor: self.list(limit=page_size, starting_after=cursor))

    async def get(self, endpoint_id: str) -> WebhookEndpoint:
        return await self._c._call(specs.get_endpoint(endpoint_id))

    async def update(
        self,
        endpoint_id: str,
        *,
        url: str | None = None,
        events: Sequence[str] | None = None,
        description: str | None = UNSET,
        status: EndpointStatus | None = None,
    ) -> WebhookEndpoint:
        return await self._c._call(
            specs.update_endpoint(endpoint_id, url=url, events=events, description=description, status=status)
        )

    async def delete(self, endpoint_id: str) -> Deleted:
        return await self._c._call(specs.delete_endpoint(endpoint_id))

    async def rotate_secret(self, endpoint_id: str, *, idempotency_key: str | None = None) -> RotatedSecret:
        return await self._c._call(specs.rotate_secret(endpoint_id, idempotency_key))

    async def ping(self, endpoint_id: str) -> WebhookPingResult:
        return await self._c._call(specs.ping_endpoint(endpoint_id))


class AsyncEvents:
    def __init__(self, client: AsyncVarizet) -> None:
        self._c = client

    async def list(
        self, *, type: str | None = None, limit: int | None = None, starting_after: str | None = None
    ) -> Page[WebhookEvent]:
        return await self._c._call(specs.list_events(type=type, limit=limit, starting_after=starting_after))

    def list_auto_paging(
        self, *, type: str | None = None, page_size: int = 100
    ) -> AsyncIterator[WebhookEvent]:
        return _apaginate(lambda cursor: self.list(type=type, limit=page_size, starting_after=cursor))

    async def resend(self, event_id: str, *, idempotency_key: str | None = None) -> EventResent:
        return await self._c._call(specs.resend_event(event_id, idempotency_key))


class AsyncTestHelpers:
    __test__ = False

    def __init__(self, client: AsyncVarizet) -> None:
        self._c = client

    async def simulate_deposit(
        self,
        *,
        amount: int,
        card_id: str | None = None,
        payer_last4: str | None = None,
        bank: str | None = None,
        idempotency_key: str | None = None,
    ) -> Deposit:
        return await self._c._call(
            specs.simulate_deposit(
                amount=amount,
                card_id=card_id,
                payer_last4=payer_last4,
                bank=bank,
                idempotency_key=idempotency_key,
            )
        )
