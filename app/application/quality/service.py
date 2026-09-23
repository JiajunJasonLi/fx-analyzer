from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID

from app.application.quality.expectations import BusinessCalendar, ExpectationPolicy, generate_expectations
from app.domain.enums import QualityState, ValidationSeverity
from app.observability.metrics import metrics


LOGGER = logging.getLogger("fx_analyzer.quality")


@dataclass(frozen=True)
class QualityAssessment:
    run_id: UUID | None
    instrument_type: str
    instrument_id: UUID
    rule_code: str
    state: QualityState
    severity: ValidationSeverity
    affected_start: date
    affected_end: date
    evaluated_at: datetime
    details: Mapping[str, Any]


class QualityStore(Protocol):
    def append_results(self, results: Sequence[QualityAssessment]) -> None: ...


class QualityEvaluationService:
    def evaluate(
        self,
        *,
        policy: ExpectationPolicy,
        calendar: BusinessCalendar | None,
        instrument_id: UUID,
        start: date,
        end: date,
        evaluated_at: datetime,
        available_dates: set[date],
        successful_fetch_evidence: bool,
        run_id: UUID | None = None,
    ) -> QualityAssessment:
        evaluated_at = _utc(evaluated_at)
        if calendar is None or not calendar.covers(start) or not calendar.covers(end):
            return self._unknown(policy, instrument_id, start, end, evaluated_at, run_id, "calendar_configuration_missing")

        expected = generate_expectations(policy, calendar, start, end)
        due = tuple(item for item in expected if item.due_at <= evaluated_at)
        if not due:
            return self._assessment(
                policy, instrument_id, start, end, evaluated_at, run_id,
                QualityState.NOT_DUE, ValidationSeverity.INFO, (), expected, available_dates,
                {"reason": "no_expected_observation_is_due"},
            )
        missing = tuple(item for item in due if item.observation_date not in available_dates)
        if missing and not successful_fetch_evidence:
            return self._assessment(
                policy, instrument_id, start, end, evaluated_at, run_id,
                QualityState.UNKNOWN, ValidationSeverity.WARNING, missing, due, available_dates,
                {"reason": "successful_fetch_evidence_missing"},
            )
        if not missing:
            state, severity = QualityState.COMPLETE, ValidationSeverity.INFO
        elif evaluated_at > max(item.due_at for item in due) + policy.stale_after:
            state, severity = QualityState.STALE, ValidationSeverity.ERROR
        else:
            state, severity = QualityState.INCOMPLETE, ValidationSeverity.WARNING
        return self._assessment(
            policy, instrument_id, start, end, evaluated_at, run_id,
            state, severity, missing, due, available_dates, {},
        )

    def evaluate_safely(self, **kwargs: Any) -> QualityAssessment:
        try:
            return self.evaluate(**kwargs)
        except Exception as exc:
            policy: ExpectationPolicy = kwargs["policy"]
            return self._unknown(
                policy, kwargs["instrument_id"], kwargs["start"], kwargs["end"],
                _utc(kwargs["evaluated_at"]), kwargs.get("run_id"),
                "quality_evaluation_failed", error_type=type(exc).__name__,
            )

    def evaluate_and_append(self, store: QualityStore, **kwargs: Any) -> QualityAssessment:
        result = self.evaluate_safely(**kwargs)
        store.append_results((result,))
        metrics.gauge("fx_analyzer_quality_state", 1,
                      instrument=result.instrument_type, state=result.state.value)
        LOGGER.info("quality evaluated", extra={
            "event": "quality_evaluated",
            "run_id": str(result.run_id) if result.run_id else None,
            "outcome": result.state.value,
            "error_context": {"instrument_type": result.instrument_type,
                              "rule_code": result.rule_code},
        })
        return result

    def _unknown(
        self, policy: ExpectationPolicy, instrument_id: UUID, start: date, end: date,
        evaluated_at: datetime, run_id: UUID | None, reason: str, **details: Any,
    ) -> QualityAssessment:
        return self._assessment(
            policy, instrument_id, start, end, evaluated_at, run_id,
            QualityState.UNKNOWN, ValidationSeverity.WARNING, (), (), set(),
            {"reason": reason, **details},
        )

    @staticmethod
    def _assessment(
        policy: ExpectationPolicy, instrument_id: UUID, start: date, end: date,
        evaluated_at: datetime, run_id: UUID | None, state: QualityState,
        severity: ValidationSeverity, missing: Sequence[Any], expected: Sequence[Any],
        available_dates: set[date], extra: Mapping[str, Any],
    ) -> QualityAssessment:
        expected_dates = [item.observation_date for item in expected]
        available_expected = sorted(set(expected_dates) & available_dates)
        details = {
            "calendar_id": policy.calendar_id,
            "release_cadence": policy.release_cadence.value,
            "expected_count": len(expected_dates),
            "missing_count": len(missing),
            "missing_dates": [item.observation_date.isoformat() for item in missing],
            "newest_expected_date": max(expected_dates).isoformat() if expected_dates else None,
            "newest_available_date": max(available_expected).isoformat() if available_expected else None,
            **extra,
        }
        return QualityAssessment(
            run_id=run_id, instrument_type=policy.instrument_type,
            instrument_id=instrument_id, rule_code="completeness_freshness",
            state=state, severity=severity, affected_start=start, affected_end=end,
            evaluated_at=evaluated_at, details=details,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluation timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)
