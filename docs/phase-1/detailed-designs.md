# Phase 1 Detailed Component Design

## 1. Purpose

This document turns the Phase 1 requirements and high-level design into implementable component contracts. It defines package responsibilities, domain types, database structures, processing algorithms, API contracts, configuration, failure behavior, and component-level verification.

It remains technology-aligned with Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, `httpx`, `pytest`, and Docker Compose. Names are proposed implementation names; equivalent names are acceptable if their responsibilities and boundaries remain intact.

## 2. Package Structure

```text
app/
  api/
    dependencies.py
    errors.py
    routers/
      fx.py
      policy_rates.py
      ingestion_runs.py
      data_quality.py
  application/
    ingestion/
      orchestrator.py
      commands.py
      run_manager.py
      scope_coordinator.py
    queries/
      observations.py
      operations.py
    quality/
      service.py
      expectations.py
  domain/
    enums.py
    models.py
    candidates.py
    validation.py
    fingerprints.py
  providers/
    base.py
    bank_of_canada/
      client.py
      parser.py
      mapper.py
    bis/
      client.py
      parser.py
      mapper.py
  repositories/
    reference.py
    raw_data.py
    observations.py
    ingestion_runs.py
    quality.py
  database/
    base.py
    session.py
    models.py
  config/
    settings.py
    loader.py
  observability/
    logging.py
    metrics.py
  worker.py
  scheduler.py
  main.py
config/
  reference-data.yaml
  providers.yaml
  quality-rules.yaml
alembic/
tests/
  unit/
  integration/
  contract/
  api/
  fixtures/providers/
```

Dependencies point inward: API and entry points call application services; application services depend on domain contracts and repository/provider protocols; adapters implement those protocols. Domain modules do not import FastAPI, SQLAlchemy, `httpx`, or provider-specific schemas.

## 3. Shared Domain Types

### 3.1 Enumerations

Use string-backed enums so persisted and API values are stable.

| Enum | Values |
|---|---|
| `ProviderCode` | `bank_of_canada`, `bis` |
| `DatasetCode` | `valet_daily_fx`, `bis_policy_rates_daily` |
| `TriggerType` | `scheduled`, `manual`, `backfill`, `retry` |
| `RunStatus` | `pending`, `running`, `succeeded`, `partially_succeeded`, `failed` |
| `ScopeStatus` | `pending`, `running`, `succeeded`, `failed`, `skipped_conflict` |
| `CandidateOutcome` | `inserted`, `unchanged`, `revised`, `quarantined`, `failed` |
| `ValidationSeverity` | `info`, `warning`, `error` |
| `ValidationState` | `valid`, `valid_with_warnings`, `invalid` |
| `QualityState` | `complete`, `incomplete`, `stale`, `not_due`, `unknown` |
| `QuoteType` | `reference` |
| `RateType` | `policy_rate` |
| `CanonicalRateUnit` | `percent_per_year` |
| `Frequency` | `daily` |

Database check constraints should mirror enum values. Adding a value requires an Alembic migration when implemented as a PostgreSQL enum; string columns plus check constraints are preferred for simpler migrations.

### 3.2 Value objects

```python
@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

@dataclass(frozen=True)
class RequestMetadata:
    method: str
    endpoint_name: str
    sanitized_parameters: Mapping[str, str | list[str]]

@dataclass(frozen=True)
class RawPayload:
    body: bytes
    media_type: str
    response_status: int
    retrieved_at: datetime
    request: RequestMetadata
    response_metadata: Mapping[str, JSONValue]

@dataclass(frozen=True)
class SourceLocator:
    raw_response_id: UUID
    record_path: str
    record_checksum: str | None
```

`DateRange` validates `start <= end`. All `datetime` values must be timezone-aware and converted to UTC at persistence boundaries. Provider-local timestamp strings and their original timezone/offset remain in source metadata.

### 3.3 Normalized candidates

```python
@dataclass(frozen=True)
class FxObservationCandidate:
    series_id: UUID
    observation_date: date
    value: Decimal
    quote_type: QuoteType
    provider_publication_timestamp: datetime | None
    provider_attributes: Mapping[str, JSONValue]
    source: SourceLocator

@dataclass(frozen=True)
class PolicyRateCandidate:
    series_id: UUID
    observation_date: date
    value: Decimal
    unit: CanonicalRateUnit
    frequency: Frequency
    rate_type: RateType
    tenor: None
    provider_publication_timestamp: datetime | None
    provider_attributes: Mapping[str, JSONValue]
    source: SourceLocator
```

Candidates represent successfully parsed and mapped records, not necessarily valid records. Validation results accompany candidates into persistence. Provider-specific fields remain in `provider_attributes`; interpretation-critical identifiers also have canonical columns in reference tables.

## 4. Configuration Component

### 4.1 Responsibilities

- Load environment settings and declarative non-secret configuration.
- Validate references and provider mappings before the application becomes ready.
- Synchronize configured reference data into PostgreSQL without destructive deletion.
- Produce a deterministic checksum of effective non-secret configuration.
- Provide typed runtime settings to clients, scheduling, validation, and quality services.

### 4.2 Inputs and precedence

1. Version-controlled YAML files define currencies, economies, pairs, series, calendars, provider paths, and quality rules.
2. Environment variables override deployment settings such as database URL, log level, provider base URL, timeout, and scheduler enablement.
3. Secrets may only come from environment variables or mounted secrets.

Unknown configuration keys fail startup. Missing mappings for enabled series fail readiness. The checksum is generated from a canonical JSON serialization after environment-independent configuration is resolved; secret values are excluded.

### 4.3 Reference synchronization

`ReferenceDataService.sync(configuration)` performs transactional upserts by stable business key. It may update names, metadata, and enabled flags, but it must not delete rows referenced by observations. Removing an item from configuration disables it or requires an explicit migration.

Validation rules include:

- ISO currency codes are exactly three uppercase letters and exist in configured currency references;
- FX base and quote differ;
- enabled Bank of Canada FX pairs have CAD as quote currency;
- provider symbols are unique within a dataset;
- BIS series maps to one economy and one currency for its effective period;
- daily frequency and canonical units match Phase 1 semantics; and
- date ranges do not overlap for a given economy/currency mapping.

### 4.4 Tests

- valid configuration produces stable typed objects and checksum;
- ordering changes do not change the checksum;
- unknown currencies, duplicate symbols, invalid pairs, and missing mappings fail clearly;
- synchronization is idempotent and never deletes referenced records;
- secrets are absent from checksum and diagnostic output.

## 5. Database Component

### 5.1 Conventions

- UUID primary keys generated by the application or PostgreSQL.
- `TIMESTAMPTZ` for instants and `DATE` for observation dates.
- `NUMERIC(24, 12)` for FX and rate values; precision may be widened by migration if provider data requires it.
- `JSONB` only for variable provider metadata and structured diagnostics, not fields needed for routine filtering or integrity.
- `created_at` and `updated_at` on mutable operational/reference rows.
- UTC enforced in the database session.
- Foreign keys use restrictive deletion for auditable data.

### 5.2 Reference schema

#### `currency`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `code` | CHAR(3) | unique, uppercase |
| `name` | TEXT | non-empty |
| `minor_units` | SMALLINT | nullable, non-negative |
| `is_active` | BOOLEAN | default true |

#### `economy`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `code` | TEXT | unique, stable internal identifier |
| `iso_country_code` | CHAR(2) | nullable; ISO country code where applicable |
| `name` | TEXT | non-empty |
| `time_zone` | TEXT | valid IANA time-zone identifier |
| `economy_type` | TEXT | `country` or `currency_union` |
| `is_active` | BOOLEAN | default true |

#### `economy_currency`

| Column | Type | Rules |
|---|---|---|
| `economy_id` | UUID | foreign key to `economy`; part of primary key |
| `currency_id` | UUID | foreign key to `currency`; part of primary key |
| `effective_from` | DATE | part of primary key |
| `effective_to` | DATE | nullable; must not precede `effective_from` |

An exclusion constraint or service validation prevents overlapping duplicate relationships.

#### `fx_pair`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `base_currency_id` | UUID | foreign key to `currency` |
| `quote_currency_id` | UUID | foreign key to `currency`; must differ from base |
| `symbol` | TEXT | unique canonical symbol |
| `is_active` | BOOLEAN | default true |

The pair `(base_currency_id, quote_currency_id)` is unique.

#### `provider_dataset`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `provider_code` | TEXT | provider enum; unique with `dataset_code` |
| `dataset_code` | TEXT | dataset enum; unique with `provider_code` |
| `display_name` | TEXT | non-empty |
| `configuration_reference` | TEXT | identifies declarative source configuration |
| `license_url` | TEXT | nullable |
| `license_notes` | TEXT | nullable |
| `attribution_text` | TEXT | nullable |
| `redistribution_restrictions` | TEXT | nullable |
| `approval_state` | TEXT | must permit intended use before ingestion |
| `is_active` | BOOLEAN | default true |

#### `fx_series`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `provider_dataset_id` | UUID | foreign key to `provider_dataset` |
| `provider_symbol` | TEXT | unique within provider dataset |
| `fx_pair_id` | UUID | foreign key to `fx_pair` |
| `frequency` | TEXT | `daily` in Phase 1 |
| `quote_type` | TEXT | `reference` in Phase 1 |
| `source_metadata` | JSONB | provider metadata not used as relational keys |
| `is_active` | BOOLEAN | default true |

#### `interest_rate_series`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `provider_dataset_id` | UUID | foreign key to `provider_dataset` |
| `economy_id` | UUID | foreign key to `economy` |
| `currency_id` | UUID | foreign key to `currency` |
| `dataflow_key` | TEXT | BIS dataflow identifier |
| `series_key` | TEXT | unique with dataset and dataflow key |
| `frequency` | TEXT | `daily` in Phase 1 |
| `unit` | TEXT | `percent_per_year` canonically |
| `rate_type` | TEXT | `policy_rate` |
| `collection_indicator` | TEXT | BIS collection classification |
| `title` | TEXT | non-empty |
| `notes` | TEXT | nullable source notes |
| `source_metadata` | JSONB | SDMX/source metadata |
| `publication_metadata` | JSONB | release and publication details |
| `is_active` | BOOLEAN | default true |

`tenor` is deliberately absent in Phase 1 because a BIS policy rate is not a matched-tenor funding rate.

### 5.3 Run and attempt schema

#### `ingestion_run`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | public run identifier |
| `trigger_type` | TEXT | enum constraint |
| `provider_dataset_id` | UUID | requested dataset |
| `requested_start` | DATE | inclusive range start |
| `requested_end` | DATE | inclusive range end; not before start |
| `status` | TEXT | run status |
| `config_checksum` | TEXT | effective non-secret configuration checksum |
| `code_version` | TEXT | application/source version |
| `requested_at` | TIMESTAMPTZ | required UTC request time |
| `started_at` | TIMESTAMPTZ | nullable UTC start time |
| `finished_at` | TIMESTAMPTZ | nullable UTC completion time |
| `heartbeat_at` | TIMESTAMPTZ | abandoned-run detection |
| `fetched_count` | BIGINT | non-negative, default zero |
| `inserted_count` | BIGINT | non-negative, default zero |
| `unchanged_count` | BIGINT | non-negative, default zero |
| `revised_count` | BIGINT | non-negative, default zero |
| `quarantined_count` | BIGINT | non-negative, default zero |
| `failed_count` | BIGINT | non-negative, default zero |
| `error_code` | TEXT | sanitized, nullable |
| `error_summary` | TEXT | sanitized, nullable |

Counts start at zero and never become negative. Terminal runs have `finished_at`; `running` runs have `started_at` and heartbeat.

#### `ingestion_scope`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `run_id` | UUID | foreign key to `ingestion_run` |
| `scope_type` | TEXT | identifies FX or policy-rate scope |
| `series_id` | UUID | canonical series identifier |
| `start_date` | DATE | inclusive chunk start |
| `end_date` | DATE | inclusive chunk end; not before start |
| `attempt_number` | INTEGER | positive |
| `status` | TEXT | scope-status enum constraint |
| `started_at` | TIMESTAMPTZ | nullable UTC start time |
| `finished_at` | TIMESTAMPTZ | nullable UTC completion time |
| `fetched_count` | BIGINT | non-negative, default zero |
| `inserted_count` | BIGINT | non-negative, default zero |
| `unchanged_count` | BIGINT | non-negative, default zero |
| `revised_count` | BIGINT | non-negative, default zero |
| `quarantined_count` | BIGINT | non-negative, default zero |
| `failed_count` | BIGINT | non-negative, default zero |
| `last_http_status` | INTEGER | nullable |
| `retry_count` | INTEGER | non-negative, default zero |
| `error_code` | TEXT | sanitized, nullable |
| `error_details` | JSONB | sanitized, nullable |

The tuple `(run_id, scope_type, series_id, start_date, end_date, attempt_number)` is unique.

Operational errors belong here or on the run. They do not create observation versions.

### 5.4 Raw and lineage schema

#### `raw_response`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `run_id` | UUID | foreign key to `ingestion_run` |
| `scope_id` | UUID | foreign key to `ingestion_scope` |
| `provider_dataset_id` | UUID | foreign key to `provider_dataset` |
| `request_method` | TEXT | expected `GET` for Phase 1 providers |
| `endpoint_name` | TEXT | logical endpoint, not a secret-bearing URL |
| `request_parameters` | JSONB | allowlisted and sanitized |
| `response_status` | INTEGER | HTTP status |
| `media_type` | TEXT | provider response content type |
| `retrieved_at` | TIMESTAMPTZ | UTC |
| `payload_checksum` | CHAR(64) | SHA-256 of exact response bytes |
| `body` | BYTEA | lossless provider response |
| `body_size` | BIGINT | non-negative and bounded |
| `content_encoding` | TEXT | nullable; explicit compression/encoding |
| `response_metadata` | JSONB | allowlisted safe metadata |

A check limits successful persisted provider bodies to the configured maximum size.

The original byte body is the default lossless representation. Compression may be added transparently with explicit `content_encoding`. Authorization/cookie headers and secrets are never accepted by the repository.

#### `raw_record`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `raw_response_id` | UUID | foreign key to `raw_response` |
| `record_path` | TEXT | deterministic locator within payload |
| `provider_natural_key` | TEXT | nullable |
| `record_checksum` | CHAR(64) | nullable SHA-256 |
| `source_metadata` | JSONB | compact record-level metadata |

The tuple `(raw_response_id, record_path)` is unique. The path is stable for a given payload, for example `observations[2026-09-01].FXUSDCAD` or an SDMX series/observation index.

#### `observation_version_run`

| Column | Type | Rules |
|---|---|---|
| `observation_version_id` | UUID | foreign key to the applicable version table |
| `ingestion_run_id` | UUID | foreign key to `ingestion_run` |
| `raw_record_id` | UUID | foreign key to `raw_record` |
| `observed_at` | TIMESTAMPTZ | UTC observation time |

The tuple `(observation_version_id, ingestion_run_id, raw_record_id)` is unique. In implementation, separate FX and policy-rate lineage tables may be used to retain enforceable foreign keys.

### 5.5 Observation schema

FX and policy rates use separate tables to retain clear semantics.

#### `fx_observation`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `fx_series_id` | UUID | foreign key to `fx_series` |
| `observation_date` | DATE | provider observation date |
| `current_version_id` | UUID | foreign key to current `fx_observation_version` |

The tuple `(fx_series_id, observation_date)` is unique.

#### `policy_rate_observation`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `interest_rate_series_id` | UUID | foreign key to `interest_rate_series` |
| `observation_date` | DATE | provider observation date |
| `current_version_id` | UUID | foreign key to current `policy_rate_observation_version` |

The tuple `(interest_rate_series_id, observation_date)` is unique.

#### `fx_observation_version`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `observation_id` | UUID | foreign key to `fx_observation` |
| `version_number` | INTEGER | positive; unique within observation |
| `value` | NUMERIC(24, 12) | strictly positive |
| `quote_type` | TEXT | `reference` |
| `version_fingerprint` | CHAR(64) | SHA-256 canonical fingerprint |
| `provider_publication_timestamp` | TIMESTAMPTZ | nullable |
| `first_observed_at` | TIMESTAMPTZ | UTC first knowledge time |
| `last_observed_at` | TIMESTAMPTZ | UTC most recent time this version was observed |
| `valid_from` | TIMESTAMPTZ | inclusive knowledge-interval start |
| `valid_to` | TIMESTAMPTZ | nullable, exclusive knowledge-interval end |
| `validation_state` | TEXT | validation-state enum constraint |
| `validation_flags` | JSONB | structured issues and warnings |
| `provider_attributes` | JSONB | interpretation-relevant source snapshot |
| `originating_raw_record_id` | UUID | foreign key to `raw_record` |
| `originating_ingestion_run_id` | UUID | foreign key to `ingestion_run` |

#### `policy_rate_observation_version`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `observation_id` | UUID | foreign key to `policy_rate_observation` |
| `version_number` | INTEGER | positive; unique within observation |
| `value` | NUMERIC(24, 12) | exact canonical value |
| `unit` | TEXT | `percent_per_year` |
| `frequency` | TEXT | `daily` |
| `rate_type` | TEXT | `policy_rate` |
| `collection_indicator` | TEXT | source classification snapshot |
| `dataset_version` | TEXT | nullable provider dataset version |
| `version_fingerprint` | CHAR(64) | SHA-256 canonical fingerprint |
| `provider_publication_timestamp` | TIMESTAMPTZ | nullable |
| `first_observed_at` | TIMESTAMPTZ | UTC first knowledge time |
| `last_observed_at` | TIMESTAMPTZ | UTC most recent time this version was observed |
| `valid_from` | TIMESTAMPTZ | inclusive knowledge-interval start |
| `valid_to` | TIMESTAMPTZ | nullable, exclusive knowledge-interval end |
| `validation_state` | TEXT | validation-state enum constraint |
| `validation_flags` | JSONB | structured issues and warnings |
| `provider_attributes` | JSONB | SDMX and interpretation snapshot |
| `originating_raw_record_id` | UUID | foreign key to `raw_record` |
| `originating_ingestion_run_id` | UUID | foreign key to `ingestion_run` |

The version snapshots prevent later reference-metadata edits from changing historical interpretation.

Constraints and indexes:

- unique `(observation_id, version_number)`;
- unique `(observation_id, version_fingerprint, valid_from)` to allow a previously seen value to become current again;
- partial unique index on `observation_id WHERE valid_to IS NULL`;
- `valid_to IS NULL OR valid_to > valid_from`;
- FX value greater than zero;
- B-tree indexes on `(series_id, observation_date)` via logical tables;
- version indexes on `(observation_id, valid_from, valid_to)`; and
- index on `first_observed_at` for audit queries.

The logical row's `current_version_id` is a convenience pointer validated to reference an open version belonging to that observation.

### 5.6 Quarantine and quality schema

#### `quarantined_record`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `run_id` | UUID | foreign key to `ingestion_run` |
| `scope_id` | UUID | foreign key to `ingestion_scope` |
| `raw_record_id` | UUID | foreign key to `raw_record` |
| `provider_natural_key` | TEXT | nullable |
| `reason_code` | TEXT | machine-readable reason |
| `stage` | TEXT | `parse`, `map`, `normalize`, `validate`, or `conflict` |
| `details` | JSONB | sanitized diagnostic details |
| `created_at` | TIMESTAMPTZ | UTC creation time |
| `updated_at` | TIMESTAMPTZ | UTC last update time |
| `resolution_state` | TEXT | review/resolution status |

Raw provider content is referenced, not duplicated into logs or error fields.

#### `quality_result`

| Column | Type | Rules |
|---|---|---|
| `id` | UUID | primary key |
| `run_id` | UUID | nullable foreign key to `ingestion_run` |
| `instrument_type` | TEXT | FX pair or policy-rate series |
| `instrument_id` | UUID | canonical instrument identifier |
| `rule_code` | TEXT | machine-readable quality rule |
| `quality_state` | TEXT | quality-state enum constraint |
| `severity` | TEXT | validation-severity enum constraint |
| `affected_start` | DATE | inclusive affected range start |
| `affected_end` | DATE | inclusive affected range end |
| `evaluated_at` | TIMESTAMPTZ | UTC |
| `details` | JSONB | structured quality evidence |

Index by instrument and evaluation time. Results are append-only audit snapshots; current quality is the newest result per rule and instrument.

### 5.7 Migration order

1. Enable required PostgreSQL extensions, if any.
2. Create reference tables.
3. Create run, scope, raw, and quarantine tables.
4. Create logical observation and version tables, then add deferred current-version foreign keys.
5. Create lineage and quality tables.
6. Add indexes and constraints.
7. Seed reference data through the application synchronization command, not migration hard-coding.

## 6. Provider Adapter Contract

### 6.1 Protocols

```python
class ProviderClient(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...

class ProviderParser(Protocol[ProviderRecordT]):
    def parse(self, payload: RawPayload) -> Iterable[ParsedRecord[ProviderRecordT]]: ...

class ProviderMapper(Protocol[ProviderRecordT, CandidateT]):
    def map(
        self,
        record: ProviderRecordT,
        source: SourceLocator,
        mappings: ReferenceSnapshot,
    ) -> CandidateT | PublishedAbsence: ...
```

`FetchRequest` contains explicit dataset/instrument selection and inclusive bounded dates. `FetchResult` contains the raw payload plus rate-limit/retry metadata. HTTP success with no published observations is a successful fetch, distinct from transport or parse failure.

Provider adapters raise typed exceptions: `TransientProviderError`, `PermanentProviderError`, `PayloadTooLargeError`, `ProviderParseError`, and `ProviderContractError`. Exceptions contain safe context and never embed full response bodies.

### 6.2 HTTP behavior

- A shared `httpx.AsyncClient` has connection pooling and explicit connect/read/write/pool timeouts.
- Only HTTPS provider base URLs are accepted outside tests.
- Redirects are disabled or restricted to the provider's configured HTTPS hosts.
- Retryable conditions are connection/timeouts, HTTP 429, and configured 5xx statuses.
- `Retry-After` takes priority; otherwise use exponential backoff with jitter and configured maximum attempts/elapsed time.
- 4xx responses other than 408/429 are permanent unless provider documentation states otherwise.
- Response size is bounded before buffering and persistence.

## 7. Bank of Canada Components

### 7.1 Valet client

The client groups enabled series only when the configured endpoint supports a multi-series query. It builds bounded requests from endpoint templates and series identifiers, requests JSON, and records a logical endpoint name plus sanitized query parameters. Business logic never constructs Valet paths.

Inputs: enabled `fx_series` snapshot and `DateRange`. Output: one or more `FetchResult` objects. A successful empty response remains successful.

### 7.2 Valet parser

The parser:

1. verifies the top-level JSON shape and configured response contract;
2. extracts response metadata and series details without discarding unknown safe fields;
3. iterates dated observations in source order;
4. emits one provider record per date/series value with a stable raw path;
5. represents explicit null/unpublished values as a typed absence; and
6. reports record-local malformed content separately from a response-wide contract failure.

Decimal values are parsed directly from source strings using `Decimal`, never through binary floating point.

### 7.3 Valet mapper

The mapper resolves the provider symbol to exactly one enabled `fx_series`. It confirms that the pair's quote currency is CAD and produces an `FxObservationCandidate` with quote type `reference`. It carries all available status/quality flags and source metadata. It never reciprocates a rate or creates a cross rate.

### 7.4 Absence handling

- Configured Canadian non-business day: `not_due`; no quarantine or failed count.
- Business day with explicit provider null/unpublished marker: published absence and potential completeness result, not request failure.
- Successful bounded response omitting an expected due date: incompleteness candidate.
- Missing/unknown series mapping: quarantine with `UNKNOWN_PROVIDER_SERIES`.
- Invalid response structure affecting all records: failed scope with `PROVIDER_PARSE_ERROR`.

## 8. BIS Components

### 8.1 SDMX client

The client builds filtered requests from configured dataflow and series keys. Routine and bounded backfill requests use SDMX REST. Bulk files are accepted only through a separate fetch method that returns the same `RawPayload` abstraction and feeds the same parser/mapping pipeline.

The client requests a configured supported media type, records content type and dataset-version response metadata, and splits date ranges or series sets to remain inside provider limits.

### 8.2 SDMX parser

The parser must not infer dimension order. It reads SDMX structure metadata or a versioned configured schema and maps dimension names to positions. For each series and observation it emits:

- dataflow and full series key;
- economy and currency/source codes;
- frequency, unit, collection indicator, and instrument attributes;
- observation date and exact decimal value;
- observation/series status attributes;
- dataset version and publication timestamp when provided; and
- a deterministic raw record path.

Unknown dimensions and attributes are preserved. Missing required dimensions fail the affected record or response depending on whether the schema can still be traversed deterministically.

### 8.3 BIS mapper and normalizer

The mapper resolves the complete configured series key, not only economy code. It validates the associated economy/currency relationship on the observation date. Supported values are normalized to `percent_per_year`; conversion is explicit and deterministic if BIS supplies an equivalent supported percentage scale. Unsupported units are quarantined rather than guessed.

It sets `rate_type=policy_rate`, `frequency=daily`, and `tenor=None`. Instrument classification, collection indicator, bands/midpoint notes, status flags, breaks, and source notes remain in the version snapshot. It persists the exact representative value BIS publishes and never manufactures corridor bounds.

### 8.4 BIS absence handling

No forward-filled observations are created. The quality service considers both daily observation semantics and configured weekly publication cadence:

- unchanged published value is a real observation and can be persisted normally;
- no due release is `not_due`;
- due release without an expected observation is `incomplete`;
- absence explicitly represented by SDMX is recorded as published absence/quality evidence; and
- request or parsing failure remains a scope failure.

## 9. Raw Data Service

`RawDataService.store_response(run_id, scope_id, fetch_result)` computes SHA-256 over the exact response bytes, sanitizes request parameters and response metadata through an allowlist, and stores the payload before parsing begins. It then returns `raw_response_id`.

`create_record_locator(raw_response_id, path, natural_key, bytes_or_canonical_fragment)` creates or returns an idempotent `raw_record`. A parser need not duplicate record bodies when the path identifies the exact content within the retained response.

Persistence failure stops processing of that response because normalized data without raw lineage is prohibited. Phase 1 has no automatic raw-data deletion job.

## 10. Normalization and Fingerprint Components

### 10.1 Normalization

Normalization is deterministic for the same raw input and configuration checksum:

- trim identifiers and apply configured case normalization;
- parse dates according to provider format with no implicit local-date conversion;
- parse numbers with `Decimal` and reject NaN/infinity;
- normalize timestamps to UTC while retaining original text/offset in attributes;
- emit explicit canonical unit/frequency/type values; and
- preserve source flags and interpretation metadata.

No statistical cleaning, interpolation, forward filling, reciprocal calculation, or value rounding occurs.

### 10.2 Fingerprints

The version fingerprint is SHA-256 of canonical JSON containing only fields whose change alters the observation's value or interpretation.

FX fingerprint fields: series stable key, observation date, canonical decimal string, quote type, provider publication timestamp when supplied, and interpretation/status attributes.

Policy-rate fields: series stable key, observation date, canonical decimal string, unit, frequency, rate type, collection/instrument attributes, dataset version when interpretation-relevant, provider publication timestamp, and status/break attributes.

Excluded fields include retrieval time, run ID, raw-response ID, HTTP headers, and record order. Decimal canonicalization uses a non-exponent string with insignificant trailing zeros removed, so `5.25` and `5.250` do not create revisions. Attribute objects are recursively key-sorted.

## 11. Validation Component

### 11.1 Contract

```python
@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    field: str | None
    details: Mapping[str, JSONValue]

@dataclass(frozen=True)
class ValidationResult:
    state: ValidationState
    issues: tuple[ValidationIssue, ...]
```

Validators are pure functions where possible. Error severity yields `invalid` and quarantine. Warnings yield `valid_with_warnings` and permit storage. Details contain safe values and thresholds, never entire raw records.

### 11.2 Common rules

| Code | Severity | Condition |
|---|---|---|
| `MISSING_REQUIRED_FIELD` | error | required identifier/date/value absent |
| `INVALID_NUMERIC_VALUE` | error | cannot parse or is non-finite |
| `UNKNOWN_REFERENCE` | error | mapping cannot resolve canonical entity |
| `INVALID_OBSERVATION_DATE` | error | invalid or beyond allowed future tolerance |
| `RAW_NORMALIZED_MISMATCH` | error | normalized value cannot be traced to raw field |
| `DUPLICATE_INPUT_IDENTICAL` | info | same natural key/fingerprint in one payload |
| `DUPLICATE_INPUT_CONFLICT` | error | same natural key with different fingerprints in one payload |

FX adds `FX_NON_POSITIVE` and `FX_INVALID_ORIENTATION` as errors, plus configurable movement/range warnings. Policy rates add `UNSUPPORTED_RATE_UNIT` as an error and configurable plausible-range/break warnings.

Statistical anomaly detection uses only observations available before the candidate's retrieval time. A simple configurable percentage/absolute-change threshold is sufficient for Phase 1; it flags values but never rejects or revises them automatically.

## 12. Revision Persistence Component

### 12.1 Contract

`ObservationRevisionService.persist(candidate, validation, run_context) -> CandidateOutcome`

Invalid candidates are never passed to this service. FX and policy-rate repositories implement a shared revision algorithm while writing type-specific tables.

### 12.2 Algorithm

Within one database transaction:

1. Insert the logical observation by natural key with conflict ignored.
2. Select the logical row and current version `FOR UPDATE`.
3. Compute the candidate fingerprint before persistence.
4. If no current version exists, insert version 1 with `valid_from=retrieved_at`, set the current pointer, and return `inserted`.
5. If the current fingerprint matches, set `last_observed_at=max(existing, retrieved_at)`, add `observation_version_run`, and return `unchanged`.
6. If it differs, set current `valid_to=retrieved_at`, insert the next version with open interval, update current pointer, add lineage, and return `revised`.
7. Commit; uniqueness constraints guard races.

If `retrieved_at` precedes the current version's `valid_from`, the candidate is an out-of-order processing event. Do not corrupt intervals: serialize raw fetches per scope, or route the candidate to an explicit interval-rebuild method tested for this case. The normal worker processes responses in retrieval order.

A source reverting to an earlier value creates a new timeline version because it became current again at a new knowledge time. Failures, missing data, and quarantined records never create versions.

### 12.3 As-of selection

Current query: select the logical current pointer.

As-of query: join a version where `valid_from <= :as_of` and (`valid_to > :as_of` or `valid_to IS NULL`). Use a half-open interval `[valid_from, valid_to)`. Additionally require `observation_date <= date(:as_of)` so future observations cannot appear.

The latest endpoint orders eligible observations by observation date descending, then provider publication timestamp and retrieval time descending, and returns one. By default, invalid versions cannot exist; warnings are returned with the valid version.

## 13. Ingestion Orchestrator

### 13.1 Command

```python
@dataclass(frozen=True)
class StartIngestionCommand:
    provider: ProviderCode
    dataset: DatasetCode
    trigger_type: TriggerType
    date_range: DateRange
    requested_series: tuple[str, ...] | None
    parent_run_id: UUID | None = None
```

The command validator enforces configured maximum range, allowed provider/dataset pairing, enabled license approval, and known requested series. Scheduled commands are generated with the same type.

### 13.2 Durable execution

1. API/CLI creates a `pending` run and commits it.
2. Worker atomically claims a pending run using `FOR UPDATE SKIP LOCKED`, changes it to `running`, and starts heartbeat updates.
3. Planner snapshots enabled configuration and creates bounded scopes.
4. Worker acquires a dataset/series/date coordination lock for each scope.
5. The provider pipeline executes and persists raw data, candidates, outcomes, and quality results.
6. Scope counters are written transactionally after each batch.
7. Run manager derives final counts from scopes and transitions to a terminal state.

PostgreSQL polling is acceptable at Phase 1 scale and avoids a message broker. The API process never performs the long-running fetch inline.

### 13.3 State transitions

```text
pending -> running -> succeeded
                   -> partially_succeeded
                   -> failed
```

Terminal states cannot return to running. A retry creates a new run linked by `parent_run_id`; it does not mutate the historical failed run.

Final status rules:

- `succeeded`: all scopes succeed, even if no observations were due;
- `partially_succeeded`: at least one scope succeeds and at least one fails;
- `failed`: all executable scopes fail, or setup/licensing/configuration prevents execution.

Quarantined individual records contribute to counts but make a run partial only if policy config declares the blocking-error ratio or critical-series condition exceeded. Otherwise the run may succeed with visible quarantine counts.

### 13.4 Coordination locks

Before work, query active scopes for overlapping provider dataset, series, and dates. Then acquire a transaction/session PostgreSQL advisory lock computed from the stable dataset and series key. Because a single advisory key cannot express arbitrary range overlap, active-scope overlap is the semantic check and the advisory lock serializes the check/claim per series.

Conflict behavior:

- manual API request returns `409` if an equivalent/overlapping active run already exists;
- scheduled runs skip the conflicting scope and record it;
- backfill may wait up to a configured short timeout, then records `skipped_conflict` for retry.

## 14. Completeness and Freshness Component

### 14.1 Expectation model

An `ExpectationPolicy` contains instrument ID, observation frequency, calendar ID, publication timezone, expected publication time, publication weekdays/cadence, grace period, and effective dates.

Calendar data is declarative and versioned. Phase 1 may use configured Canadian business holidays and provider release weekday rules; it must not assume every weekday is due for every provider.

### 14.2 Evaluation

For a requested date range:

1. Generate expected observation dates.
2. Apply non-business days and release cadence.
3. Determine whether each date is due at evaluation time, including grace period.
4. Compare against valid observation versions known at evaluation time.
5. emit missing dates/count, newest expected date, newest available date, and state.

Freshness is based on the newest due observation/release, not simply elapsed wall-clock time from the latest observation. Output rules:

- `not_due`: no expected publication is due;
- `complete`: all due observations are present;
- `incomplete`: one or more due observations are absent;
- `stale`: latest due period exceeds freshness threshold;
- `unknown`: schedule/calendar or successful-fetch evidence is insufficient.

Quality evaluation failure does not roll back valid observations. It records an operational error and yields `unknown`.

## 15. Repository Interfaces and Transactions

Repositories expose domain-oriented methods and receive an explicit SQLAlchemy `AsyncSession` or unit of work. They never commit independently when participating in a service transaction.

Core protocols:

```python
class IngestionRunRepository(Protocol):
    async def create(self, command: StartIngestionCommand, context: RunContext) -> IngestionRun: ...
    async def claim_next(self, worker_id: str) -> IngestionRun | None: ...
    async def heartbeat(self, run_id: UUID, now: datetime) -> None: ...
    async def finalize(self, run_id: UUID, status: RunStatus) -> None: ...

class ObservationRepository(Protocol[CandidateT]):
    async def persist_revision(...) -> CandidateOutcome: ...
    async def list_history(...) -> Page[ObservationView]: ...
    async def latest(...) -> ObservationView | None: ...

class QualityRepository(Protocol):
    async def append_results(self, results: Sequence[QualityResult]) -> None: ...
    async def latest_by_instrument(...) -> Sequence[QualityResult]: ...
```

Transaction boundaries:

- run creation/claim/finalization: one transaction each;
- raw response persistence: committed before parsing normalized records;
- a bounded observation batch: raw record, candidate outcome, lineage, quarantine, and counter increment in one transaction;
- quality evaluation: one transaction per scope.

This permits safe partial progress while preserving record-level lineage.

## 16. Query Service

### 16.1 Query rules

- Require pair/series/economy/currency filters as specified by the endpoint.
- Require bounded history dates and enforce configurable maximum page size.
- Validate that `start <= end` and reject dates beyond allowed domain bounds.
- Default `as_of` to request time in UTC.
- Use keyset pagination based on `(observation_date, observation_id)` rather than offset for stable large histories.
- Order history ascending by observation date unless an explicit supported direction is provided.
- Return exact decimal values as JSON strings to avoid precision loss.

Filtering policy rates by multiple identifiers uses intersection semantics. Ambiguous currency-only latest queries that match multiple economies/series return a validation error requiring narrower selection rather than choosing arbitrarily.

### 16.2 Observation response

```json
{
  "observation_id": "uuid",
  "version_id": "uuid",
  "version_number": 2,
  "instrument": {"type": "fx_pair", "symbol": "USD/CAD"},
  "observation_date": "2026-09-01",
  "value": "1.347500000000",
  "unit": "CAD_per_USD",
  "classification": "reference",
  "provider": "bank_of_canada",
  "provider_series": "FXUSDCAD",
  "provider_publication_timestamp": null,
  "retrieved_at": "2026-09-01T20:35:00Z",
  "valid_from": "2026-09-01T20:35:00Z",
  "valid_to": null,
  "is_current": true,
  "validation": {"state": "valid", "flags": []},
  "provenance": {"run_id": "uuid", "raw_record_id": "uuid"}
}
```

For policy rates, `unit` is `percent_per_year`, `classification` is `policy_rate`, and `tenor` is explicitly null.

## 17. FastAPI Component

### 17.1 Routes

| Method and path | Validation and result |
|---|---|
| `GET /api/v1/fx-observations` | pair, inclusive dates, optional as-of/cursor; paged history |
| `GET /api/v1/fx-observations/latest` | pair and optional as-of; one observation or 404 |
| `GET /api/v1/policy-rates` | bounded dates plus identifying filters; paged history |
| `GET /api/v1/policy-rates/latest` | unambiguous identifying filters and optional as-of |
| `POST /api/v1/ingestion-runs` | bounded command; 202 with run resource; 409 on overlap |
| `GET /api/v1/ingestion-runs/{id}` | run, scopes, counts, sanitized errors |
| `GET /api/v1/ingestion-runs` | bounded filters and keyset pagination |
| `GET /api/v1/data-quality` | instrument and bounded range/current results |
| `GET /api/v1/quarantine/counts` | aggregate only, filtered by run/reason/stage |
| `GET /health/live` | process liveness only |
| `GET /health/ready` | database, config, migrations, and reference readiness |
| `GET /metrics` | local metrics endpoint if enabled |

### 17.2 Ingestion request

```json
{
  "provider": "bis",
  "dataset": "bis_policy_rates_daily",
  "trigger_type": "backfill",
  "start_date": "2025-09-01",
  "end_date": "2026-09-01",
  "series": ["configured-series-key"]
}
```

Clients cannot submit `scheduled` unless the request originates from the internal scheduler entry point. Manual HTTP requests use `manual` or `backfill` based on configured date-range policy.

### 17.3 Error contract

```json
{
  "error": {
    "code": "INVALID_DATE_RANGE",
    "message": "start_date must not be after end_date",
    "request_id": "uuid",
    "details": {"field": "start_date"}
  }
}
```

Map validation to 422, unknown resources to 404, overlap to 409, licensing/configuration unavailability to 503, and unexpected failures to 500. Unexpected responses expose no stack trace, SQL, payload, or secret.

The API binds to loopback by default. Authentication and public deployment are outside Phase 1.

## 18. Worker and Scheduler Components

### 18.1 Worker

The worker polls for pending runs at a bounded interval, claims one safely, executes scopes, and updates heartbeats. Graceful shutdown stops claiming new work and completes or safely releases the current transaction. Long provider operations update heartbeat between attempts/pages.

On startup, `RunRecoveryService` finds running runs with expired heartbeat leases, marks their active scopes and run failed with `WORKER_LEASE_EXPIRED`, and permits an operator/scheduler to create a linked retry. It never assumes the old run succeeded.

### 18.2 Scheduler

The scheduler is a thin command producer. Schedule rules live in configuration:

- Bank of Canada: Canadian business days after 16:30 America/Toronto plus grace delay;
- BIS: configured weekly release cadence plus grace delay.

Before creating a run, it checks for an active equivalent or a successful run covering the same effective scope. Duplicate scheduler triggers therefore do not create unnecessary work. Calendar decisions are logged with reason codes.

No external alerting is included.

## 19. Observability Component

### 19.1 Logging

Use structured JSON through a single configured logger. Middleware creates or accepts a safe request ID; run and scope context is bound during ingestion.

Required event names include `run_created`, `run_started`, `provider_request_completed`, `provider_retry`, `raw_response_stored`, `record_quarantined`, `observation_inserted`, `observation_revised`, `scope_completed`, `quality_evaluated`, and `run_completed`.

Routine unchanged observations should be aggregated rather than logged individually to control volume. A sanitization processor removes disallowed keys such as authorization, cookie, token, password, secret, and API key before output.

### 19.2 Metrics

Proposed names:

- `fx_analyzer_ingestion_runs_total{provider,dataset,status}`;
- `fx_analyzer_ingestion_run_duration_seconds{provider,dataset}`;
- `fx_analyzer_provider_requests_total{provider,outcome,status_class}`;
- `fx_analyzer_provider_request_duration_seconds{provider}`;
- `fx_analyzer_provider_retries_total{provider,reason}`;
- `fx_analyzer_observations_total{provider,outcome}`;
- `fx_analyzer_quarantined_records_total{provider,reason}`;
- `fx_analyzer_quality_state{instrument,state}`; and
- `fx_analyzer_worker_active_runs`.

Do not use run IDs, series keys, URLs, or dates as metric labels where they create unbounded cardinality. Detailed series health remains queryable in PostgreSQL/API.

## 20. Security and Compliance Components

- `Settings` uses secret-aware fields whose representations are redacted.
- Request metadata uses an allowlist rather than a denylist.
- Provider clients validate HTTPS and certificate verification is enabled.
- Database migrations use an owner role; application services use a DML-only role where practical.
- Compose publishes the API and database only to loopback by default; database publication may be omitted.
- Raw payload access is not exposed through Phase 1 API.
- Enabled datasets require recorded license approval, attribution, retention permission, and redistribution policy.
- Logs and quarantine details store record paths and reason codes, not full raw records.
- Dependency versions are pinned and container images use non-root users where supported.

## 21. Docker Compose and Runtime

Services:

| Service | Command/responsibility | Dependency |
|---|---|---|
| `db` | PostgreSQL with persistent named volume and health check | none |
| `migrate` | run Alembic upgrade and reference sync as explicit setup job | healthy db |
| `api` | FastAPI/ASGI query and operations API | migrated db |
| `worker` | durable ingestion worker | migrated db |
| `scheduler` | create scheduled run commands | migrated db |

The API, worker, and scheduler use the same application image and configuration. Health checks distinguish liveness from readiness. Restart policies may restart processes, while idempotent claims and lease recovery protect data integrity.

Required environment variables include `DATABASE_URL`; optional variables include log level, worker poll interval, lease timeout, provider timeout/retry settings, and schedule enablement. A checked-in `.env.example` contains no credentials.

## 22. Test Design by Component

### Configuration and reference data

- schema and cross-reference validation;
- deterministic checksum;
- idempotent synchronization and disabling behavior;
- license approval gate.

### Provider clients

- correct bounded parameters and configured paths;
- HTTPS, timeout, retry, `Retry-After`, size limit, and sanitized metadata;
- empty success versus HTTP failure.

### Parsers and mappers

- golden Valet and BIS fixtures;
- missing/null values and status flags;
- unknown series/dimensions and malformed record/response;
- exact decimal parsing, FX orientation, BIS unit/frequency/type, and metadata preservation;
- identical normalized output for identical input/configuration.

### Validation and quality

- every reason code and severity;
- boundary values and future tolerance;
- business holidays and publication grace periods;
- missing, stale, not-due, and unknown distinctions;
- anomaly flags never silently reject normalizable data.

### Revision service

- first insert, unchanged re-fetch, genuine revision, and value reversion;
- `observation_version_run` lineage for unchanged data;
- half-open as-of boundaries and absence of future revisions;
- concurrent inserts leave one current version;
- failures/quarantine never produce versions.

### Orchestrator and recovery

- all run state transitions and count aggregation;
- partial series failure preserves successful batches;
- overlapping scopes are coordinated;
- retry creates a linked new run;
- expired heartbeat recovery is safe;
- raw storage failure prevents canonical persistence.

### Repositories and API

- constraints against duplicate natural keys/current versions;
- query indexes exercised with representative volume;
- pagination stability;
- filters, decimal serialization, provenance, validation flags, and as-of responses;
- error status/body contracts and local health endpoints.

### Acceptance and performance

An end-to-end test loads representative responses for all configured G10 mappings through mocked HTTP, runs a 12-month backfill, repeats it unchanged, then changes one provider value. It verifies raw lineage, quarantine isolation, one added revision, current/as-of results, completeness/freshness, and run counters.

Generate a representative 20-year daily dataset to verify a typical single pair/series history query completes within two seconds under expected local single-user load. A scheduled incremental test verifies completion within the 15-minute design target excluding simulated provider delays.

The normal `pytest` suite never calls live provider APIs. Optional explicitly marked smoke tests may do so only when an operator opts in.

## 23. Implementation Sequence

1. Establish application skeleton, typed settings, database session management, Docker Compose, and Alembic.
2. Add reference schema, configuration validation/synchronization, and licensing gate.
3. Add run, scope, raw-response, raw-record, and quarantine storage.
4. Add observation/version schemas, fingerprinting, revision service, and repository tests.
5. Implement Bank of Canada client/parser/mapper with fixtures and validation.
6. Implement BIS client/parser/mapper with fixtures and validation.
7. Implement orchestrator, worker claim/heartbeat/recovery, concurrency control, and run counters.
8. Implement completeness/freshness rules and quality storage.
9. Implement FastAPI observation and operational endpoints.
10. Add scheduler configuration and commands.
11. Add structured logging, metrics, security checks, and performance verification.
12. Complete setup documentation and operator runbook; execute the 12-month acceptance backfill.

Each step should remain deployable and tested. Provider adapters are completed independently but both must use the shared ingestion, validation, revision, and persistence path.

## 24. Requirement-to-Component Traceability

| Requirement | Primary components |
|---|---|
| FR-1 | Configuration, reference schema, reference synchronization |
| FR-2 | Valet client, parser, mapper, FX validator, revision repository |
| FR-3 | BIS client, SDMX parser, mapper/normalizer, revision repository |
| FR-4 | Raw data service and raw/lineage schema |
| FR-5 | Normalization, validation, expectation and quality services, quarantine |
| FR-6 | Fingerprint and revision persistence components |
| FR-7 | API/CLI commands, orchestrator, worker, scheduler, scope coordinator |
| FR-8 | Run manager, operational repositories/API, logging, metrics |
| FR-9 | Query service, observation repositories, FastAPI routers |
| NFR-1 | Transactions, scope isolation, idempotency, lease recovery |
| NFR-2 | Bounded requests, batching, indexes, keyset pagination, performance tests |
| NFR-3 | Settings, HTTPS client policy, least-privilege roles, local binding |
| NFR-4 | Raw lineage, immutable versions, checksums, code/config version, as-of query |
| NFR-5 | Provider dataset licensing gate and restricted raw access |

## 25. Deferred Decisions and Explicit Exclusions

Before implementation, provider-specific fixtures must confirm exact Valet and BIS response fields, SDMX dimension order/structure resolution, series keys, release schedules, status codes, and license terms. Those values belong in configuration and contract tests rather than assumptions embedded in business logic.

The following remain deliberately excluded: derived FX rates, reciprocals, policy-rate forward filling, tenor assignment, parity calculations, opportunity scoring, external alerts, public authentication, a web UI, and automated raw-data expiry.
