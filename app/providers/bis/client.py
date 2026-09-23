from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import timedelta
from typing import Any

from app.domain.provider import DateRange, FetchRequest, FetchResult, RawPayload, RequestMetadata, RetryMetadata
from app.providers.base import ProviderContractError
from app.providers.http import RetryingHttpFetcher


class BISClient:
    """Build bounded, filtered requests for one BIS dataflow."""

    def __init__(
        self,
        fetcher: RetryingHttpFetcher,
        *,
        dataset: str,
        dataflow: str,
        endpoint_template: str = "data/{dataflow}/{series}",
        max_range_days: int = 366,
        max_series_per_request: int = 1,
        media_type: str = "application/vnd.sdmx.data+json;version=2.0.0",
    ) -> None:
        if max_range_days < 1 or max_series_per_request < 1:
            raise ValueError("BIS request limits must be positive")
        self._fetcher = fetcher
        self._dataset = dataset
        self._dataflow = dataflow
        self._endpoint_template = endpoint_template
        self._max_range_days = max_range_days
        self._max_series_per_request = max_series_per_request
        self._media_type = media_type

    def requests(self, series_keys: Iterable[str], date_range: DateRange) -> tuple[FetchRequest, ...]:
        keys = tuple(dict.fromkeys(series_keys))
        if not keys:
            raise ProviderContractError("BIS request requires at least one complete series key")
        chunks: list[FetchRequest] = []
        range_start = date_range.start
        while range_start <= date_range.end:
            range_end = min(date_range.end, range_start + timedelta(days=self._max_range_days - 1))
            for offset in range(0, len(keys), self._max_series_per_request):
                selected = keys[offset : offset + self._max_series_per_request]
                # BIS supports '+' as the OR operator in a key dimension.
                series_filter = "+".join(selected)
                path = "/" + self._endpoint_template.format(
                    dataflow=self._dataflow, series=series_filter
                ).lstrip("/")
                chunks.append(
                    FetchRequest(
                        dataset=self._dataset,
                        instruments=selected,
                        date_range=DateRange(range_start, range_end),
                        endpoint_name="bis_sdmx_data",
                        path=path,
                        parameters={
                            "startPeriod": range_start.isoformat(),
                            "endPeriod": range_end.isoformat(),
                        },
                    )
                )
            range_start = range_end + timedelta(days=1)
        return tuple(chunks)

    async def fetch(self, request: FetchRequest) -> FetchResult:
        result = await self._fetcher.fetch(request)
        # Retain an allowlisted, provider-neutral request description even though
        # BIS names its query parameters startPeriod/endPeriod.
        safe_request = RequestMetadata(
            method=result.payload.request.method,
            endpoint_name=result.payload.request.endpoint_name,
            sanitized_parameters={
                "start_date": request.date_range.start.isoformat(),
                "end_date": request.date_range.end.isoformat(),
                "format": self._media_type,
                "key": list(request.instruments),
            },
        )
        return replace(result, payload=replace(result.payload, request=safe_request))

    async def fetch_all(
        self, series_keys: Iterable[str], date_range: DateRange
    ) -> tuple[FetchResult, ...]:
        return tuple([await self.fetch(request) for request in self.requests(series_keys, date_range)])

    @staticmethod
    def bulk_payload(
        body: bytes,
        *,
        retrieved_at: Any,
        media_type: str = "text/csv",
        dataset_version: str | None = None,
    ) -> FetchResult:
        """Wrap an already acquired bulk file for the normal raw/parser pipeline."""
        metadata = {"dataset-version": dataset_version} if dataset_version else {}
        return FetchResult(
            payload=RawPayload(
                body=body,
                media_type=media_type,
                response_status=200,
                retrieved_at=retrieved_at,
                request=RequestMetadata("GET", "bis_bulk_download", {}),
                response_metadata=metadata,
            ),
            retry=RetryMetadata(attempts=1),
        )
