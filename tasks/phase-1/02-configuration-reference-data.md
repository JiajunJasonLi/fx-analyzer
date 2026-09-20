# Module 02: Configuration and Reference Data

## Goal

Provide validated declarative configuration and idempotent synchronization of Phase 1 currencies, economies, FX pairs, provider datasets, and series.

## Inputs

- Detailed design sections 4 and 5.2
- Requirements FR-1 and NFR-5

## Dependencies

- [ ] Module 01 complete

## Checklist

- [ ] Define typed configuration models for currencies, economies, economy-currency relationships, FX pairs, provider datasets, FX series, BIS policy-rate series, calendars, and provider settings.
- [ ] Add version-controlled configuration for the G10 universe, nine foreign-currency/CAD pairs, and configured BIS series mappings without embedding mappings in business logic.
- [ ] Validate ISO codes, pair orientation, duplicate provider symbols/keys, effective-date overlap, Phase 1 units/frequency, and enabled-series references.
- [ ] Compute a deterministic checksum from canonicalized non-secret effective configuration.
- [ ] Implement reference-data synchronization as transactional, idempotent upserts; missing configured entries must be disabled or explicitly handled, never destructively deleted.
- [ ] Implement the provider-dataset license approval gate and persist attribution/redistribution metadata.
- [ ] Add a CLI command to validate configuration and synchronize reference data.
- [ ] Add unit tests for valid configuration, invalid references, duplicate mappings, checksum stability, secret exclusion, and license gating.
- [ ] Add integration tests proving repeated synchronization creates no duplicates.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Configuration validation fails fast with actionable errors.
- [ ] All enabled instruments can be resolved by stable keys from the database.
- [ ] No external API is called by this module.

