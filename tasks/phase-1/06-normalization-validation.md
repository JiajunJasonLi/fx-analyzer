# Module 06: Normalization, Fingerprints, and Validation

## Goal

Convert mapped provider records into deterministic canonical candidates, fingerprints, and machine-readable validation results.

## Inputs

- Detailed design sections 3.3, 10, and 11
- Requirements FR-5 and section 9

## Dependencies

- [ ] Module 02 complete
- [ ] Module 04 complete

## Checklist

- [ ] Implement immutable typed FX and policy-rate candidate models using `Decimal` and timezone-aware timestamps.
- [ ] Implement deterministic identifier, date, decimal, timestamp, unit, frequency, and classification normalization.
- [ ] Preserve original timestamp/time-zone and interpretation attributes without rounding, interpolation, reciprocation, or forward filling.
- [ ] Implement canonical JSON and SHA-256 fingerprints with stable key ordering and decimal normalization.
- [ ] Implement common, FX-specific, and policy-rate validation rules with stable reason codes and severity.
- [ ] Treat unnormalizable records as errors; treat plausible range, movement, freshness, and future-tolerance concerns as flags where specified.
- [ ] Detect identical and conflicting duplicate candidates within one input batch.
- [ ] Ensure statistical checks only use observations known before candidate retrieval time.
- [ ] Add unit tests for all rules, boundary values, equivalent decimal fingerprints, interpretation-changing fingerprints, and deterministic output.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] The same raw input and configuration produce the same candidate and fingerprint.
- [ ] Validation clearly separates quarantine-causing errors from non-blocking warnings.

