from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
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
    clock_client_mode: Literal["disabled", "fixture", "live"] = "disabled"
    clock_fixture_bookings_path: Path | None = None
    clock_fixture_rooms_path: Path | None = None
    clock_field_mapping_path: Path = Path("config/clock.mapping.example.yaml")
    clock_polling_enabled: bool = False
    clock_bookings_endpoint_path: str | None = None
    clock_rooms_endpoint_path: str | None = None
    clock_endpoint_doc_reference: str | None = None

    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_topic_prefix: str = "hotel/v1"
    mqtt_client_id: str = "clock-ha-orchestrator"
    mqtt_connect_timeout_seconds: int = Field(default=5, ge=1)
    mqtt_publish_timeout_seconds: int = Field(default=2, ge=1)
    mqtt_callback_workers: int = Field(default=1, ge=1, le=16)

    policy_scheduler_enabled: bool = False
    policy_tick_seconds: int = Field(default=60, ge=10)
    outbox_worker_enabled: bool = False
    outbox_poll_seconds: int = Field(default=5, ge=1)
    outbox_batch_size: int = Field(default=25, ge=1)
    outbox_max_attempts: int = Field(default=8, ge=1)
    outbox_stale_publish_seconds: int = Field(default=30, ge=10)
    admin_api_key: SecretStr | None = None

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

    @model_validator(mode="after")
    def validate_runtime_security(self) -> Self:
        if self.app_env == "production":
            if self.secret_key.get_secret_value() == "change-me":
                raise ValueError("SECRET_KEY must be changed in production")
            if self.admin_api_key is None:
                raise ValueError("ADMIN_API_KEY is required in production")
        if self.clock_client_mode == "fixture" and self.clock_fixture_bookings_path is None:
            raise ValueError("CLOCK_FIXTURE_BOOKINGS_PATH is required for fixture Clock mode")
        if self.clock_polling_enabled and self.clock_client_mode == "disabled":
            raise ValueError("CLOCK_POLLING_ENABLED requires CLOCK_CLIENT_MODE fixture or live")
        if self.outbox_worker_enabled and not self.mqtt_enabled:
            raise ValueError("OUTBOX_WORKER_ENABLED requires MQTT_ENABLED")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
