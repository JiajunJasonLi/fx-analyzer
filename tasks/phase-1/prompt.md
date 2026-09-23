# Phase 1 Autonomous Vibe-Coding Prompt

You are the main implementation agent for Phase 1 of the FX analyzer. Complete Phase 1 autonomously by coordinating sub-agents, integrating their work, verifying every requirement, and maintaining the task checklists as the authoritative record of progress.

No human will participate during development. Do not pause for clarification, routine decisions, reviews, or status approval. Resolve ambiguity from the repository documentation, choose the smallest maintainable design consistent with it, record material assumptions, and continue. Do not claim completion for work that was not verified.

## Authoritative Inputs

Read these files completely before changing code:

1. `AGENTS.md`
2. `docs/phase-1/requirements.md`
3. `docs/phase-1/designs.md`
4. `docs/phase-1/detailed-designs.md`
5. Every module file matching `tasks/phase-1/[0-9][0-9]-*.md`
6. `tasks/phase-1/progress.md`

The requested input name `docs/phase-1/deatiled-designs.md` is a typo; use `docs/phase-1/detailed-designs.md`.

Apply instructions in this order when they conflict:

1. `AGENTS.md`
2. Phase 1 requirements
3. Detailed design
4. High-level design
5. Module task files

Do not implement anything listed as a Phase 1 non-goal or explicit exclusion.

## Mission

Implement all modules in `tasks/phase-1/`, satisfy their checklists and **Done When** conditions, pass the complete test suite, and update `tasks/phase-1/progress.md` with evidence-backed completion.

The main agent owns:

- dependency ordering and sub-agent dispatch;
- task and file ownership coordination;
- review and integration of every sub-agent result;
- architectural consistency across modules;
- progress/checklist updates;
- repository-wide tests and acceptance verification; and
- the final report.

Each implementation module must be assigned to a sub-agent. A sub-agent may implement only one numbered module per assignment. Reuse a completed sub-agent for follow-up fixes when practical, but keep module ownership explicit.

## Non-Negotiable Engineering Rules

- Use Python type hints throughout.
- Preserve the API → service → repository → database layering.
- Keep Bank of Canada and BIS provider code outside business logic.
- Use PostgreSQL, SQLAlchemy, Alembic, FastAPI, `httpx`, `pytest`, and Docker Compose as documented.
- Use `Decimal`/PostgreSQL `NUMERIC` for financial values and timezone-aware UTC timestamps for instants.
- Never hardcode credentials or emit secrets, authorization headers, raw payloads, or sensitive URLs in logs/errors.
- Normal automated tests must use fixtures and mocked HTTP; they must not call live provider APIs.
- Preserve raw lineage before canonical persistence.
- Do not create observation versions for failures, absences, or quarantined records.
- Do not calculate reciprocals, cross rates, forward rates, parity, or trading opportunities.
- Do not add a public UI, external alerts, public authentication, or unrelated infrastructure.
- Do not delete or overwrite user work. Inspect the worktree before edits and preserve unrelated changes.
- Avoid new dependencies unless required by the documented design and justified in the final report.

## Progress Ownership

The main agent is the only agent allowed to edit:

- `tasks/phase-1/progress.md`; and
- checklist markers in `tasks/phase-1/[0-9][0-9]-*.md`.

Sub-agents must report completed checklist items, changed files, tests run, failures, assumptions, and residual risks. They must not mark their own task complete.

Only change a checklist item from `[ ]` to `[x]` after inspecting the implementation and verifying the corresponding behavior. A module in `progress.md` may be checked only when every checklist item and every **Done When** item in that module file is checked.

If a task was already implemented before this run, verify it against the same standard rather than reimplementing it.

## Initial Audit

Before delegation:

1. Inspect the full repository and current Git status.
2. Determine which task items already have implementation evidence.
3. Run the existing test suite once to establish a baseline; if no tests exist yet, record that fact and continue.
4. Inspect available runtime tools, Python version, Docker availability, and PostgreSQL test strategy.
5. Create a concise internal ownership map so parallel agents do not edit the same files.
6. Do not reset, clean, or discard existing changes.

## Dependency Plan

Use the dependencies declared inside each task file. The intended execution graph is:

```text
01 Foundation
├── 02 Configuration and Reference Data
│   └── 04 Provider Core
│       ├── 05 Raw Data and Lineage ──┐
│       └── 06 Normalization          ├── 07 Bank of Canada Adapter ──┐
│                                    ├── 08 BIS Adapter ──────────────┤
03 Database Schema ──────────────────┼── 09 Versioning ───────────────┤
                                     │                                v
                                     └────────────────────────────── 10 Orchestration
02 + 03 + 09 ─────────────────────────────────────────────────────── 11 Data Quality
09 + 10 + 11 ────────────────────────────────────────────────────── 12 Query API
10 + 11 ─────────────────────────────────────────────────────────── 13 Worker/Scheduler
01–13 ───────────────────────────────────────────────────────────── 14 Acceptance
```

The task files are authoritative if this diagram and their dependencies differ.

Use parallel sub-agents only when prerequisites are complete and file ownership does not overlap. A safe default sequence is:

1. Module 01.
2. Modules 02 and 03 in parallel after Module 01.
3. Module 04 after Module 02.
4. Modules 05 and 06 in parallel after their prerequisites.
5. Modules 07, 08, and 09 in parallel after Modules 05 and 06.
6. Modules 10 and 11 when their respective prerequisites are complete.
7. Modules 12 and 13 in parallel after Modules 10 and 11.
8. Module 14 after Modules 01–13.

If the available agent concurrency is lower, preserve dependency order and run fewer modules concurrently. Never bypass a dependency merely to increase parallelism.

## Sub-Agent Assignment Template

For each numbered module, give its sub-agent a prompt containing all of the following:

```text
Implement Module NN from tasks/phase-1/<module-file>.md.

Read AGENTS.md, docs/phase-1/requirements.md, docs/phase-1/designs.md,
docs/phase-1/detailed-designs.md, and the complete module task file before editing.

Scope:
- Implement every unchecked checklist and Done When item in this module.
- Respect completed prerequisite interfaces; do not redesign unrelated modules.
- Work only in the assigned ownership paths unless an integration change is essential.
- Preserve unrelated and pre-existing changes in the shared worktree.
- Do not edit tasks/phase-1/progress.md or task checklist markers.
- Use mocked provider I/O in normal tests; do not require live external services.
- Run focused tests and relevant broader tests before reporting.

Return:
- concise implementation summary;
- exact files changed;
- checklist-to-evidence mapping;
- commands/tests run and their outcomes;
- assumptions and any remaining risks or blockers.
```

Add module-specific ownership paths and known interfaces to each assignment. Tell each agent that the workspace is shared and that edits from other agents may appear while it works.

## Module Review Gate

When a sub-agent reports completion, the main agent must:

1. Inspect all changed files and the current worktree, not merely trust the report.
2. Compare the result line-by-line with the module checklist, requirements, and detailed design.
3. Check architectural boundaries, types, migration consistency, error handling, security, and test quality.
4. Run the module's focused tests itself.
5. Run all tests for already completed modules to catch regressions.
6. Fix small integration issues directly; send substantial module defects back to the responsible sub-agent.
7. Update the module task checkboxes with `[x]` only for verified items.
8. Check the module in `progress.md` only after every module item and **Done When** condition is verified.
9. Record unresolved evidence in a short `## Verification Notes` section in the module task file when needed.

Do not accept placeholder implementations, skipped assertions, empty migrations, pass-only tests, silent exception handling, or TODOs standing in for required behavior.

## Testing Strategy

Use the smallest test scope that provides fast feedback, then widen it at integration gates:

- After each sub-agent: its focused unit/integration/API tests.
- After Modules 03, 06, 09, 10, 12, and 13: all tests for completed modules.
- Before and after Module 14: the complete `pytest` suite.
- For PostgreSQL integration behavior: use the documented local PostgreSQL/Docker test setup, not SQLite substitutes for PostgreSQL-specific constraints or locking.
- For provider behavior: use representative committed fixtures and mocked `httpx` transports.
- For concurrency: verify actual database uniqueness/locking behavior, not only mocked repository calls.
- For migrations: verify a clean upgrade and safe downgrade where supported.
- For Docker Compose: validate configuration and start/health behavior when the runtime is available.

Never mark a test checklist complete merely because test code exists; the relevant test must pass.

## Autonomous Decision Policy

No human will answer questions. Apply these rules:

- Prefer the simplest option explicitly allowed by the detailed design.
- When multiple choices are equivalent, select the one using the existing stack and fewest dependencies.
- Derive provider-specific fields from committed fixtures or authoritative documentation already in the repository. Do not invent live identifiers silently.
- If non-destructive web access is available and exact provider contracts must be verified, use official Bank of Canada or BIS sources only; capture representative responses as sanitized fixtures and keep normal tests offline.
- If network, Docker, or PostgreSQL is temporarily unavailable, continue all independent work, use static/mocked verification where valid, and retry local verification later.
- Do not weaken requirements to make tests pass.
- Do not fabricate license approval, live backfill results, provider availability, performance numbers, or test results.
- Never perform destructive cleanup, expose services publicly, or use real credentials.

When an external fact or capability cannot be obtained autonomously, implement the complete safe code path, fixtures, tests, configuration gate, and documentation. Mark only the externally dependent checklist item as unresolved and record the exact blocker and reproduction command. Continue every other module and acceptance item. An unavailable live provider must not block offline implementation and mocked acceptance tests.

## Integration Requirements

The main agent must ensure the final system demonstrates these end-to-end properties:

- Reference configuration is validated, checksummed, synchronized idempotently, and license-gated.
- Both provider adapters use shared contracts but retain provider-specific parsing/mapping.
- Successful responses are stored losslessly before canonical processing.
- Valid records survive alongside quarantined invalid records in the same run.
- Unchanged reprocessing creates lineage but no duplicate canonical version.
- A provider value change creates a new immutable version and closes the prior knowledge interval.
- Current and as-of queries return the correct version without future-data leakage.
- Missing/not-due data is distinct from fetch/parse failure.
- Overlapping ingestion scopes are safely rejected, skipped, deferred, or serialized as designed.
- Interrupted workers leave recoverable durable state.
- Quality status accounts for calendars and provider release cadence.
- API responses preserve decimal precision and expose validation/provenance.
- Logs and metrics are useful, sanitized, and bounded in cardinality.
- Docker Compose, migrations, setup instructions, and operator recovery steps are reproducible.

## Completion Procedure

After Modules 01–13 pass their review gates, delegate Module 14 to a sub-agent and then independently perform final integration review.

Final verification must include:

1. Run the complete `pytest` suite and retain the exact summary.
2. Validate Alembic migration from an empty PostgreSQL database.
3. Validate Docker Compose configuration and service health when Docker is available.
4. Run the mocked-provider end-to-end acceptance scenario.
5. Verify current/as-of behavior with an unchanged fetch, a revision, and a reversion.
6. Verify quarantine isolation, raw lineage, run counters, overlap handling, and recovery.
7. Verify every Phase 1 acceptance criterion against code, tests, documentation, or explicit external blocker evidence.
8. Update all verified task checklists and `tasks/phase-1/progress.md`.
9. Search for unfinished placeholders, accidental live calls, secrets, out-of-scope features, and stale documentation.
10. Inspect the final diff and ensure unrelated user changes remain untouched.

The live 12-month provider backfill may be marked complete only when provider usage/license approval is recorded, live access is available, and the run actually succeeds. Otherwise leave that item unchecked, document the external blocker precisely, and complete the offline/mock acceptance path. Do not misrepresent this condition.

## Final Response

Return a concise, evidence-based report containing:

- modules completed and any module left incomplete;
- major implementation decisions;
- complete test command(s) and exact pass/fail summary;
- migration and Docker verification results;
- acceptance-criteria status;
- unresolved external blockers, especially licensing or live backfill;
- links/paths to `tasks/phase-1/progress.md`, developer setup documentation, and operator runbook; and
- confirmation that unrelated pre-existing changes were preserved.

Do not stop after producing a plan. Begin the initial audit, delegate Module 01, and continue until Phase 1 is complete or only genuinely external, explicitly documented blockers remain.
