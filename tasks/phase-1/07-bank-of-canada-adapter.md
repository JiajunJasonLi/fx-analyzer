# Module 07: Bank of Canada Valet Adapter

## Goal

Fetch, parse, and map configured Bank of Canada daily indicative FX observations into canonical FX candidates and typed absences.

## Inputs

- Detailed design section 7
- Requirements FR-2

## Dependencies

- [x] Module 02 complete
- [x] Module 04 complete
- [x] Module 05 complete
- [x] Module 06 complete

## Checklist

- [x] Implement a Valet client using configured HTTPS base URL, endpoint templates, series identifiers, JSON format, and bounded dates.
- [x] Group series only where the configured endpoint supports it.
- [x] Store each successful raw response before parsing.
- [x] Implement the Valet parser for response metadata, series details, dated values, status flags, explicit nulls, and stable raw paths.
- [x] Parse source numeric strings directly to `Decimal`.
- [x] Implement provider-symbol mapping to exactly one enabled foreign-currency/CAD `fx_series`.
- [x] Produce only source-oriented `reference` candidates; never generate reciprocals or non-CAD crosses.
- [x] Distinguish non-business days, explicit unpublished values, omitted expected dates, unknown series, malformed records, and response-wide parse failures.
- [x] Add representative JSON fixtures and mocked HTTP contract tests for all above outcomes.
- [x] Verify all configured nine G10 foreign-currency/CAD mappings.
- [x] Run `pytest` and record the result.

## Done When

- [x] A bounded fixture request yields traced, validated FX candidates in published orientation.
- [x] No normal automated test uses the live Valet API.

## Verification Notes

- Bank of Canada contract tests: 11 passed.
- Full Python 3.12 suite at review: 72 passed, 7 PostgreSQL-dependent tests skipped.
