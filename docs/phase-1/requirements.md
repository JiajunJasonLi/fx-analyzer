# Phase 1 Requirements: FX and Interest-Rate Data Ingestion

## 1. Purpose

Build a reliable data foundation for analyzing covered interest-rate parity (CIP), uncovered interest-rate parity (UIP), and potential FX carry trades in later phases.

Phase 1 will ingest, validate, normalize, store, and expose:

- Bank of Canada daily indicative exchange rates; and
- BIS central-bank policy-rate observations associated with currencies and economies.

This phase does **not** identify, rank, or recommend arbitrage or carry trades. Its output is a trustworthy historical dataset and an ingestion process that later analytical components can use.

## 2. Background

Later parity calculations require observations that are comparable by currency, tenor, market convention, and time. A simple country policy rate is useful for macroeconomic context but is not sufficient by itself for CIP calculations. CIP generally requires spot FX, forward FX (or equivalent forward points), and comparable funding rates for the same tenor. UIP and carry-trade analysis may use policy rates or market yields, but must distinguish them from investable funding rates.

Phase 1 therefore stores the policy-rate classification, observation date, source metadata, and revision history. The BIS policy-rate series has no tenor and must not be treated as a matched-tenor funding rate. Forward FX ingestion and parity calculations are deferred to a later phase.

Because the project is a research tool rather than a trading system, Phase 1 uses BIS central-bank policy rates and Bank of Canada indicative daily average FX rates for simplicity.

## 3. Goals

1. Ingest Bank of Canada daily exchange rates and BIS central-bank policy-rate data.
2. Preserve raw inputs and enough provenance to audit every normalized observation.
3. Support safe re-runs without creating unintended duplicate observations.
4. Detect missing, stale, malformed, or implausible data.
5. Provide a queryable store suitable for historical analysis and later calculation services.
6. Establish operational visibility through structured logs, metrics, and ingestion-run records.

## 4. Non-goals

The following are outside Phase 1:

- CIP or UIP calculations;
- trade recommendations, execution, brokerage integration, or portfolio management;
- forward, swap, futures, options, volatility, or order-book ingestion;
- transaction-cost, tax, capital-control, credit-risk, or liquidity modelling;
- real-time/low-latency market-data streaming;
- a public web UI or charting application;
- forecasting exchange rates or interest rates;
- automated currency-hedging decisions; and
- external freshness, failure, UIP, CIP, or trading-opportunity alerts.

## 5. Assumptions

These assumptions define an implementable initial scope and should be confirmed before implementation:

- The first release is a research tool, not a production trading system.
- Phase 1 runs locally, with PostgreSQL provided through Docker Compose.
- The application exposes its query and ingestion status capabilities through an internal FastAPI HTTP API.
- The initial historical backfill covers the preceding 12 months, subject to provider availability.
- Phase 1 does not send external alerts. Freshness, completeness, and ingestion failures are inspected through logs and the internal API.
- Observation frequency is daily for FX and BIS policy-rate data. Provider release schedules may be less frequent than the observation frequency.
- The initial universe is G10 currencies: USD, EUR, JPY, GBP, CHF, CAD, AUD, NZD, SEK, and NOK. Coverage remains configurable rather than hard-coded.
- The Bank of Canada Valet API is the Phase 1 FX exchange-rate provider.
- The BIS Data Portal and BIS SDMX REST API are the Phase 1 interest-rate source and programmatic interface, respectively. Phase 1 uses the BIS central-bank policy-rates dataset.
- FX observations are the Bank of Canada's daily indicative averages, published once per Canadian business day, normally by 16:30 Eastern Time. They are reference values and are not treated as executable quotes.
- Bank of Canada FX series express one unit of a foreign currency in Canadian dollars. Direct source observations therefore have CAD as the quote currency.
- Bid and ask values and spreads are not required or stored in Phase 1.
- Phase 1 interest-rate coverage is limited to the BIS main policy-rate series for the G10 economies. The BIS series contains the target rate or, when a target is unavailable, the traded rate for the main policy instrument.
- BIS daily policy-rate observations are expressed as percent per year and are generally released weekly. Monthly BIS series are not required in Phase 1 because they are derived from the daily series.
- FX symbols use ISO 4217 currency codes and an explicit base/quote convention: one unit of `base_currency` is worth `rate` units of `quote_currency`.

## 6. Users and Use Cases

### 6.1 Primary user

An analyst or developer researching cross-country interest differentials and FX behavior.

### 6.2 Primary use cases

- Retrieve the latest valid daily exchange rate for a currency pair.
- Retrieve historical daily exchange rates for a pair and date range.
- Retrieve the latest or historical BIS policy-rate observations by currency, economy, series, and date.
- Determine the source, source timestamp, and ingestion run for any observation.
- Re-run ingestion for a date range after a failure or provider revision.
- Assess data completeness and freshness before running downstream analysis.

## 7. Functional Requirements

### FR-1: Instrument and series configuration

The system shall:

1. Maintain a configurable list of supported currencies, countries, FX pairs, and interest-rate series.
2. Store the canonical base and quote currencies for every FX pair.
3. Store BIS policy-rate metadata including economy, currency, dataflow/series identifiers, frequency, unit, collection indicator, title, source notes, and publication metadata where available.
4. Permit a series or pair to be enabled or disabled without code changes.
5. Reject unknown or invalid currency codes and malformed pair definitions.

### FR-2: FX exchange-rate ingestion

The system shall:

1. Fetch daily exchange-rate observations for all enabled G10 FX series from the Bank of Canada Valet API.
2. Use the Valet observations endpoint and JSON response format; endpoint paths and series identifiers shall be configuration rather than business-logic constants.
3. Capture at minimum the foreign/base currency, CAD quote currency, observation date, reference value, Bank of Canada series identifier, and retrieval time.
4. Store each source observation in its published orientation: one unit of foreign currency expressed in Canadian dollars.
5. Classify each value as a daily indicative average/reference rate. The system shall not represent it as a bid, ask, executable quote, or transaction price.
6. Preserve Bank of Canada response metadata and quality/status flags when available.
7. Distinguish Canadian non-business days and unpublished observations from ingestion failures.
8. Do not persist reciprocals or non-CAD cross rates as source observations. If later required, they shall be calculated from same-date source observations and clearly identified as derived values.

### FR-3: Interest-rate ingestion

The system shall:

1. Fetch daily observations for the enabled G10 economies from the BIS central-bank policy-rates dataset through the BIS SDMX REST API.
2. Support filtered API retrieval for routine and bounded backfill runs. BIS bulk CSV or SDMX downloads may be used for an initial or recovery backfill if they pass through the same normalization and validation process.
3. Capture at minimum the economy, associated currency, observation date, value, unit, frequency, collection indicator, BIS dataflow/series key, dataset version when supplied, and retrieval time.
4. Preserve the BIS SDMX dimensions, attributes, status flags, and series metadata needed to interpret an observation.
5. Classify the canonical rate as the economy's `policy_rate`; it has no tenor. The source metadata shall retain whether the underlying instrument is a target, traded rate, repo rate, discount rate, or another instrument when BIS supplies that information.
6. Preserve the BIS-published value for policy corridors or target bands. BIS normally publishes the midpoint unless the relevant central bank has indicated a different representative rate; the system shall not manufacture separate upper and lower bounds.
7. Distinguish an unchanged policy rate, a missing observation, a not-yet-released period, and a request/parsing failure.
8. Preserve revised observations and identify the currently active version.

### FR-4: Raw-data preservation

The system shall:

1. Preserve the unmodified provider response or a lossless equivalent for each successful fetch.
2. Associate raw data with provider, request parameters, retrieval time, response status, checksum, and ingestion-run identifier.
3. Retain all raw provider responses captured by the initial 12-month backfill and subsequent incremental runs. Phase 1 shall not automatically delete or expire this raw data.
4. Avoid storing secrets, authorization headers, or credentials in raw payloads or logs.

### FR-5: Normalization and validation

The system shall:

1. Retain the original provider timestamp and time-zone information when supplied.
2. Normalize percentage units consistently. The canonical representation shall be documented and exposed with an explicit unit.
3. Validate that numeric values are parseable and that FX spot values are greater than zero.
4. Validate required identifiers and referential integrity.
5. Detect duplicate provider observations using a documented natural key.
6. Flag, rather than silently discard, stale or statistically implausible observations.
7. Quarantine records that cannot be normalized, recording a machine-readable reason and the associated raw record.
8. Produce completeness checks for every configured pair/series according to its observation frequency, release schedule, and applicable business calendar.

### FR-6: Idempotency and revisions

The system shall:

1. Make repeated ingestion of the same unchanged provider observation idempotent.
2. Avoid duplicate canonical records during retries or historical backfills.
3. Preserve provider revisions as new versions when a previously published value changes.
4. Record when each version was first and last observed and which version is current.
5. Prevent a partial retry from deleting previously valid data.

### FR-7: Scheduling, manual runs, and backfills

The system shall:

1. Support scheduled daily Bank of Canada ingestion and provider-aware BIS ingestion aligned with the BIS release cadence.
2. Support a manually triggered run for a provider, dataset, and bounded date range.
3. Support historical backfills using the same validation and persistence path as scheduled runs.
4. Prevent or safely coordinate overlapping runs for the same provider, dataset, and period.
5. Apply bounded retries with backoff for transient provider failures.
6. Respect provider rate limits and usage terms.

### FR-8: Run tracking and observability

For every ingestion run, the system shall record:

- a unique run identifier;
- trigger type (scheduled, manual, or backfill);
- provider and dataset;
- requested date range;
- start and finish timestamps;
- status (running, succeeded, partially succeeded, or failed);
- counts fetched, inserted, unchanged, revised, quarantined, and failed; and
- sanitized error details.

The system shall emit structured logs and metrics sufficient to diagnose failures and shall make stale, incomplete, quarantined, or failed ingestion visible through logs and the internal API. It shall not send external alerts in Phase 1.

### FR-9: Data access

The system shall provide a documented internal FastAPI HTTP API to:

1. Retrieve FX reference-rate observations by pair and time range.
2. Retrieve BIS policy-rate observations by currency/economy, series, and time range.
3. Retrieve the latest valid observation as of a specified timestamp without using later revisions or future data.
4. Retrieve provenance and validation state for returned observations.
5. Query ingestion-run status and quarantined-record counts.

The API is intended for local/internal use. Public hosting, authentication for internet exposure, and third-party API access are not required in Phase 1.

## 8. Canonical Data Requirements

The physical schema may differ, but it must represent the following entities and relationships.

### 8.1 Reference entities

- **Currency:** ISO code, name, minor-unit metadata, active flag.
- **Country/economy:** stable internal identifier, ISO country code where applicable, name, time zone, active flag. Currency unions must be representable without pretending they are a single country.
- **FX pair:** base currency, quote currency, canonical symbol, active flag.
- **Provider:** name, dataset, license/usage metadata, and configuration reference.
- **Interest-rate series:** economy, currency, BIS dataflow/series key, rate type (`policy_rate`), frequency, unit, collection indicator, source metadata, publication metadata, active flag.

### 8.2 Observation entities

**FX reference-rate observation** shall include:

- pair identifier;
- observation date;
- daily indicative average/reference-rate value;
- quote type (`reference` for the Phase 1 Bank of Canada feed);
- provider and provider symbol;
- provider publication timestamp if available;
- retrieval timestamp;
- raw-record reference;
- version/current-version markers; and
- validation status and flags.

**Interest-rate observation** shall include:

- series identifier;
- observation date;
- numeric value and explicit unit;
- provider publication timestamp if available;
- retrieval timestamp;
- raw-record reference;
- version/current-version markers; and
- validation status and flags.

**Ingestion run**, **raw record**, and **quarantined record** entities shall support the audit and operational requirements above.

## 9. Data-Quality Rules

At minimum, the system shall evaluate:

- required fields present;
- supported currency and valid pair orientation;
- FX values strictly positive;
- Bank of Canada source observations quoted as foreign currency to CAD;
- interest-rate value within a configurable plausible range;
- observation timestamp not unreasonably in the future;
- freshness relative to the provider's release schedule, observation frequency, and applicable calendar;
- duplicates and conflicting observations;
- gaps on expected publication/business dates; and
- consistency between a normalized record and its raw source.

Threshold breaches that may represent legitimate market events shall be flagged for review, not automatically overwritten or discarded. Weekends, holidays, and differing publication schedules must not be treated as missing data without consulting the applicable calendar/configuration.

## 10. Non-functional Requirements

### NFR-1: Reliability

- A failure in one provider or series shall not corrupt successfully processed observations.
- Database writes for a logical batch shall be transactional where practical.
- The system shall recover safely from process interruption and allow retry.

### NFR-2: Performance and scale

- The initial target is daily data for the 10 G10 currencies, the 9 direct foreign-currency-to-CAD series, the corresponding available BIS policy-rate series, and 20 years of history where the sources provide it.
- The Phase 1 initial backfill is limited to the 12 months immediately preceding the run date; the larger history target is retained as a capacity goal for later expansion.
- A normal daily ingestion run should complete within 15 minutes, excluding provider outages or enforced rate-limit waits.
- Typical single-series or single-pair historical queries over 20 years should return within 2 seconds under expected single-user research load.

These are design targets, not exchange-grade latency requirements.

### NFR-3: Security

- Database access shall follow least privilege.
- External connections shall use encrypted transport.

### NFR-4: Reproducibility and auditability

- A downstream result must be able to identify the exact observation versions it used.
- Historical “as-of” queries shall not accidentally incorporate later provider revisions.
- Stored raw data, transformations, code version, and run metadata shall be sufficient to explain normalized values.

### NFR-5: Licensing and compliance

- Only data sources whose terms permit the intended retrieval, storage, and research use shall be used.
- Provider attribution and redistribution restrictions shall be recorded.
- The system shall not expose stored data beyond what provider licenses allow.

## 11. Provider Integration Requirements

Every provider adapter shall:

1. Accept an explicit dataset/instrument selection and bounded time range where supported.
2. Map provider identifiers to canonical instruments/series.
3. Distinguish “no observation published” from request or parsing failure.
4. Surface rate-limit and retry information.
5. Produce the same normalized result for the same input and configuration version.

The FX provider is the Bank of Canada Valet API, and the interest-rate provider is the BIS SDMX REST API using the central-bank policy-rates dataset. Each integration must respect its source's series semantics, revision behavior, licensing, availability, and usage limits.

## 12. Acceptance Criteria

Phase 1 is complete when all of the following are demonstrated in a non-production environment:

1. The Bank of Canada Valet integration ingests all available enabled G10 daily exchange-rate series, and the BIS integration ingests daily central-bank policy-rate series for all enabled G10 economies available in the BIS dataset.
2. An initial backfill covering the preceding 12 months, where provider data is available, completes and produces queryable normalized observations with retained raw-source records.
3. Scheduled provider-aware runs can ingest incremental data and record their outcomes.
4. Re-running the same input creates no unintended duplicate canonical observations.
5. A changed provider value is retained as a revision, and both current and as-of queries behave correctly.
6. FX orientation and BIS SDMX dimension, date, unit, frequency, and value normalization are verified against representative provider responses.
7. Invalid sample records are quarantined with reasons and do not corrupt valid records in the same run.
8. Every normalized observation can be traced to its provider, raw record, retrieval time, and ingestion run.
9. Completeness and freshness status can be queried for every enabled pair and series.
10. Setup, backfill, daily-run, retry, and failure-recovery instructions are documented and reproducible.
11. The configured data sources have documented license/usage approval for the intended use.

## 13. Delivery Artifacts

Phase 1 implementation is expected to produce:

- declarative instrument/series configuration;
- a local Docker Compose environment containing the application and PostgreSQL database;
- an internal FastAPI HTTP interface for the required data queries and ingestion status;
- scheduled and manual ingestion entry points;
- raw, normalized, quarantine, and ingestion-run storage;
- data-quality checks and operational metrics/logging;
- developer setup documentation; and
- an operator runbook for backfills, retries, and common failures.

## 14. Risks and Dependencies

- Bank of Canada exchange rates are indicative daily averages, not executable prices, and cannot model spreads or transaction costs.
- Bank of Canada publishes direct foreign-currency-to-CAD rates; non-CAD crosses require derived calculations using same-date observations.
- Publication times, holidays, and revisions differ across central banks and providers.
- BIS daily policy-rate observations are generally released weekly, so a current observation date does not imply same-day availability.
- The BIS policy-rate series can splice different policy instruments over time; source metadata and documented breaks must be retained for correct historical interpretation.
- Policy rates are not directly comparable to matched-tenor funding rates.
- FX and rate observations taken at different market cut-off times can create false apparent opportunities.
- Currency unions and currencies used by multiple economies require careful modelling.
- Provider licensing may restrict raw-data retention or redistribution.
- CIP analysis in a later phase will require forward FX and matched-tenor rates, which Phase 1 does not yet ingest.

## 15. Proposed Phase Boundary

Phase 1 ends with audited, versioned FX reference-rate and interest-rate observations. A proposed Phase 2 would add forward FX and matched-tenor instrument selection, then calculate CIP deviations, UIP/carry indicators, transaction-cost-adjusted opportunities, confidence/data-quality warnings, and any corresponding alerting requirements. Any output describing an “opportunity” should clearly distinguish a theoretical parity deviation from an executable, risk-adjusted trade.
