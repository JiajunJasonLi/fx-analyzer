from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.application.ingestion.raw_data import RawDataService
from app.config.reference import ProviderSettingsConfig, load_reference_configuration
from app.domain.enums import QuoteType
from app.domain.provider import DateRange, RawPayload, ReferenceSnapshot, RequestMetadata
from app.providers.base import ProviderContractError, ProviderParseError
from app.providers.bank_of_canada import (
    ValetClient,
    ValetMalformedRecord,
    ValetMapper,
    ValetObservation,
    ValetParser,
    ValetRawFirstAdapter,
    ValetSeriesMapping,
    classify_missing_dates,
)
from app.providers.http import HttpPolicy, RetryingHttpFetcher, create_async_client


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests/fixtures/bank_of_canada/valet_g10.json"


def payload(body: bytes | None = None) -> RawPayload:
    return RawPayload(
        body=body if body is not None else FIXTURE.read_bytes(),
        media_type="application/json",
        response_status=200,
        retrieved_at=datetime(2026, 9, 20, 20, tzinfo=timezone.utc),
        request=RequestMetadata("GET", "valet-observations"),
        response_metadata={},
    )


def mappings() -> ReferenceSnapshot:
    configuration = load_reference_configuration(ROOT / "config/reference-data.yaml")
    pairs = {item.symbol: item for item in configuration.fx_pairs}
    return ReferenceSnapshot(
        {
            item.provider_symbol: ValetSeriesMapping(
                uuid4(), item.provider_symbol, item.pair,
                pairs[item.pair].base_currency, pairs[item.pair].quote_currency,
            )
            for item in configuration.fx_series
        }
    )


def test_parser_preserves_all_g10_values_metadata_flags_and_decimal() -> None:
    parsed = ValetParser().parse(payload())
    observations = [item for item in parsed if isinstance(item.value, ValetObservation)]
    assert len(observations) == 9
    assert {item.value.provider_symbol for item in observations} == {
        "FXUSDCAD", "FXEURCAD", "FXJPYCAD", "FXGBPCAD", "FXCHFCAD",
        "FXAUDCAD", "FXNZDCAD", "FXSEKCAD", "FXNOKCAD",
    }
    usd = observations[0]
    assert usd.value.value == Decimal("1.3725")
    assert usd.value.status_flags == {"status": "published"}
    assert usd.value.series_detail["label"] == "USD/CAD"
    assert usd.value.response_metadata["terms"]["url"].startswith("https://")
    assert usd.record_path == "observations[0].FXUSDCAD"
    assert len(usd.record_checksum or "") == 64


def test_parser_isolates_explicit_absence_and_malformed_records() -> None:
    parsed = ValetParser().parse(payload())
    assert any(getattr(item.value, "reason", None) == "unpublished" for item in parsed)
    malformed = [item.value for item in parsed if isinstance(item.value, ValetMalformedRecord)]
    assert {item.reason for item in malformed} == {"value_not_string", "invalid_date"}


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"observations": {}}'])
def test_response_wide_contract_failures_are_typed(body: bytes) -> None:
    with pytest.raises(ProviderParseError):
        ValetParser().parse(payload(body))


def test_mapper_maps_exactly_one_enabled_series_in_published_orientation() -> None:
    parsed = ValetParser().parse(payload())[0]
    assert isinstance(parsed.value, ValetObservation)
    snapshot = mappings()
    candidate = ValetMapper().map(
        parsed.value,
        SimpleNamespace(raw_response_id=uuid4(), record_path=parsed.record_path, record_checksum=parsed.record_checksum),
        snapshot,
    )
    assert candidate.quote_type is QuoteType.REFERENCE
    assert candidate.value == Decimal("1.3725")
    assert candidate.provider_attributes["base_currency"] == "USD"
    assert candidate.provider_attributes["quote_currency"] == "CAD"
    assert candidate.provider_attributes["classification"] == "daily_indicative_average"


def test_all_nine_configured_g10_symbols_map_to_their_canonical_pair() -> None:
    snapshot = mappings()
    observations = [
        item for item in ValetParser().parse(payload()) if isinstance(item.value, ValetObservation)
    ]
    candidates = [
        ValetMapper().map(
            item.value,
            SimpleNamespace(
                raw_response_id=uuid4(),
                record_path=item.record_path,
                record_checksum=item.record_checksum,
            ),
            snapshot,
        )
        for item in observations
    ]
    assert len(candidates) == 9
    assert {candidate.provider_attributes["pair_symbol"] for candidate in candidates} == {
        "USDCAD", "EURCAD", "JPYCAD", "GBPCAD", "CHFCAD",
        "AUDCAD", "NZDCAD", "SEKCAD", "NOKCAD",
    }
    assert {candidate.provider_attributes["quote_currency"] for candidate in candidates} == {"CAD"}


def test_unknown_and_ambiguous_series_are_contract_errors_for_quarantine() -> None:
    record = ValetObservation("UNKNOWN", date(2026, 9, 18), Decimal("1"), datetime.now(timezone.utc))
    with pytest.raises(ProviderContractError) as unknown:
        ValetMapper().map(record, SimpleNamespace(), ReferenceSnapshot({}))
    assert unknown.value.context["code"] == "UNKNOWN_PROVIDER_SERIES"


def test_missing_dates_distinguish_weekend_from_omitted_due_date() -> None:
    absences = classify_missing_dates(
        requested_symbols=("FXUSDCAD",),
        start=date(2026, 9, 18),
        end=date(2026, 9, 21),
        parsed=(),
    )
    assert [item.reason for item in absences] == [
        "omitted_expected_date", "not_due", "not_due", "omitted_expected_date"
    ]


def test_client_uses_configured_template_json_bounded_dates_and_grouping() -> None:
    settings = ProviderSettingsConfig("https://example.test/", "observations/{series}", max_range_days=10)
    client = ValetClient(settings, SimpleNamespace())  # type: ignore[arg-type]
    request = client.build_requests(
        ("FXUSDCAD", "FXEURCAD"), DateRange(date(2026, 9, 18), date(2026, 9, 20))
    )[0]
    assert request.path == "/observations/FXUSDCAD,FXEURCAD/json"
    assert request.parameters == {"start_date": "2026-09-18", "end_date": "2026-09-20"}
    assert request.instruments == ("FXUSDCAD", "FXEURCAD")
    split = ValetClient(settings, SimpleNamespace(), supports_grouped_series=False)  # type: ignore[arg-type]
    assert len(split.build_requests(request.instruments, request.date_range)) == 2


class RecordingRawRepository:
    def __init__(self) -> None:
        self.events: list[str] = []

    def add_response(self, **values: object) -> SimpleNamespace:
        self.events.append("response")
        return SimpleNamespace(id=uuid4())

    def get_or_create_record(self, **values: object) -> SimpleNamespace:
        self.events.append("record")
        return SimpleNamespace(**values)


def test_mocked_http_contract_stores_raw_response_before_parsing() -> None:
    repository = RecordingRawRepository()

    async def run() -> tuple[object, ...]:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=FIXTURE.read_bytes()))
        policy = HttpPolicy()
        async with create_async_client(
            "http://provider.test", policy, transport=transport, allow_insecure_for_tests=True
        ) as http:
            client = ValetClient(
                ProviderSettingsConfig("https://provider.test", "observations/{series}"),
                RetryingHttpFetcher(http, policy),
            )
            request = client.build_requests(
                ("FXUSDCAD",), DateRange(date(2026, 9, 18), date(2026, 9, 20))
            )[0]
            return await ValetRawFirstAdapter(
                client, RawDataService(repository), ValetParser()  # type: ignore[arg-type]
            ).fetch_store_parse(
                request, run_id=uuid4(), scope_id=uuid4(), provider_dataset_id=uuid4()
            )

    records = asyncio.run(run())
    assert repository.events[0] == "response"
    assert len(records) == 12
    assert repository.events.count("record") == 12
