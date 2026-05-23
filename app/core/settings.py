from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Telegram AI Reminder Bot"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_timezone: str = "Europe/Moscow"

    telegram_bot_token: str = Field(default="test-token")
    telegram_bot_token_test: str | None = Field(default=None)
    telegram_use_test_bot: bool = Field(default=False)
    telegram_webhook_secret: str = Field(default="dev-secret")
    telegram_webhook_path: str = Field(default="/webhook/telegram")
    telegram_delivery_mode: Literal["webhook", "polling"] = Field(default="webhook")
    telegram_polling_drop_pending_updates: bool = Field(default=True)

    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@db:5432/reminder_bot")
    llm_provider: Literal["openai", "deepseek"] = Field(default="openai")
    openai_api_key: str = Field(default="replace_me")
    openai_model: str = Field(default="gpt-4.1-mini")
    stt_provider: Literal["openai", "http", "groq"] = Field(default="openai")
    openai_transcription_model: str = Field(default="gpt-4o-mini-transcribe")
    stt_http_url: str = Field(default="http://127.0.0.1:18100/transcribe")
    stt_http_timeout_seconds: float = Field(default=120.0)
    groq_api_key: str | None = Field(default=None)
    groq_stt_base_url: str = Field(default="https://api.groq.com/openai/v1")
    groq_stt_model: str = Field(default="whisper-large-v3-turbo")
    groq_stt_language: str = Field(default="ru")
    groq_stt_timeout_seconds: float = Field(default=120.0)
    deepseek_api_key: str | None = Field(default=None)
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    deepseek_model: str = Field(default="deepseek-v4-flash")
    openai_monthly_budget_usd: float = Field(default=10.0)
    openai_estimated_input_cost_per_1k: float = Field(default=0.0003)
    openai_estimated_output_cost_per_1k: float = Field(default=0.0012)
    app_log_level: str = Field(default="INFO")
    chat_rate_limit_requests: int = Field(default=5)
    chat_rate_limit_window_seconds: int = Field(default=60)
    llm_circuit_failure_threshold: int = Field(default=3)
    llm_circuit_open_seconds: int = Field(default=60)
    webhook_max_update_age_seconds: int = Field(default=300)

    @property
    def telegram_active_bot_token(self) -> str:
        if self.telegram_use_test_bot and self.telegram_bot_token_test:
            return self.telegram_bot_token_test
        return self.telegram_bot_token


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
