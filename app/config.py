from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_key: str = Field(..., alias="WAHA_API_KEY")
    server_host: str = Field("0.0.0.0", alias="WAHA_HOST")
    server_port: int = Field(3000, alias="WAHA_PORT")
    mongodb_connection_string: str = Field(..., alias="WAHA_MONGO_URL")
    mongodb_database_name: str = Field("whatsapp_api", alias="WAHA_MONGO_DB")
    webhook_target_url: str | None = Field(None, alias="WAHA_WEBHOOK_URL")
    auto_start_session_names: str = Field("", alias="WAHA_AUTO_START_SESSIONS")

    # Inbound API Rate Limiting
    rate_limit_enabled: bool = Field(True, alias="WAHA_RATE_LIMIT_ENABLED")
    rate_limit_rpm: int = Field(60, alias="WAHA_RATE_LIMIT_RPM")

    # Outbound Anti-Ban Message Queue & Human Pacing
    queue_enabled: bool = Field(True, alias="WAHA_QUEUE_ENABLED")
    queue_min_delay_seconds: float = Field(2.0, alias="WAHA_QUEUE_MIN_DELAY")
    queue_max_delay_seconds: float = Field(5.0, alias="WAHA_QUEUE_MAX_DELAY")
    queue_simulate_typing: bool = Field(True, alias="WAHA_QUEUE_SIMULATE_TYPING")
    queue_typing_min_seconds: float = Field(1.0, alias="WAHA_QUEUE_TYPING_MIN_SECONDS")
    queue_typing_max_seconds: float = Field(3.0, alias="WAHA_QUEUE_TYPING_MAX_SECONDS")
    queue_max_per_minute: int = Field(20, alias="WAHA_QUEUE_MAX_PER_MINUTE")
    queue_max_per_hour: int = Field(250, alias="WAHA_QUEUE_MAX_PER_HOUR")

    # Session storage and backup (WAHA approach)
    sessions_base_dir: str = Field("./.sessions", alias="WAHA_SESSIONS_DIR")
    session_backup_interval_seconds: int = Field(60, alias="WAHA_SESSION_BACKUP_INTERVAL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
