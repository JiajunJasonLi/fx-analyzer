# Module 04: Provider Adapter Core

## Goal

Implement shared provider contracts and HTTP behavior so Bank of Canada and BIS adapters remain isolated from business logic.

## Inputs

- Detailed design sections 3 and 6
- Requirements section 11

## Dependencies

- [x] Module 01 complete
- [x] Module 02 complete

## Checklist

- [x] Implement typed `DateRange`, request metadata, raw payload, source locator, fetch request/result, parsed record, and published-absence domain types.
- [x] Define `ProviderClient`, `ProviderParser`, and `ProviderMapper` protocols without SQLAlchemy or FastAPI dependencies.
- [x] Define typed transient, permanent, payload-size, parse, and contract errors containing sanitized context only.
- [x] Build the shared `httpx.AsyncClient` factory with explicit timeouts, connection pooling, TLS verification, host/redirect restrictions, and response-size limits.
- [x] Implement bounded retry classification for transport errors, 408/429, and configured 5xx responses.
- [x] Honor `Retry-After`; otherwise apply bounded exponential backoff with jitter.
- [x] Sanitize request and response metadata through an allowlist.
- [x] Add mocked-transport unit tests for success, empty success, timeout, rate limit, retry exhaustion, permanent 4xx, redirect rejection, and oversized responses.
- [x] Ensure normal tests make no live network calls.
- [x] Run `pytest` and record the result.

## Done When

- [x] Both provider integrations can implement the same stable protocols.
- [x] No credentials, authorization headers, or payload bodies appear in exceptions or logs.

## Verification Notes

- `pytest -q tests/unit/test_provider_core.py`: 11 passed using mocked transports only.
- Full-suite collection remains blocked by the incompatible host SQLAlchemy/Alembic environment recorded in Modules 01–03; no provider-core test failed.
