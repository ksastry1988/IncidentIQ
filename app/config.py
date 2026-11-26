from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ToolAccessSettings(BaseSettings):
    """Allow-lists (comma-separated) for investigation tool calls."""

    model_config = SettingsConfigDict(
        env_prefix="INCIDENTIQ_", env_file=".env", extra="ignore"
    )

    tool_allowed_services: str = (
        "checkout,fraud-check,inventory,inventory-db,payments,search,search-index"
    )
    tool_allowed_environments: str = "production,staging"


class ToolTimeoutSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INCIDENTIQ_", env_file=".env", extra="ignore"
    )

    tool_timeout_seconds: float = Field(default=10.0, gt=0, allow_inf_nan=False)


class ToolRedactionSettings(BaseSettings):
    """Server-held secrets (comma-separated) that must never appear in tool output."""

    model_config = SettingsConfigDict(
        env_prefix="INCIDENTIQ_", env_file=".env", extra="ignore"
    )

    tool_redact_values: str = ""


class Settings(ToolAccessSettings):
    """Single typed source of configuration, read from INCIDENTIQ_* env vars or .env."""

    model_config = SettingsConfigDict(
        env_prefix="INCIDENTIQ_", env_file=".env", extra="ignore"
    )

    # Required: no default so a missing value fails at startup.
    database_url: str = Field(min_length=1)
    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "IncidentIQ"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
