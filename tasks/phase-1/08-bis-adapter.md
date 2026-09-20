# Module 08: BIS SDMX Policy-Rate Adapter

## Goal

Fetch, parse, and map configured BIS central-bank policy-rate observations into canonical no-tenor policy-rate candidates and typed absences.

## Inputs

- Detailed design section 8
- Requirements FR-3

## Dependencies

- [ ] Module 02 complete
- [ ] Module 04 complete
- [ ] Module 05 complete
- [ ] Module 06 complete

## Checklist

- [ ] Implement filtered, bounded BIS SDMX REST requests from configured dataflow and complete series keys.
- [ ] Split requests to remain within configured provider limits and retain dataset-version metadata.
- [ ] Support bulk input through the same raw-payload/parser path without creating a separate normalization path.
- [ ] Parse dimensions by name using SDMX structure metadata or a versioned configured schema; never assume positional order without validation.
- [ ] Preserve economy, currency, frequency, unit, collection/instrument attributes, status flags, breaks, publication metadata, and unknown safe attributes.
- [ ] Map the complete series key to one enabled canonical series and validate the effective economy/currency relationship.
- [ ] Normalize supported values to `percent_per_year`, with `rate_type=policy_rate`, `frequency=daily`, and `tenor=None`; quarantine unsupported units.
- [ ] Preserve the BIS-published representative value and never manufacture corridor bounds or forward-filled observations.
- [ ] Distinguish unchanged values, explicit absence, not-yet-due data, mapping errors, and request/parse failures.
- [ ] Add representative SDMX/bulk fixtures and mocked HTTP contract tests, including reordered dimensions, revisions, bands, flags, and malformed input.
- [ ] Verify every configured available G10 BIS series mapping.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] A bounded fixture request yields traced policy-rate candidates with explicit units and no tenor.
- [ ] No normal automated test uses the live BIS API.

