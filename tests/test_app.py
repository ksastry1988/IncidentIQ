import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.main import app_factory, create_app


def test_create_app_returns_working_app(client):
    assert isinstance(client.app, FastAPI)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "environment": "test"}


def test_defaults(monkeypatch):
    monkeypatch.setenv("INCIDENTIQ_DATABASE_URL", "sqlite:///x.db")
    s = Settings(_env_file=None)
    assert s.environment == "development"
    assert s.debug is False


def test_overrides_do_not_mutate_production_settings(monkeypatch, settings):
    monkeypatch.setenv("INCIDENTIQ_DATABASE_URL", "sqlite:///prod.db")
    get_settings.cache_clear()
    prod = get_settings()
    app = create_app(settings)
    assert app.state.settings.environment == "test"
    assert get_settings() is prod
    assert prod.database_url == "sqlite:///prod.db"
    get_settings.cache_clear()


def test_env_vars_loaded(monkeypatch):
    monkeypatch.setenv("INCIDENTIQ_DATABASE_URL", "sqlite:///env.db")
    monkeypatch.setenv("INCIDENTIQ_ENVIRONMENT", "production")
    app = create_app(Settings(_env_file=None))
    assert app.state.settings.environment == "production"


def test_missing_required_config_fails_clearly(monkeypatch):
    monkeypatch.delenv("INCIDENTIQ_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_invalid_config_fails_clearly(monkeypatch):
    monkeypatch.setenv("INCIDENTIQ_DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("INCIDENTIQ_ENVIRONMENT", "staging")
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None)


def test_app_factory_startup_fails_without_config(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INCIDENTIQ_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="database_url"):
        app_factory()
    get_settings.cache_clear()
