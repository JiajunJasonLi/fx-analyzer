# Module 03: Phase 1 Database Schema

## Goal

Create the complete PostgreSQL schema and constraints required for reference data, ingestion operations, raw lineage, versioned observations, quarantine, and quality results.

## Inputs

- Detailed design section 5
- Requirements sections 8 and 10

## Dependencies

- [ ] Module 01 complete

## Checklist

- [ ] Implement typed SQLAlchemy models for every table specified in detailed design sections 5.2 through 5.6.
- [ ] Use UUID keys, UTC `TIMESTAMPTZ`, `DATE`, `NUMERIC(24, 12)`, and JSONB according to the design.
- [ ] Add foreign keys, natural-key uniqueness, enum/check constraints, non-negative counters, and date/interval checks.
- [ ] Add one-current-version constraints and indexes for natural-key, as-of, run, quality, and query access paths.
- [ ] Resolve circular current-version foreign keys through migration ordering or deferred constraints.
- [ ] Use separate enforceable FX and policy-rate lineage tables if a polymorphic foreign key cannot preserve integrity.
- [ ] Generate Alembic migrations in the order specified by the design.
- [ ] Add repository-neutral integration tests for constraints, exact decimal round trips, UTC timestamps, cascade/restrict behavior, and indexes expected by query paths.
- [ ] Verify upgrade from empty database and downgrade where safely supported.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] A clean migration creates the full Phase 1 schema.
- [ ] Database constraints reject duplicate natural keys and competing open versions.
- [ ] No provider-specific fetching or application workflow is included.

