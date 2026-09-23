# Module 05: Raw Data and Lineage

## Goal

Persist every successful provider response losslessly before normalization and create observation-level lineage references.

## Inputs

- Detailed design sections 5.4 and 9
- Requirements FR-4 and NFR-4

## Dependencies

- [x] Module 03 complete
- [x] Module 04 complete

## Checklist

- [x] Implement raw-response, raw-record, and observation-version/run lineage repositories.
- [x] Implement `RawDataService.store_response` to hash exact bytes with SHA-256, sanitize metadata, enforce size limits, and persist before parsing.
- [x] Implement deterministic raw-record locators with idempotent `(raw_response_id, record_path)` behavior.
- [x] Preserve retrieval time, media type, HTTP status, encoding, provider dataset, run, scope, and sanitized request identity.
- [x] Ensure a raw-storage failure prevents canonical observation persistence for that response.
- [x] Preserve all raw payloads indefinitely in Phase 1; add no expiry job.
- [x] Add integration tests for byte-for-byte retrieval, checksums, duplicate locator handling, lineage, secret rejection, and transaction failure.
- [x] Run `pytest` and record the result.

## Done When

- [x] Any normalized observation can reference an exact raw record and response.
- [x] Unchanged re-fetches can add run lineage without creating observation revisions.

## Verification Notes

- Python 3.12 full suite: 54 passed, 7 PostgreSQL-dependent tests skipped.
- Raw-data/provider focused tests passed, including exact compressed wire-byte preservation.
- PostgreSQL raw-data integration tests passed in the full 124-test suite.
