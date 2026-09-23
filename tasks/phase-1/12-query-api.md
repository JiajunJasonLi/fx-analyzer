# Module 12: Query and Operations API

## Goal

Expose internal FastAPI endpoints for current/as-of observations, ingestion operations, data quality, and quarantine counts.

## Inputs

- Detailed design sections 16 and 17
- Requirements FR-9

## Dependencies

- [x] Module 09 complete
- [x] Module 10 complete
- [x] Module 11 complete

## Checklist

- [x] Implement query services for FX history/latest and policy-rate history/latest with bounded filters and intersection semantics.
- [x] Require unambiguous identifying filters and reject unbounded/invalid date ranges.
- [x] Implement stable keyset pagination and deterministic ordering.
- [x] Serialize exact decimals as strings and timestamps as UTC ISO 8601 values.
- [x] Return version identity, validation flags, source identifiers, and run/raw provenance.
- [x] Implement `POST /api/v1/ingestion-runs` as durable enqueue only, returning `202`; do not execute provider calls in the request lifecycle.
- [x] Implement run detail/list, data-quality, and quarantine-count endpoints.
- [x] Implement consistent error bodies and mappings for 404, 409, 422, 500, and 503.
- [x] Add `/health/ready` checks for database connectivity, migration level, configuration, and reference readiness.
- [x] Keep raw payload retrieval and public authentication outside the API.
- [x] Add API tests for filters, pagination, precision, latest/as-of behavior, provenance, errors, run overlap, and readiness.
- [x] Run `pytest` and record the result.

## Done When

- [x] All FR-9 queries are available under `/api/v1`.
- [x] An as-of response cannot contain an observation version learned later.

## Verification Notes

- API query/health suite: 16 passed.
- Complete PostgreSQL-backed suite after integration: 140 passed, 1 warning.
