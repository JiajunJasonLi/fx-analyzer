from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.ingestion.raw_data import RawDataService, RawStoragePolicy
from app.domain.provider import FetchResult, RawPayload, RequestMetadata, RetryMetadata
from app.providers.base import PayloadTooLargeError


class RecordingRepository:
    def __init__(self) -> None:
        self.responses: list[dict[str, object]] = []
        self.records: dict[tuple[object, str], SimpleNamespace] = {}

    def add_response(self, **values: object) -> SimpleNamespace:
        self.responses.append(values)
        return SimpleNamespace(id=uuid4())

    def get_or_create_record(self, **values: object) -> SimpleNamespace:
        key = (values["raw_response_id"], str(values["record_path"]))
        record = self.records.get(key)
        if record is None:
            record = SimpleNamespace(id=uuid4(), **values)
            self.records[key] = record
        return record


def make_result(body: bytes = b'\x00{"value":"1.25"}\xff') -> FetchResult:
    payload = RawPayload(
        body=body,
        media_type="application/json",
        response_status=200,
        retrieved_at=datetime(2026, 9, 20, 8, 30, tzinfo=timezone(timedelta(hours=-4))),
        request=RequestMetadata(
            method="get",
            endpoint_name="daily-observations",
            sanitized_parameters={
                "start_date": "2026-09-01",
                "series": ["FXUSDCAD"],
                "api_token": "must-not-persist",
            },
        ),
        response_metadata={
            "ETag": "safe-value",
            "Content-Encoding": "gzip",
            "Set-Cookie": "must-not-persist",
            "Authorization": "must-not-persist",
        },
    )
    return FetchResult(payload=payload, retry=RetryMetadata(attempts=1))


def test_store_response_preserves_exact_bytes_and_safe_identity() -> None:
    repository = RecordingRepository()
    service = RawDataService(repository)  # type: ignore[arg-type]
    result = make_result()

    raw_response_id = service.store_response(
        run_id=uuid4(),
        scope_id=uuid4(),
        provider_dataset_id=uuid4(),
        fetch_result=result,
    )

    stored = repository.responses[0]
    assert raw_response_id is not None
    assert stored["body"] == result.payload.body
    assert stored["payload_checksum"] == hashlib.sha256(result.payload.body).hexdigest()
    assert stored["body_size"] == len(result.payload.body)
    assert stored["request_method"] == "GET"
    assert stored["request_parameters"] == {
        "start_date": "2026-09-01",
        "series": ["FXUSDCAD"],
    }
    assert stored["response_metadata"] == {
        "etag": "safe-value",
        "content-encoding": "gzip",
    }
    assert stored["content_encoding"] == "gzip"
    assert stored["retrieved_at"] == datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)


def test_store_response_enforces_size_before_repository_write() -> None:
    repository = RecordingRepository()
    service = RawDataService(
        repository, RawStoragePolicy(max_response_bytes=2)  # type: ignore[arg-type]
    )

    with pytest.raises(PayloadTooLargeError):
        service.store_response(
            run_id=uuid4(),
            scope_id=uuid4(),
            provider_dataset_id=uuid4(),
            fetch_result=make_result(b"abc"),
        )
    assert repository.responses == []


def test_record_locator_is_deterministic_and_rejects_sensitive_metadata() -> None:
    repository = RecordingRepository()
    service = RawDataService(repository)  # type: ignore[arg-type]
    response_id = uuid4()

    first = service.store_record(
        raw_response_id=response_id,
        record_path="observations[2026-09-20].FXUSDCAD",
        provider_natural_key="FXUSDCAD:2026-09-20",
        record_checksum="a" * 64,
        source_metadata={"status": "published"},
    )
    second = service.store_record(
        raw_response_id=response_id,
        record_path="observations[2026-09-20].FXUSDCAD",
        provider_natural_key="FXUSDCAD:2026-09-20",
        record_checksum="a" * 64,
        source_metadata={"status": "published"},
    )
    assert first == second
    assert len(repository.records) == 1

    with pytest.raises(ValueError, match="sensitive"):
        service.store_record(
            raw_response_id=response_id,
            record_path="observations[1]",
            source_metadata={"access_token": "secret"},
        )


def test_raw_repository_failure_is_propagated() -> None:
    class FailingRepository(RecordingRepository):
        def add_response(self, **values: object) -> SimpleNamespace:
            raise RuntimeError("database write failed")

    with pytest.raises(RuntimeError, match="database write failed"):
        RawDataService(FailingRepository()).store_response(  # type: ignore[arg-type]
            run_id=uuid4(),
            scope_id=uuid4(),
            provider_dataset_id=uuid4(),
            fetch_result=make_result(),
        )


def test_secret_bearing_endpoint_identity_is_rejected_before_storage() -> None:
    repository = RecordingRepository()
    result = make_result()
    unsafe = FetchResult(
        payload=RawPayload(
            body=result.payload.body,
            media_type=result.payload.media_type,
            response_status=result.payload.response_status,
            retrieved_at=result.payload.retrieved_at,
            request=RequestMetadata(
                method="GET",
                endpoint_name="https://provider.test/data?token=secret",
            ),
        ),
        retry=result.retry,
    )
    with pytest.raises(ValueError, match="logical name"):
        RawDataService(repository).store_response(  # type: ignore[arg-type]
            run_id=uuid4(),
            scope_id=uuid4(),
            provider_dataset_id=uuid4(),
            fetch_result=unsafe,
        )
    assert repository.responses == []
