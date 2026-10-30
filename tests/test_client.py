from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

import varizet
from varizet import (
    APIConnectionError,
    APIServerError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    Order,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
    Varizet,
)

from .conftest import (
    BASE,
    LIVE_KEY,
    TEST_KEY,
    Recorder,
    deposit_json,
    endpoint_json,
    error_json,
    order_json,
)


def client(rec: Recorder, **kwargs: object) -> Varizet:
    c = Varizet(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(rec), **kwargs)  # type: ignore[arg-type]
    c._sleep = lambda _s: None
    return c


def test_rejects_bad_keys_and_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="vz_live_"):
        Varizet("sk_test_123")
    monkeypatch.delenv("VARIZET_API_KEY", raising=False)
    with pytest.raises(ValueError):
        Varizet()
    monkeypatch.setenv("VARIZET_API_KEY", LIVE_KEY)
    c = Varizet()
    assert c.livemode
    assert "live" in repr(c)
    assert LIVE_KEY not in repr(c)


def test_create_order_sends_headers_body_and_idempotency_key() -> None:
    rec = Recorder()
    rec.on("POST", "/v1/orders", httpx.Response(201, json=order_json()))
    with client(rec, app_info="shop/1.0") as c:
        order = c.orders.create(
            amount=8_500_000,
            merchant_order_id="INV-12345",
            customer={"name": "سارا محمدی", "phone": "09121234567", "email": None},
            metadata={"cart_id": "c_998"},
            expires_in=1800,
        )
    req = rec.requests[0]
    assert req.url == f"{BASE}/v1/orders"
    assert req.headers["authorization"] == f"Bearer {TEST_KEY}"
    assert req.headers["varizet-version"] == "2026-10-01"
    assert req.headers["user-agent"] == f"varizet-python/{varizet.__version__} shop/1.0"
    assert req.headers["content-type"] == "application/json"
    assert len(req.headers["idempotency-key"]) == 36
    assert rec.body() == {
        "amount": 8_500_000,
        "merchant_order_id": "INV-12345",
        "customer": {"name": "سارا محمدی", "phone": "09121234567"},
        "expires_in": 1800,
        "metadata": {"cart_id": "c_998"},
    }
    # non-ASCII is sent as UTF-8, not \\u escapes
    assert "سارا".encode() in req.content
    assert isinstance(order, Order)
    assert order.unique_amount == 8_500_430
    assert order.destination.bank == "mellat"
    assert order.created_at == datetime(2026, 10, 28, 10, 32, tzinfo=timezone.utc)
    assert order.customer is not None and order.customer.phone == "09121234567"


def test_explicit_idempotency_key_and_money_must_be_int() -> None:
    rec = Recorder()
    rec.on("POST", "/v1/orders", httpx.Response(201, json=order_json()))
    c = client(rec)
    c.orders.create(amount=10_000, idempotency_key="order-INV-1")
    assert rec.requests[0].headers["idempotency-key"] == "order-INV-1"
    with pytest.raises(TypeError, match="int number of rial"):
        c.orders.create(amount=8_500_000.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        c.orders.create(amount=True)
    with pytest.raises(ValueError):
        c.orders.create(amount=-1)
    assert len(rec.requests) == 1


def test_get_list_and_cancel() -> None:
    rec = Recorder()
    rec.on(
        "GET",
        "/v1/orders/VZ-P2K9TH",
        httpx.Response(
            200,
            json=order_json(
                status="paid",
                paid_amount=8_500_430,
                paid_at="2026-10-28T10:34:11Z",
                match={
                    "score": 98,
                    "channel": "android_sms",
                    "deposit_id": "dep_1",
                    "reasons": ["exact_amount"],
                },
                payer={"card_last4": "1234"},
            ),
        ),
    )
    rec.on(
        "GET",
        "/v1/orders",
        httpx.Response(200, json={"data": [order_json()], "has_more": False, "next_cursor": None}),
    )
    rec.on("POST", "/v1/orders/ord_1%2Fx/cancel", httpx.Response(200, json=order_json(status="canceled")))
    c = client(rec)
    paid = c.orders.get("VZ-P2K9TH")
    assert paid.is_paid and paid.paid_amount == 8_500_430
    assert paid.match is not None and paid.match.score == 98
    assert paid.payer_card_last4 == "1234"
    page = c.orders.list(
        status="paid",
        created_gte=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_lte="2026-10-31T00:00:00Z",
        limit=10,
    )
    assert len(page) == 1 and page.has_more is False
    params = dict(rec.requests[1].url.params)
    assert params == {
        "status": "paid",
        "created[gte]": "2026-10-01T00:00:00Z",
        "created[lte]": "2026-10-31T00:00:00Z",
        "limit": "10",
    }
    canceled = c.orders.cancel("ord_1/x")
    assert canceled.status == "canceled"
    assert rec.requests[2].headers["idempotency-key"]
    with pytest.raises(ValueError):
        c.orders.list(limit=500)


def test_auto_pagination_follows_next_cursor() -> None:
    rec = Recorder()

    def page(n: int, more: bool) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [order_json(id=f"ord_{n}a"), order_json(id=f"ord_{n}b")],
                "has_more": more,
                "next_cursor": f"ord_{n}b" if more else None,
            },
        )

    rec.on("GET", "/v1/orders", page(1, True), page(2, True), page(3, False))
    ids = [o.id for o in client(rec).orders.list_auto_paging(status="paid", page_size=2)]
    assert ids == ["ord_1a", "ord_1b", "ord_2a", "ord_2b", "ord_3a", "ord_3b"]
    assert [r.url.params.get("starting_after") for r in rec.requests] == [None, "ord_1b", "ord_2b"]
    assert all(r.url.params["limit"] == "2" and r.url.params["status"] == "paid" for r in rec.requests)


@pytest.mark.parametrize(
    ("status", "type_", "code", "cls"),
    [
        (400, "invalid_request", "amount_too_small", InvalidRequestError),
        (401, "authentication_error", "invalid_api_key", AuthenticationError),
        (403, "permission_error", "testmode_required", PermissionDeniedError),
        (404, "not_found", "order_not_found", NotFoundError),
        (409, "conflict", "idempotency_mismatch", ConflictError),
        (422, "validation_error", "merchant_order_id_duplicate", ValidationError),
        (429, "rate_limited", "too_many_requests", RateLimitError),
        (500, "api_error", "internal_error", APIServerError),
    ],
)
def test_error_shape_maps_to_typed_errors(
    status: int, type_: str, code: str, cls: type[varizet.APIError]
) -> None:
    rec = Recorder()
    headers = {"retry-after": "7"} if status == 429 else {}
    rec.on(
        "GET",
        "/v1/orders/x",
        httpx.Response(status, json=error_json(type_, code, "پیام فارسی", "amount"), headers=headers),
    )
    with pytest.raises(cls) as caught:
        client(rec, max_retries=0).orders.get("x")
    err = caught.value
    assert (err.status, err.type, err.code, err.message, err.param, err.request_id) == (
        status,
        type_,
        code,
        "پیام فارسی",
        "amount",
        "req_TEST",
    )
    assert code in str(err) and "req_TEST" in str(err)
    if isinstance(err, RateLimitError):
        assert err.retry_after == 7.0


def test_error_without_a_body_and_unexpected_shapes() -> None:
    rec = Recorder()
    rec.on("GET", "/v1/orders/a", httpx.Response(502, text="Bad Gateway", headers={"x-request-id": "req_gw"}))
    rec.on("GET", "/v1/orders/b", httpx.Response(200, json={"id": "ord_1"}))
    rec.on("GET", "/v1/orders/c", httpx.Response(200, text="<html>"))
    c = client(rec, max_retries=0)
    with pytest.raises(APIServerError) as caught:
        c.orders.get("a")
    assert caught.value.code == "http_502" and caught.value.request_id == "req_gw"
    with pytest.raises(APIConnectionError, match="unexpected response shape"):
        c.orders.get("b")
    with pytest.raises(APIConnectionError, match="non-JSON"):
        c.orders.get("c")


def test_retries_5xx_with_the_same_idempotency_key_then_succeeds() -> None:
    rec = Recorder()
    rec.on(
        "POST",
        "/v1/orders",
        httpx.Response(503, json=error_json("api_error", "internal_error", "x")),
        httpx.Response(502, text=""),
        httpx.Response(201, json=order_json()),
    )
    order = client(rec, max_retries=2).orders.create(amount=8_500_000)
    assert order.code == "VZ-P2K9TH"
    keys = {r.headers["idempotency-key"] for r in rec.requests}
    assert len(rec.requests) == 3 and len(keys) == 1


def test_does_not_retry_4xx_and_gives_up_after_max_retries() -> None:
    rec = Recorder()
    rec.on(
        "GET", "/v1/orders/x", httpx.Response(409, json=error_json("conflict", "order_not_cancelable", "x"))
    )
    rec.on("GET", "/v1/orders/y", httpx.Response(503, text=""))
    c = client(rec, max_retries=2)
    with pytest.raises(ConflictError):
        c.orders.get("x")
    assert len(rec.requests) == 1
    with pytest.raises(APIServerError):
        c.orders.get("y")
    assert len(rec.requests) == 4


def test_network_errors_and_timeouts() -> None:
    calls = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=order_json())

    c = Varizet(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(flaky), max_retries=1)
    c._sleep = lambda _s: None
    assert c.orders.get("VZ-P2K9TH").id.startswith("ord_")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    c2 = Varizet(TEST_KEY, base_url=BASE, transport=httpx.MockTransport(slow), max_retries=0)
    with pytest.raises(APITimeoutError):
        c2.orders.get("x")


def test_refunds_webhook_endpoints_events_simulator_and_me() -> None:
    rec = Recorder()
    rec.on(
        "POST",
        "/v1/refunds",
        httpx.Response(
            201,
            json={
                "id": "ref_1",
                "order_id": "ord_1",
                "amount": 500_000,
                "method": "card",
                "reference": "TRK-9",
                "reason": None,
                "created_at": "2026-10-28T12:00:00Z",
            },
        ),
    )
    rec.on(
        "POST",
        "/v1/webhook_endpoints",
        httpx.Response(201, json={**endpoint_json(), "secret": "whsec_" + "x" * 32}),
    )
    rec.on(
        "GET",
        "/v1/webhook_endpoints",
        httpx.Response(200, json={"data": [endpoint_json()], "has_more": False, "next_cursor": None}),
    )
    eid = "whe_01M624HA8BEEAB3PP3H5M2434M"
    rec.on("GET", f"/v1/webhook_endpoints/{eid}", httpx.Response(200, json=endpoint_json()))
    rec.on(
        "PATCH",
        f"/v1/webhook_endpoints/{eid}",
        httpx.Response(
            200,
            json=endpoint_json(status="disabled", secret_rotation={"old_expires_at": "2026-10-29T10:00:00Z"}),
        ),
    )
    rec.on("DELETE", f"/v1/webhook_endpoints/{eid}", httpx.Response(200, json={"id": eid, "deleted": True}))
    rec.on(
        "POST",
        f"/v1/webhook_endpoints/{eid}/rotate_secret",
        httpx.Response(
            200, json={"id": eid, "secret": "whsec_new", "old_expires_at": "2026-10-29T10:00:00Z"}
        ),
    )
    rec.on(
        "POST",
        f"/v1/webhook_endpoints/{eid}/ping",
        httpx.Response(
            200,
            json={
                "id": eid,
                "event_id": "evt_1",
                "ok": False,
                "status_code": None,
                "latency_ms": 10_000,
                "error": "timeout after 10000 ms",
            },
        ),
    )
    event = {
        "id": "evt_1",
        "type": "order.paid",
        "created_at": "2026-10-28T10:34:12Z",
        "livemode": False,
        "data": {"object": order_json(status="paid")},
    }
    rec.on(
        "GET",
        "/v1/events",
        httpx.Response(200, json={"data": [event], "has_more": False, "next_cursor": None}),
    )
    rec.on(
        "POST", "/v1/events/evt_1/resend", httpx.Response(202, json={"id": "evt_1", "endpoints_queued": 2})
    )
    rec.on("POST", "/v1/test/deposits", httpx.Response(201, json=deposit_json()))
    rec.on(
        "GET",
        "/v1/me",
        httpx.Response(
            200,
            json={
                "store": {"id": "sto_1", "name": "کتاب‌نما", "slug": "ketabnama"},
                "livemode": False,
                "scopes": ["orders:read"],
                "key": {"prefix": "vz_test_AAAAAAAA", "last4": "t3st"},
            },
        ),
    )
    c = client(rec)

    refund = c.refunds.create(order_id="ord_1", amount=500_000, reference="TRK-9")
    assert refund.amount == 500_000 and rec.body() == {
        "order_id": "ord_1",
        "amount": 500_000,
        "method": "card",
        "reference": "TRK-9",
    }
    assert refund.currency == "IRR" and refund.livemode is False

    created = c.webhook_endpoints.create(url="https://ketabnama.ir/webhooks/varizet", events=["order.paid"])
    assert created.secret.startswith("whsec_") and created.endpoint.id == eid
    assert [e.id for e in c.webhook_endpoints.list_auto_paging()] == [eid]
    assert c.webhook_endpoints.get(eid).events == ["order.paid"]
    updated = c.webhook_endpoints.update(eid, status="disabled", description=None)
    assert rec.body() == {"status": "disabled", "description": None}
    assert updated.old_secret_expires_at == datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="nothing to update"):
        c.webhook_endpoints.update(eid)
    assert c.webhook_endpoints.delete(eid).deleted is True
    assert c.webhook_endpoints.rotate_secret(eid).secret == "whsec_new"
    ping = c.webhook_endpoints.ping(eid)
    assert ping.ok is False and ping.status_code is None and ping.error
    events = c.events.list(type="order.paid")
    assert events.data[0].order().status == "paid"
    assert events.data[0].object["id"] == "ord_01M625GX23ECNVXYSAC9QVFVJF"
    assert c.events.resend("evt_1").endpoints_queued == 2
    deposit = c.test.simulate_deposit(amount=8_500_430, card_id="card_1")
    assert deposit.match_status == "matched" and deposit.order_id
    assert rec.body() == {"amount": 8_500_430, "card_id": "card_1"}
    me = c.me()
    assert me.store.slug == "ketabnama" and me.key_last4 == "t3st" and not me.livemode


def test_models_ignore_unknown_fields_and_keep_raw() -> None:
    data = order_json(new_field_from_2027={"x": 1}, status="some_future_status")
    order = Order.from_dict(data)
    assert order.status == "some_future_status"
    assert order.raw["new_field_from_2027"] == {"x": 1}
    assert "raw" not in repr(order)


def test_refunds_read_back_the_api_shape() -> None:
    rec = Recorder()
    api = {
        "id": "ref_01K8F3M2Q0V7E6W5X4Y3Z2A1B0",
        "order_id": "ord_01JBX4Q8M6",
        "amount": 5_000,
        "currency": "IRR",
        "method": "iban",
        "reference": None,
        "reason": None,
        "livemode": True,
        "created_at": "2026-10-28T12:00:00.000Z",
    }
    rec.on("GET", f"/v1/refunds/{api['id']}", httpx.Response(200, json=api))
    page = {"data": [api], "has_more": False, "next_cursor": None}
    rec.on("GET", "/v1/refunds", httpx.Response(200, json=page))
    c = client(rec)
    got = c.refunds.get(str(api["id"]))
    assert got.livemode is True and got.method == "iban" and got.reference is None
    assert [r.id for r in c.refunds.list_auto_paging(order="VZ-8K2Q")] == [api["id"]]
