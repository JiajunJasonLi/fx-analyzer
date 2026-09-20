# Module 09: Observation Repositories and Versioning

## Goal

Persist valid observations idempotently, retain genuine revisions, and support correct current and knowledge-time queries.

## Inputs

- Detailed design sections 5.5 and 12
- Requirements FR-6 and NFR-4

## Dependencies

- [ ] Module 03 complete
- [ ] Module 05 complete
- [ ] Module 06 complete

## Checklist

- [ ] Implement typed FX and policy-rate observation repository interfaces.
- [ ] Implement atomic logical-observation creation by documented natural key.
- [ ] Lock the logical observation/current version before comparing fingerprints.
- [ ] Insert version 1 for a new observation and set the current pointer.
- [ ] For an unchanged fingerprint, update `last_observed_at` and add run/raw lineage without inserting a version.
- [ ] For a changed fingerprint, close the old half-open knowledge interval and insert the next current version in one transaction.
- [ ] Permit a value to revert later by creating a new timeline version.
- [ ] Reject or safely serialize out-of-order retrieval events so knowledge intervals cannot overlap.
- [ ] Ensure invalid, missing, failed, and quarantined records never create observation versions.
- [ ] Implement current and as-of repository queries that exclude future observations and later revisions.
- [ ] Add concurrency integration tests proving exactly one current version and no duplicate natural keys.
- [ ] Test insert, unchanged, revision, reversion, interval boundaries, lineage, and rollback behavior.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Reprocessing unchanged input is idempotent.
- [ ] Current and as-of queries return the correct version at every interval boundary.

