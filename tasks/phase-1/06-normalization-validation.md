# Module 06: Normalization, Fingerprints, and Validation

## Goal

Convert mapped provider records into deterministic canonical candidates, fingerprints, and machine-readable validation results.

## Inputs

- Detailed design sections 3.3, 10, and 11
- Requirements FR-5 and section 9

## Dependencies

- [x] Module 02 complete
- [x] Module 04 complete

## Checklist

- [x] Implement immutable typed FX and policy-rate candidate models using `Decimal` and timezone-aware timestamps.
- [x] Implement deterministic identifier, date, decimal, timestamp, unit, frequency, and classification normalization.
- [x] Preserve original timestamp/time-zone and interpretation attributes without rounding, interpolation, reciprocation, or forward filling.
- [x] Implement canonical JSON and SHA-256 fingerprints with stable key ordering and decimal normalization.
- [x] Implement common, FX-specific, and policy-rate validation rules with stable reason codes and severity.
- [x] Treat unnormalizable records as errors; treat plausible range, movement, freshness, and future-tolerance concerns as flags where specified.
- [x] Detect identical and conflicting duplicate candidates within one input batch.
- [x] Ensure statistical checks only use observations known before candidate retrieval time.
- [x] Add unit tests for all rules, boundary values, equivalent decimal fingerprints, interpretation-changing fingerprints, and deterministic output.
- [x] Run `pytest` and record the result.

## Done When

- [x] The same raw input and configuration produce the same candidate and fingerprint.
- [x] Validation clearly separates quarantine-causing errors from non-blocking warnings.

## Verification Notes

- Normalization/validation plus provider-core tests: 31 passed under pinned dependencies.
- Python 3.12 full suite: 54 passed, 7 PostgreSQL-dependent tests skipped.
