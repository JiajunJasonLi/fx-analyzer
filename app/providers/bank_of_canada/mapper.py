from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.domain.candidates import FxObservationCandidate
from app.domain.enums import QuoteType
from app.domain.provider import JSONValue, ReferenceSnapshot, SourceLocator
from app.providers.base import ProviderContractError
from app.providers.bank_of_canada.parser import ValetObservation


@dataclass(frozen=True)
class ValetSeriesMapping:
    series_id: UUID
    provider_symbol: str
    pair_symbol: str
    base_currency: str
    quote_currency: str
    enabled: bool = True
    source_metadata: Mapping[str, JSONValue] = field(default_factory=dict)


class ValetMapper:
    def map(
        self,
        record: ValetObservation,
        source: SourceLocator,
        mappings: ReferenceSnapshot,
    ) -> FxObservationCandidate:
        mapping = self._resolve(record.provider_symbol, mappings)
        if mapping.quote_currency != "CAD" or mapping.base_currency == "CAD":
            raise ProviderContractError(
                "Bank of Canada FX mapping has invalid orientation",
                context={"provider_symbol": record.provider_symbol},
            )
        attributes: dict[str, Any] = {
            "provider_symbol": record.provider_symbol,
            "pair_symbol": mapping.pair_symbol,
            "base_currency": mapping.base_currency,
            "quote_currency": mapping.quote_currency,
            "classification": "daily_indicative_average",
            "status_flags": dict(record.status_flags),
            "series_detail": dict(record.series_detail),
            "response_metadata": dict(record.response_metadata),
            **dict(mapping.source_metadata),
        }
        return FxObservationCandidate(
            series_id=mapping.series_id,
            observation_date=record.observation_date,
            value=record.value,
            quote_type=QuoteType.REFERENCE,
            retrieved_at=record.retrieved_at,
            source=source,
            provider_attributes=attributes,
        )

    @staticmethod
    def _resolve(symbol: str, snapshot: ReferenceSnapshot) -> ValetSeriesMapping:
        raw = snapshot.values.get(symbol)
        candidates: Sequence[object]
        if isinstance(raw, (list, tuple)):
            candidates = raw
        elif raw is None:
            candidates = ()
        else:
            candidates = (raw,)
        enabled = [item for item in candidates if isinstance(item, ValetSeriesMapping) and item.enabled]
        if len(enabled) != 1:
            raise ProviderContractError(
                "Bank of Canada series must map to exactly one enabled FX series",
                context={
                    "code": "UNKNOWN_PROVIDER_SERIES" if not enabled else "AMBIGUOUS_PROVIDER_SERIES",
                    "provider_symbol": symbol,
                },
            )
        return enabled[0]
