"""Regression tests for the fail-closed live-trading guard.

CLAUDE.md: "If LIVE is selected, execution must fail closed." This is a
critical behaviour, so it gets a regression test per CLAUDE.md's testing
rules even at the scaffolding stage.
"""

import pytest
from pydantic import ValidationError

from forex_agent.apps.settings import LiveTradingNotPermittedError, Settings


def test_default_settings_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("BROKER_ENVIRONMENT", raising=False)
    monkeypatch.delenv("LIVE_TRADING_COMPILED", raising=False)

    settings = Settings(_env_file=None)

    assert settings.trading_mode == "PAPER"
    assert settings.broker_environment == "PRACTICE"
    assert settings.live_trading_compiled is False


def test_live_trading_compiled_true_fails_closed() -> None:
    with pytest.raises(LiveTradingNotPermittedError):
        Settings(_env_file=None, live_trading_compiled=True)


@pytest.mark.parametrize("mode", ["LIVE", "live", "paper", ""])
def test_non_paper_trading_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, trading_mode=mode)


@pytest.mark.parametrize("environment", ["LIVE", "PRODUCTION", "practice", ""])
def test_non_practice_broker_environment_is_rejected(environment: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, broker_environment=environment)
