"""Django: a view decorator that verifies ``Varizet-Signature`` before your view runs.

.. code-block:: python

    # settings.py
    VARIZET_WEBHOOK_SECRETS = ["whsec_…"]  # current first; add the previous one while rotating

    # views.py
    from varizet.contrib.django import varizet_webhook

    @varizet_webhook
    def varizet_hook(request):
        event = request.varizet_event  # varizet.WebhookEvent
        if event.type == "order.paid":
            mark_paid(event.order().merchant_order_id)
        return HttpResponse(status=200)

The view is CSRF-exempt and POST-only; a bad or stale signature answers ``400`` without calling it.
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable, Sequence
from typing import Any, TypeVar, cast, overload

try:
    from django.conf import settings
    from django.http import HttpRequest, HttpResponse, JsonResponse
    from django.views.decorators.csrf import csrf_exempt
except ImportError as err:  # pragma: no cover - exercised only without the extra
    raise ImportError("varizet.contrib.django needs Django: pip install 'varizet[django]'") from err

from ..webhooks import DEFAULT_TOLERANCE, SIGNATURE_HEADER, WebhookSignatureError, construct_event

V = TypeVar("V", bound=Callable[..., Any])


def _configured_secrets() -> list[str]:
    many = getattr(settings, "VARIZET_WEBHOOK_SECRETS", None)
    if many:
        return [str(s) for s in many]
    one = getattr(settings, "VARIZET_WEBHOOK_SECRET", None)
    if one:
        return [str(one)]
    raise RuntimeError("set VARIZET_WEBHOOK_SECRETS (or VARIZET_WEBHOOK_SECRET) in Django settings")


def _reject(request: HttpRequest, secrets: Sequence[str] | None, tolerance: int) -> HttpResponse | None:
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    try:
        request.varizet_event = construct_event(
            request.body,
            request.headers.get(SIGNATURE_HEADER),
            list(secrets) if secrets else _configured_secrets(),
            tolerance=tolerance,
        )
    except WebhookSignatureError as err:
        return JsonResponse({"error": err.reason}, status=400)
    return None


@overload
def varizet_webhook(view: V) -> V: ...
@overload
def varizet_webhook(
    view: None = None, *, secrets: str | Sequence[str] | None = None, tolerance: int = DEFAULT_TOLERANCE
) -> Callable[[V], V]: ...
def varizet_webhook(
    view: V | None = None, *, secrets: str | Sequence[str] | None = None, tolerance: int = DEFAULT_TOLERANCE
) -> V | Callable[[V], V]:
    """Use as ``@varizet_webhook`` (secrets from settings) or ``@varizet_webhook(secrets=[…])``.
    Works for sync and async views; the verified event is ``request.varizet_event``."""
    fixed = [secrets] if isinstance(secrets, str) else (list(secrets) if secrets else None)

    def decorate(fn: V) -> V:
        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_view(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
                rejected = _reject(request, fixed, tolerance)
                return rejected if rejected is not None else await fn(request, *args, **kwargs)

            return cast(V, csrf_exempt(async_view))

        @functools.wraps(fn)
        def sync_view(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            rejected = _reject(request, fixed, tolerance)
            return rejected if rejected is not None else fn(request, *args, **kwargs)

        return cast(V, csrf_exempt(sync_view))

    return decorate(view) if view is not None else decorate


__all__ = ["varizet_webhook"]
