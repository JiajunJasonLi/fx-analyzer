# FX Analyzer

Phase 1 provides a local, auditable store for Bank of Canada FX reference rates
and BIS central-bank policy rates, including ingestion workers and a local API.

## Local development

Python 3.11 or newer and Docker with Docker Compose are required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

To start the local runtime, first create local-only configuration and replace
the example password in both relevant values:

```bash
cp .env.example .env
docker compose up --build
curl http://127.0.0.1:8000/health/live
```

The API and PostgreSQL ports bind only to loopback. PostgreSQL data is retained
in the `postgres_data` named volume. Apply migrations independently with:

```bash
docker compose run --rm migrate
```

See [developer setup](docs/phase-1/developer-setup.md) for test-database and
least-privilege details, and the [operator runbook](docs/phase-1/operator-runbook.md)
for backfills, retries, recovery, quarantine review, and backup/restore.
