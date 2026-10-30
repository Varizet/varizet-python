from __future__ import annotations

import json
import time

import pytest

from varizet.webhooks import build_signature_header

SECRET = "whsec_" + "k" * 32
OLD_SECRET = "whsec_" + "o" * 32
BODY = json.dumps(
    {
        "id": "evt_01M625J4NJEW9AJ5AXJV9SN958",
        "type": "order.paid",
        "created_at": "2026-10-28T10:34:12.000Z",
        "livemode": False,
        "data": {"object": {"id": "ord_1", "status": "paid", "note": "سارا"}},
    },
    ensure_ascii=False,
    separators=(",", ":"),
).encode()


def signed(secret: str = SECRET, body: bytes = BODY, at: int | None = None) -> str:
    return build_signature_header(secret, at if at is not None else int(time.time()), body)


# --- Django ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def django_client():  # type: ignore[no-untyped-def]
    django = pytest.importorskip("django")
    from django.conf import settings

    if not settings.configured:
        settings.configure(
            DEBUG=False,
            SECRET_KEY="test",
            ROOT_URLCONF=__name__,
            ALLOWED_HOSTS=["testserver"],
            MIDDLEWARE=["django.middleware.csrf.CsrfViewMiddleware"],
            VARIZET_WEBHOOK_SECRETS=[SECRET, OLD_SECRET],
        )
        django.setup()
    from django.http import HttpResponse, JsonResponse
    from django.test import Client
    from django.urls import path

    from varizet.contrib.django import varizet_webhook

    @varizet_webhook
    def hook(request):  # type: ignore[no-untyped-def]
        event = request.varizet_event
        return JsonResponse({"type": event.type, "order": event.object["id"]})

    @varizet_webhook(secrets="whsec_only_this")
    def strict(request):  # type: ignore[no-untyped-def]
        return HttpResponse("ok")

    @varizet_webhook
    async def async_hook(request):  # type: ignore[no-untyped-def]
        return JsonResponse({"type": request.varizet_event.type})

    global urlpatterns
    urlpatterns = [path("hook", hook), path("strict", strict), path("async", async_hook)]
    return Client(enforce_csrf_checks=True)


urlpatterns: list[object] = []


def post(client, url: str, body: bytes, header: str | None):  # type: ignore[no-untyped-def]
    extra = {"HTTP_VARIZET_SIGNATURE": header} if header is not None else {}
    return client.post(url, data=body, content_type="application/json", **extra)


def test_django_decorator_verifies_and_exposes_the_event(django_client) -> None:  # type: ignore[no-untyped-def]
    res = post(django_client, "/hook", BODY, signed())
    assert res.status_code == 200, res.content
    assert res.json() == {"type": "order.paid", "order": "ord_1"}
    # the previous secret from settings still verifies (rotation)
    assert post(django_client, "/hook", BODY, signed(OLD_SECRET)).status_code == 200
    assert post(django_client, "/async", BODY, signed()).json() == {"type": "order.paid"}


def test_django_decorator_rejects_with_400_and_is_post_only(django_client) -> None:  # type: ignore[no-untyped-def]
    cases = [
        (BODY, None, "malformed"),
        (BODY, signed("whsec_wrong"), "mismatch"),
        (BODY, signed(at=int(time.time()) - 301), "expired"),
        (BODY.replace(b"paid", b"PAID"), signed(), "mismatch"),
    ]
    for body, header, reason in cases:
        res = post(django_client, "/hook", body, header)
        assert res.status_code == 400
        assert res.json() == {"error": reason}
    assert post(django_client, "/strict", BODY, signed()).status_code == 400
    assert post(django_client, "/strict", BODY, signed("whsec_only_this")).status_code == 200
    assert django_client.get("/hook").status_code == 405


# --- FastAPI --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fastapi_client():  # type: ignore[no-untyped-def]
    pytest.importorskip("fastapi")
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from varizet import WebhookEvent
    from varizet.contrib.fastapi import VarizetWebhook

    app = FastAPI()
    verified = VarizetWebhook([SECRET, OLD_SECRET])
    lazy = VarizetWebhook(lambda: [SECRET])

    @app.post("/hook")
    async def hook(event: WebhookEvent = Depends(verified)) -> dict[str, str]:  # noqa: B008
        return {"type": event.type, "id": event.id}

    @app.post("/lazy")
    async def lazy_hook(event: WebhookEvent = Depends(lazy)) -> dict[str, str]:  # noqa: B008
        return {"type": event.type}

    return TestClient(app)


def test_fastapi_dependency_verifies_the_raw_body(fastapi_client) -> None:  # type: ignore[no-untyped-def]
    ok = fastapi_client.post("/hook", content=BODY, headers={"Varizet-Signature": signed()})
    assert ok.status_code == 200
    assert ok.json() == {"type": "order.paid", "id": "evt_01M625J4NJEW9AJ5AXJV9SN958"}
    assert (
        fastapi_client.post(
            "/hook", content=BODY, headers={"Varizet-Signature": signed(OLD_SECRET)}
        ).status_code
        == 200
    )
    assert (
        fastapi_client.post("/lazy", content=BODY, headers={"Varizet-Signature": signed()}).status_code == 200
    )


def test_fastapi_dependency_rejects_with_400(fastapi_client) -> None:  # type: ignore[no-untyped-def]
    for headers, reason in [
        ({}, "malformed"),
        ({"Varizet-Signature": signed("whsec_wrong")}, "mismatch"),
        ({"Varizet-Signature": signed(at=int(time.time()) + 400)}, "expired"),
    ]:
        res = fastapi_client.post("/hook", content=BODY, headers=headers)
        assert res.status_code == 400
        assert res.json() == {"detail": {"error": reason}}
    garbage = b"not json"
    res = fastapi_client.post("/hook", content=garbage, headers={"Varizet-Signature": signed(body=garbage)})
    assert res.json() == {"detail": {"error": "invalid_payload"}}
