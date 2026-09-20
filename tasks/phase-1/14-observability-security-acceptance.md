# Module 14: Observability, Security, Documentation, and Acceptance

## Goal

Finish Phase 1 with diagnosable operations, safe local defaults, reproducible documentation, and end-to-end acceptance evidence.

## Inputs

- Detailed design sections 19, 20, 22, and 25
- Requirements FR-8, NFR-2 through NFR-5, and sections 12–13

## Dependencies

- [ ] Modules 01 through 13 complete

## Checklist

- [ ] Implement structured JSON logging with request, run, scope, provider, dataset, event, duration, outcome, and sanitized error context.
- [ ] Add the documented low-cardinality counters, histograms, and gauges and expose `/metrics` only when locally enabled.
- [ ] Aggregate unchanged-observation logs and prevent secrets, raw payloads, SQL, and authorization/cookie fields from being logged.
- [ ] Verify TLS enforcement, loopback binding, least-privilege database roles, non-root containers where supported, and pinned dependencies.
- [ ] Verify dataset license approval, attribution, retention, and redistribution records before enabling ingestion.
- [ ] Write developer setup documentation and an operator runbook for setup, initial backfill, daily runs, retries, abandoned-run recovery, quarantine review, common failures, and database backup/restore.
- [ ] Add an end-to-end mocked-provider acceptance test covering both providers, raw lineage, quarantine isolation, unchanged rerun, revision, current/as-of queries, quality status, and run counters.
- [ ] Verify all configured nine FX series and all available configured G10 BIS series through fixtures.
- [ ] Run a representative 20-year query performance test against the two-second design target.
- [ ] Run an incremental ingestion performance test against the 15-minute design target excluding provider waits/outages.
- [ ] Execute and document the non-production 12-month backfill once provider licensing and optional live access are explicitly approved.
- [ ] Run the complete `pytest` suite and record all results/failures.

## Done When

- [ ] Every Phase 1 acceptance criterion has recorded evidence or an explicit unresolved blocker.
- [ ] The system emits no external alerts and exposes no public UI or trading/parity behavior.
- [ ] Setup and recovery are reproducible from documentation.

