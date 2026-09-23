from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.application.ingestion.raw_data import RawDataService
from app.domain.provider import FetchRequest, ParsedRecord, SourceLocator
from app.providers.bank_of_canada.client import ValetClient
from app.providers.bank_of_canada.parser import ValetParsedValue, ValetParser


@dataclass(frozen=True)
class StoredValetRecord:
    parsed: ValetParsedValue
    source: SourceLocator


class ValetRawFirstAdapter:
    """Enforce durable raw-response storage before any JSON parsing occurs."""

    def __init__(self, client: ValetClient, raw_data: RawDataService, parser: ValetParser) -> None:
        self._client = client
        self._raw_data = raw_data
        self._parser = parser

    async def fetch_store_parse(
        self,
        request: FetchRequest,
        *,
        run_id: UUID,
        scope_id: UUID,
        provider_dataset_id: UUID,
    ) -> tuple[StoredValetRecord, ...]:
        result = await self._client.fetch(request)
        raw_response_id = self._raw_data.store_response(
            run_id=run_id,
            scope_id=scope_id,
            provider_dataset_id=provider_dataset_id,
            fetch_result=result,
        )
        parsed = self._parser.parse(result.payload)
        return tuple(self._store_record(raw_response_id, item) for item in parsed)

    def _store_record(
        self, raw_response_id: UUID, parsed: ParsedRecord[ValetParsedValue]
    ) -> StoredValetRecord:
        value = parsed.value
        symbol = getattr(value, "provider_symbol", None) or getattr(value, "instrument", None)
        observation_date = getattr(value, "observation_date", None)
        natural_key = (
            f"{symbol}:{observation_date.isoformat()}"
            if symbol is not None and observation_date is not None
            else None
        )
        source = self._raw_data.store_record(
            raw_response_id=raw_response_id,
            record_path=parsed.record_path,
            provider_natural_key=natural_key,
            record_checksum=parsed.record_checksum,
        )
        return StoredValetRecord(value, source)
