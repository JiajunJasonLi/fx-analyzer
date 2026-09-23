from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Mapping

from app.domain.candidates import FxObservationCandidate, PolicyRateCandidate


def canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("fingerprints require finite decimals")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


def canonical_json(value: Any) -> bytes:
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fingerprint timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def _selected(attributes: Mapping[str, Any], keys: Iterable[str] | None) -> Mapping[str, Any]:
    return dict(attributes) if keys is None else {key: attributes[key] for key in keys if key in attributes}


def fx_fingerprint(candidate: FxObservationCandidate, series_stable_key: str, *, interpretation_attributes: Iterable[str] | None = None) -> str:
    return sha256_fingerprint({
        "series": series_stable_key,
        "observation_date": candidate.observation_date,
        "value": candidate.value,
        "quote_type": candidate.quote_type,
        "provider_publication_timestamp": candidate.provider_publication_timestamp,
        "attributes": _selected(candidate.provider_attributes, interpretation_attributes),
    })


def policy_rate_fingerprint(candidate: PolicyRateCandidate, series_stable_key: str, *, interpretation_attributes: Iterable[str] | None = None) -> str:
    return sha256_fingerprint({
        "series": series_stable_key,
        "observation_date": candidate.observation_date,
        "value": candidate.value,
        "unit": candidate.unit,
        "frequency": candidate.frequency,
        "rate_type": candidate.rate_type,
        "provider_publication_timestamp": candidate.provider_publication_timestamp,
        "attributes": _selected(candidate.provider_attributes, interpretation_attributes),
    })
