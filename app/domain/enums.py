from enum import Enum


class StringEnum(str, Enum):
    pass


class ValidationSeverity(StringEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationState(StringEnum):
    VALID = "valid"
    VALID_WITH_WARNINGS = "valid_with_warnings"
    INVALID = "invalid"


class QuoteType(StringEnum):
    REFERENCE = "reference"


class RateType(StringEnum):
    POLICY_RATE = "policy_rate"


class CanonicalRateUnit(StringEnum):
    PERCENT_PER_YEAR = "percent_per_year"


class Frequency(StringEnum):
    DAILY = "daily"


class CandidateOutcome(StringEnum):
    INSERTED = "inserted"
    UNCHANGED = "unchanged"
    REVISED = "revised"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class QualityState(StringEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    NOT_DUE = "not_due"
    UNKNOWN = "unknown"
