from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar

from app.domain.provider import (
    FetchRequest,
    FetchResult,
    ParsedRecord,
    PublishedAbsence,
    RawPayload,
    ReferenceSnapshot,
    SourceLocator,
)


ProviderRecordT = TypeVar("ProviderRecordT", contravariant=True)
ParsedProviderRecordT = TypeVar("ParsedProviderRecordT", covariant=True)
CandidateT = TypeVar("CandidateT", covariant=True)


class ProviderClient(Protocol):
    async def fetch(self, request: FetchRequest) -> FetchResult: ...


class ProviderParser(Protocol[ParsedProviderRecordT]):
    def parse(
        self, payload: RawPayload
    ) -> Iterable[ParsedRecord[ParsedProviderRecordT]]: ...


class ProviderMapper(Protocol[ProviderRecordT, CandidateT]):
    def map(
        self,
        record: ProviderRecordT,
        source: SourceLocator,
        mappings: ReferenceSnapshot,
    ) -> CandidateT | PublishedAbsence: ...


class ProviderError(Exception):
    """Base error whose details are deliberately limited to sanitized context."""

    def __init__(self, message: str, *, context: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.context = dict(context or {})


class TransientProviderError(ProviderError):
    pass


class PermanentProviderError(ProviderError):
    pass


class PayloadTooLargeError(PermanentProviderError):
    pass


class ProviderParseError(PermanentProviderError):
    pass


class ProviderContractError(PermanentProviderError):
    pass
