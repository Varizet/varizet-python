# Changelog

All notable changes to the `varizet` Python SDK. Versions follow [SemVer](https://semver.org/).

## [0.2.0] - 2026-10-29

### Added

- Refunds are served by the API now: `refunds.get`, `refunds.list` and `refunds.list_auto_paging`
  (sync and async), and `currency` / `livemode` on the `Refund` model; `reference` and `reason`
  are optional on create.

### Changed

- `refunds.create` no longer documents a 404: `POST /v1/refunds` is live.

## [0.1.0] - 2026-10-29

- First release: sync and async clients on httpx (orders, refunds, webhook endpoints, events, test
  deposits, `GET /v1/me`), typed models and errors, automatic `Idempotency-Key`, webhook signature
  verification shared with the API through a test vector, Django and FastAPI helpers.
