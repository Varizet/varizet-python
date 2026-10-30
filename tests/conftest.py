from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

TEST_KEY = "vz_test_" + "A" * 28 + "t3st"
LIVE_KEY = "vz_live_" + "B" * 28 + "l1ve"
BASE = "https://api.test"

#: Shared cross-language vectors, read in place (packages/contracts/test).
VECTORS = Path(__file__).resolve().parents[2] / "contracts" / "test"


def load_vector(name: str) -> dict[str, Any]:
    path = VECTORS / name
    if not path.exists():
        pytest.skip(f"shared vector {path} not available (sdist install)")
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def order_json(**patch: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "ord_01M625GX23ECNVXYSAC9QVFVJF",
        "code": "VZ-P2K9TH",
        "status": "awaiting_payment",
        "amount": 8_500_000,
        "unique_amount": 8_500_430,
        "unique_mode": "increase",
        "currency": "IRR",
        "payment_url": "https://pay.varizet.ir/p/kJ8s2QaX7mZr4TnB",
        "destination": {
            "card_id": "card_01M618SA0HET9AB5T5N6X7Q9S6",
            "bank": "mellat",
            "last4": "4520",
            "owner_name": "سارا محمدی",
        },
        "expires_at": "2026-10-28T11:02:00.000Z",
        "grace_until": "2026-10-28T12:02:00.000Z",
        "paid_at": None,
        "paid_amount": None,
        "paid_late": False,
        "payer": None,
        "match": None,
        "merchant_order_id": "INV-12345",
        "customer": {"name": "سارا محمدی", "phone": "09121234567", "email": None},
        "metadata": {"cart_id": "c_998"},
        "livemode": False,
        "created_at": "2026-10-28T10:32:00.000Z",
    }
    data.update(patch)
    return data


def deposit_json(**patch: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "dep_01M625H2HCEA3RQ8F5CK249H8K",
        "amount": 8_500_430,
        "direction": "credit",
        "bank": "mellat",
        "account_hint": "6104****4520",
        "payer_last4": None,
        "tracking_ref": None,
        "occurred_at": "2026-10-28T10:34:00.000Z",
        "channel": "android_sms",
        "parse_confidence": 1,
        "match_status": "matched",
        "order_id": "ord_01M625GX23ECNVXYSAC9QVFVJF",
    }
    data.update(patch)
    return data


def endpoint_json(**patch: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "whe_01M624HA8BEEAB3PP3H5M2434M",
        "url": "https://ketabnama.ir/webhooks/varizet",
        "description": None,
        "events": ["order.paid"],
        "status": "enabled",
        "api_version": "2026-10-01",
        "livemode": False,
        "secret_rotation": None,
        "created_at": "2026-10-28T10:00:00.000Z",
    }
    data.update(patch)
    return data


def error_json(type_: str, code: str, message: str, param: str | None = None) -> dict[str, Any]:
    return {
        "error": {"type": type_, "code": code, "message": message, "param": param, "request_id": "req_TEST"}
    }


Handler = Callable[[httpx.Request], httpx.Response]


class Recorder:
    """A MockTransport handler that records requests and replays queued responses per route."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[str, list[httpx.Response | Callable[[httpx.Request], httpx.Response]]] = {}

    def on(
        self, method: str, path: str, *responses: httpx.Response | Callable[[httpx.Request], httpx.Response]
    ) -> None:
        self.routes[f"{method} {path}"] = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # the raw (still percent-encoded) path, so encoded ids are checked as sent
        path = request.url.raw_path.decode().split("?")[0]
        queue = self.routes.get(f"{request.method} {path}")
        if not queue:
            return httpx.Response(404, json=error_json("not_found", "route_missing", request.url.path))
        step = queue.pop(0) if len(queue) > 1 else queue[0]
        return step(request) if callable(step) else step

    def body(self, i: int = -1) -> Any:
        return json.loads(self.requests[i].content)
