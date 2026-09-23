# Module 11: Completeness and Freshness

## Goal

Evaluate configured observation expectations and expose auditable completeness and freshness results without mistaking schedules or holidays for failures.

## Inputs

- Detailed design section 14
- Requirements FR-5.8, FR-8, and section 9

## Dependencies

- [x] Module 02 complete
- [x] Module 03 complete
- [x] Module 09 complete

## Checklist

- [x] Implement typed expectation policies for calendar, observation frequency, publication timezone/time, release cadence, grace period, and effective dates.
- [x] Load versioned Canadian business-calendar and provider release rules from configuration.
- [x] Generate expected dates and determine which are due at a supplied evaluation timestamp.
- [x] Compare due dates with valid versions known as of that timestamp.
- [x] Produce `complete`, `incomplete`, `stale`, `not_due`, or `unknown` with missing dates/counts and explanatory evidence.
- [x] Treat BIS daily observations separately from its generally weekly publication cadence.
- [x] Persist append-only quality snapshots and implement current-quality retrieval.
- [x] Ensure quality-evaluation failure never rolls back valid observations and instead yields visible `unknown`/operational error state.
- [x] Add unit tests for weekends, holidays, grace periods, weekly releases, gaps, stale data, and missing calendar configuration.
- [x] Add integration tests for quality persistence and as-of evaluation.
- [x] Run `pytest` and record the result.

## Done When

- [x] Every enabled pair and series can receive an explainable quality state.
- [x] A not-yet-due observation is never reported as an ingestion failure.

## Verification Notes

- Focused quality/configuration tests: 18 passed.
- Full Python 3.12 suite: 97 passed, 11 PostgreSQL-dependent tests skipped.
- PostgreSQL append-only quality persistence and latest-result retrieval passed in the full 124-test suite.
