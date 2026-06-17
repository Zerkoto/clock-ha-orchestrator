from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    secret_key: SecretStr = Field(default=SecretStr("change-me"))

    database_url: str = "postgresql+psycopg://clock_ha:clock_ha@localhost:5432/clock_ha"

    clock_base_url: str = "https://sky-eu1.clock-software.com"
    clock_api_user: str | None = None
    clock_api_key: SecretStr | None = None
    clock_subscription_id: str | None = None
    clock_account_id: str | None = None
    clock_poll_interval_seconds: int = Field(default=300, ge=60)
    clock_sync_overlap_seconds: int = Field(default=120, ge=0)
    clock_reconciliation_days_past: int = Field(default=2, ge=0)
    clock_reconciliation_days_future: int = Field(default=45, ge=1)
    clock_bookings_endpoint_path: str | None = None
    clock_rooms_endpoint_path: str | None = None
    clock_endpoint_doc_reference: str | None = None

    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_topic_prefix: str = "hotel/v1"
    mqtt_client_id: str = "clock-ha-orchestrator"

    room_registry_path: Path = Path("config/rooms.example.yaml")
    policy_path: Path = Path("config/policies.example.yaml")

    @field_validator("clock_base_url")
    @classmethod
    def require_https_clock(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("Clock API base URL must use HTTPS")
        return value.rstrip("/")

    @field_validator("mqtt_topic_prefix")
    @classmethod
    def normalize_mqtt_prefix(cls, value: str) -> str:
        normalized = value.strip("/")
        if not normalized:
            raise ValueError("MQTT topic prefix cannot be empty")
        return normalized

    @property
    def live_clock_mapping_enabled(self) -> bool:
        return bool(
            self.clock_bookings_endpoint_path
            and self.clock_rooms_endpoint_path
            and self.clock_endpoint_doc_reference
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
