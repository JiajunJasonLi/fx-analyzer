import pytest

from app.config.settings import DEFAULT_DATABASE_URL, Settings


def test_settings_use_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = Settings.from_env()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.log_level == "INFO"


def test_settings_load_environment_and_normalize_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://db/fx")
    monkeypatch.setenv("LOG_LEVEL", "debug")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql+psycopg://db/fx"
    assert settings.log_level == "DEBUG"


def test_settings_reject_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings.from_env()

