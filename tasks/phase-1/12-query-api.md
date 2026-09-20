# Module 12: Query and Operations API

## Goal

Expose internal FastAPI endpoints for current/as-of observations, ingestion operations, data quality, and quarantine counts.

## Inputs

- Detailed design sections 16 and 17
- Requirements FR-9

## Dependencies

- [ ] Module 09 complete
- [ ] Module 10 complete
- [ ] Module 11 complete

## Checklist

- [ ] Implement query services for FX history/latest and policy-rate history/latest with bounded filters and intersection semantics.
- [ ] Require unambiguous identifying filters and reject unbounded/invalid date ranges.
- [ ] Implement stable keyset pagination and deterministic ordering.
- [ ] Serialize exact decimals as strings and timestamps as UTC ISO 8601 values.
- [ ] Return version identity, validation flags, source identifiers, and run/raw provenance.
- [ ] Implement `POST /api/v1/ingestion-runs` as durable enqueue only, returning `202`; do not execute provider calls in the request lifecycle.
- [ ] Implement run detail/list, data-quality, and quarantine-count endpoints.
- [ ] Implement consistent error bodies and mappings for 404, 409, 422, 500, and 503.
- [ ] Add `/health/ready` checks for database connectivity, migration level, configuration, and reference readiness.
- [ ] Keep raw payload retrieval and public authentication outside the API.
- [ ] Add API tests for filters, pagination, precision, latest/as-of behavior, provenance, errors, run overlap, and readiness.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] All FR-9 queries are available under `/api/v1`.
- [ ] An as-of response cannot contain an observation version learned later.

