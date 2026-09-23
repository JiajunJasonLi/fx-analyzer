# Module 09: Observation Repositories and Versioning

## Goal

Persist valid observations idempotently, retain genuine revisions, and support correct current and knowledge-time queries.

## Inputs

- Detailed design sections 5.5 and 12
- Requirements FR-6 and NFR-4

## Dependencies

- [x] Module 03 complete
- [x] Module 05 complete
- [x] Module 06 complete

## Checklist

- [x] Implement typed FX and policy-rate observation repository interfaces.
- [x] Implement atomic logical-observation creation by documented natural key.
- [x] Lock the logical observation/current version before comparing fingerprints.
- [x] Insert version 1 for a new observation and set the current pointer.
- [x] For an unchanged fingerprint, update `last_observed_at` and add run/raw lineage without inserting a version.
- [x] For a changed fingerprint, close the old half-open knowledge interval and insert the next current version in one transaction.
- [x] Permit a value to revert later by creating a new timeline version.
- [x] Reject or safely serialize out-of-order retrieval events so knowledge intervals cannot overlap.
- [x] Ensure invalid, missing, failed, and quarantined records never create observation versions.
- [x] Implement current and as-of repository queries that exclude future observations and later revisions.
- [x] Add concurrency integration tests proving exactly one current version and no duplicate natural keys.
- [x] Test insert, unchanged, revision, reversion, interval boundaries, lineage, and rollback behavior.
- [x] Run `pytest` and record the result.

## Done When

- [x] Reprocessing unchanged input is idempotent.
- [x] Current and as-of queries return the correct version at every interval boundary.

## Verification Notes

- Offline/unit review: 5 focused tests passed; full Python 3.12 suite: 79 passed.
- PostgreSQL revision, lineage, interval, future-date exclusion, and concurrent-worker tests passed in the full 124-test suite.
