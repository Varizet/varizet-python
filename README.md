# varizet (Python)

SDK رسمی پایتون برای API عمومی واریزت: سفارش کارت‌به‌کارت با مبلغ یکتا، وب‌هوک امضاشده و Sandbox.

Official Python SDK for the [Varizet](https://varizet.ir) public API (`/v1`, [developer docs](https://varizet.ir/developers)). Python 3.10+, sync and async
clients on [httpx](https://www.python-httpx.org/) (the only required dependency), typed models,
typed errors, webhook verification, and optional Django and FastAPI helpers.

**Money is always an `int` number of rial** (never float, never toman). Timestamps are aware UTC
`datetime` objects.

```bash
pip install varizet            # client + webhooks
pip install 'varizet[django]'  # + view decorator
pip install 'varizet[fastapi]' # + dependency
```

## Quick start

```python
from varizet import Varizet

client = Varizet("vz_test_…")  # or set VARIZET_API_KEY; VARIZET_API_BASE overrides the URL

order = client.orders.create(
    amount=8_500_000,                     # rial
    merchant_order_id="INV-12345",
    customer={"name": "سارا محمدی", "phone": "09121234567"},
    metadata={"cart_id": "c_998"},
)
print(order.code, order.unique_amount, order.payment_url)  # the customer pays unique_amount

order = client.orders.get("VZ-8K2Q")                        # ord_… or VZ-…
client.orders.cancel(order.id)
print(client.me().store.name)                                # GET /v1/me: store, mode, scopes
```

Async, same surface:

```python
from varizet import AsyncVarizet

async with AsyncVarizet("vz_test_…") as client:
    order = await client.orders.create(amount=8_500_000)
    async for o in client.orders.list_auto_paging(status="paid"):
        ...
```

| Resource            | Methods                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `orders`            | `create`, `get`, `list`, `list_auto_paging`, `cancel`                                                                    |
| `refunds`           | `create` (see the caveat below)                                                                                          |
| `webhook_endpoints` | `create` (returns the one-time `secret`), `list`, `list_auto_paging`, `get`, `update`, `delete`, `rotate_secret`, `ping` |
| `events`            | `list`, `list_auto_paging`, `resend`                                                                                     |
| `test`              | `simulate_deposit` (test keys only)                                                                                      |
| client              | `me()`                                                                                                                   |

### Idempotency and retries

Every `POST` sends an `Idempotency-Key`: a fresh UUID, or yours with `idempotency_key="…"`. Use your
own (for example `f"order-{invoice.id}"`) when you might call again after a crash: the API replays
the first answer for 24 h, and a different body with the same key raises `ConflictError`
(`idempotency_mismatch`). Network errors, timeouts and `500/502/503/504` are retried up to
`max_retries` (default 2) with backoff, **with the same key**, so a retry never creates a second
order.

### Pagination

`list()` returns one `Page` (`data`, `has_more`, `next_cursor`); pass `starting_after=page.next_cursor`
for the next one, or let `list_auto_paging()` walk every page lazily (`limit` 1–100, newest first).
Order filters: `status`, `merchant_order_id`, `customer_phone`, `created_gte`, `created_lte`
(`datetime` or ISO string).

### Errors

Failed calls raise a subclass of `varizet.VarizetError`. API errors carry the stable English `code`
and the Persian `message` from the API:

| Exception                                | When                                                  |
| ---------------------------------------- | ----------------------------------------------------- |
| `InvalidRequestError`                    | 400 (`amount_too_small`, `invalid_parameter`…)        |
| `AuthenticationError`                    | 401 (`invalid_api_key`, `key_revoked`)                |
| `PermissionDeniedError`                  | 403 (`scope_missing`, `testmode_required`…)           |
| `NotFoundError`                          | 404 (`order_not_found`…)                              |
| `ConflictError`                          | 409 (`idempotency_mismatch`, `order_not_cancelable`…) |
| `ValidationError`                        | 422 (`merchant_order_id_duplicate`…)                  |
| `RateLimitError`                         | 429; `retry_after` seconds                            |
| `APIServerError`                         | 5xx; give `request_id` to support                     |
| `APIConnectionError` / `APITimeoutError` | no usable answer (network, timeout, malformed body)   |

```python
from varizet import ConflictError

try:
    client.orders.cancel("VZ-8K2Q")
except ConflictError as err:
    print(err.code, err.message, err.request_id)  # order_not_cancelable, این سفارش قابل لغو نیست.
```

## Webhooks

Varizet signs every delivery: `Varizet-Signature: t=<unix>,v1=<hex hmac_sha256(secret, t + "." + body)>`.
Verify the **raw body bytes** (never re-serialised JSON); pass the current secret and, while a
rotation overlaps (24 h), the previous one too. Timestamps older or newer than 300 s are rejected.

```python
from varizet import WebhookSignatureError, construct_event

try:
    event = construct_event(raw_body, headers.get("Varizet-Signature"), ["whsec_current", "whsec_previous"])
except WebhookSignatureError as err:
    return 400, err.reason          # malformed | expired | mismatch | invalid_payload
if event.type == "order.paid":
    order = event.order()           # data.object as a typed Order
```

`verify_signature(...)` only checks; `compute_signature` / `build_signature_header` sign (tests).
The rules are pinned by cross-language test vectors shared with the API and the other SDKs.

### Django

```python
# settings.py
VARIZET_WEBHOOK_SECRETS = ["whsec_…"]

# views.py
from django.http import HttpResponse
from varizet.contrib.django import varizet_webhook

@varizet_webhook                       # or @varizet_webhook(secrets=[…]); sync or async views
def varizet_hook(request):
    event = request.varizet_event      # varizet.WebhookEvent
    ...
    return HttpResponse(status=200)
```

CSRF-exempt and POST-only; a bad signature answers `400 {"error": "<reason>"}` without calling the view.

### FastAPI

```python
from fastapi import Depends, FastAPI
from varizet import WebhookEvent
from varizet.contrib.fastapi import VarizetWebhook

app = FastAPI()
verified = VarizetWebhook(["whsec_…"])   # or a callable returning the secrets

@app.post("/webhooks/varizet")
async def hook(event: WebhookEvent = Depends(verified)):
    return {"received": True}
```

Rejected requests get `HTTPException(400, {"error": "<reason>"})`.

## Test mode

With a `vz_test_…` key everything is real except the money: create an order, then pay it through
the real matcher with a simulated bank SMS (`POST /v1/test/deposits`):

```python
order = client.orders.create(amount=8_500_000)
deposit = client.test.simulate_deposit(amount=order.unique_amount, card_id=order.destination.card_id)
assert deposit.match_status == "matched"
assert client.orders.get(order.id).is_paid   # order.paid webhook follows
```

Live keys get `PermissionDeniedError` (`testmode_required`).

## Refunds

`client.refunds.create(order_id=…, amount=…, method="card"|"iban", reference=…, reason=…)` records a
refund the merchant transferred (`POST /v1/refunds`, `refunds:write`; a bookkeeping
record, the merchant moves the money). It is the same record as «ثبت بازپرداخت» in the panel, and
both send the `refund.created` webhook whose `data.object` parses with `Refund.from_dict`.
`client.refunds.get(id)`, `.list(order=…)` and `.list_auto_paging()` read them back
(`orders:read` or `refunds:write`).

## Formatting

```python
from varizet import format_rial
format_rial(8_500_430)                          # '۸٬۵۰۰٬۴۳۰'
format_rial(8_500_430, unit=True)               # '۸٬۵۰۰٬۴۳۰ ریال'
format_rial(8_500_430, persian_digits=False)    # '8,500,430'
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest                      # httpx.MockTransport, Django test client, FastAPI TestClient
ruff check src tests && mypy
python -m build             # dist/varizet-0.1.0-py3-none-any.whl + sdist
```

Inside the Varizet monorepo the webhook tests also read the API's shared vectors; elsewhere (this
repository, an sdist) those cases are skipped.

---

## Contributing and security

Issues and pull requests are welcome. This repository is published from Varizet's main repository:
accepted changes are applied there and appear here with the next release.

Please report security vulnerabilities privately to support@varizet.ir, not in public issues.

## License

MIT, see [LICENSE](LICENSE).
