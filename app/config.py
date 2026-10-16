from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    database_url: str = "sqlite+aiosqlite:///./data/planner.db"

    # How often (minutes) a pending task is re-nagged by default, and after
    # how many reminders in a row the tone escalates.
    default_reminder_interval_minutes: int = 15
    escalation_threshold: int = 5
    # How long a "snooze" button push pushes a task back, in minutes.
    snooze_minutes: int = 60
    # How often (seconds) the background scheduler scans for due reminders.
    scheduler_poll_seconds: int = 60

    # Web cabinet (dashboard) -- a single-user admin login, same pattern
    # as the realtor bot's cabinet.
    web_host: str = "0.0.0.0"
    web_port: int = 8010
    web_admin_username: str = "admin"
    web_admin_password: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
