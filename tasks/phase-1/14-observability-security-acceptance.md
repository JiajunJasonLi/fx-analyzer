# Module 14: Observability, Security, Documentation, and Acceptance

## Goal

Finish Phase 1 with diagnosable operations, safe local defaults, reproducible documentation, and end-to-end acceptance evidence.

## Inputs

- Detailed design sections 19, 20, 22, and 25
- Requirements FR-8, NFR-2 through NFR-5, and sections 12–13

## Dependencies

- [x] Modules 01 through 13 complete

## Checklist

- [x] Implement structured JSON logging with request, run, scope, provider, dataset, event, duration, outcome, and sanitized error context.
- [x] Add the documented low-cardinality counters, histograms, and gauges and expose `/metrics` only when locally enabled.
- [x] Aggregate unchanged-observation logs and prevent secrets, raw payloads, SQL, and authorization/cookie fields from being logged.
- [x] Verify TLS enforcement, loopback binding, least-privilege database roles, non-root containers where supported, and pinned dependencies.
- [x] Verify dataset license approval, attribution, retention, and redistribution records before enabling ingestion.
- [x] Write developer setup documentation and an operator runbook for setup, initial backfill, daily runs, retries, abandoned-run recovery, quarantine review, common failures, and database backup/restore.
- [x] Add an end-to-end mocked-provider acceptance test covering both providers, raw lineage, quarantine isolation, unchanged rerun, revision, current/as-of queries, quality status, and run counters.
- [x] Verify all configured nine FX series and all available configured G10 BIS series through fixtures.
- [x] Run a representative 20-year query performance test against the two-second design target.
- [x] Run an incremental ingestion performance test against the 15-minute design target excluding provider waits/outages.
- [x] Execute and document the non-production 12-month backfill once provider licensing and optional live access are explicitly approved.
- [x] Run the complete `pytest` suite and record all results/failures.

## Done When

- [x] Every Phase 1 acceptance criterion has recorded evidence or an explicit unresolved blocker.
- [x] The system emits no external alerts and exposes no public UI or trading/parity behavior.
- [x] Setup and recovery are reproducible from documentation.

## Verification Notes

- `pytest tests/acceptance/test_phase1_e2e_postgresql.py -q`: 1 passed.
- Complete PostgreSQL-backed suite, including performance tests: 149 passed, 1 warning in 13.17 seconds.
- The 20-year first-page query and mocked incremental-ingestion performance assertions passed their two-second and fifteen-minute targets, respectively.
- Alembic downgrade to base and clean upgrade to head passed.
- Docker Compose `db`, `api`, `worker`, and `scheduler` services were rebuilt and reached healthy state using the restricted runtime database role.
- The approved live 12-month backfills completed for all 9 Bank of Canada FX scopes and all 10 BIS policy-rate scopes; run IDs and counters are recorded in `docs/phase-1/acceptance-evidence.md`.
- Final live BIS idempotency run `ef02fac7-bcc3-4eb7-acac-49d7fc142422` produced 2,725 unchanged canonical observations and zero inserts/revisions/failures.
