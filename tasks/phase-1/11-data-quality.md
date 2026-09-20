# Module 11: Completeness and Freshness

## Goal

Evaluate configured observation expectations and expose auditable completeness and freshness results without mistaking schedules or holidays for failures.

## Inputs

- Detailed design section 14
- Requirements FR-5.8, FR-8, and section 9

## Dependencies

- [ ] Module 02 complete
- [ ] Module 03 complete
- [ ] Module 09 complete

## Checklist

- [ ] Implement typed expectation policies for calendar, observation frequency, publication timezone/time, release cadence, grace period, and effective dates.
- [ ] Load versioned Canadian business-calendar and provider release rules from configuration.
- [ ] Generate expected dates and determine which are due at a supplied evaluation timestamp.
- [ ] Compare due dates with valid versions known as of that timestamp.
- [ ] Produce `complete`, `incomplete`, `stale`, `not_due`, or `unknown` with missing dates/counts and explanatory evidence.
- [ ] Treat BIS daily observations separately from its generally weekly publication cadence.
- [ ] Persist append-only quality snapshots and implement current-quality retrieval.
- [ ] Ensure quality-evaluation failure never rolls back valid observations and instead yields visible `unknown`/operational error state.
- [ ] Add unit tests for weekends, holidays, grace periods, weekly releases, gaps, stale data, and missing calendar configuration.
- [ ] Add integration tests for quality persistence and as-of evaluation.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Every enabled pair and series can receive an explainable quality state.
- [ ] A not-yet-due observation is never reported as an ingestion failure.

