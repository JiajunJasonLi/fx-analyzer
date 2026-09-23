from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")
ISO_COUNTRY = re.compile(r"^[A-Z]{2}$")


class ConfigurationError(ValueError):
    """Raised when declarative reference configuration is inconsistent."""


@dataclass(frozen=True)
class CurrencyConfig:
    code: str
    name: str
    minor_units: int | None = None
    enabled: bool = True


@dataclass(frozen=True)
class EconomyConfig:
    code: str
    name: str
    time_zone: str
    economy_type: str = "country"
    iso_country_code: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class EconomyCurrencyConfig:
    economy: str
    currency: str
    effective_from: date
    effective_to: date | None = None


@dataclass(frozen=True)
class FxPairConfig:
    symbol: str
    base_currency: str
    quote_currency: str
    enabled: bool = True


@dataclass(frozen=True)
class ProviderSettingsConfig:
    base_url: str
    endpoint_template: str
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    max_range_days: int = 366


@dataclass(frozen=True)
class ProviderDatasetConfig:
    provider_code: str
    dataset_code: str
    display_name: str
    configuration_reference: str
    approval_state: str
    retention_permitted: bool
    redistribution_policy: str
    license_url: str | None = None
    license_notes: str | None = None
    attribution_text: str | None = None
    enabled: bool = True
    settings: ProviderSettingsConfig | None = None

    @property
    def key(self) -> str:
        return f"{self.provider_code}:{self.dataset_code}"


@dataclass(frozen=True)
class FxSeriesConfig:
    stable_key: str
    dataset: str
    provider_symbol: str
    pair: str
    frequency: str = "daily"
    quote_type: str = "reference"
    enabled: bool = True
    source_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterestRateSeriesConfig:
    stable_key: str
    dataset: str
    economy: str
    currency: str
    dataflow_key: str
    series_key: str
    collection_indicator: str
    title: str
    frequency: str = "daily"
    unit: str = "percent_per_year"
    rate_type: str = "policy_rate"
    enabled: bool = True
    notes: str | None = None
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    publication_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CalendarConfig:
    code: str
    time_zone: str
    weekend_days: tuple[int, ...]
    holidays: tuple[date, ...] = ()
    release_weekdays: tuple[int, ...] = ()
    version: str = "1"
    effective_from: date = date(1900, 1, 1)
    effective_to: date | None = None


@dataclass(frozen=True)
class ExpectationPolicyConfig:
    instrument_type: str
    instrument_key: str
    observation_frequency: str
    calendar: str
    publication_time_zone: str
    publication_time: time
    release_cadence: str
    release_weekdays: tuple[int, ...]
    grace_period: timedelta
    stale_after: timedelta
    effective_from: date
    effective_to: date | None = None


@dataclass(frozen=True)
class ReferenceConfiguration:
    currencies: tuple[CurrencyConfig, ...]
    economies: tuple[EconomyConfig, ...]
    economy_currencies: tuple[EconomyCurrencyConfig, ...]
    fx_pairs: tuple[FxPairConfig, ...]
    provider_datasets: tuple[ProviderDatasetConfig, ...]
    fx_series: tuple[FxSeriesConfig, ...]
    interest_rate_series: tuple[InterestRateSeriesConfig, ...]
    calendars: tuple[CalendarConfig, ...]
    expectation_policies: tuple[ExpectationPolicyConfig, ...] = ()

    @property
    def checksum(self) -> str:
        canonical = _canonicalize(asdict(self))
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def assert_ingestion_allowed(self, dataset_key: str) -> None:
        dataset = next((item for item in self.provider_datasets if item.key == dataset_key), None)
        if dataset is None:
            raise ConfigurationError(f"unknown provider dataset: {dataset_key}")
        if not dataset.enabled:
            raise ConfigurationError(f"provider dataset is disabled: {dataset_key}")
        if dataset.approval_state != "approved":
            raise ConfigurationError(f"license is not approved for dataset: {dataset_key}")
        if not dataset.retention_permitted:
            raise ConfigurationError(f"raw-data retention is not permitted for dataset: {dataset_key}")
        if not dataset.redistribution_policy.strip():
            raise ConfigurationError(f"redistribution policy is missing for dataset: {dataset_key}")


def load_reference_configuration(path: str | Path) -> ReferenceConfiguration:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot load configuration {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("configuration root must be a mapping")
    allowed = {
        "currencies", "economies", "economy_currencies", "fx_pairs",
        "provider_datasets", "fx_series", "interest_rate_series", "calendars",
        "expectation_policies",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigurationError(f"unknown configuration keys: {', '.join(unknown)}")
    try:
        configuration = ReferenceConfiguration(
            currencies=_items(raw, "currencies", CurrencyConfig),
            economies=_items(raw, "economies", EconomyConfig),
            economy_currencies=_items(raw, "economy_currencies", EconomyCurrencyConfig),
            fx_pairs=_items(raw, "fx_pairs", FxPairConfig),
            provider_datasets=_datasets(raw),
            fx_series=_items(raw, "fx_series", FxSeriesConfig),
            interest_rate_series=_items(raw, "interest_rate_series", InterestRateSeriesConfig),
            calendars=_calendars(raw),
            expectation_policies=_expectation_policies(raw),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid configuration shape: {exc}") from exc
    _validate(configuration)
    return configuration


def _items(raw: Mapping[str, Any], key: str, model: type[Any]) -> tuple[Any, ...]:
    values = raw.get(key, [])
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise ConfigurationError(f"{key} must be a list of mappings")
    return tuple(model(**value) for value in values)


def _datasets(raw: Mapping[str, Any]) -> tuple[ProviderDatasetConfig, ...]:
    values = raw.get("provider_datasets", [])
    if not isinstance(values, list):
        raise ConfigurationError("provider_datasets must be a list")
    result = []
    for value in values:
        item = dict(value)
        settings = item.get("settings")
        item["settings"] = ProviderSettingsConfig(**settings) if settings else None
        result.append(ProviderDatasetConfig(**item))
    return tuple(result)


def _calendars(raw: Mapping[str, Any]) -> tuple[CalendarConfig, ...]:
    values = raw.get("calendars", [])
    return tuple(CalendarConfig(
        **{**value,
           "weekend_days": tuple(value.get("weekend_days", [])),
           "holidays": tuple(value.get("holidays", [])),
           "release_weekdays": tuple(value.get("release_weekdays", []))}
    ) for value in values)


def _expectation_policies(raw: Mapping[str, Any]) -> tuple[ExpectationPolicyConfig, ...]:
    values = raw.get("expectation_policies", [])
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise ConfigurationError("expectation_policies must be a list of mappings")
    policies = []
    for value in values:
        item = dict(value)
        try:
            item["publication_time"] = time.fromisoformat(str(item["publication_time"]))
            item["release_weekdays"] = tuple(item.get("release_weekdays", ()))
            item["grace_period"] = timedelta(minutes=int(item.pop("grace_minutes", 0)))
            item["stale_after"] = timedelta(days=int(item.pop("stale_after_days", 0)))
            policies.append(ExpectationPolicyConfig(**item))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"invalid expectation policy: {exc}") from exc
    return tuple(policies)


def _validate(config: ReferenceConfiguration) -> None:
    _unique((item.code for item in config.currencies), "currency code")
    _unique((item.code for item in config.economies), "economy code")
    _unique((item.symbol for item in config.fx_pairs), "FX pair symbol")
    _unique((item.key for item in config.provider_datasets), "provider dataset")
    _unique((item.stable_key for item in (*config.fx_series, *config.interest_rate_series)), "series stable key")
    _unique((item.code for item in config.calendars), "calendar code")
    _unique(((item.instrument_type, item.instrument_key) for item in config.expectation_policies), "expectation policy")
    currency_codes = {item.code for item in config.currencies}
    economy_codes = {item.code for item in config.economies}
    datasets = {item.key for item in config.provider_datasets}
    pair_symbols = {item.symbol for item in config.fx_pairs}
    for item in config.currencies:
        if not ISO_CURRENCY.fullmatch(item.code):
            raise ConfigurationError(f"invalid ISO currency code: {item.code}")
        if item.minor_units is not None and item.minor_units < 0:
            raise ConfigurationError(f"minor_units must be non-negative: {item.code}")
    for item in config.economies:
        if not isinstance(item.code, str) or not item.code.strip():
            raise ConfigurationError(f"invalid economy code: {item.code!r}")
        if item.iso_country_code and not ISO_COUNTRY.fullmatch(item.iso_country_code):
            raise ConfigurationError(f"invalid ISO country code: {item.iso_country_code}")
        if item.economy_type not in {"country", "currency_union"}:
            raise ConfigurationError(f"invalid economy_type: {item.economy_type}")
        try:
            ZoneInfo(item.time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"invalid time zone: {item.time_zone}") from exc
    for item in config.economy_currencies:
        _reference(item.economy, economy_codes, "economy")
        _reference(item.currency, currency_codes, "currency")
        if item.effective_to and item.effective_to < item.effective_from:
            raise ConfigurationError(f"invalid effective dates: {item.economy}/{item.currency}")
    _validate_no_overlaps(config.economy_currencies)
    for item in config.fx_pairs:
        _reference(item.base_currency, currency_codes, "base currency")
        _reference(item.quote_currency, currency_codes, "quote currency")
        if item.base_currency == item.quote_currency:
            raise ConfigurationError(f"FX pair currencies must differ: {item.symbol}")
        if item.symbol != item.base_currency + item.quote_currency:
            raise ConfigurationError(f"FX pair symbol does not match orientation: {item.symbol}")
    for item in config.provider_datasets:
        if item.approval_state not in {"pending", "approved", "rejected"}:
            raise ConfigurationError(f"invalid approval state: {item.key}")
        if item.settings is None:
            raise ConfigurationError(f"provider settings are missing: {item.key}")
        if not item.settings.base_url.startswith("https://"):
            raise ConfigurationError(f"provider base URL must use HTTPS: {item.key}")
        if not item.settings.endpoint_template.strip():
            raise ConfigurationError(f"provider endpoint template is empty: {item.key}")
        if item.settings.timeout_seconds <= 0 or item.settings.max_attempts <= 0 or item.settings.max_range_days <= 0:
            raise ConfigurationError(f"provider request limits must be positive: {item.key}")
    symbols: set[tuple[str, str]] = set()
    keys: set[tuple[str, str, str]] = set()
    for item in config.fx_series:
        _reference(item.dataset, datasets, "dataset")
        _reference(item.pair, pair_symbols, "FX pair")
        pair = next(pair for pair in config.fx_pairs if pair.symbol == item.pair)
        dataset = next(dataset for dataset in config.provider_datasets if dataset.key == item.dataset)
        if item.enabled and (not pair.enabled or not dataset.enabled):
            raise ConfigurationError(f"enabled FX series references a disabled item: {item.stable_key}")
        if item.enabled and pair.quote_currency != "CAD":
            raise ConfigurationError(f"enabled Bank of Canada pair must quote CAD: {item.pair}")
        if item.frequency != "daily" or item.quote_type != "reference":
            raise ConfigurationError(f"invalid Phase 1 FX semantics: {item.stable_key}")
        _add_unique(symbols, (item.dataset, item.provider_symbol), "provider symbol")
    relationships = {(item.economy, item.currency) for item in config.economy_currencies}
    for item in config.interest_rate_series:
        _reference(item.dataset, datasets, "dataset")
        _reference(item.economy, economy_codes, "economy")
        _reference(item.currency, currency_codes, "currency")
        if (item.economy, item.currency) not in relationships:
            raise ConfigurationError(f"missing economy/currency relationship: {item.economy}/{item.currency}")
        dataset = next(dataset for dataset in config.provider_datasets if dataset.key == item.dataset)
        economy = next(economy for economy in config.economies if economy.code == item.economy)
        currency = next(currency for currency in config.currencies if currency.code == item.currency)
        if item.enabled and (not dataset.enabled or not economy.enabled or not currency.enabled):
            raise ConfigurationError(f"enabled policy series references a disabled item: {item.stable_key}")
        if item.frequency != "daily" or item.unit != "percent_per_year" or item.rate_type != "policy_rate":
            raise ConfigurationError(f"invalid Phase 1 policy-rate semantics: {item.stable_key}")
        _add_unique(keys, (item.dataset, item.dataflow_key, item.series_key), "BIS series key")
    for item in config.calendars:
        try:
            ZoneInfo(item.time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"invalid calendar time zone: {item.time_zone}") from exc
        if any(day not in range(7) for day in (*item.weekend_days, *item.release_weekdays)):
            raise ConfigurationError(f"calendar weekdays must be between 0 and 6: {item.code}")
        if item.effective_to and item.effective_to < item.effective_from:
            raise ConfigurationError(f"invalid calendar effective dates: {item.code}")
    calendar_codes = {item.code for item in config.calendars}
    series_keys = {item.stable_key for item in (*config.fx_series, *config.interest_rate_series)}
    for item in config.expectation_policies:
        if item.instrument_type not in {"fx_pair", "policy_rate_series"}:
            raise ConfigurationError(f"invalid expectation instrument type: {item.instrument_type}")
        _reference(item.instrument_key, series_keys, "expectation instrument")
        _reference(item.calendar, calendar_codes, "expectation calendar")
        if item.observation_frequency != "daily" or item.release_cadence not in {"daily_business", "weekly"}:
            raise ConfigurationError(f"invalid Phase 1 expectation cadence: {item.instrument_key}")
        if item.release_cadence == "weekly" and not item.release_weekdays:
            raise ConfigurationError(f"weekly expectation has no release weekday: {item.instrument_key}")
        if any(day not in range(7) for day in item.release_weekdays):
            raise ConfigurationError(f"expectation weekdays must be between 0 and 6: {item.instrument_key}")
        if item.grace_period < timedelta(0) or item.stale_after < timedelta(0):
            raise ConfigurationError(f"expectation durations must be non-negative: {item.instrument_key}")
        if item.effective_to and item.effective_to < item.effective_from:
            raise ConfigurationError(f"invalid expectation effective dates: {item.instrument_key}")
        try:
            ZoneInfo(item.publication_time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"invalid expectation time zone: {item.instrument_key}") from exc
    enabled_series = {
        item.stable_key for item in (*config.fx_series, *config.interest_rate_series) if item.enabled
    }
    configured_expectations = {item.instrument_key for item in config.expectation_policies}
    missing_expectations = sorted(enabled_series - configured_expectations)
    if missing_expectations:
        raise ConfigurationError(
            f"missing expectation policy for enabled series: {', '.join(missing_expectations)}"
        )


def _unique(values: Any, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ConfigurationError(f"duplicate {label}: {value}")
        seen.add(value)


def _add_unique(seen: set[Any], value: Any, label: str) -> None:
    if value in seen:
        raise ConfigurationError(f"duplicate {label}: {'/'.join(value)}")
    seen.add(value)


def _reference(value: str, valid: set[str], label: str) -> None:
    if value not in valid:
        raise ConfigurationError(f"unknown {label}: {value}")


def _validate_no_overlaps(items: tuple[EconomyCurrencyConfig, ...]) -> None:
    groups: dict[tuple[str, str], list[EconomyCurrencyConfig]] = {}
    for item in items:
        groups.setdefault((item.economy, item.currency), []).append(item)
    for key, periods in groups.items():
        ordered = sorted(periods, key=lambda value: value.effective_from)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.effective_to is None or current.effective_from <= previous.effective_to:
                raise ConfigurationError(f"overlapping effective dates: {'/'.join(key)}")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value
