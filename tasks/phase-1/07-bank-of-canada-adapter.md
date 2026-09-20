# Module 07: Bank of Canada Valet Adapter

## Goal

Fetch, parse, and map configured Bank of Canada daily indicative FX observations into canonical FX candidates and typed absences.

## Inputs

- Detailed design section 7
- Requirements FR-2

## Dependencies

- [ ] Module 02 complete
- [ ] Module 04 complete
- [ ] Module 05 complete
- [ ] Module 06 complete

## Checklist

- [ ] Implement a Valet client using configured HTTPS base URL, endpoint templates, series identifiers, JSON format, and bounded dates.
- [ ] Group series only where the configured endpoint supports it.
- [ ] Store each successful raw response before parsing.
- [ ] Implement the Valet parser for response metadata, series details, dated values, status flags, explicit nulls, and stable raw paths.
- [ ] Parse source numeric strings directly to `Decimal`.
- [ ] Implement provider-symbol mapping to exactly one enabled foreign-currency/CAD `fx_series`.
- [ ] Produce only source-oriented `reference` candidates; never generate reciprocals or non-CAD crosses.
- [ ] Distinguish non-business days, explicit unpublished values, omitted expected dates, unknown series, malformed records, and response-wide parse failures.
- [ ] Add representative JSON fixtures and mocked HTTP contract tests for all above outcomes.
- [ ] Verify all configured nine G10 foreign-currency/CAD mappings.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] A bounded fixture request yields traced, validated FX candidates in published orientation.
- [ ] No normal automated test uses the live Valet API.

