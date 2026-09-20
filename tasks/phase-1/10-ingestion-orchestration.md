# Module 10: Ingestion Runs and Orchestration

## Goal

Execute scheduled, manual, retry, and backfill requests through one durable, failure-isolated ingestion pipeline.

## Inputs

- Detailed design sections 13 and 15
- Requirements FR-7, FR-8, and NFR-1

## Dependencies

- [ ] Modules 02 through 09 complete

## Checklist

- [ ] Implement the typed start-ingestion command and bounded request validation.
- [ ] Implement run and scope repositories, state transitions, heartbeats, counters, sanitized errors, and parent-run retry links.
- [ ] Snapshot the effective configuration/checksum and plan bounded per-series scopes.
- [ ] Implement PostgreSQL pending-run claiming with `FOR UPDATE SKIP LOCKED`.
- [ ] Coordinate overlapping series/date scopes using active-scope checks plus advisory locks.
- [ ] Implement the shared pipeline: fetch, raw persist, parse, map, normalize, validate, quarantine/flag, version persist, and quality trigger.
- [ ] Commit independent bounded batches so one scope failure cannot corrupt successful scopes.
- [ ] Implement exact final-status aggregation for succeeded, partially succeeded, failed, and conflict-skipped scopes.
- [ ] Make retries create new linked runs and never delete prior valid observations.
- [ ] Add integration tests for full success, empty success, partial provider failure, quarantine, overlap, retry, transaction rollback, and counter accuracy.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] The same pipeline handles all trigger types and both providers.
- [ ] A failure in one scope preserves valid committed work in other scopes.

