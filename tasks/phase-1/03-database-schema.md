# Module 03: Phase 1 Database Schema

## Goal

Create the complete PostgreSQL schema and constraints required for reference data, ingestion operations, raw lineage, versioned observations, quarantine, and quality results.

## Inputs

- Detailed design section 5
- Requirements sections 8 and 10

## Dependencies

- [x] Module 01 complete

## Checklist

- [x] Implement typed SQLAlchemy models for every table specified in detailed design sections 5.2 through 5.6.
- [x] Use UUID keys, UTC `TIMESTAMPTZ`, `DATE`, `NUMERIC(24, 12)`, and JSONB according to the design.
- [x] Add foreign keys, natural-key uniqueness, enum/check constraints, non-negative counters, and date/interval checks.
- [x] Add one-current-version constraints and indexes for natural-key, as-of, run, quality, and query access paths.
- [x] Resolve circular current-version foreign keys through migration ordering or deferred constraints.
- [x] Use separate enforceable FX and policy-rate lineage tables if a polymorphic foreign key cannot preserve integrity.
- [x] Generate Alembic migrations in the order specified by the design.
- [x] Add repository-neutral integration tests for constraints, exact decimal round trips, UTC timestamps, cascade/restrict behavior, and indexes expected by query paths.
- [x] Verify upgrade from empty database and downgrade where safely supported.
- [x] Run `pytest` and record the result.

## Done When

- [x] A clean migration creates the full Phase 1 schema.
- [x] Database constraints reject duplicate natural keys and competing open versions.
- [x] No provider-specific fetching or application workflow is included.

## Verification Notes

- Static Python compilation and PostgreSQL DDL review passed.
- Schema tests exist for table registration, PostgreSQL types, constraints, indexes, lineage foreign keys, and canonical enum values.
- PostgreSQL upgrade/downgrade, exact decimals, UTC behavior, restrictive foreign keys, natural-key constraints, and one-open-version constraints passed in the full 124-test suite.
