# Module 08: BIS SDMX Policy-Rate Adapter

## Goal

Fetch, parse, and map configured BIS central-bank policy-rate observations into canonical no-tenor policy-rate candidates and typed absences.

## Inputs

- Detailed design section 8
- Requirements FR-3

## Dependencies

- [x] Module 02 complete
- [x] Module 04 complete
- [x] Module 05 complete
- [x] Module 06 complete

## Checklist

- [x] Implement filtered, bounded BIS SDMX REST requests from configured dataflow and complete series keys.
- [x] Split requests to remain within configured provider limits and retain dataset-version metadata.
- [x] Support bulk input through the same raw-payload/parser path without creating a separate normalization path.
- [x] Parse dimensions by name using SDMX structure metadata or a versioned configured schema; never assume positional order without validation.
- [x] Preserve economy, currency, frequency, unit, collection/instrument attributes, status flags, breaks, publication metadata, and unknown safe attributes.
- [x] Map the complete series key to one enabled canonical series and validate the effective economy/currency relationship.
- [x] Normalize supported values to `percent_per_year`, with `rate_type=policy_rate`, `frequency=daily`, and `tenor=None`; quarantine unsupported units.
- [x] Preserve the BIS-published representative value and never manufacture corridor bounds or forward-filled observations.
- [x] Distinguish unchanged values, explicit absence, not-yet-due data, mapping errors, and request/parse failures.
- [x] Add representative SDMX/bulk fixtures and mocked HTTP contract tests, including reordered dimensions, revisions, bands, flags, and malformed input.
- [x] Verify every configured available G10 BIS series mapping.
- [x] Run `pytest` and record the result.

## Done When

- [x] A bounded fixture request yields traced policy-rate candidates with explicit units and no tenor.
- [x] No normal automated test uses the live BIS API.

## Verification Notes

- BIS contract tests: 9 passed.
- Full Python 3.12 suite at review: 74 passed, 7 PostgreSQL-dependent tests skipped.
