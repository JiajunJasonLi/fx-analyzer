# Module 10: Ingestion Runs and Orchestration

## Goal

Execute scheduled, manual, retry, and backfill requests through one durable, failure-isolated ingestion pipeline.

## Inputs

- Detailed design sections 13 and 15
- Requirements FR-7, FR-8, and NFR-1

## Dependencies

- [x] Modules 02 through 09 complete

## Checklist

- [x] Implement the typed start-ingestion command and bounded request validation.
- [x] Implement run and scope repositories, state transitions, heartbeats, counters, sanitized errors, and parent-run retry links.
- [x] Snapshot the effective configuration/checksum and plan bounded per-series scopes.
- [x] Implement PostgreSQL pending-run claiming with `FOR UPDATE SKIP LOCKED`.
- [x] Coordinate overlapping series/date scopes using active-scope checks plus advisory locks.
- [x] Implement the shared pipeline: fetch, raw persist, parse, map, normalize, validate, quarantine/flag, version persist, and quality trigger.
- [x] Commit independent bounded batches so one scope failure cannot corrupt successful scopes.
- [x] Implement exact final-status aggregation for succeeded, partially succeeded, failed, and conflict-skipped scopes.
- [x] Make retries create new linked runs and never delete prior valid observations.
- [x] Add integration tests for full success, empty success, partial provider failure, quarantine, overlap, retry, transaction rollback, and counter accuracy.
- [x] Run `pytest` and record the result.

## Done When

- [x] The same pipeline handles all trigger types and both providers.
- [x] A failure in one scope preserves valid committed work in other scopes.

## Verification Notes

- PostgreSQL orchestration integration suite: 8 passed, covering success, empty success, partial failure, quarantine, overlap, retry, rollback, counter accuracy, and both candidate types.
- Complete PostgreSQL-backed suite after integration: 140 passed, 1 warning.

- Focused command/run-manager tests: 9 passed.
- Full Python 3.12 suite: 97 passed, 11 PostgreSQL-dependent tests skipped.
- PostgreSQL end-to-end orchestration coverage exists but is unexecuted without `TEST_DATABASE_URL`; the integration and database-backed Done When items remain unchecked.
