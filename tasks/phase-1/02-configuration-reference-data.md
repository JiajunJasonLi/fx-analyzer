# Module 02: Configuration and Reference Data

## Goal

Provide validated declarative configuration and idempotent synchronization of Phase 1 currencies, economies, FX pairs, provider datasets, and series.

## Inputs

- Detailed design sections 4 and 5.2
- Requirements FR-1 and NFR-5

## Dependencies

- [x] Module 01 complete

## Checklist

- [x] Define typed configuration models for currencies, economies, economy-currency relationships, FX pairs, provider datasets, FX series, BIS policy-rate series, calendars, and provider settings.
- [x] Add version-controlled configuration for the G10 universe, nine foreign-currency/CAD pairs, and configured BIS series mappings without embedding mappings in business logic.
- [x] Validate ISO codes, pair orientation, duplicate provider symbols/keys, effective-date overlap, Phase 1 units/frequency, and enabled-series references.
- [x] Compute a deterministic checksum from canonicalized non-secret effective configuration.
- [x] Implement reference-data synchronization as transactional, idempotent upserts; missing configured entries must be disabled or explicitly handled, never destructively deleted.
- [x] Implement the provider-dataset license approval gate and persist attribution/redistribution metadata.
- [x] Add a CLI command to validate configuration and synchronize reference data.
- [x] Add unit tests for valid configuration, invalid references, duplicate mappings, checksum stability, secret exclusion, and license gating.
- [x] Add integration tests proving repeated synchronization creates no duplicates.
- [x] Run `pytest` and record the result.

## Done When

- [x] Configuration validation fails fast with actionable errors.
- [x] All enabled instruments can be resolved by stable keys from the database.
- [x] No external API is called by this module.

## Verification Notes

- Focused configuration/service tests: 13 passed.
- Configuration CLI validation passed with checksum `46f2bc8b7749f8f6b8da062f533e8ab22ba70ec6333c681af8abe7b516ced070` after aligning dataset identifiers with the canonical schema enums.
- PostgreSQL synchronization and stable-key resolution passed against the migrated local database. The Norway code is quoted explicitly in YAML and validated as a string to avoid YAML 1.1 boolean coercion.
