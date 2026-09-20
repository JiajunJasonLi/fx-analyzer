# Module 04: Provider Adapter Core

## Goal

Implement shared provider contracts and HTTP behavior so Bank of Canada and BIS adapters remain isolated from business logic.

## Inputs

- Detailed design sections 3 and 6
- Requirements section 11

## Dependencies

- [ ] Module 01 complete
- [ ] Module 02 complete

## Checklist

- [ ] Implement typed `DateRange`, request metadata, raw payload, source locator, fetch request/result, parsed record, and published-absence domain types.
- [ ] Define `ProviderClient`, `ProviderParser`, and `ProviderMapper` protocols without SQLAlchemy or FastAPI dependencies.
- [ ] Define typed transient, permanent, payload-size, parse, and contract errors containing sanitized context only.
- [ ] Build the shared `httpx.AsyncClient` factory with explicit timeouts, connection pooling, TLS verification, host/redirect restrictions, and response-size limits.
- [ ] Implement bounded retry classification for transport errors, 408/429, and configured 5xx responses.
- [ ] Honor `Retry-After`; otherwise apply bounded exponential backoff with jitter.
- [ ] Sanitize request and response metadata through an allowlist.
- [ ] Add mocked-transport unit tests for success, empty success, timeout, rate limit, retry exhaustion, permanent 4xx, redirect rejection, and oversized responses.
- [ ] Ensure normal tests make no live network calls.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Both provider integrations can implement the same stable protocols.
- [ ] No credentials, authorization headers, or payload bodies appear in exceptions or logs.

