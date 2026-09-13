"""Typed runtime settings.

This module is the single place environment variables are read. Per
CLAUDE.md, the domain and application layers must never read environment
variables directly — only `apps` (composition root) and `infrastructure`
adapters may depend on this module.

Safety-critical settings are validated here and fail closed: if
`TRADING_MODE` is ever anything other than "PAPER", or `BROKER_ENVIRONMENT"
anything other than "PRACTICE", or live trading is compiled in, startup
raises rather than silently falling back to a safe default.
"""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiveTradingNotPermittedError(RuntimeError):
    """Raised when configuration would allow live-money trading in V1."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    # --- Safety-critical (see CLAUDE.md "Safety rules") ---------------------
    trading_mode: Literal["PAPER"] = "PAPER"
    broker_environment: Literal["PRACTICE"] = "PRACTICE"
    live_trading_compiled: bool = False

    # --- Database -------------------------------------------------------
    database_url: str = "postgresql+asyncpg://forex:forex@localhost:5432/forex_agent"

    # --- OANDA Practice API ----------------------------------------------
    oanda_api_key: str | None = None
    oanda_account_id: str | None = None
    oanda_api_base_url: str = "https://api-fxpractice.oanda.com"

    @model_validator(mode="after")
    def _fail_closed_on_live_trading(self) -> Settings:
        is_paper = self.trading_mode == "PAPER"
        is_practice = self.broker_environment == "PRACTICE"
        if not is_paper or not is_practice or self.live_trading_compiled:
            raise LiveTradingNotPermittedError(
                "V1 must not connect to a live brokerage endpoint. Refusing to start: "
                f"trading_mode={self.trading_mode!r}, "
                f"broker_environment={self.broker_environment!r}, "
                f"live_trading_compiled={self.live_trading_compiled!r}."
            )
        return self


def get_settings() -> Settings:
    """Load and validate settings. Raises `LiveTradingNotPermittedError` fail-closed."""
    return Settings()
