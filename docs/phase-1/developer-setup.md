# Phase 1 Developer Setup

## Prerequisites

- Python 3.11 or newer
- Docker with Docker Compose
- Free loopback ports 8000 and 5432

Install and test locally:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest
```

Normal tests use committed provider fixtures and mocked HTTP. PostgreSQL-specific tests require an isolated migrated database:

```bash
export TEST_DATABASE_URL='postgresql+psycopg://OWNER:PASSWORD@127.0.0.1:5432/fx_analyzer_test'
pytest tests/integration
```

## Local services

Copy `.env.example` to `.env` and replace both example passwords with different local-only values. `DATABASE_URL` is the migration-owner connection; `APP_DATABASE_URL` is the restricted DML connection used by API, worker, and scheduler.

```bash
docker compose config
docker compose up --build -d db
docker compose run --rm migrate
docker compose up -d api worker scheduler
curl http://127.0.0.1:8000/health/ready
```

The image runs as the non-root `app` user. Published ports bind to loopback. Provider clients require HTTPS. Dependencies and the PostgreSQL image use pinned versions.

Metrics are disabled by default. Set `METRICS_ENABLED=true` to expose the local `/metrics` endpoint. This endpoint is not intended for public exposure.

## License gate

Both datasets were approved by the project operator on 2026-09-21 and are configured with `approval_state: approved` and `retention_permitted: true`. Their license URLs, attribution, and redistribution notes remain part of versioned configuration. Any future terms change must be reviewed before continued ingestion; never change approval fields merely to make a test pass.

## Useful checks

```bash
alembic upgrade head
pytest -q
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Phase 1 has no UI, public authentication, external alerting, parity calculation, or trading functionality.
