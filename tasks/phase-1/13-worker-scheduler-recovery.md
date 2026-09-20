# Module 13: Worker, Scheduler, and Recovery

## Goal

Run durable ingestion work outside HTTP requests, create provider-aware schedules, and recover safely from interrupted workers.

## Inputs

- Detailed design section 18
- Requirements FR-7 and NFR-1

## Dependencies

- [ ] Module 10 complete
- [ ] Module 11 complete

## Checklist

- [ ] Implement the worker polling loop, atomic claim, bounded idle interval, heartbeat, and graceful shutdown.
- [ ] Update heartbeat between long provider attempts/pages without weakening transaction isolation.
- [ ] Implement expired-lease recovery that marks abandoned scopes/runs failed with a stable code and never assumes success.
- [ ] Implement the scheduler as a thin command producer using configured calendars, publication times, release cadence, and grace delay.
- [ ] Schedule Bank of Canada after the configured 16:30 America/Toronto publication window on Canadian business days.
- [ ] Schedule BIS using configured provider-aware weekly cadence despite daily observation frequency.
- [ ] Suppress duplicate scheduled runs already active or successfully covering the same effective scope.
- [ ] Wire real worker and scheduler commands into Docker Compose health/restart behavior.
- [ ] Add tests with a controllable clock for due/not-due decisions, duplicate suppression, heartbeat expiry, recovery, and graceful shutdown.
- [ ] Run `pytest` and record the result.

## Done When

- [ ] Scheduled and API-created runs are executed by the same worker/orchestrator path.
- [ ] Process interruption can be detected and safely retried without data loss or duplicate observations.

