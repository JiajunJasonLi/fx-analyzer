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

- [ ] Create the documented `app/` package structure with importable empty subpackages.
- [ ] Add project dependency configuration for Python, FastAPI, SQLAlchemy, Alembic, `httpx`, PostgreSQL driver, and `pytest` only where needed.
- [ ] Implement typed environment settings with `DATABASE_URL`, log level, and safe defaults; do not hardcode credentials.
- [ ] Implement SQLAlchemy session/engine creation with UTC database-session behavior.
- [ ] Add a minimal FastAPI application with `/health/live`.
- [ ] Configure Alembic against the shared SQLAlchemy metadata.
- [ ] Add Dockerfiles and Docker Compose services for `db`, `migrate`, `api`, `worker`, and `scheduler`; worker and scheduler may be no-op entry points until their module is implemented.
- [ ] Bind externally published ports to loopback by default and persist PostgreSQL data in a named volume.
- [ ] Add `.env.example` without secrets and basic local startup commands to developer documentation.
- [ ] Add smoke tests for settings loading, application import, and liveness.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Docker Compose can start PostgreSQL and the API from a clean checkout.
- [ ] Alembic can run against an empty local database.
- [ ] `GET /health/live` returns success.
- [ ] No provider ingestion or business logic is included.

