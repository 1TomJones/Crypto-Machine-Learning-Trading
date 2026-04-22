"""Application configuration via Pydantic BaseSettings.

All values can be overridden by environment variables (case-insensitive).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str
    postgres_user: str = "trader"
    postgres_password: str = "trader"
    postgres_db: str = "trading"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str

    # ── Security ──────────────────────────────────────────────────────────────
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Admin credentials (password stored as bcrypt hash)
    admin_username: str = "admin"
    admin_password_hash: str = ""

    # ── Application ───────────────────────────────────────────────────────────
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # ── Exchange APIs ─────────────────────────────────────────────────────────
    binance_base_url: str = "https://data-api.binance.vision"
    binance_ws_url: str = "wss://stream.binance.com:9443"
    binance_api_key: str = ""
    binance_api_secret: str = ""

    kraken_api_key: str = ""
    kraken_api_secret: str = ""

    # ── Notifications ─────────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Observability ─────────────────────────────────────────────────────────
    sentry_dsn: str = ""

    # ── Live trader ───────────────────────────────────────────────────────────
    trading_symbol: str = "BTC/USDT"
    trading_timeframe: str = "1m"
    initial_capital: float = 10_000.0
    model_artifact_path: str = "/app/models"

    # ── Risk controls (defaults; overridden by RiskSettings DB row) ───────────
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_position_notional_pct: float = 1.0
    max_open_orders: int = 5
    max_order_rate_per_min: int = 30
    target_volatility: float = 0.10

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def cors_origins_list(self) -> list[str]:
        """Split comma-separated CORS origins string into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("secret_key")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 16:
            raise ValueError("SECRET_KEY must be at least 16 characters long")
        return v

    @field_validator("log_level")
    @classmethod
    def log_level_valid(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.  Call ``get_settings.cache_clear()``
    in tests to force re-instantiation with different env vars."""
    return Settings()
