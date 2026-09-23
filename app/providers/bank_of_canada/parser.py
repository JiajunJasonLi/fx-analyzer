from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.domain.provider import JSONValue, ParsedRecord, PublishedAbsence, RawPayload
from app.providers.base import ProviderParseError


@dataclass(frozen=True)
class ValetObservation:
    provider_symbol: str
    observation_date: date
    value: Decimal
    retrieved_at: datetime
    status_flags: Mapping[str, JSONValue] = field(default_factory=dict)
    series_detail: Mapping[str, JSONValue] = field(default_factory=dict)
    response_metadata: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ValetMalformedRecord:
    provider_symbol: str | None
    observation_date: date | None
    reason: str
    details: Mapping[str, JSONValue] = field(default_factory=dict)


ValetParsedValue = ValetObservation | PublishedAbsence | ValetMalformedRecord


def classify_missing_dates(
    *,
    requested_symbols: tuple[str, ...],
    start: date,
    end: date,
    parsed: tuple[ParsedRecord[ValetParsedValue], ...],
    weekend_days: tuple[int, ...] = (5, 6),
    holidays: tuple[date, ...] = (),
) -> tuple[PublishedAbsence, ...]:
    """Classify omitted dates without confusing calendar absences with failures."""
    present = {
        (getattr(item.value, "provider_symbol", None) or getattr(item.value, "instrument", None),
         getattr(item.value, "observation_date", None))
        for item in parsed
    }
    result: list[PublishedAbsence] = []
    current = start
    while current <= end:
        due = current.weekday() not in weekend_days and current not in holidays
        for symbol in requested_symbols:
            if (symbol, current) not in present:
                result.append(
                    PublishedAbsence(
                        instrument=symbol,
                        observation_date=current,
                        reason="omitted_expected_date" if due else "not_due",
                        provider_attributes={"calendar": "canada_business"},
                    )
                )
        current += timedelta(days=1)
    return tuple(result)


class ValetParser:
    """Parse Valet JSON while keeping record failures isolated."""

    def parse(self, payload: RawPayload) -> tuple[ParsedRecord[ValetParsedValue], ...]:
        document = self._load_document(payload)
        observations = document.get("observations")
        if not isinstance(observations, list):
            raise ProviderParseError(
                "Valet response observations must be a list",
                context={"endpoint_name": payload.request.endpoint_name},
            )
        details = document.get("seriesDetail", {})
        if details is None:
            details = {}
        if not isinstance(details, dict):
            raise ProviderParseError("Valet seriesDetail must be an object")
        response_metadata = {
            key: value
            for key, value in document.items()
            if key not in {"observations", "seriesDetail"}
        }
        parsed: list[ParsedRecord[ValetParsedValue]] = []
        for index, item in enumerate(observations):
            if not isinstance(item, dict):
                parsed.append(self._malformed(index, None, None, "observation_not_object", item))
                continue
            raw_date = item.get("d")
            try:
                observation_date = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
            except ValueError:
                observation_date = None
            series_items = [(key, value) for key, value in item.items() if key != "d"]
            if raw_date is None or observation_date is None:
                if not series_items:
                    parsed.append(self._malformed(index, None, None, "invalid_date", item))
                else:
                    parsed.extend(
                        self._malformed(index, symbol, None, "invalid_date", value)
                        for symbol, value in series_items
                    )
                continue
            for symbol, raw_value in series_items:
                parsed.append(
                    self._parse_value(
                        index, symbol, observation_date, raw_value, details, response_metadata, payload
                    )
                )
        return tuple(parsed)

    @staticmethod
    def _load_document(payload: RawPayload) -> dict[str, Any]:
        body = payload.body
        encoding = str(payload.response_metadata.get("content-encoding", "")).lower()
        if encoding == "gzip":
            try:
                body = gzip.decompress(body)
            except (OSError, EOFError) as exc:
                raise ProviderParseError("invalid gzip Valet response") from exc
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderParseError(
                "invalid Valet JSON", context={"endpoint_name": payload.request.endpoint_name}
            ) from exc
        if not isinstance(value, dict):
            raise ProviderParseError("Valet response must be an object")
        return value

    def _parse_value(
        self,
        index: int,
        symbol: str,
        observation_date: date,
        raw_value: object,
        details: Mapping[str, object],
        response_metadata: Mapping[str, JSONValue],
        payload: RawPayload,
    ) -> ParsedRecord[ValetParsedValue]:
        path = self._path(index, symbol)
        checksum = self._checksum(raw_value)
        if not isinstance(raw_value, dict):
            return self._malformed(index, symbol, observation_date, "series_value_not_object", raw_value)
        attributes = {key: value for key, value in raw_value.items() if key != "v"}
        source_value = raw_value.get("v")
        if source_value is None:
            return ParsedRecord(
                PublishedAbsence(symbol, observation_date, "unpublished", attributes), path, checksum
            )
        if not isinstance(source_value, str):
            return self._malformed(index, symbol, observation_date, "value_not_string", raw_value)
        try:
            numeric = Decimal(source_value)
            if not numeric.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            return self._malformed(index, symbol, observation_date, "invalid_decimal", raw_value)
        series_detail = details.get(symbol, {})
        if not isinstance(series_detail, dict):
            series_detail = {"unparsed_detail": series_detail}
        return ParsedRecord(
            ValetObservation(
                provider_symbol=symbol,
                observation_date=observation_date,
                value=numeric,
                retrieved_at=payload.retrieved_at,
                status_flags=attributes,
                series_detail=series_detail,
                response_metadata=response_metadata,
            ),
            path,
            checksum,
        )

    def _malformed(
        self,
        index: int,
        symbol: str | None,
        observation_date: date | None,
        reason: str,
        raw_value: object,
    ) -> ParsedRecord[ValetParsedValue]:
        path = self._path(index, symbol)
        return ParsedRecord(
            ValetMalformedRecord(symbol, observation_date, reason),
            path,
            self._checksum(raw_value),
        )

    @staticmethod
    def _path(index: int, symbol: str | None) -> str:
        base = f"observations[{index}]"
        return f"{base}.{symbol}" if symbol else base

    @staticmethod
    def _checksum(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()
