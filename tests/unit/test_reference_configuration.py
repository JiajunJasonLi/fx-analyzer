from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from app.config.reference import ConfigurationError, load_reference_configuration


CONFIG_PATH = Path("config/reference-data.yaml")


def _write_config(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "reference.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _raw() -> dict[str, object]:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_phase_one_configuration_loads_complete_universe() -> None:
    config = load_reference_configuration(CONFIG_PATH)

    assert len(config.currencies) == 10
    assert len(config.fx_pairs) == 9
    assert len(config.fx_series) == 9
    assert len(config.interest_rate_series) == 10
    assert any(item.code == "NO" and item.iso_country_code == "NO" for item in config.economies)
    assert len(config.checksum) == 64


def test_checksum_is_stable_when_declaration_order_changes(tmp_path: Path) -> None:
    raw = _raw()
    reordered = deepcopy(raw)
    reordered["currencies"] = list(reversed(reordered["currencies"]))  # type: ignore[index]
    reordered["fx_series"] = list(reversed(reordered["fx_series"]))  # type: ignore[index]

    assert load_reference_configuration(CONFIG_PATH).checksum == load_reference_configuration(
        _write_config(tmp_path, reordered)
    ).checksum


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["fx_pairs"][0].update(base_currency="ZZZ"), "unknown base currency"),
        (lambda raw: raw["fx_series"][1].update(provider_symbol="FXUSDCAD"), "duplicate provider symbol"),
        (lambda raw: raw["fx_pairs"][0].update(symbol="CADUSD"), "does not match orientation"),
        (lambda raw: raw["interest_rate_series"][0].update(currency="CAD"), "missing economy/currency"),
    ],
)
def test_invalid_references_fail_with_actionable_message(
    tmp_path: Path, mutate: object, message: str
) -> None:
    raw = _raw()
    mutate(raw)  # type: ignore[operator]
    with pytest.raises(ConfigurationError, match=message):
        load_reference_configuration(_write_config(tmp_path, raw))


def test_unknown_keys_fail_fast(tmp_path: Path) -> None:
    raw = _raw()
    raw["database_password"] = "must-not-be-accepted"
    with pytest.raises(ConfigurationError, match="unknown configuration keys: database_password"):
        load_reference_configuration(_write_config(tmp_path, raw))


def test_secrets_cannot_affect_checksum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:first@localhost/db")
    first = load_reference_configuration(CONFIG_PATH).checksum
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:second@localhost/db")
    second = load_reference_configuration(CONFIG_PATH).checksum
    assert first == second


def test_license_gate_rejects_unapproved_and_accepts_approved(tmp_path: Path) -> None:
    raw = _raw()
    dataset = raw["provider_datasets"][0]  # type: ignore[index]
    dataset["approval_state"] = "pending"
    dataset["retention_permitted"] = False
    pending = load_reference_configuration(_write_config(tmp_path, raw))
    with pytest.raises(ConfigurationError, match="license is not approved"):
        pending.assert_ingestion_allowed("bank_of_canada:valet_daily_fx")

    dataset["approval_state"] = "approved"
    dataset["retention_permitted"] = True
    approved = load_reference_configuration(_write_config(tmp_path, raw))
    approved.assert_ingestion_allowed("bank_of_canada:valet_daily_fx")
