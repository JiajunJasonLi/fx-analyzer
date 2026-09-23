# Module 13: Worker, Scheduler, and Recovery

## Goal

Run durable ingestion work outside HTTP requests, create provider-aware schedules, and recover safely from interrupted workers.

## Inputs

- Detailed design section 18
- Requirements FR-7 and NFR-1

## Dependencies

- [x] Module 10 complete
- [x] Module 11 complete

## Checklist

- [x] Implement the worker polling loop, atomic claim, bounded idle interval, heartbeat, and graceful shutdown.
- [x] Update heartbeat between long provider attempts/pages without weakening transaction isolation.
- [x] Implement expired-lease recovery that marks abandoned scopes/runs failed with a stable code and never assumes success.
- [x] Implement the scheduler as a thin command producer using configured calendars, publication times, release cadence, and grace delay.
- [x] Schedule Bank of Canada after the configured 16:30 America/Toronto publication window on Canadian business days.
- [x] Schedule BIS using configured provider-aware weekly cadence despite daily observation frequency.
- [x] Suppress duplicate scheduled runs already active or successfully covering the same effective scope.
- [x] Wire real worker and scheduler commands into Docker Compose health/restart behavior.
- [x] Add tests with a controllable clock for due/not-due decisions, duplicate suppression, heartbeat expiry, recovery, and graceful shutdown.
- [x] Run `pytest` and record the result.

## Done When

- [x] Scheduled and API-created runs are executed by the same worker/orchestrator path.
- [x] Process interruption can be detected and safely retried without data loss or duplicate observations.

## Verification Notes

- Worker/scheduler focused unit suite: 17 passed.
- PostgreSQL claim/recovery suite: 2 passed, including concurrent claims and linked recovery retries.
- Complete PostgreSQL-backed suite after integration: 140 passed, 1 warning.
