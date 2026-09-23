from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from app.config.reference import ReferenceConfiguration


class ReleaseCadence(str, Enum):
    DAILY_BUSINESS = "daily_business"
    WEEKLY = "weekly"


@dataclass(frozen=True)
class BusinessCalendar:
    code: str
    version: str
    time_zone: str
    weekend_days: frozenset[int]
    holidays: frozenset[date]
    effective_from: date
    effective_to: date | None = None

    def covers(self, value: date) -> bool:
        return self.effective_from <= value and (self.effective_to is None or value <= self.effective_to)

    def is_business_day(self, value: date) -> bool:
        return self.covers(value) and value.weekday() not in self.weekend_days and value not in self.holidays


@dataclass(frozen=True)
class ExpectationPolicy:
    instrument_id: str
    instrument_type: str
    observation_frequency: str
    calendar_id: str
    publication_time_zone: str
    publication_time: time
    release_cadence: ReleaseCadence
    release_weekdays: frozenset[int]
    grace_period: timedelta
    stale_after: timedelta
    effective_from: date
    effective_to: date | None = None

    def applies_on(self, value: date) -> bool:
        return self.effective_from <= value and (self.effective_to is None or value <= self.effective_to)


@dataclass(frozen=True)
class ExpectedObservation:
    observation_date: date
    due_at: datetime


def load_quality_configuration(
    configuration: ReferenceConfiguration,
) -> tuple[dict[str, BusinessCalendar], tuple[ExpectationPolicy, ...]]:
    calendars = {
        item.code: BusinessCalendar(
            code=item.code, version=item.version, time_zone=item.time_zone,
            weekend_days=frozenset(item.weekend_days), holidays=frozenset(item.holidays),
            effective_from=item.effective_from, effective_to=item.effective_to,
        )
        for item in configuration.calendars
    }
    policies = tuple(
        ExpectationPolicy(
            instrument_id=item.instrument_key, instrument_type=item.instrument_type,
            observation_frequency=item.observation_frequency, calendar_id=item.calendar,
            publication_time_zone=item.publication_time_zone,
            publication_time=item.publication_time,
            release_cadence=ReleaseCadence(item.release_cadence),
            release_weekdays=frozenset(item.release_weekdays),
            grace_period=item.grace_period, stale_after=item.stale_after,
            effective_from=item.effective_from, effective_to=item.effective_to,
        )
        for item in configuration.expectation_policies
    )
    return calendars, policies


def generate_expectations(
    policy: ExpectationPolicy,
    calendar: BusinessCalendar,
    start: date,
    end: date,
) -> tuple[ExpectedObservation, ...]:
    if start > end:
        raise ValueError("expectation start must not exceed end")
    if policy.observation_frequency != "daily":
        raise ValueError("Phase 1 supports only daily observation expectations")
    if policy.calendar_id != calendar.code:
        raise ValueError("expectation policy references a different calendar")
    zone = ZoneInfo(policy.publication_time_zone)
    result: list[ExpectedObservation] = []
    current = start
    while current <= end:
        if policy.applies_on(current) and calendar.is_business_day(current):
            release_date = _release_date(current, policy, calendar)
            local_due = datetime.combine(release_date, policy.publication_time, tzinfo=zone)
            result.append(ExpectedObservation(current, (local_due + policy.grace_period).astimezone(timezone.utc)))
        current += timedelta(days=1)
    return tuple(result)


def _release_date(value: date, policy: ExpectationPolicy, calendar: BusinessCalendar) -> date:
    if policy.release_cadence is ReleaseCadence.DAILY_BUSINESS:
        return value
    if not policy.release_weekdays:
        raise ValueError("weekly release cadence requires at least one release weekday")
    candidate = value
    for _ in range(14):
        if candidate.weekday() in policy.release_weekdays and calendar.is_business_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise ValueError("no valid release date found within two weeks")
