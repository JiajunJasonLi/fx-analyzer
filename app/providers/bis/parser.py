from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from app.domain.normalization import normalize_date, normalize_decimal, normalize_timestamp
from app.domain.provider import ParsedRecord, RawPayload
from app.providers.base import ProviderParseError
from app.providers.bis.models import BISRecord


_SERIES_ALIASES = {
    "FREQ": "frequency",
    "REF_AREA": "economy",
    "ECONOMY": "economy",
    "CURRENCY": "currency",
    "UNIT_MEASURE": "unit",
    "UNIT": "unit",
    "COLLECTION": "collection_indicator",
    "COLLECTION_INDICATOR": "collection_indicator",
    "INSTRUMENT": "instrument",
}
_OBSERVATION_ALIASES = {"TIME_PERIOD": "observation_date"}


class BISParser:
    """Parse SDMX-JSON or BIS bulk CSV without relying on dimension positions."""

    def __init__(self, *, dataflow: str, configured_dimension_order: Sequence[str] | None = None,
                 configured_currency: str | None = None,
                 configured_collection_indicator: str | None = None,
                 configured_unit: str | None = None) -> None:
        self._dataflow = dataflow
        self._configured_dimension_order = tuple(configured_dimension_order or ())
        self._configured_currency = configured_currency
        self._configured_collection_indicator = configured_collection_indicator
        self._configured_unit = configured_unit

    def parse(self, payload: RawPayload) -> Iterable[ParsedRecord[BISRecord]]:
        try:
            if "csv" in payload.media_type.lower():
                return tuple(self._parse_csv(payload))
            return tuple(self._parse_json(payload))
        except ProviderParseError:
            raise
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
            raise ProviderParseError(
                "invalid BIS response contract", context={"endpoint_name": payload.request.endpoint_name}
            ) from exc

    def _parse_json(self, payload: RawPayload) -> Iterable[ParsedRecord[BISRecord]]:
        body = payload.body
        content_encoding = payload.response_metadata.get("content-encoding", "").lower()
        if content_encoding == "gzip":
            try:
                body = gzip.decompress(body)
            except (OSError, EOFError) as exc:
                raise ProviderParseError("invalid gzip-encoded BIS response") from exc
        elif content_encoding not in ("", "identity"):
            raise ProviderParseError("unsupported BIS content encoding")
        document = json.loads(body.decode("utf-8"), parse_float=str, parse_int=str)
        content = document.get("data", document)
        if not isinstance(content, Mapping):
            raise ProviderParseError("BIS response data must be an object")
        structures = content.get("structure", {}).get("dimensions", {})
        series_dimensions = self._dimensions(structures.get("series"), "series")
        observation_dimensions = self._dimensions(structures.get("observation"), "observation")
        if not series_dimensions:
            raise ProviderParseError("BIS structure is missing named series dimensions")
        time_positions = [i for i, (name, _) in enumerate(observation_dimensions) if _OBSERVATION_ALIASES.get(name.upper()) == "observation_date"]
        if len(time_positions) != 1:
            raise ProviderParseError("BIS structure must define TIME_PERIOD exactly once")
        # ``meta.datasetId`` is a volatile response identifier in the live BIS
        # API, not a dataset revision, and must never affect fingerprints.
        dataset_version = self._first(document, "datasetVersion", "version") or payload.response_metadata.get("dataset-version")
        # BIS ``meta.prepared`` describes response generation, not an
        # observation publication instant. It remains preserved in raw bytes
        # and must not enter canonical fingerprints.
        publication = self._timestamp_or_none(self._first(document, "publicationTimestamp"))
        attributes = self._attribute_definitions(content.get("structure", {}).get("attributes", {}))
        datasets = content.get("dataSets")
        if not isinstance(datasets, list):
            raise ProviderParseError("BIS response is missing dataSets")
        for dataset_index, dataset in enumerate(datasets):
            series_collection = dataset.get("series", {})
            if not isinstance(series_collection, dict):
                raise ProviderParseError("BIS dataSet series must be an object")
            for encoded_key, series in series_collection.items():
                dimensions = self._decode_key(encoded_key, series_dimensions)
                series_attrs = self._decode_attributes(series.get("attributes", []), attributes.get("series", ()))
                named_values = {**dimensions, **series_attrs}
                canonical = {_SERIES_ALIASES.get(key.upper(), key.lower()): value for key, value in named_values.items()}
                if self._configured_currency is not None:
                    canonical.setdefault("currency", self._configured_currency)
                if self._configured_unit is not None:
                    canonical.setdefault("unit", self._configured_unit)
                if self._configured_collection_indicator is not None:
                    canonical.setdefault("collection_indicator", self._configured_collection_indicator)
                required = {"frequency", "economy", "currency", "unit", "collection_indicator"}
                if not required.issubset(canonical):
                    raise ProviderParseError("BIS series is missing required named dimensions or attributes")
                key_order = self._configured_dimension_order or tuple(name for name, _ in series_dimensions)
                try:
                    full_key = ".".join(named_values[name] for name in key_order)
                except KeyError as exc:
                    raise ProviderParseError("configured BIS key dimension is absent") from exc
                observations = series.get("observations", {})
                if not isinstance(observations, dict):
                    raise ProviderParseError("BIS observations must be an object")
                for observation_key, observation in observations.items():
                    obs_values = self._decode_key(observation_key, observation_dimensions)
                    observation_date = normalize_date(obs_values[observation_dimensions[time_positions[0]][0]])
                    if not isinstance(observation, list) or not observation:
                        raise ProviderParseError("BIS observation must be a non-empty array")
                    raw_value = observation[0]
                    value = None if _is_published_absence(raw_value) else normalize_decimal(raw_value)
                    obs_attrs = self._decode_attributes(observation[1:], attributes.get("observation", ()))
                    merged = {**dimensions, **series_attrs, **obs_attrs}
                    record_path = f"dataSets[{dataset_index}].series[{encoded_key}].observations[{observation_key}]"
                    yield self._parsed(
                        record_path,
                        BISRecord(
                            dataflow=self._dataflow,
                            series_key=full_key,
                            economy=canonical["economy"],
                            currency=canonical["currency"],
                            frequency=canonical["frequency"],
                            unit=canonical["unit"],
                            collection_indicator=canonical["collection_indicator"],
                            observation_date=observation_date,
                            value=value,
                            publication_timestamp=publication,
                            dataset_version=str(dataset_version) if dataset_version is not None else None,
                            attributes=merged,
                        ),
                    )

    def _parse_csv(self, payload: RawPayload) -> Iterable[ParsedRecord[BISRecord]]:
        reader = csv.DictReader(io.StringIO(payload.body.decode("utf-8-sig")))
        if reader.fieldnames is None:
            raise ProviderParseError("BIS bulk CSV has no header")
        names = {name.upper(): name for name in reader.fieldnames}
        required = {"FREQ", "REF_AREA", "CURRENCY", "UNIT_MEASURE", "COLLECTION", "TIME_PERIOD", "OBS_VALUE"}
        if not required.issubset(names):
            raise ProviderParseError("BIS bulk CSV is missing required named columns")
        key_columns = self._configured_dimension_order or ("FREQ", "REF_AREA")
        for row_index, row in enumerate(reader, start=2):
            dimensions = {name: row[names[name]] for name in key_columns}
            full_key = ".".join(dimensions[name] for name in key_columns)
            value_text = row[names["OBS_VALUE"]]
            publication_text = row.get(names.get("PUBLICATION_TIMESTAMP", ""), "")
            known = required | set(key_columns) | {"PUBLICATION_TIMESTAMP", "DATASET_VERSION"}
            attributes = {key: value for key, value in row.items() if key.upper() not in known and value not in (None, "")}
            record = BISRecord(
                dataflow=self._dataflow,
                series_key=full_key,
                economy=row[names["REF_AREA"]],
                currency=row[names["CURRENCY"]],
                frequency=row[names["FREQ"]],
                unit=row[names["UNIT_MEASURE"]],
                collection_indicator=row[names["COLLECTION"]],
                observation_date=normalize_date(row[names["TIME_PERIOD"]]),
                value=None if value_text.strip() == "" else normalize_decimal(value_text),
                publication_timestamp=self._timestamp_or_none(publication_text),
                dataset_version=row.get(names.get("DATASET_VERSION", "")) or payload.response_metadata.get("dataset-version"),
                attributes={**dimensions, **attributes},
            )
            yield self._parsed(f"rows[{row_index}]", record)

    @staticmethod
    def _dimensions(value: Any, level: str) -> tuple[tuple[str, Sequence[Any]], ...]:
        if not isinstance(value, list):
            raise ProviderParseError(f"BIS {level} dimensions must be an array")
        result = []
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("values"), list):
                raise ProviderParseError(f"invalid BIS {level} dimension")
            result.append((item["id"], item["values"]))
        return tuple(result)

    @staticmethod
    def _decode_key(encoded: str, dimensions: Sequence[tuple[str, Sequence[Any]]]) -> dict[str, str]:
        indices = encoded.split(":")
        if len(indices) != len(dimensions):
            raise ProviderParseError("BIS dimension key length does not match structure")
        result = {}
        for raw_index, (name, values) in zip(indices, dimensions):
            try:
                member = values[int(raw_index)]
                result[name] = str(member.get("id", member.get("name")))
            except (ValueError, IndexError, TypeError, AttributeError) as exc:
                raise ProviderParseError("invalid BIS dimension member index") from exc
        return result

    @staticmethod
    def _attribute_definitions(value: Any) -> dict[str, tuple[tuple[str, Sequence[Any]], ...]]:
        result = {}
        if not isinstance(value, dict):
            return result
        for level in ("series", "observation"):
            entries = value.get(level, [])
            if isinstance(entries, list):
                result[level] = tuple((item["id"], item.get("values", ())) for item in entries if isinstance(item, dict) and "id" in item)
        return result

    @staticmethod
    def _decode_attributes(values: Any, definitions: Sequence[tuple[str, Sequence[Any]]]) -> dict[str, Any]:
        if not isinstance(values, list):
            return {}
        result = {}
        for index, value_index in enumerate(values):
            if value_index is None or index >= len(definitions):
                continue
            name, members = definitions[index]
            try:
                member = members[int(value_index)]
                result[name] = member.get("id", member.get("name"))
            except (ValueError, IndexError, TypeError, AttributeError):
                result[name] = value_index
        return result

    @staticmethod
    def _first(document: Mapping[str, Any], *keys: str) -> Any:
        header = document.get("header", {})
        meta = document.get("meta", {})
        for source in (header, meta, document):
            for key in keys:
                if isinstance(source, Mapping) and source.get(key) is not None:
                    return source[key]
        return None

    @staticmethod
    def _timestamp_or_none(value: Any, *, assume_utc: bool = False) -> datetime | None:
        if value in (None, ""):
            return None
        if assume_utc and isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return parsed.replace(tzinfo=timezone.utc)
        return normalize_timestamp(value, field="publication_timestamp")[0]

    @staticmethod
    def _parsed(path: str, record: BISRecord) -> ParsedRecord[BISRecord]:
        checksum = hashlib.sha256(repr(record).encode("utf-8")).hexdigest()
        return ParsedRecord(value=record, record_path=path, record_checksum=checksum)


def _is_published_absence(value: Any) -> bool:
    return value is None or (
        isinstance(value, str)
        and value.strip().lower() in {"nan", "na", "n/a"}
    )
