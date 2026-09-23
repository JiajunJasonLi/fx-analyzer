# Phase 1 Acceptance Evidence

## Offline acceptance

The normal suite is fixture-based and makes no live provider calls. The coherent PostgreSQL-gated scenario in `tests/acceptance/test_phase1_e2e_postgresql.py` drives production orchestration with mocked Bank of Canada and BIS I/O and verifies raw lineage, quarantine isolation, unchanged reprocessing, revision, current/as-of queries, quality, and run counters.

| Acceptance behavior | Automated evidence |
|---|---|
| Both provider contracts and configured mappings | `tests/contract/test_bank_of_canada_valet.py`, `tests/contract/test_bis_adapter.py` |
| Raw-first lineage and quarantine isolation | `tests/integration/test_raw_data_postgresql.py`, `tests/integration/test_ingestion_orchestration_postgresql.py` |
| Unchanged rerun, revision, reversion, and as-of safety | `tests/integration/test_observation_versioning_postgresql.py`, `tests/api/test_query_api.py` |
| Both provider candidate types through shared orchestration | `test_same_pipeline_handles_both_provider_candidate_types` |
| Run counters, overlap, partial failure, and recovery | orchestration and worker-recovery PostgreSQL tests |
| Completeness/freshness quality status | unit and PostgreSQL data-quality tests |
| Logging, metrics, security defaults, and license gate | `tests/unit/test_observability_security.py` |

Configured coverage is verified for all nine foreign-currency/CAD FX series and all ten configured G10 BIS economy/currency mappings. Representative performance tests are opt-in PostgreSQL tests and must report their measured durations against the two-second history-query and fifteen-minute incremental-ingestion design targets.

## Requirements acceptance criteria

| # | Status | Evidence or blocker |
|---|---|---|
| 1 | Verified live | The 2025-09-21 through 2026-09-21 backfills succeeded for all 9 configured Bank of Canada FX series and all 10 configured BIS policy-rate series. |
| 2 | Verified live | Bank of Canada run `77047629-aaac-4bfc-8930-37d483724371` and final BIS run `b37dc3ba-acb4-44b8-a17d-79082724a1bb` completed successfully with retained raw responses and queryable canonical observations. |
| 3 | Verified offline | Scheduler tests verify provider calendars and durable command creation; orchestration tests verify incremental execution and recorded outcomes. Live scheduled provider execution shares criterion 1's approval blocker. |
| 4 | Verified | The coherent acceptance scenario reruns the same FX value and verifies one unchanged outcome, two lineage links, and no additional canonical version. |
| 5 | Verified | The scenario changes the FX value and verifies an immutable second version plus correct current and pre-revision as-of results. Dedicated versioning tests also cover value reversion and half-open boundaries. |
| 6 | Verified | Bank of Canada and BIS contract tests validate published orientation, named SDMX dimensions, exact dates/decimals, canonical unit/frequency/type, status attributes, and representative fixtures. |
| 7 | Verified | The scenario processes a valid and invalid FX record in one response, verifies one quarantine with one valid inserted observation, and confirms no invalid canonical version. |
| 8 | Verified | The scenario verifies raw responses/records, version-run lineage, provider identifiers, retrieval/knowledge timestamps, run ID, and raw-record provenance returned by production queries. |
| 9 | Verified offline | Quality unit/integration tests cover complete, incomplete, stale, not-due, and unknown schedules; configuration has an expectation policy for every enabled pair/series; the internal quality API exposes results. |
| 10 | Verified | `developer-setup.md` and `operator-runbook.md` cover setup, initial backfill, daily operation, manual reruns/internal linked retries, lease recovery, quarantine review, common failures, and backup/restore. |
| 11 | Verified | The project operator approved both documented sources on 2026-09-21; license URLs, attribution, redistribution notes, approval state, and raw-retention permission are recorded in versioned configuration. |

## Security and operating constraints

- Provider base URLs require HTTPS; insecure transport exists only as an explicit test option.
- Docker publishes API/PostgreSQL on loopback, runs application containers as non-root, and separates migration-owner and runtime DML roles.
- Python dependencies and the PostgreSQL container image are pinned.
- Logs use an allowlisted JSON shape and redact credentials, URLs, authorization/cookie values, raw bodies, and SQL-keyed context.
- Metrics have a fixed low-cardinality label schema and are disabled unless `METRICS_ENABLED=true`.
- There is no external alert integration, public UI, raw-payload endpoint, parity logic, or trading behavior.

## Live backfill evidence

The non-production 12-month backfill was executed for 2025-09-21 through 2026-09-21 after the project operator approved both sources and raw retention.

| Provider | Successful run | Result |
|---|---|---|
| Bank of Canada | `77047629-aaac-4bfc-8930-37d483724371` | 2,241 fetched; 2,232 inserted; 9 unchanged; 0 quarantined; 0 failed across all 9 FX scopes. |
| BIS | `b37dc3ba-acb4-44b8-a17d-79082724a1bb` | 3,088 fetched; 1,238 inserted; 355 unchanged; 1,132 immutable revisions; 0 quarantined; 0 failed across all 10 policy-rate scopes. |
| BIS idempotency verification | `ef02fac7-bcc3-4eb7-acac-49d7fc142422` | 3,088 fetched; 2,725 valid observations unchanged; 0 inserted; 0 revised; 0 quarantined; 0 failed. Provider `NaN` absences created no versions. |

The original BIS attempt failed with HTTP 406 because the live v1 API requires SDMX-JSON selection through `Accept`, not a `format` query parameter. Later runs exposed gzip responses, provider `NaN` absence markers, and volatile response-level `datasetId`/`prepared` metadata. Those failed/partial runs and the resulting immutable diagnostic revisions remain in durable history. The adapter now keeps volatile response metadata only in raw lineage, and the final identical pass proved stable fingerprints with zero revisions.

Non-destructive database verification found all 9 FX pairs populated with 249 observations each and all 10 BIS series populated. The database retained 68 raw responses and 6,896 raw records across the backfill, diagnostic retries, and scheduler activity, with zero quarantined records.
