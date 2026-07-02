from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="/opt/etf-radar/.env", env_file_encoding="utf-8")

    app_host: str = "0.0.0.0"
    app_port: int = 8088
    api_token: str = ""
    web_auth_enabled: bool = True
    web_username: str = "admin"
    web_password_hash: str = ""
    web_session_secret: str = ""
    web_session_ttl_seconds: int = Field(default=43_200, ge=900, le=604_800)
    poll_interval_seconds: int = Field(default=30, ge=10, le=300)
    api_polling_enabled: bool = True
    collector_refresh_history_on_start: bool = True
    history_refresh_every_ticks: int = Field(default=10, ge=1, le=240)
    data_stale_seconds: int = Field(default=90, ge=30, le=600)
    source_soft_stale_seconds: int = Field(default=120, ge=30, le=1200)
    database_path: str = "/opt/etf-radar/data/etf_radar.sqlite3"
    free_quote_fallback_enabled: bool = True
    discovery_cache_seconds: int = Field(default=30, ge=5, le=300)
    discovery_min_amount: float = Field(default=50_000_000, ge=1_000_000)
    discovery_max_directions: int = Field(default=8, ge=3, le=20)

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: int = Field(default=20, ge=5, le=120)
    deepseek_cache_seconds: int = Field(default=180, ge=30, le=1800)

    alert_webhook_url: str = ""
    alert_webhook_timeout_seconds: int = Field(default=8, ge=2, le=60)
    alert_cooldown_seconds: int = Field(default=300, ge=30, le=3600)

    kafka_enabled: bool = False
    kafka_bootstrap_servers: str = "redpanda:9092"
    kafka_topic_prefix: str = "etf_radar"
    kafka_flush_timeout_seconds: float = Field(default=0.5, ge=0, le=10)
    signal_consumer_group: str = "etf-radar-signal-worker"

    clickhouse_enabled: bool = False
    clickhouse_url: str = "http://clickhouse:8123"
    clickhouse_database: str = "etf_radar"
    clickhouse_user: str = "etf"
    clickhouse_password: str = ""
    clickhouse_timeout_seconds: float = Field(default=8, ge=1, le=60)

    postgres_enabled: bool = False
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "etf_radar"
    postgres_user: str = "etf"
    postgres_password: str = ""
    postgres_timeout_seconds: float = Field(default=5, ge=1, le=30)

    redis_enabled: bool = False
    redis_url: str = "redis://redis:6379/0"
    redis_key_prefix: str = "etf_radar"
    redis_timeout_seconds: float = Field(default=3, ge=1, le=30)

    main_etf_codes: str = "513120,159516"
    backup_etf_codes: str = "515880"
    benchmark_codes: str = "510300,588000"

    @property
    def main_codes(self) -> list[str]:
        return _csv(self.main_etf_codes)

    @property
    def backup_codes(self) -> list[str]:
        return _csv(self.backup_etf_codes)

    @property
    def benchmark_code_list(self) -> list[str]:
        return _csv(self.benchmark_codes)

    @property
    def exposed_codes(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for code in [*self.main_codes, *self.backup_codes]:
            if code not in seen:
                result.append(code)
                seen.add(code)
        return result

    @property
    def all_poll_codes(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for code in [*self.exposed_codes, *self.benchmark_code_list]:
            if code not in seen:
                result.append(code)
                seen.add(code)
        return result

    def ensure_data_dir(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
