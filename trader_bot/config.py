from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    dukascopy_api_key: str | None = None
    duckdb_path: Path = Path(".data/research.duckdb")
    cache_root: Path = Path(".data/cache")
    request_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    request_retries: int = Field(default=4, ge=0, le=10)
    max_bars_per_request: int = Field(default=5000, ge=1, le=5000)
    max_history_window_days: int = Field(default=7, ge=1, le=31)
    live_trading_enabled: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    settings.cache_root.mkdir(parents=True, exist_ok=True)
    return settings
