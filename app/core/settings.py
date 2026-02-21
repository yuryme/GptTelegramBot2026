from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Telegram AI Reminder Bot"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    telegram_bot_token: str = Field(default="test-token")
    telegram_webhook_secret: str = Field(default="dev-secret")
    telegram_webhook_path: str = Field(default="/webhook/telegram")

    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@db:5432/reminder_bot")
    openai_api_key: str = Field(default="replace_me")
    openai_model: str = Field(default="gpt-4.1-mini")
    openai_monthly_budget_usd: float = Field(default=10.0)
    openai_estimated_input_cost_per_1k: float = Field(default=0.0003)
    openai_estimated_output_cost_per_1k: float = Field(default=0.0012)
    app_log_level: str = Field(default="INFO")
    chat_rate_limit_requests: int = Field(default=5)
    chat_rate_limit_window_seconds: int = Field(default=60)
    llm_circuit_failure_threshold: int = Field(default=3)
    llm_circuit_open_seconds: int = Field(default=60)
    webhook_max_update_age_seconds: int = Field(default=300)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
