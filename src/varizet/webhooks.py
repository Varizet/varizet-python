"""Webhook signature verification (docs/05 §6).

``Varizet-Signature: t=<unix seconds>,v1=<hex hmac_sha256(secret, t + "." + raw_body)>``. During a
secret rotation the header carries one ``v1=`` per valid secret. The rules are identical to the
server's (``apps/api/src/common/crypto/signatures.ts``) and pinned by the shared vectors in
``packages/contracts/test/*.vector.json``.

Always verify the **raw** request body bytes, never a re-serialised JSON object.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from ._errors import VarizetError
from ._models import ShapeError, WebhookEvent

SIGNATURE_HEADER = "Varizet-Signature"
DEFAULT_TOLERANCE = 300
_MAX_HEADER_LENGTH = 1024
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNIX_SECONDS = re.compile(r"[0-9]{1,12}")

Reason = Literal["malformed", "expired", "mismatch", "invalid_payload"]
Payload = bytes | bytearray | memoryview | str
Secrets = str | bytes | Sequence[str | bytes]


class WebhookSignatureError(VarizetError):
    """The webhook was rejected; ``reason`` is ``malformed``, ``expired``, ``mismatch`` or
    ``invalid_payload``. Answer it with HTTP 400."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(f"Varizet webhook rejected: {reason}")
        self.reason: Reason = reason


def _bytes(value: Payload | bytes) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _secret_list(secrets: Secrets) -> list[bytes]:
    items: Sequence[str | bytes] = [secrets] if isinstance(secrets, (str, bytes)) else secrets
    out = [_bytes(s) for s in items]
    if not out:
        raise ValueError("at least one webhook secret is required")
    return out


def compute_signature(secret: str | bytes, timestamp: int, payload: Payload) -> str:
    """``hex(hmac_sha256(secret, f"{timestamp}." + payload))``."""
    mac = hmac.new(_bytes(secret), f"{timestamp}.".encode(), hashlib.sha256)
    mac.update(_bytes(payload))
    return mac.hexdigest()


def build_signature_header(secrets: Secrets, timestamp: int, payload: Payload) -> str:
    """``t=…,v1=…[,v1=…]``, one ``v1`` per secret (current first) — what Varizet sends."""
    parts = [f"t={timestamp}"] + [
        f"v1={compute_signature(s, timestamp, payload)}" for s in _secret_list(secrets)
    ]
    return ",".join(parts)


def parse_signature_header(header: str | None) -> tuple[int, list[str]] | None:
    """``(timestamp, [v1, …])``, or ``None`` when the header is malformed. Unknown schemes are
    ignored; a repeated or non-numeric ``t`` and a non-hex ``v1`` make it malformed."""
    if not header or len(header) > _MAX_HEADER_LENGTH:
        return None
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        eq = part.find("=")
        if eq <= 0:
            return None
        key = part[:eq].strip()
        value = part[eq + 1 :].strip()
        if key == "t":
            if timestamp is not None or not _UNIX_SECONDS.fullmatch(value):
                return None
            timestamp = int(value)
        elif key == "v1":
            if not _HEX_SHA256.fullmatch(value):
                return None
            signatures.append(value)
    if timestamp is None or not signatures:
        return None
    return timestamp, signatures


def _now_seconds(now: datetime | float | None) -> int:
    if now is None:
        return int(time.time())
    if isinstance(now, datetime):
        return int(now.timestamp())
    return int(now)


def verify_signature(
    payload: Payload,
    header: str | None,
    secrets: Secrets,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    now: datetime | float | None = None,
) -> None:
    """Raises :class:`WebhookSignatureError` unless ``header`` signs ``payload`` with one of
    ``secrets`` (pass the current and, during a rotation, the previous one) within ``tolerance``
    seconds of ``now`` (inclusive)."""
    keys = _secret_list(secrets)
    parsed = parse_signature_header(header)
    if parsed is None:
        raise WebhookSignatureError("malformed")
    timestamp, candidates = parsed
    if abs(_now_seconds(now) - timestamp) > tolerance:
        raise WebhookSignatureError("expired")
    body = _bytes(payload)
    for key in keys:
        expected = compute_signature(key, timestamp, body).encode()
        matched = False
        # compare against every candidate so timing does not reveal which one matched
        for candidate in candidates:
            matched = hmac.compare_digest(expected, candidate.encode()) or matched
        if matched:
            return
    raise WebhookSignatureError("mismatch")


def construct_event(
    payload: Payload,
    header: str | None,
    secrets: Secrets,
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    now: datetime | float | None = None,
) -> WebhookEvent:
    """Verifies the signature, then parses the body into a typed :class:`WebhookEvent`."""
    verify_signature(payload, header, secrets, tolerance=tolerance, now=now)
    try:
        data = json.loads(_bytes(payload).decode("utf-8"))
        if not isinstance(data, dict):
            raise WebhookSignatureError("invalid_payload")
        return WebhookEvent.from_dict(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ShapeError) as err:
        raise WebhookSignatureError("invalid_payload") from err


__all__ = [
    "DEFAULT_TOLERANCE",
    "SIGNATURE_HEADER",
    "WebhookSignatureError",
    "build_signature_header",
    "compute_signature",
    "construct_event",
    "parse_signature_header",
    "verify_signature",
]
