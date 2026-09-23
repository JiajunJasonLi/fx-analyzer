from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.application.queries.observations import ObservationPage, ObservationView


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def observation(value: ObservationView) -> dict[str, Any]:
    return {
        "observation_id": str(value.observation_id), "version_id": str(value.version_id),
        "version_number": value.version_number,
        "instrument": {"type": value.instrument_type, "symbol": value.instrument_symbol},
        "observation_date": value.observation_date.isoformat(), "value": format(value.value, "f"),
        "unit": value.unit, "classification": value.classification, "tenor": value.tenor,
        "provider": value.provider, "provider_series": value.provider_series,
        "provider_publication_timestamp": utc_iso(value.provider_publication_timestamp),
        "retrieved_at": utc_iso(value.retrieved_at), "valid_from": utc_iso(value.valid_from),
        "valid_to": utc_iso(value.valid_to), "is_current": value.is_current,
        "validation": {"state": value.validation_state, "flags": value.validation_flags},
        "provenance": {"run_id": str(value.run_id), "raw_record_id": str(value.raw_record_id)},
    }


def page(value: ObservationPage) -> dict[str, Any]:
    return {"items": [observation(item) for item in value.items], "next_cursor": value.next_cursor}


def json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "hex"):
        return str(value)
    return value
