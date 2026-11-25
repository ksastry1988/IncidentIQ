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
