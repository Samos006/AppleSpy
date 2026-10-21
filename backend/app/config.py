from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    webapp_url: str = Field(default="https://applespy.panoff.dev", alias="WEBAPP_URL")
    bot_mode: str = Field(default="polling", alias="BOT_MODE")
    webhook_path: str = Field(default="/tg/webhook", alias="WEBHOOK_PATH")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")

    postgres_user: str = Field(default="applespy", alias="POSTGRES_USER")
    postgres_password: str = Field(default="applespy", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="applespy", alias="POSTGRES_DB")
    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")


    ga_city_id: str = Field(
        default="0c5b2444-70a0-4932-980c-b4dc0d3f02b5", alias="GA_CITY_ID"
    )
    ga_region_id: str = Field(default="", alias="GA_REGION_ID")
    ga_proxies_raw: str = Field(default="", alias="GA_PROXIES")
    ga_browser_fallback: bool = Field(default=False, alias="GA_BROWSER_FALLBACK")
    ga_cookie_ttl: int = Field(default=1800, alias="GA_COOKIE_TTL")
    ga_request_timeout: float = Field(default=25.0, alias="GA_REQUEST_TIMEOUT")

    check_interval: int = Field(default=900, alias="CHECK_INTERVAL")
    check_delay_between: float = Field(default=7.0, alias="CHECK_DELAY_BETWEEN")
    check_batch_size: int = Field(default=25, alias="CHECK_BATCH_SIZE")

    stock_confirmations: int = Field(default=2, alias="STOCK_CONFIRMATIONS")
    notify_cooldown: int = Field(default=21600, alias="NOTIFY_COOLDOWN")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    @field_validator("bot_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE must be 'polling' or 'webhook'")
        return v

    @property
    def region_id(self) -> str:
        return self.ga_region_id or self.ga_city_id

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def proxies(self) -> list[str]:
        return [p.strip() for p in self.ga_proxies_raw.split(",") if p.strip()]

    @property
    def admin_ids(self) -> set[int]:
        out: set[int] = set()
        for chunk in self.admin_ids_raw.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                out.add(int(chunk))
        return out

    @property
    def webhook_url(self) -> str:
        return self.webapp_url.rstrip("/") + self.webhook_path

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
