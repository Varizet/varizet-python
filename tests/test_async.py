from __future__ import annotations

import httpx
import pytest

from varizet import AsyncVarizet, ConflictError, NotFoundError

from .conftest import BASE, TEST_KEY, Recorder, deposit_json, error_json, order_json

pytestmark = pytest.mark.anyio


async def _no_sleep(_s: float) -> None:
    return None


def client(rec: Recorder, **kwargs: object) -> AsyncVarizet:
    c = AsyncVarizet(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(rec), **kwargs)  # type: ignore[arg-type]
    c._sleep = _no_sleep
    return c


async def test_async_create_pay_and_get() -> None:
    rec = Recorder()
    rec.on("POST", "/v1/orders", httpx.Response(201, json=order_json()))
    rec.on("POST", "/v1/test/deposits", httpx.Response(201, json=deposit_json()))
    rec.on(
        "GET",
        "/v1/orders/ord_01M625GX23ECNVXYSAC9QVFVJF",
        httpx.Response(200, json=order_json(status="paid")),
    )
    async with client(rec) as c:
        order = await c.orders.create(amount=8_500_000, merchant_order_id="INV-1")
        await c.test.simulate_deposit(amount=order.unique_amount, card_id=order.destination.card_id)
        assert (await c.orders.get(order.id)).is_paid
    assert rec.requests[0].headers["idempotency-key"] != rec.requests[1].headers["idempotency-key"]
    assert rec.body(1) == {"amount": 8_500_430, "card_id": "card_01M618SA0HET9AB5T5N6X7Q9S6"}


async def test_async_auto_pagination() -> None:
    rec = Recorder()
    rec.on(
        "GET",
        "/v1/orders",
        httpx.Response(
            200, json={"data": [order_json(id="ord_a")], "has_more": True, "next_cursor": "ord_a"}
        ),
        httpx.Response(200, json={"data": [order_json(id="ord_b")], "has_more": False, "next_cursor": None}),
    )
    c = client(rec)
    ids = [o.id async for o in c.orders.list_auto_paging()]
    assert ids == ["ord_a", "ord_b"]
    assert rec.requests[1].url.params["starting_after"] == "ord_a"


async def test_async_errors_and_retries() -> None:
    rec = Recorder()
    rec.on(
        "POST",
        "/v1/orders/x/cancel",
        httpx.Response(504, text=""),
        httpx.Response(409, json=error_json("conflict", "order_not_cancelable", "این سفارش قابل لغو نیست.")),
    )
    rec.on(
        "GET",
        "/v1/orders/missing",
        httpx.Response(404, json=error_json("not_found", "order_not_found", "سفارش پیدا نشد.")),
    )
    c = client(rec)
    with pytest.raises(ConflictError) as caught:
        await c.orders.cancel("x")
    assert caught.value.message == "این سفارش قابل لغو نیست."
    assert len({r.headers["idempotency-key"] for r in rec.requests}) == 1
    with pytest.raises(NotFoundError):
        await c.orders.get("missing")
    await c.close()


async def test_async_webhook_endpoints_and_events() -> None:
    rec = Recorder()
    eid = "whe_01M624HA8BEEAB3PP3H5M2434M"
    rec.on(
        "POST",
        f"/v1/webhook_endpoints/{eid}/ping",
        httpx.Response(
            200,
            json={
                "id": eid,
                "event_id": "evt_1",
                "ok": True,
                "status_code": 200,
                "latency_ms": 31,
                "error": None,
            },
        ),
    )
    event = {
        "id": "evt_1",
        "type": "order.created",
        "created_at": "2026-10-28T10:34:12Z",
        "livemode": False,
        "data": {"object": {}},
    }
    rec.on(
        "GET",
        "/v1/events",
        httpx.Response(200, json={"data": [event], "has_more": False, "next_cursor": None}),
    )
    c = client(rec)
    assert (await c.webhook_endpoints.ping(eid)).ok
    assert [e.type async for e in c.events.list_auto_paging(type="order.created")] == ["order.created"]
    assert rec.requests[1].url.params["type"] == "order.created"
