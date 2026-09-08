# AGENTS.md

## Project
This repository contains an FX and interest-rate data platform.

The long-term goal is to analyze interest-rate parity and carry-trade opportunities.

## Working Style
- Read `README.md` and all relevant files under `docs/` before making changes.
- Do not implement features outside the documented phase.
- Prefer simple, maintainable solutions over unnecessary abstractions.
- Keep external API integrations isolated from business logic.
- Do not hardcode secrets or credentials.
- Use environment variables for configuration.
- Update documentation when architecture or behavior changes.

## Technology

Use:
- Python
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- httpx
- pytest
- Docker / Docker Compose

Use Python type hints throughout the application.

## Architecture

Prefer the following layers:

API
→ Service
→ Repository
→ Database

External data providers should be implemented separately from application
business logic.

Example:

- BIS client/service for interest-rate data
- Bank of Canada client/service for FX data

Normalize external responses into internal domain models before storing them.

## Database
- Use PostgreSQL.
- Use Alembic for schema migrations.
- Use NUMERIC/DECIMAL for financial values where appropriate.
- Add uniqueness constraints to prevent duplicate observations.
- Store timestamps in UTC.

## Testing
For new functionality:

- Write unit tests for transformation/business logic.
- Write integration tests for database behavior where appropriate.
- Mock external APIs in automated tests.
- Do not rely on live external APIs for the normal test suite.

Before finishing a task, run:

pytest

and report any failing tests.

## Code Quality
- Keep functions reasonably small.
- Avoid duplicated logic.
- Use descriptive names.
- Add comments only where the intent is not obvious.
- Do not introduce libraries unless there is a clear need.