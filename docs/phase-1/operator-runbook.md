# Phase 1 Operator Runbook

## Initial setup

Follow [developer-setup.md](developer-setup.md), verify `/health/ready`, and confirm that the database migration version equals the repository Alembic head. Keep the API and database loopback-only.

Before any provider run, inspect each `provider_datasets` entry in `config/reference-data.yaml`. The project operator approved the current Bank of Canada and BIS use, attribution, and raw retention on 2026-09-21. If provider terms or intended use change, return the affected dataset to `pending` until an authorized review is recorded.

## Initial 12-month backfill

Only after approval, submit one bounded request per provider using dates from 12 months before the run date through the run date:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ingestion-runs \
  -H 'content-type: application/json' \
  -d '{"provider":"bank_of_canada","dataset":"valet_daily_fx","trigger_type":"backfill","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}'
```

Repeat for `provider=bis` and `dataset=bis_policy_rates_daily`. A `202` response means durable enqueue only. Poll the returned `Location`; the worker performs provider I/O. Never treat enqueue as successful ingestion.

## Daily operation

The scheduler creates provider-aware pending runs. Inspect `/api/v1/ingestion-runs`, `/api/v1/data-quality`, `/api/v1/quarantine/counts`, structured logs, and optional local metrics. `succeeded` may include quarantined records; review counts. `not_due` is not a provider failure.

## Retry and overlap handling

Do not mutate a failed run. Re-submit its bounded scope as a manual run through `POST /api/v1/ingestion-runs`; historical failed-run evidence remains immutable. Internal retry producers may use `trigger_type: retry` with a terminal `parent_run_id`. Manual overlapping scopes return `409`; scheduled overlaps are recorded and skipped. Retrying unchanged data adds lineage but no canonical version. A changed value adds an immutable version and closes the prior knowledge interval.

## Abandoned workers

On worker startup, expired `running` leases are marked failed with `WORKER_LEASE_EXPIRED`. Confirm the old run is terminal, inspect its completed scopes, then create a linked retry for the failed scope. Never delete prior valid observations or raw responses.

## Quarantine review

Use `/api/v1/quarantine/counts` with `run_id`, `reason`, or `stage`. Full raw payloads are intentionally not exposed by HTTP. Inspect raw evidence through restricted database access, resolve the mapping/configuration defect, and rerun the bounded scope. Do not manually convert a quarantined record into an observation version.

## Common failures

| Symptom | Action |
|---|---|
| Readiness reports migrations false | Run `docker compose run --rm migrate`; inspect Alembic output. |
| Configuration/license returns 503 | Correct configuration or obtain documented approval; do not bypass the gate. |
| Provider timeout/5xx | Allow bounded retries, then create a linked retry after recovery. |
| Scope overlap 409 | Wait for the active run or investigate an expired worker lease. |
| Stale/incomplete quality | Check calendar/release cadence and latest successful raw fetch before retrying. |
| Parse/quarantine increase | Compare fixture/provider contract and raw record locator; never log the payload. |

## Backup and restore

Create a consistent logical backup with the owner credential:

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > fx-analyzer.dump
```

Restore only into an empty, isolated database after stopping API, worker, and scheduler:

```bash
docker compose stop api worker scheduler
docker compose exec -T db createdb -U "$POSTGRES_USER" fx_analyzer_restore
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d fx_analyzer_restore --clean --if-exists < fx-analyzer.dump
```

Point a temporary API at the restored database, run readiness and representative current/as-of queries, then deliberately switch configuration if validation succeeds. Retain backups according to the approved provider terms; Phase 1 performs no automatic raw-data deletion.
