from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from varizet import WebhookSignatureError, construct_event, format_rial, to_persian_digits, verify_signature
from varizet.webhooks import build_signature_header, compute_signature, parse_signature_header

from .conftest import load_vector


@pytest.fixture
def vector() -> dict:  # type: ignore[type-arg]
    return load_vector("webhook-signature.vector.json")


def test_reproduces_the_shared_webhook_vector_byte_for_byte(vector: dict) -> None:  # type: ignore[type-arg]
    t, body, secrets = vector["timestamp"], vector["body"], vector["secrets"]
    assert build_signature_header(secrets, t, body) == vector["header"]
    assert build_signature_header(secrets[0], t, body) == vector["single_secret_header"]
    assert build_signature_header(secrets[0], t, body.encode()) == vector["single_secret_header"]


def test_reproduces_the_device_vector_too() -> None:
    device = load_vector("device-signature.vector.json")
    t = int(device["timestamp"])
    assert f"t={t},v1={compute_signature(device['secret'], t, device['body'])}" == device["header"]
    verify_signature(device["body"], device["header"], device["secret"], now=t)


def test_accepts_either_rotation_secret_within_the_window(vector: dict) -> None:  # type: ignore[type-arg]
    t, tol = vector["timestamp"], vector["tolerance_sec"]
    for secret in vector["secrets"]:
        verify_signature(vector["body"], vector["header"], [secret], now=t + tol)
        verify_signature(vector["body"].encode(), vector["header"], secret, now=t - tol)
    verify_signature(
        vector["body"], vector["header"], vector["secrets"], now=datetime.fromtimestamp(t, timezone.utc)
    )
    for offset in (tol + 1, -(tol + 1)):
        with pytest.raises(WebhookSignatureError) as caught:
            verify_signature(vector["body"], vector["header"], vector["secrets"], now=t + offset)
        assert caught.value.reason == "expired"
    verify_signature(vector["body"], vector["header"], vector["secrets"], now=t + 1000, tolerance=1000)


def test_rejects_tampered_bodies_wrong_secrets_and_reserialised_json(vector: dict) -> None:  # type: ignore[type-arg]
    t = vector["timestamp"]
    bad = [
        (vector["body"].replace("8500430", "9500430"), vector["secrets"]),
        (vector["body"], ["whsec_other"]),
        (json.dumps(json.loads(vector["body"]), ensure_ascii=False, indent=1), vector["secrets"]),
        (json.dumps(json.loads(vector["body"])), vector["secrets"]),  # \\u escapes change the bytes
    ]
    for body, secrets in bad:
        with pytest.raises(WebhookSignatureError) as caught:
            verify_signature(body, vector["header"], secrets, now=t)
        assert caught.value.reason == "mismatch"
    # a header signed only with the current secret does not verify with the previous one
    with pytest.raises(WebhookSignatureError):
        verify_signature(vector["body"], vector["single_secret_header"], vector["secrets"][1], now=t)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "t=1",
        "v1=" + "a" * 64,
        "t=1,t=2,v1=" + "a" * 64,
        "t=x,v1=" + "a" * 64,
        "t=1,v1=" + "A" * 64,
        "t=1,v1=abc",
        "t=1,,v1=" + "a" * 64,
        "t=١٢٣,v1=" + "a" * 64,  # Arabic-Indic digits are not unix seconds
        "t=1234567890123,v1=" + "a" * 64,
        "x" * 1025,
    ],
)
def test_malformed_headers(header: str | None) -> None:
    assert parse_signature_header(header) is None
    with pytest.raises(WebhookSignatureError) as caught:
        verify_signature("{}", header, "whsec_x", now=1)
    assert caught.value.reason == "malformed"


def test_unknown_schemes_are_ignored_and_whitespace_is_trimmed() -> None:
    sig = compute_signature("whsec_x", 100, "{}")
    assert parse_signature_header(f"t=100, v0=zz , v1={sig}") == (100, [sig])
    verify_signature("{}", f"t=100,v0=zz,v1={sig}", "whsec_x", now=100)


def test_construct_event_returns_a_typed_event(vector: dict) -> None:  # type: ignore[type-arg]
    event = construct_event(vector["body"], vector["header"], vector["secrets"], now=vector["timestamp"])
    assert event.type == "order.paid" and event.livemode is False
    assert event.object["unique_amount"] == 8_500_430
    assert event.object["customer"]["name"] == "سارا محمدی"
    body = '["not an event"]'
    header = build_signature_header("whsec_x", 5, body)
    with pytest.raises(WebhookSignatureError) as caught:
        construct_event(body, header, "whsec_x", now=5)
    assert caught.value.reason == "invalid_payload"
    with pytest.raises(ValueError, match="at least one"):
        verify_signature("{}", header, [], now=5)


def test_format_rial() -> None:
    assert format_rial(8_500_430) == "۸٬۵۰۰٬۴۳۰"
    assert format_rial(8_500_430, persian_digits=False) == "8,500,430"
    assert format_rial(8_500_430, unit=True) == "۸٬۵۰۰٬۴۳۰ ریال"
    assert format_rial(999, persian_digits=False, unit=True) == "999 IRR"
    assert format_rial(-1000, persian_digits=False) == "-1,000"
    assert to_persian_digits("VZ-8K2Q") == "VZ-۸K۲Q"
    with pytest.raises(TypeError):
        format_rial(8.5)  # type: ignore[arg-type]
