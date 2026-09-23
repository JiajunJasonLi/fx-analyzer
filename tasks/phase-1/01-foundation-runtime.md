# Module 01: Foundation and Local Runtime

## Goal

Create the smallest runnable Python application skeleton and local PostgreSQL environment on which all later Phase 1 modules depend.

## Inputs

- `docs/phase-1/requirements.md`
- `docs/phase-1/designs.md`
- `docs/phase-1/detailed-designs.md`, especially sections 2, 5.1, and 21

## Dependencies

None.

## Checklist

- [x] Create the documented `app/` package structure with importable empty subpackages.
- [x] Add project dependency configuration for Python, FastAPI, SQLAlchemy, Alembic, `httpx`, PostgreSQL driver, and `pytest` only where needed.
- [x] Implement typed environment settings with `DATABASE_URL`, log level, and safe defaults; do not hardcode credentials.
- [x] Implement SQLAlchemy session/engine creation with UTC database-session behavior.
- [x] Add a minimal FastAPI application with `/health/live`.
- [x] Configure Alembic against the shared SQLAlchemy metadata.
- [x] Add Dockerfiles and Docker Compose services for `db`, `migrate`, `api`, `worker`, and `scheduler`; worker and scheduler may be no-op entry points until their module is implemented.
- [x] Bind externally published ports to loopback by default and persist PostgreSQL data in a named volume.
- [x] Add `.env.example` without secrets and basic local startup commands to developer documentation.
- [x] Add smoke tests for settings loading, application import, and liveness.
- [x] Run `pytest` and record the result.

## Done When

- [x] Docker Compose can start PostgreSQL and the API from a clean checkout.
- [x] Alembic can run against an empty local database.
- [x] `GET /health/live` returns success.
- [x] No provider ingestion or business logic is included.

## Verification Notes

- `pytest -q`: 6 passed.
- `docker compose --env-file .env.example config`: passed.
- `docker compose --env-file .env.example up --build -d api`: built the non-root image, ran migrations, and started PostgreSQL and the API.
- `curl --fail http://127.0.0.1:8000/health/live`: returned `{"status":"ok"}`.
