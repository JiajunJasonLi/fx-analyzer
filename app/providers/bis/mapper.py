from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.domain.candidates import PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, Frequency, RateType
from app.domain.normalization import normalize_frequency, normalize_rate_unit
from app.domain.provider import PublishedAbsence, ReferenceSnapshot, SourceLocator
from app.providers.base import ProviderContractError
from app.providers.bis.models import BISRecord, BISSeriesMapping


class BISMapper:
    def map(
        self, record: BISRecord, source: SourceLocator, mappings: ReferenceSnapshot
    ) -> PolicyRateCandidate | PublishedAbsence:
        mapping = self._resolve(record, mappings.values.get("bis_series", ()))
        attributes = {
            **dict(record.attributes),
            "dataflow": record.dataflow,
            "series_key": record.series_key,
            "economy": record.economy,
            "currency": record.currency,
            "source_unit": record.unit,
            "collection_indicator": record.collection_indicator,
            "dataset_version": record.dataset_version,
        }
        if record.value is None:
            return PublishedAbsence(
                instrument=mapping.complete_key,
                observation_date=record.observation_date,
                reason="published_absence",
                provider_attributes=attributes,
            )
        unit = normalize_rate_unit(record.unit)
        frequency = normalize_frequency(record.frequency)
        if unit is not CanonicalRateUnit.PERCENT_PER_YEAR or frequency is not Frequency.DAILY:
            raise ProviderContractError("unsupported BIS policy-rate semantics")
        return PolicyRateCandidate(
            series_id=mapping.series_id,
            observation_date=record.observation_date,
            value=record.value,
            unit=CanonicalRateUnit.PERCENT_PER_YEAR,
            frequency=Frequency.DAILY,
            rate_type=RateType.POLICY_RATE,
            tenor=None,
            retrieved_at=mappings.values["retrieved_at"],
            source=source,
            provider_publication_timestamp=record.publication_timestamp,
            provider_attributes=attributes,
        )

    @staticmethod
    def _resolve(record: BISRecord, configured: Iterable[Any]) -> BISSeriesMapping:
        candidates = []
        for value in configured:
            mapping = value if isinstance(value, BISSeriesMapping) else BISSeriesMapping(**dict(value))
            if mapping.enabled and mapping.complete_key == f"{record.dataflow}:{record.series_key}" and mapping.applies_on(record.observation_date):
                candidates.append(mapping)
        if len(candidates) != 1:
            raise ProviderContractError("BIS complete series key does not resolve uniquely")
        mapping = candidates[0]
        if mapping.economy != record.economy or mapping.currency != record.currency:
            raise ProviderContractError("BIS economy/currency mapping mismatch")
        return mapping
