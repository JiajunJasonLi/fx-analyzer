from types import SimpleNamespace

import pytest

from app.application.ingestion.run_manager import RunManager


class Scopes:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses

    def list_for_run(self, run_id: object):
        return [SimpleNamespace(status=item) for item in self.statuses]


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["succeeded", "succeeded"], "succeeded"),
        (["succeeded", "failed"], "partially_succeeded"),
        (["succeeded", "skipped_conflict"], "partially_succeeded"),
        (["failed", "failed"], "failed"),
        (["skipped_conflict"], "failed"),
    ],
)
def test_exact_final_status_aggregation(statuses: list[str], expected: str) -> None:
    manager = object.__new__(RunManager)
    manager.scopes = Scopes(statuses)
    assert manager.derive_status(object()) == expected


def test_active_scope_prevents_finalization() -> None:
    manager = object.__new__(RunManager)
    manager.scopes = Scopes(["succeeded", "running"])
    with pytest.raises(ValueError, match="active"):
        manager.derive_status(object())

