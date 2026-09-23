from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TypeVar

from app.domain.enums import CanonicalRateUnit, Frequency, QuoteType, RateType


class NormalizationCode(str, Enum):
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_IDENTIFIER = "INVALID_IDENTIFIER"
    INVALID_OBSERVATION_DATE = "INVALID_OBSERVATION_DATE"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    UNSUPPORTED_RATE_UNIT = "UNSUPPORTED_RATE_UNIT"
    UNSUPPORTED_FREQUENCY = "UNSUPPORTED_FREQUENCY"
    UNSUPPORTED_CLASSIFICATION = "UNSUPPORTED_CLASSIFICATION"


class NormalizationError(ValueError):
    def __init__(self, code: NormalizationCode, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def normalize_identifier(value: object, *, field: str, uppercase: bool = False) -> str:
    if value is None or not str(value).strip():
        raise NormalizationError(NormalizationCode.MISSING_REQUIRED_FIELD, field, f"{field} is required")
    result = str(value).strip()
    return result.upper() if uppercase else result


def normalize_date(value: date | str, *, field: str = "observation_date") -> date:
    if isinstance(value, datetime):
        raise NormalizationError(NormalizationCode.INVALID_OBSERVATION_DATE, field, "datetime is not a date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(normalize_identifier(value, field=field))
    except ValueError as exc:
        raise NormalizationError(NormalizationCode.INVALID_OBSERVATION_DATE, field, "invalid ISO date") from exc


def normalize_decimal(value: Decimal | int | str, *, field: str = "value") -> Decimal:
    if value is None or isinstance(value, bool):
        raise NormalizationError(NormalizationCode.MISSING_REQUIRED_FIELD, field, f"{field} is required")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise NormalizationError(NormalizationCode.INVALID_NUMERIC_VALUE, field, "invalid decimal") from exc
    if not result.is_finite():
        raise NormalizationError(NormalizationCode.INVALID_NUMERIC_VALUE, field, "decimal must be finite")
    return result


def normalize_timestamp(value: datetime | str, *, field: str) -> tuple[datetime, str]:
    original = value.isoformat() if isinstance(value, datetime) else normalize_identifier(value, field=field)
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(original.replace("Z", "+00:00"))
    except ValueError as exc:
        raise NormalizationError(NormalizationCode.INVALID_TIMESTAMP, field, "invalid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NormalizationError(NormalizationCode.INVALID_TIMESTAMP, field, "timestamp requires an offset")
    return parsed.astimezone(timezone.utc), original


EnumT = TypeVar("EnumT", bound=Enum)


def _normalize_enum(value: object, enum_type: type[EnumT], code: NormalizationCode, field: str) -> EnumT:
    normalized = normalize_identifier(value, field=field).lower()
    try:
        return enum_type(normalized)
    except ValueError as exc:
        raise NormalizationError(code, field, f"unsupported {field}") from exc


def normalize_rate_unit(value: object) -> CanonicalRateUnit:
    aliases = {"percent": "percent_per_year", "percent per annum": "percent_per_year", "% p.a.": "percent_per_year"}
    normalized = normalize_identifier(value, field="unit").lower()
    return _normalize_enum(aliases.get(normalized, normalized), CanonicalRateUnit, NormalizationCode.UNSUPPORTED_RATE_UNIT, "unit")


def normalize_frequency(value: object) -> Frequency:
    aliases = {"d": "daily"}
    normalized = normalize_identifier(value, field="frequency").lower()
    return _normalize_enum(aliases.get(normalized, normalized), Frequency, NormalizationCode.UNSUPPORTED_FREQUENCY, "frequency")


def normalize_quote_type(value: object) -> QuoteType:
    return _normalize_enum(value, QuoteType, NormalizationCode.UNSUPPORTED_CLASSIFICATION, "quote_type")


def normalize_rate_type(value: object) -> RateType:
    return _normalize_enum(value, RateType, NormalizationCode.UNSUPPORTED_CLASSIFICATION, "rate_type")
