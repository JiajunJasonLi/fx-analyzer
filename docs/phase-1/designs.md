# Phase 1 High-Level Design: FX and Interest-Rate Data Ingestion

## 1. Overview

Phase 1 provides a local, auditable data platform for daily Bank of Canada FX reference rates and BIS central-bank policy rates. It fetches provider data, preserves the raw responses, normalizes and validates observations, stores revisions without losing history, and exposes observations and ingestion health through an internal FastAPI API.

The design deliberately stops at trusted data acquisition and retrieval. It does not calculate interest-rate parity, derive cross rates, ingest forwards, or identify trading opportunities.

## 2. Design Goals and Principles

- Preserve every accepted normalized observation's lineage to the provider response and ingestion run.
- Make scheduled runs, retries, and bounded backfills use the same processing path.
- Make unchanged reprocessing idempotent while retaining genuine provider revisions.
- Prevent failures in one provider, series, or record from corrupting other valid data.
- Keep provider protocols and schemas outside business logic.
- Represent financial values with exact decimal types and dates/timestamps explicitly.
- Make data quality visible without silently rejecting plausible market events.
- Support point-in-time queries that do not introduce revisions published later.
- Keep currencies, pairs, series, calendars, thresholds, and endpoints configurable.

## 3. Scope and Constraints

### In scope

- Bank of Canada Valet daily indicative FX averages in their published foreign-currency/CAD orientation.
- BIS SDMX daily central-bank policy-rate observations for configured G10 economies.
- A 12-month initial backfill and incremental provider-aware ingestion.
- Raw response retention, normalization, validation, versioning, quarantine, run tracking, structured logs, and metrics.
- An internal/local FastAPI API for observations, provenance, freshness, completeness, run status, and quarantine counts.

### Out of scope

- Cross-rate or reciprocal persistence, forward FX, matched-tenor funding rates, parity calculations, forecasting, alerts, trading, and portfolio functions.
- Real-time ingestion, a public UI, or internet-facing authentication.
- Automated deletion of raw data.

## 4. System Context

```text
                       scheduled/manual/backfill trigger
                                     |
                                     v
+----------------+          +-------------------+
| Bank of Canada |--------->|                   |
| Valet API      |          | Ingestion service |----+
+----------------+          |                   |    |
                            +-------------------+    v
+----------------+                    |         +------------+
| BIS SDMX REST  |--------------------+-------->| PostgreSQL |
| API / bulk     |                              +------------+
+----------------+                                    ^
                                                      |
                                               +-------------+
                                               | FastAPI API |
                                               +-------------+
                                                      ^
                                                      |
                                              analyst/developer
```

The application and PostgreSQL run locally with Docker Compose. External provider calls use HTTPS. Only provider adapters understand Valet JSON or BIS SDMX formats; downstream services operate on internal models.

## 5. Logical Architecture
The application follows the project layering convention:

```text
API / command entry points
          |
          v
Application services and ingestion orchestration
          |
          +----> provider clients and provider-specific mappers
          |
          v
Repositories
          |
          v
PostgreSQL
```

### 5.1 API and entry points
- **Query API:** validates filters, calls query services, and serializes canonical observations and provenance.
- **Operations API:** starts bounded manual/backfill runs and returns run, freshness, completeness, and quarantine summaries.
- **Scheduler entry point:** invokes the same ingestion application service used by manual runs. A lightweight scheduler process or host cron may call provider-specific commands; scheduling policy remains separate from ingestion logic.
- **CLI entry point:** supports reproducible setup, backfills, retries, and operational recovery without requiring direct database changes.

Long-running ingestion requests should create an ingestion-run record and execute outside the HTTP request lifecycle. Phase 1 may use a dedicated worker process backed by PostgreSQL rather than introduce a separate message broker.

### 5.2 Application services
- **Ingestion orchestrator:** resolves enabled configuration, coordinates run ownership, calls provider adapters, and maintains run status and counters.
- **Normalization services:** convert provider records into typed internal candidates without database concerns.
- **Validation service:** applies common and dataset-specific rules and returns structured validation results.
- **Revision service:** compares a candidate with the current stored version and classifies it as inserted, unchanged, revised, or conflicting.
- **Completeness/freshness service:** evaluates expected observations using configured release cadence and calendars.
- **Observation query service:** implements current and point-in-time retrieval semantics.

### 5.3 Provider integrations
Each provider integration consists of:

- an `httpx` client responsible for bounded requests, timeouts, retry hints, response status, and sanitized request metadata;
- a provider parser that reads Valet JSON or BIS SDMX/bulk data;
- a mapper that resolves provider identifiers to configured canonical pairs or series; and
- provider-specific classification of published, missing, not-yet-released, malformed, and request-failure outcomes.

Clients receive endpoint paths, identifiers, and request limits from configuration. They return typed provider records and metadata; they do not write directly to observation tables.

### 5.4 Repository layer
Repositories isolate SQLAlchemy persistence for configuration, raw responses, ingestion runs, canonical observations and versions, quarantine records, and quality summaries. Service-level logical batches use database transactions, with per-series or bounded-page commit boundaries to avoid losing an entire provider run after one independent failure.

## 6. Configuration
Declarative configuration defines:

- currencies and economies, including currency-union relationships;
- canonical FX pairs and Bank of Canada series mappings;
- BIS dataflow, series keys, dimensions, and economy/currency mappings;
- enabled/disabled state;
- provider base URLs, endpoint templates, request bounds, timeouts, and retry limits;
- interest-rate plausibility ranges and future-date tolerances;
- calendars, expected frequencies, publication delays, and freshness thresholds; and
- licensing, attribution, and redistribution notes.

Non-secret defaults may be version-controlled YAML or TOML loaded into reference tables through a repeatable seed/synchronization command. Environment variables supply deployment-specific settings such as database URLs. Secrets, if ever needed, are never persisted in request metadata, raw payload metadata, or logs.

Each run records a configuration version, preferably the source-control commit plus a checksum of the effective non-secret configuration, so transformations can be reproduced.

## 7. Data Model
PostgreSQL uses UUID primary keys, `DATE` for observation dates, timezone-aware UTC timestamps, and `NUMERIC` for financial values. JSONB retains provider metadata whose shape is not stable enough for canonical columns. Foreign keys enforce reference integrity.

### 7.1 Reference tables

| Entity | Important fields and constraints |
|---|---|
| `currency` | ISO 4217 code (unique), name, minor units, active flag |
| `economy` | stable code (unique), optional ISO country code, name, time zone, economy type, active flag |
| `economy_currency` | economy, currency, effective dates; supports unions and historical changes |
| `fx_pair` | base currency, quote currency, canonical symbol, active flag; unique base/quote pair; base must differ from quote |
| `provider_dataset` | provider, dataset, configuration reference, license/usage metadata |
| `fx_series` | provider dataset, provider symbol, FX pair, quote type, frequency, active flag; provider symbol unique within dataset |
| `interest_rate_series` | provider dataset, economy, currency, dataflow/series key, `policy_rate`, frequency, unit, collection indicator, title, source/publication metadata, active flag |

For Phase 1, every enabled Bank of Canada source pair has CAD as quote currency and `reference` as quote type. BIS canonical units are documented as **percent per year**; values such as `5.25` remain `5.25`, not decimal fraction `0.0525`.

### 7.2 Operational and raw-data tables

| Entity | Important fields and constraints |
|---|---|
| `ingestion_run` | run UUID, trigger type, provider dataset, requested range, configuration/code version, timestamps, status, counters, sanitized error summary |
| `ingestion_scope` | run, series or dataset scope, date range, status; used for coordination and partial outcomes |
| `raw_response` | run, provider dataset, sanitized request parameters, retrieval time, HTTP status, media type, checksum, lossless payload or object reference, provider response metadata |
| `raw_record` | raw response, stable record locator/index, provider natural key and optional checksum; permits observation-level lineage |
| `quarantined_record` | run, raw record, candidate identifiers where known, reason code, sanitized details, created time, resolution state |
| `quality_result` | run and pair/series scope, rule code, severity/status, affected date or range, structured details |

Raw response uniqueness is based on provider dataset, sanitized request identity, payload checksum, and retrieval event as appropriate. Repeated identical responses may share a stored payload, but every processing run retains an auditable association to the fetched content.

### 7.3 Versioned observation tables

Use stable logical observation rows plus immutable version rows:

```text
fx_observation                 fx_observation_version
- id                           - id
- fx_series_id                 - observation_id
- observation_date            - version_number
- current_version_id --------> - value
                               - provider publication time
                               - retrieved_at / first_observed_at
                               - last_observed_at
                               - raw_record_id / ingestion_run_id
                               - validation status and flags
                               - valid_from / valid_to

interest_rate_observation      interest_rate_observation_version
- id                           - equivalent version fields
- series_id                    - explicit unit and source attributes
- observation_date
- current_version_id --------> ...
```

Natural keys are:

- FX: `(fx_series_id, observation_date)`;
- interest rate: `(interest_rate_series_id, observation_date)`.

Within each observation, a version fingerprint covers the normalized value and interpretation-relevant source fields. The pair `(observation_id, version_fingerprint)` is unique. Exactly one version is current, enforced through a partial unique constraint or transactionally maintained current pointer. `first_observed_at` and `last_observed_at` describe when the platform knew a version; `valid_from` and `valid_to` provide explicit knowledge-time intervals for as-of queries.

Observation versions are immutable except for `last_observed_at`, `valid_to`, and the current marker. Revisions insert a new version and close the previous version in one transaction. Later reappearance of a historical value still creates the correct knowledge timeline rather than rewriting history.

## 8. Ingestion Flow

### 8.1 Common pipeline

1. Accept a scheduled, manual, retry, or backfill request with provider, dataset, and bounded dates.
2. Validate the request and create an `ingestion_run` in `running` state.
3. Acquire a PostgreSQL advisory lock derived from provider, dataset, and overlapping scope. Reject or defer a conflicting run.
4. Resolve enabled instruments and immutable effective configuration for the run.
5. Fetch bounded pages/series with timeouts, provider rate-limit handling, and bounded exponential backoff with jitter for transient errors.
6. Store each successful lossless raw response and sanitized request metadata before normalization.
7. Parse response records and create observation-level raw locators.
8. Map each record to a canonical pair or rate series.
9. Normalize values, dates, timestamps, units, flags, and source attributes.
10. Validate each candidate. Store unnormalizable records in quarantine; attach non-fatal warnings to valid candidates.
11. Upsert each valid candidate through the revision service as inserted, unchanged, or revised.
12. Evaluate completeness and freshness for the requested scope, accounting for calendars and publication cadence.
13. Commit independent logical batches and update run counters.
14. Mark the run `succeeded`, `partially_succeeded`, or `failed`, release the lock, and emit final structured metrics/logs.

An unexpected interruption leaves the run visibly `running`; recovery marks abandoned runs failed after a configured lease expires and safely retries their scopes. A retry never deletes existing valid records.

### 8.2 Bank of Canada specifics

- Request enabled Valet series through configurable observations endpoints in JSON format.
- Map each provider series to exactly one configured foreign-currency/CAD pair.
- Retain only published orientation; do not store reciprocal or non-CAD derived observations.
- Persist the value classification as a daily indicative average/reference rate.
- Retain provider metadata and status/quality flags when supplied.
- Treat dates excluded by the configured Canadian business calendar and explicit unpublished values as expected absence, not request failure.

### 8.3 BIS specifics

- Use filtered, bounded SDMX REST queries for normal runs and backfills.
- Allow bulk CSV/SDMX for initial or recovery backfills, but feed decoded records into the same mapper, validator, and revision service.
- Preserve all interpretation-relevant SDMX dimensions, attributes, status flags, dataset version, collection indicator, and series metadata.
- Store the canonical rate type as `policy_rate`, frequency as daily, and unit as percent per year with no tenor.
- Preserve BIS's published representative value for bands; do not construct upper/lower values.
- Determine unchanged rate, absent observation, and not-yet-released data from response semantics and configured release cadence rather than by forward-filling observations.

## 9. Validation and Data Quality

Validation produces machine-readable rule results with `error`, `warning`, or `info` severity.

### Blocking errors

- missing required identifiers, date, or value;
- numeric parse failure or non-finite value;
- unknown currency, pair, economy, or series mapping;
- invalid FX orientation or a non-positive FX value;
- referential-integrity failure; and
- internally inconsistent normalized/raw values.

Blocking records are quarantined and do not prevent valid records in the same batch from being stored.

### Non-blocking flags

- rate outside a configurable plausible range;
- statistically implausible movement;
- timestamp beyond configured future tolerance;
- stale series relative to release cadence;
- unexpected publication-date gap; and
- conflicting records for the same natural key within one response.

These candidates remain auditable and are not silently overwritten or discarded. Conflicts that cannot be deterministically resolved are quarantined rather than selected arbitrarily.

Completeness is calculated against an expectation model keyed by series, calendar, frequency, and release delay. A daily BIS observation date is not assumed to be available daily; checks distinguish observation frequency from publication cadence. Results include `complete`, `incomplete`, `stale`, `not_due`, and `unknown` states with explanatory details.

## 10. Idempotency and Revision Semantics

For each normalized candidate, the revision service locks or atomically creates the logical observation row and compares its fingerprint with the current version:

- **New natural key:** insert logical observation and version 1.
- **Same fingerprint:** do not insert a version; update `last_observed_at` and record the run-to-version association.
- **Different fingerprint:** close the current knowledge interval and insert a new current version.
- **Duplicate candidate in the same input:** process once when identical; quarantine or fail the scope when conflicting.

Database uniqueness constraints are the final concurrency guard. Serializable operations or row-level locks around a single natural key prevent two workers from creating competing current versions.

The platform distinguishes:

- `observation_date`: date the measurement represents;
- `provider_publication_timestamp`: when the provider says it was published, if supplied;
- `retrieved_at`: when this platform fetched it; and
- `valid_from` / `valid_to`: when this platform first and last considered that version current.

An as-of query selects the version whose knowledge interval contains the requested timestamp. It never selects a version first observed after that timestamp. When exact provider publication time is unavailable, the API documents that platform retrieval time is the conservative availability boundary.

## 11. API Design

The internal API is versioned under `/api/v1`. Dates use ISO 8601; timestamps include an offset and are returned in UTC. Collection endpoints use bounded pagination and deterministic ordering.

### 11.1 Observation endpoints

- `GET /api/v1/fx-observations?pair={base}/{quote}&start={date}&end={date}&as_of={timestamp}`
- `GET /api/v1/fx-observations/latest?pair={base}/{quote}&as_of={timestamp}`
- `GET /api/v1/policy-rates?currency={code}&economy={code}&series={key}&start={date}&end={date}&as_of={timestamp}`
- `GET /api/v1/policy-rates/latest?currency={code}&economy={code}&series={key}&as_of={timestamp}`

At least one identifying filter is required for rate history. `as_of` defaults to the current knowledge state; when supplied, the query returns only versions known at that timestamp. Responses include value and unit, observation/version IDs, current status, validation state and flags, provider identifiers, publication/retrieval timestamps, raw-record reference, and ingestion-run reference.

### 11.2 Operational endpoints

- `POST /api/v1/ingestion-runs` with provider, dataset, trigger type, and bounded date range; returns `202 Accepted` and a run ID.
- `GET /api/v1/ingestion-runs/{run_id}`
- `GET /api/v1/ingestion-runs?provider={provider}&status={status}`
- `GET /api/v1/data-quality?instrument={id}&start={date}&end={date}`
- `GET /api/v1/quarantine/counts?run_id={run_id}&reason={code}`

Raw payload download need not be exposed through the API. Access can remain an operator/database concern to limit accidental redistribution and must follow recorded provider license terms.

Errors use a consistent body containing a stable code, human-readable message, request correlation ID, and safe details. The API rejects unbounded date ranges and unknown identifiers.

## 12. Scheduling and Concurrency

- Bank of Canada ingestion runs after the expected 16:30 Eastern publication window on Canadian business days, with a configurable delay.
- BIS scheduling reflects its generally weekly release cadence even though observations are daily; cadence remains configuration.
- Backfills are split into bounded provider-appropriate windows and use the same pipeline as incremental runs.
- PostgreSQL advisory locks coordinate overlapping scopes without adding infrastructure. Exact lock granularity and backfill chunk size are configurable.
- Retries apply only to transient network errors, rate limits, and selected 5xx responses. Parse, mapping, and validation failures are recorded without blind retry.
- Rate-limit headers and `Retry-After` are honored where available.

## 13. Observability and Operations

Structured JSON logs contain correlation ID, run ID, provider, dataset, series/pair, date scope, event, duration, outcome, and sanitized error code. Payloads, credentials, authorization headers, and full URLs containing secrets are excluded.

Metrics include:

- run duration and final status;
- request count, latency, retries, rate limits, and failures by provider;
- fetched, inserted, unchanged, revised, quarantined, and failed counts;
- last successful retrieval and latest valid observation by series;
- freshness/completeness state and gap counts; and
- active/contended ingestion scopes.

Phase 1 exposes these through application metrics, logs, and operational API responses. It sends no external alerts. Operator documentation will cover initial backfill, normal runs, retry, abandoned-run recovery, quarantine inspection, and restoration from backups.

## 14. Deployment and Security

Docker Compose defines at least:

- `api`: FastAPI application;
- `worker`: ingestion execution process;
- `scheduler`: provider-aware trigger process, if host scheduling is not used; and
- `db`: PostgreSQL with a persistent volume and health check.

Alembic owns schema changes. Containers run without embedded credentials and use environment variables for connection configuration. Separate least-privilege database roles should be used where practical: migrations own DDL, while the application role receives only required DML privileges. Provider and database connections use encrypted transport when leaving the local Compose network. The API binds locally by default and is not designed for public exposure.

Raw-data storage and API behavior must be reviewed against each provider's license before ingestion is enabled. License and attribution metadata are associated with the provider dataset.

## 15. Failure Handling

| Failure | Behavior |
|---|---|
| Provider timeout, rate limit, or transient 5xx | Retry with bounded backoff; retain request outcome; fail only affected scope after exhaustion |
| Permanent HTTP or authorization error | Do not retry blindly; mark affected scope failed with sanitized detail |
| Malformed individual record | Quarantine record and continue logical batch |
| Unparseable whole response | Retain raw response; fail affected scope without observation writes |
| Database error in a logical batch | Roll back that batch; retain earlier committed independent batches; run becomes partial or failed |
| Concurrent overlapping run | Reject with conflict or defer until lock is available; never process concurrently without coordination |
| Process interruption | Leave durable progress; expire run lease; retry safely through idempotent pipeline |
| Quality threshold breach | Store with flag when normalizable; never silently modify or discard |

## 16. Testing Strategy

- **Unit tests:** provider parsing/mapping, decimal and date normalization, fingerprinting, validation rules, calendar/release expectations, status aggregation, and as-of interval selection.
- **Contract/fixture tests:** representative Valet and BIS SDMX responses, including missing values, flags, revisions, bands, metadata changes, and malformed inputs. Normal tests use fixtures and mocked HTTP transport, never live APIs.
- **Repository integration tests:** PostgreSQL constraints, transactional batches, natural-key idempotency, concurrent revision insertion, immutable history, quarantine lineage, and point-in-time queries.
- **API tests:** filtering, pagination, latest/as-of semantics, provenance, validation output, bounded-run validation, and error contracts.
- **End-to-end tests:** mocked provider to raw retention, normalization, version storage, quality results, and API retrieval; repeat unchanged inputs and revised inputs.
- **Operational tests:** interrupted runs, expired leases, retry exhaustion, partial provider failure, and overlapping-run coordination.

Acceptance fixtures should demonstrate all Phase 1 acceptance criteria, including the configured nine foreign-currency/CAD FX series and available G10 BIS series. Performance tests should verify the 15-minute normal-run and two-second single-series/pair query design targets at a representative 20-year daily dataset size.

## 17. Requirements Traceability

| Requirement area | Design sections |
|---|---|
| Configuration and provider mappings (FR-1) | 6, 7.1 |
| FX and BIS ingestion (FR-2, FR-3) | 5.3, 8.2, 8.3 |
| Raw preservation (FR-4) | 7.2, 8.1 |
| Validation and quality (FR-5) | 9 |
| Idempotency and revisions (FR-6) | 7.3, 10 |
| Scheduling, manual runs, backfills (FR-7) | 5.1, 8.1, 12 |
| Run tracking and observability (FR-8) | 7.2, 13 |
| Data access and as-of behavior (FR-9) | 10, 11 |
| Reliability, security, audit, and compliance | 13, 14, 15 |
| Verification and acceptance | 16 |

## 18. Key Design Decisions and Deferred Choices

Decisions established by this design:

- Store canonical policy rates as percent per year with no tenor.
- Preserve provider observations only in their source orientation.
- Model revisions as immutable versions with knowledge-time intervals.
- Use retrieval time as the conservative as-of boundary when publication time is absent.
- Use PostgreSQL for both durable ingestion coordination and data storage in Phase 1.
- Quarantine normalization failures and flag plausible quality anomalies.

Implementation-level choices that may be resolved without changing the architecture include the scheduler package, metrics exposition library, exact raw-payload storage encoding, configuration file format, and backfill page sizes. If provider licenses prohibit retaining a response in its original encoding, the lossless-equivalent representation and its approval must be documented before implementation.
