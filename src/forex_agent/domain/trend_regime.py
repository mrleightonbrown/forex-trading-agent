from enum import Enum


class TrendRegime(Enum):
    """Whether a trailing window of candles shows a sustained directional
    move (TRENDING) or not (RANGING) — classified via ADX, see
    `forex_agent.domain.regime_detection.classify_regime`."""

    TRENDING = "TRENDING"
    RANGING = "RANGING"
