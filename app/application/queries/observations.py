from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql import Select

from app.database.models import (
    Currency,
    Economy,
    FxObservation,
    FxObservationVersion,
    FxPair,
    FxSeries,
    InterestRateSeries,
    PolicyRateObservation,
    PolicyRateObservationVersion,
    ProviderDataset,
)


class QueryValidationError(ValueError):
    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


class AmbiguousQueryError(QueryValidationError):
    pass


@dataclass(frozen=True)
class ObservationView:
    observation_id: UUID
    version_id: UUID
    version_number: int
    instrument_type: Literal["fx_pair", "policy_rate_series"]
    instrument_symbol: str
    observation_date: date
    value: Decimal
    unit: str
    classification: str
    tenor: str | None
    provider: str
    provider_series: str
    provider_publication_timestamp: datetime | None
    retrieved_at: datetime
    valid_from: datetime
    valid_to: datetime | None
    is_current: bool
    validation_state: str
    validation_flags: list[dict[str, Any]]
    run_id: UUID
    raw_record_id: UUID


@dataclass(frozen=True)
class ObservationPage:
    items: tuple[ObservationView, ...]
    next_cursor: str | None


def validate_history_range(start: date, end: date, *, maximum_days: int = 9132) -> None:
    if start > end:
        raise QueryValidationError("INVALID_DATE_RANGE", "start_date must not be after end_date", field="start_date")
    if start < date(1900, 1, 1):
        raise QueryValidationError("DATE_OUT_OF_BOUNDS", "start_date must be on or after 1900-01-01", field="start_date")
    if end > datetime.now(timezone.utc).date():
        raise QueryValidationError("DATE_OUT_OF_BOUNDS", "end_date must not be in the future", field="end_date")
    if (end - start).days + 1 > maximum_days:
        raise QueryValidationError("DATE_RANGE_TOO_LARGE", f"date range must not exceed {maximum_days} days", field="end_date")


def validate_page_size(page_size: int, *, maximum: int = 500) -> None:
    if page_size < 1 or page_size > maximum:
        raise QueryValidationError("INVALID_PAGE_SIZE", f"page_size must be between 1 and {maximum}", field="page_size")


class ObservationQueryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def fx_history(self, *, pair: str, start: date, end: date, as_of: datetime | None,
                   cursor: str | None, page_size: int) -> ObservationPage:
        validate_history_range(start, end)
        validate_page_size(page_size)
        symbol = _pair_symbol(pair)
        as_of = _utc(as_of or datetime.now(timezone.utc))
        query = self._fx_query(as_of).where(FxPair.symbol == symbol, FxObservation.observation_date.between(start, end))
        query = _after_cursor(query, FxObservation.observation_date, FxObservation.id, cursor)
        rows = self.session.execute(query.order_by(FxObservation.observation_date, FxObservation.id).limit(page_size + 1)).all()
        return _page(tuple(self._fx_view(row) for row in rows), page_size)

    def fx_latest(self, *, pair: str, as_of: datetime | None) -> ObservationView | None:
        symbol = _pair_symbol(pair)
        instant = _utc(as_of or datetime.now(timezone.utc))
        row = self.session.execute(
            self._fx_query(instant).where(FxPair.symbol == symbol)
            .order_by(FxObservation.observation_date.desc(), FxObservationVersion.provider_publication_timestamp.desc().nullslast(), FxObservationVersion.first_observed_at.desc())
            .limit(1)
        ).first()
        return self._fx_view(row) if row else None

    def policy_history(self, *, start: date, end: date, series: str | None,
                       economy: str | None, currency: str | None, as_of: datetime | None,
                       cursor: str | None, page_size: int) -> ObservationPage:
        validate_history_range(start, end)
        validate_page_size(page_size)
        filters = _policy_filters(series, economy, currency)
        instant = _utc(as_of or datetime.now(timezone.utc))
        query = self._policy_query(instant).where(
            PolicyRateObservation.observation_date.between(start, end), *filters
        )
        query = _after_cursor(query, PolicyRateObservation.observation_date, PolicyRateObservation.id, cursor)
        rows = self.session.execute(query.order_by(PolicyRateObservation.observation_date, PolicyRateObservation.id).limit(page_size + 1)).all()
        return _page(tuple(self._policy_view(row) for row in rows), page_size)

    def policy_latest(self, *, series: str | None, economy: str | None,
                      currency: str | None, as_of: datetime | None) -> ObservationView | None:
        filters = _policy_filters(series, economy, currency)
        instant = _utc(as_of or datetime.now(timezone.utc))
        series_ids = tuple(self.session.scalars(
            select(InterestRateSeries.id)
            .join(Economy, Economy.id == InterestRateSeries.economy_id)
            .join(Currency, Currency.id == InterestRateSeries.currency_id)
            .where(*filters).limit(2)
        ))
        if len(series_ids) > 1:
            raise AmbiguousQueryError("AMBIGUOUS_POLICY_RATE", "filters match multiple policy-rate series; provide a series or narrower filters")
        if not series_ids:
            return None
        row = self.session.execute(
            self._policy_query(instant).where(InterestRateSeries.id == series_ids[0])
            .order_by(PolicyRateObservation.observation_date.desc(), PolicyRateObservationVersion.provider_publication_timestamp.desc().nullslast(), PolicyRateObservationVersion.first_observed_at.desc())
            .limit(1)
        ).first()
        return self._policy_view(row) if row else None

    @staticmethod
    def _fx_query(as_of: datetime) -> Select[Any]:
        base = aliased(Currency)
        quote = aliased(Currency)
        return select(FxObservation, FxObservationVersion, FxSeries, FxPair, ProviderDataset, base, quote).join(
            FxObservationVersion, FxObservationVersion.observation_id == FxObservation.id
        ).join(FxSeries, FxSeries.id == FxObservation.fx_series_id).join(
            FxPair, FxPair.id == FxSeries.fx_pair_id
        ).join(ProviderDataset, ProviderDataset.id == FxSeries.provider_dataset_id).join(
            base, base.id == FxPair.base_currency_id
        ).join(quote, quote.id == FxPair.quote_currency_id).where(
            FxObservation.observation_date <= as_of.date(),
            FxObservationVersion.valid_from <= as_of,
            or_(FxObservationVersion.valid_to.is_(None), FxObservationVersion.valid_to > as_of),
            FxObservationVersion.validation_state.in_(("valid", "valid_with_warnings")),
        )

    @staticmethod
    def _policy_query(as_of: datetime) -> Select[Any]:
        return select(PolicyRateObservation, PolicyRateObservationVersion, InterestRateSeries, ProviderDataset, Economy, Currency).join(
            PolicyRateObservationVersion, PolicyRateObservationVersion.observation_id == PolicyRateObservation.id
        ).join(InterestRateSeries, InterestRateSeries.id == PolicyRateObservation.interest_rate_series_id).join(
            ProviderDataset, ProviderDataset.id == InterestRateSeries.provider_dataset_id
        ).join(Economy, Economy.id == InterestRateSeries.economy_id).join(
            Currency, Currency.id == InterestRateSeries.currency_id
        ).where(
            PolicyRateObservation.observation_date <= as_of.date(),
            PolicyRateObservationVersion.valid_from <= as_of,
            or_(PolicyRateObservationVersion.valid_to.is_(None), PolicyRateObservationVersion.valid_to > as_of),
            PolicyRateObservationVersion.validation_state.in_(("valid", "valid_with_warnings")),
        )

    @staticmethod
    def _fx_view(row: Any) -> ObservationView:
        observation, version, series, pair, dataset, base, quote = row
        return ObservationView(observation.id, version.id, version.version_number, "fx_pair", pair.symbol,
            observation.observation_date, version.value, f"{quote.code}_per_{base.code}", version.quote_type, None,
            dataset.provider_code, series.provider_symbol, version.provider_publication_timestamp,
            version.first_observed_at, version.valid_from, version.valid_to, version.valid_to is None,
            version.validation_state, version.validation_flags, version.originating_ingestion_run_id,
            version.originating_raw_record_id)

    @staticmethod
    def _policy_view(row: Any) -> ObservationView:
        observation, version, series, dataset, economy, currency = row
        return ObservationView(observation.id, version.id, version.version_number, "policy_rate_series",
            series.series_key, observation.observation_date, version.value, version.unit, version.rate_type, None,
            dataset.provider_code, series.series_key, version.provider_publication_timestamp,
            version.first_observed_at, version.valid_from, version.valid_to, version.valid_to is None,
            version.validation_state, version.validation_flags, version.originating_ingestion_run_id,
            version.originating_raw_record_id)


def _policy_filters(series: str | None, economy: str | None, currency: str | None) -> list[Any]:
    if not any((series, economy, currency)):
        raise QueryValidationError("IDENTIFYING_FILTER_REQUIRED", "provide series, economy, or currency")
    filters: list[Any] = []
    if series:
        filters.append(InterestRateSeries.series_key == series)
    if economy:
        filters.append(Economy.code == economy.upper())
    if currency:
        filters.append(Currency.code == currency.upper())
    return filters


def _pair_symbol(pair: str) -> str:
    symbol = pair.replace("/", "").strip().upper()
    if len(symbol) != 6 or not symbol.isalpha():
        raise QueryValidationError("INVALID_FX_PAIR", "pair must contain two three-letter currency codes", field="pair")
    return symbol


def _after_cursor(query: Select[Any], date_column: Any, id_column: Any, cursor: str | None) -> Select[Any]:
    if not cursor:
        return query
    cursor_date, cursor_id = decode_cursor(cursor)
    return query.where(or_(date_column > cursor_date, and_(date_column == cursor_date, id_column > cursor_id)))


def encode_cursor(value_date: date, value_id: UUID) -> str:
    raw = json.dumps([value_date.isoformat(), str(value_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[date, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        date_text, id_text = json.loads(raw)
        return date.fromisoformat(date_text), UUID(id_text)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise QueryValidationError("INVALID_CURSOR", "cursor is invalid", field="cursor") from exc


def _page(items: tuple[ObservationView, ...], page_size: int) -> ObservationPage:
    visible = items[:page_size]
    cursor = encode_cursor(visible[-1].observation_date, visible[-1].observation_id) if len(items) > page_size else None
    return ObservationPage(visible, cursor)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QueryValidationError("INVALID_AS_OF", "as_of must include a timezone offset", field="as_of")
    return value.astimezone(timezone.utc)
