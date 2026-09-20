# Module 05: Raw Data and Lineage

## Goal

Persist every successful provider response losslessly before normalization and create observation-level lineage references.

## Inputs

- Detailed design sections 5.4 and 9
- Requirements FR-4 and NFR-4

## Dependencies

- [ ] Module 03 complete
- [ ] Module 04 complete

## Checklist

- [ ] Implement raw-response, raw-record, and observation-version/run lineage repositories.
- [ ] Implement `RawDataService.store_response` to hash exact bytes with SHA-256, sanitize metadata, enforce size limits, and persist before parsing.
- [ ] Implement deterministic raw-record locators with idempotent `(raw_response_id, record_path)` behavior.
- [ ] Preserve retrieval time, media type, HTTP status, encoding, provider dataset, run, scope, and sanitized request identity.
- [ ] Ensure a raw-storage failure prevents canonical observation persistence for that response.
- [ ] Preserve all raw payloads indefinitely in Phase 1; add no expiry job.
- [ ] Add integration tests for byte-for-byte retrieval, checksums, duplicate locator handling, lineage, secret rejection, and transaction failure.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Any normalized observation can reference an exact raw record and response.
- [ ] Unchanged re-fetches can add run lineage without creating observation revisions.

