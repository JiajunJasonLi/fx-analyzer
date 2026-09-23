from __future__ import annotations

import asyncio
import gzip
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.domain.candidates import PolicyRateCandidate
from app.domain.enums import CanonicalRateUnit, Frequency, RateType
from app.domain.provider import DateRange, PublishedAbsence, ReferenceSnapshot, SourceLocator
from app.config.reference import load_reference_configuration
from app.domain.normalization import NormalizationError
from app.providers.base import ProviderContractError, ProviderParseError
from app.providers.bis import BISClient, BISMapper, BISParser, BISRecord, BISSeriesMapping
from app.providers.http import HttpPolicy, RetryingHttpFetcher, create_async_client


FIXTURES = Path(__file__).parents[1] / "fixtures" / "bis"
SERIES_ID = UUID("00000000-0000-0000-0000-000000000008")
RAW_ID = UUID("00000000-0000-0000-0000-000000000009")
RETRIEVED = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)
ORDER = ("FREQ", "REF_AREA")
KEY = "D.US"


def _snapshot() -> ReferenceSnapshot:
    return ReferenceSnapshot(
        {
            "retrieved_at": RETRIEVED,
            "bis_series": (
                BISSeriesMapping(
                    series_id=SERIES_ID,
                    dataflow="WS_CBPOL",
                    series_key=KEY,
                    economy="US",
                    currency="USD",
                    effective_from=date(1900, 1, 1),
                ),
            ),
        }
    )


def test_filtered_requests_are_bounded_and_split_without_partial_keys() -> None:
    async def unused_sleep(_: float) -> None:
        return None

    client = httpx.AsyncClient(
        base_url="https://stats.bis.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    adapter = BISClient(
        RetryingHttpFetcher(client, HttpPolicy(), sleep=unused_sleep),
        dataset="bis_policy_rates_daily",
        dataflow="WS_CBPOL",
        max_range_days=2,
        max_series_per_request=1,
    )
    requests = adapter.requests(("D.US", "D.CA"), DateRange(date(2026, 9, 1), date(2026, 9, 3)))
    assert len(requests) == 4
    assert requests[0].path == "/data/WS_CBPOL/D.US"
    assert requests[0].parameters["startPeriod"] == "2026-09-01"
    assert "format" not in requests[0].parameters
    assert requests[-1].parameters["endPeriod"] == "2026-09-03"
    asyncio.run(client.aclose())


def test_reordered_named_dimensions_map_to_candidate_and_absence() -> None:
    result = BISClient.bulk_payload(
        (FIXTURES / "sdmx_reordered.json").read_bytes(),
        retrieved_at=RETRIEVED,
        media_type="application/vnd.sdmx.data+json",
    )
    parsed = tuple(BISParser(dataflow="WS_CBPOL", configured_dimension_order=ORDER).parse(result.payload))
    assert len(parsed) == 2
    assert parsed[0].value.series_key == KEY
    assert parsed[0].value.attributes["BAND_NOTE"] == "representative_midpoint"
    assert parsed[1].value.attributes["BREAKS"] == "policy_change"

    mapper = BISMapper()
    candidate = mapper.map(parsed[0].value, SourceLocator(RAW_ID, parsed[0].record_path, parsed[0].record_checksum), _snapshot())
    absence = mapper.map(parsed[1].value, SourceLocator(RAW_ID, parsed[1].record_path, parsed[1].record_checksum), _snapshot())
    assert isinstance(candidate, PolicyRateCandidate)
    assert candidate.value.as_tuple() == candidate.value.as_tuple()  # exact Decimal input retained
    assert str(candidate.value) == "5.250"
    assert candidate.unit is CanonicalRateUnit.PERCENT_PER_YEAR
    assert candidate.frequency is Frequency.DAILY
    assert candidate.rate_type is RateType.POLICY_RATE
    assert candidate.tenor is None
    assert candidate.provider_attributes["dataset_version"] == "2026-09"
    assert isinstance(absence, PublishedAbsence)
    assert absence.reason == "published_absence"


def test_bulk_csv_uses_same_record_and_mapper_path() -> None:
    payload = BISClient.bulk_payload(
        (FIXTURES / "bulk.csv").read_bytes(), retrieved_at=RETRIEVED, dataset_version="fallback"
    ).payload
    parsed = tuple(BISParser(dataflow="WS_CBPOL", configured_dimension_order=ORDER).parse(payload))
    assert [item.value.series_key for item in parsed] == [KEY, KEY]
    mapped = BISMapper().map(
        parsed[0].value,
        SourceLocator(RAW_ID, parsed[0].record_path, parsed[0].record_checksum),
        _snapshot(),
    )
    assert isinstance(mapped, PolicyRateCandidate)
    assert mapped.provider_publication_timestamp == datetime(2026, 9, 18, 6, tzinfo=timezone.utc)
    assert mapped.provider_attributes["OBS_STATUS"] == "A"


def test_complete_key_and_effective_economy_currency_are_enforced() -> None:
    payload = BISClient.bulk_payload(
        (FIXTURES / "bulk.csv").read_bytes(), retrieved_at=RETRIEVED
    ).payload
    record = next(iter(BISParser(dataflow="WS_CBPOL", configured_dimension_order=ORDER).parse(payload))).value
    wrong = ReferenceSnapshot(
        {
            "retrieved_at": RETRIEVED,
            "bis_series": ({
                "series_id": SERIES_ID,
                "dataflow": "WS_CBPOL",
                "series_key": KEY,
                "economy": "US",
                "currency": "CAD",
                "effective_from": date(1900, 1, 1),
            },),
        }
    )
    with pytest.raises(ProviderContractError, match="economy/currency"):
        BISMapper().map(record, SourceLocator(RAW_ID, "rows[2]"), wrong)


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"structure":{"dimensions":{"series":[],"observation":[]}},"dataSets":[]}'],
)
def test_malformed_contract_is_typed_parse_failure(body: bytes) -> None:
    payload = BISClient.bulk_payload(body, retrieved_at=RETRIEVED, media_type="application/json").payload
    with pytest.raises(ProviderParseError):
        tuple(BISParser(dataflow="WS_CBPOL").parse(payload))


def test_mocked_http_fetch_retains_dataset_version_header() -> None:
    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=(FIXTURES / "sdmx_reordered.json").read_bytes(),
                headers={"Content-Type": "application/vnd.sdmx.data+json", "ETag": "2026-09"},
            )
        )
        async with create_async_client(
            "https://stats.bis.test", HttpPolicy(), transport=transport,
            headers={"Accept": "application/vnd.sdmx.data+json;version=1.0.0"},
        ) as http_client:
            adapter = BISClient(
                RetryingHttpFetcher(http_client, HttpPolicy()),
                dataset="bis_policy_rates_daily",
                dataflow="WS_CBPOL",
            )
            request = adapter.requests((KEY,), DateRange(date(2026, 9, 17), date(2026, 9, 18)))[0]
            return await adapter.fetch(request)

    result = asyncio.run(run())
    assert result.payload.response_metadata["etag"] == "2026-09"
    assert result.payload.request.sanitized_parameters["key"] == [KEY]
    assert result.payload.request.sanitized_parameters["start_date"] == "2026-09-17"


def test_current_bis_envelope_uses_configured_series_metadata() -> None:
    fixture = __import__("json").loads((FIXTURES / "sdmx_reordered.json").read_text())
    for dimension in fixture["structure"]["dimensions"]["series"]:
        if dimension["id"] in {"CURRENCY", "UNIT_MEASURE", "COLLECTION"}:
            dimension["values"] = []
    fixture["structure"]["dimensions"]["series"] = [
        item for item in fixture["structure"]["dimensions"]["series"]
        if item["id"] not in {"CURRENCY", "UNIT_MEASURE", "COLLECTION"}
    ]
    fixture["dataSets"][0]["series"] = {
        ":".join(key.split(":")[:2]): value
        for key, value in fixture["dataSets"][0]["series"].items()
    }
    envelope = {"meta": {"prepared": "2026-09-18T12:00:00", "datasetId": "live-v1"}, "data": fixture}
    payload = BISClient.bulk_payload(
        __import__("json").dumps(envelope).encode(), retrieved_at=RETRIEVED,
        media_type="application/vnd.sdmx.data+json",
    ).payload
    parsed = tuple(BISParser(
        dataflow="WS_CBPOL", configured_dimension_order=ORDER,
        configured_currency="USD", configured_unit="percent",
        configured_collection_indicator="main",
    ).parse(payload))
    assert parsed[0].value.currency == "USD"
    assert parsed[0].value.unit == "percent"
    assert parsed[0].value.collection_indicator == "main"
    assert parsed[0].value.dataset_version is None
    assert parsed[0].value.publication_timestamp is None
    assert "PROVIDER_PREPARED_RAW" not in parsed[0].value.attributes


def test_gzip_json_is_decoded_without_changing_raw_bytes() -> None:
    body = (FIXTURES / "sdmx_reordered.json").read_bytes()
    compressed = gzip.compress(body)
    result = BISClient.bulk_payload(compressed, retrieved_at=RETRIEVED)
    payload = result.payload.__class__(
        body=compressed,
        media_type="application/vnd.sdmx.data+json",
        response_status=200,
        retrieved_at=RETRIEVED,
        request=result.payload.request,
        response_metadata={"content-encoding": "gzip"},
    )
    parsed = tuple(BISParser(dataflow="WS_CBPOL", configured_dimension_order=ORDER).parse(payload))
    assert len(parsed) == 2
    assert payload.body == compressed


def test_provider_nan_is_published_absence() -> None:
    fixture = __import__("json").loads((FIXTURES / "sdmx_reordered.json").read_text())
    series = next(iter(fixture["dataSets"][0]["series"].values()))
    series["observations"]["0"][0] = "NaN"
    payload = BISClient.bulk_payload(
        __import__("json").dumps(fixture).encode(), retrieved_at=RETRIEVED,
        media_type="application/vnd.sdmx.data+json",
    ).payload
    record = next(iter(BISParser(dataflow="WS_CBPOL", configured_dimension_order=ORDER).parse(payload))).value
    assert record.value is None
    mapped = BISMapper().map(record, SourceLocator(RAW_ID, "observations[0]"), _snapshot())
    assert isinstance(mapped, PublishedAbsence)


def test_every_configured_g10_series_resolves_by_complete_key() -> None:
    configuration = load_reference_configuration("config/reference-data.yaml")
    configured = configuration.interest_rate_series
    assert {item.currency for item in configured} == {
        "USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK"
    }
    mappings = tuple(
        BISSeriesMapping(
            series_id=UUID(int=index),
            dataflow=item.dataflow_key,
            series_key=item.series_key,
            economy=item.economy,
            currency=item.currency,
            effective_from=date(1900, 1, 1),
        )
        for index, item in enumerate(configured, start=1)
    )
    snapshot = ReferenceSnapshot({"retrieved_at": RETRIEVED, "bis_series": mappings})
    for item, mapping in zip(configured, mappings):
        candidate = BISMapper().map(
            BISRecord(
                dataflow=item.dataflow_key,
                series_key=item.series_key,
                economy=item.economy,
                currency=item.currency,
                frequency="D",
                unit="percent",
                collection_indicator=item.collection_indicator,
                observation_date=date(2026, 9, 18),
                value=Decimal("1.25"),
            ),
            SourceLocator(RAW_ID, f"series[{item.series_key}]"),
            snapshot,
        )
        assert isinstance(candidate, PolicyRateCandidate)
        assert candidate.series_id == mapping.series_id


def test_unsupported_unit_is_a_normalization_failure_for_quarantine() -> None:
    record = BISRecord(
        dataflow="WS_CBPOL",
        series_key=KEY,
        economy="US",
        currency="USD",
        frequency="D",
        unit="basis_points",
        collection_indicator="main",
        observation_date=date(2026, 9, 18),
        value=Decimal("525"),
    )
    with pytest.raises(NormalizationError, match="unsupported unit"):
        BISMapper().map(record, SourceLocator(RAW_ID, "observations[0]"), _snapshot())
