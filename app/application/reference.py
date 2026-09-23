from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config.reference import ReferenceConfiguration


@dataclass(frozen=True)
class ReferenceSyncResult:
    inserted: int
    updated: int
    disabled: int
    checksum: str


class ReferenceDataRepository(Protocol):
    def synchronize(self, configuration: ReferenceConfiguration) -> tuple[int, int, int]: ...


class ReferenceDataService:
    """Application boundary for one-transaction reference synchronization."""

    def __init__(self, repository: ReferenceDataRepository) -> None:
        self._repository = repository

    def sync(self, configuration: ReferenceConfiguration) -> ReferenceSyncResult:
        inserted, updated, disabled = self._repository.synchronize(configuration)
        return ReferenceSyncResult(
            inserted=inserted,
            updated=updated,
            disabled=disabled,
            checksum=configuration.checksum,
        )
