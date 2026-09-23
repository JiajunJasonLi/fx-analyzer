from __future__ import annotations

from pathlib import Path

from app.application.reference import ReferenceDataService
from app.config.reference import ReferenceConfiguration, load_reference_configuration


class RecordingRepository:
    configuration: ReferenceConfiguration | None = None

    def synchronize(self, configuration: ReferenceConfiguration) -> tuple[int, int, int]:
        self.configuration = configuration
        return 4, 2, 1


def test_service_returns_counts_and_checksum() -> None:
    configuration = load_reference_configuration(Path("config/reference-data.yaml"))
    repository = RecordingRepository()
    result = ReferenceDataService(repository).sync(configuration)
    assert repository.configuration is configuration
    assert (result.inserted, result.updated, result.disabled) == (4, 2, 1)
    assert result.checksum == configuration.checksum
