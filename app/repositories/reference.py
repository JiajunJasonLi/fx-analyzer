from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.reference import ReferenceConfiguration
from app.database.models import Currency, Economy, EconomyCurrency, FxPair, FxSeries, InterestRateSeries, ProviderDataset

Model = TypeVar("Model")


class SqlAlchemyReferenceDataRepository:
    """Reconcile reference configuration in the caller-owned transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.inserted = self.updated = self.disabled = 0

    def synchronize(self, config: ReferenceConfiguration) -> tuple[int, int, int]:
        currencies = self._currencies(config)
        economies = self._economies(config)
        self.session.flush()
        datasets = self._datasets(config)
        pairs = self._pairs(config, currencies)
        self.session.flush()
        self._relationships(config, economies, currencies)
        self._fx_series(config, datasets, pairs)
        self._rate_series(config, datasets, economies, currencies)
        self.session.flush()
        return self.inserted, self.updated, self.disabled

    def _currencies(self, config: ReferenceConfiguration) -> dict[str, Currency]:
        rows = self._by(Currency, lambda row: row.code)
        for item in config.currencies:
            values = {"name": item.name, "minor_units": item.minor_units, "is_active": item.enabled}
            rows[item.code] = self._upsert(rows.get(item.code), Currency(code=item.code, **values), values)
        self._disable(rows.values(), {item.code for item in config.currencies}, lambda row: row.code)
        return rows

    def _economies(self, config: ReferenceConfiguration) -> dict[str, Economy]:
        rows = self._by(Economy, lambda row: row.code)
        for item in config.economies:
            values = {"name": item.name, "iso_country_code": item.iso_country_code,
                      "time_zone": item.time_zone, "economy_type": item.economy_type,
                      "is_active": item.enabled}
            rows[item.code] = self._upsert(rows.get(item.code), Economy(code=item.code, **values), values)
        self._disable(rows.values(), {item.code for item in config.economies}, lambda row: row.code)
        return rows

    def _datasets(self, config: ReferenceConfiguration) -> dict[str, ProviderDataset]:
        key_fn = lambda row: f"{row.provider_code}:{row.dataset_code}"
        rows = self._by(ProviderDataset, key_fn)
        for item in config.provider_datasets:
            values = {"display_name": item.display_name, "configuration_reference": item.configuration_reference,
                      "license_url": item.license_url, "license_notes": item.license_notes,
                      "attribution_text": item.attribution_text,
                      "redistribution_restrictions": item.redistribution_policy,
                      "approval_state": item.approval_state, "is_active": item.enabled}
            rows[item.key] = self._upsert(rows.get(item.key), ProviderDataset(
                provider_code=item.provider_code, dataset_code=item.dataset_code, **values), values)
        self._disable(rows.values(), {item.key for item in config.provider_datasets}, key_fn)
        return rows

    def _pairs(self, config: ReferenceConfiguration, currencies: dict[str, Currency]) -> dict[str, FxPair]:
        rows = self._by(FxPair, lambda row: row.symbol)
        for item in config.fx_pairs:
            values = {"base_currency_id": currencies[item.base_currency].id,
                      "quote_currency_id": currencies[item.quote_currency].id, "is_active": item.enabled}
            rows[item.symbol] = self._upsert(rows.get(item.symbol), FxPair(symbol=item.symbol, **values), values)
        self._disable(rows.values(), {item.symbol for item in config.fx_pairs}, lambda row: row.symbol)
        return rows

    def _relationships(self, config: ReferenceConfiguration, economies: dict[str, Economy], currencies: dict[str, Currency]) -> None:
        rows = {(row.economy_id, row.currency_id, row.effective_from): row for row in self._all(EconomyCurrency)}
        for item in config.economy_currencies:
            key = (economies[item.economy].id, currencies[item.currency].id, item.effective_from)
            self._upsert(rows.get(key), EconomyCurrency(economy_id=key[0], currency_id=key[1],
                         effective_from=key[2], effective_to=item.effective_to), {"effective_to": item.effective_to})

    def _fx_series(self, config: ReferenceConfiguration, datasets: dict[str, ProviderDataset], pairs: dict[str, FxPair]) -> None:
        key_fn = lambda row: (row.provider_dataset_id, row.provider_symbol)
        rows = self._by(FxSeries, key_fn)
        configured = set()
        for item in config.fx_series:
            key = (datasets[item.dataset].id, item.provider_symbol)
            configured.add(key)
            values = {"fx_pair_id": pairs[item.pair].id, "frequency": item.frequency,
                      "quote_type": item.quote_type, "source_metadata": dict(item.source_metadata), "is_active": item.enabled}
            self._upsert(rows.get(key), FxSeries(provider_dataset_id=key[0], provider_symbol=key[1], **values), values)
        self._disable(rows.values(), configured, key_fn)

    def _rate_series(self, config: ReferenceConfiguration, datasets: dict[str, ProviderDataset],
                     economies: dict[str, Economy], currencies: dict[str, Currency]) -> None:
        key_fn = lambda row: (row.provider_dataset_id, row.dataflow_key, row.series_key)
        rows = self._by(InterestRateSeries, key_fn)
        configured = set()
        for item in config.interest_rate_series:
            key = (datasets[item.dataset].id, item.dataflow_key, item.series_key)
            configured.add(key)
            values = {"economy_id": economies[item.economy].id, "currency_id": currencies[item.currency].id,
                      "frequency": item.frequency, "unit": item.unit, "rate_type": item.rate_type,
                      "collection_indicator": item.collection_indicator, "title": item.title, "notes": item.notes,
                      "source_metadata": dict(item.source_metadata),
                      "publication_metadata": dict(item.publication_metadata), "is_active": item.enabled}
            self._upsert(rows.get(key), InterestRateSeries(provider_dataset_id=key[0], dataflow_key=key[1],
                         series_key=key[2], **values), values)
        self._disable(rows.values(), configured, key_fn)

    def _all(self, model: type[Model]) -> list[Model]:
        return list(self.session.scalars(select(model)))

    def _by(self, model: type[Model], key: Callable[[Model], Any]) -> dict[Any, Model]:
        return {key(row): row for row in self._all(model)}

    def _upsert(self, row: Model | None, new_row: Model, values: dict[str, Any]) -> Model:
        if row is None:
            self.session.add(new_row)
            self.inserted += 1
            return new_row
        changed = False
        for name, value in values.items():
            if getattr(row, name) != value:
                setattr(row, name, value)
                changed = True
        self.updated += int(changed)
        return row

    def _disable(self, rows: Iterable[Model], configured: set[Any], key: Callable[[Model], Any]) -> None:
        for row in rows:
            if key(row) not in configured and getattr(row, "is_active", False):
                setattr(row, "is_active", False)
                self.disabled += 1
