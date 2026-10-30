"""FastAPI: a dependency that verifies ``Varizet-Signature`` over the raw body.

.. code-block:: python

    from fastapi import Depends, FastAPI
    from varizet import WebhookEvent
    from varizet.contrib.fastapi import VarizetWebhook

    app = FastAPI()
    verified = VarizetWebhook(secrets=["whsec_…"])  # or a callable returning them

    @app.post("/webhooks/varizet")
    async def hook(event: WebhookEvent = Depends(verified)) -> dict[str, bool]:
        if event.type == "order.paid":
            ...
        return {"received": True}

A bad or stale signature raises ``HTTPException(400)`` before your handler runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

try:
    from fastapi import HTTPException, Request
except ImportError as err:  # pragma: no cover - exercised only without the extra
    raise ImportError("varizet.contrib.fastapi needs FastAPI: pip install 'varizet[fastapi]'") from err

from .._models import WebhookEvent
from ..webhooks import DEFAULT_TOLERANCE, SIGNATURE_HEADER, WebhookSignatureError, construct_event

SecretSource = str | Sequence[str] | Callable[[], Sequence[str]]


class VarizetWebhook:
    """``Depends(VarizetWebhook(secrets))`` → the verified :class:`~varizet.WebhookEvent`."""

    def __init__(self, secrets: SecretSource, *, tolerance: int = DEFAULT_TOLERANCE) -> None:
        self._secrets = secrets
        self._tolerance = tolerance

    def _resolve(self) -> list[str]:
        source = self._secrets() if callable(self._secrets) else self._secrets
        return [source] if isinstance(source, str) else list(source)

    async def __call__(self, request: Request) -> WebhookEvent:
        body = await request.body()
        try:
            return construct_event(
                body, request.headers.get(SIGNATURE_HEADER), self._resolve(), tolerance=self._tolerance
            )
        except WebhookSignatureError as err:
            raise HTTPException(status_code=400, detail={"error": err.reason}) from err


__all__ = ["VarizetWebhook"]
