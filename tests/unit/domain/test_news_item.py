from datetime import UTC, datetime

import pytest

from forex_agent.domain.news_item import NewsItem
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.timestamps import UtcTimestamp

_T = UtcTimestamp(datetime(2026, 9, 29, 9, 2, tzinfo=UTC))


def test_valid_news_item_constructs() -> None:
    item = NewsItem(
        news_item_key="FED:abc",
        first_seen_at=_T,
        first_observation_mode=NewsObservationMode.PROSPECTIVE,
    )
    assert item.first_seen_at == _T
    assert item.first_observation_mode is NewsObservationMode.PROSPECTIVE


def test_news_item_key_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="news_item_key"):
        NewsItem(
            news_item_key="",
            first_seen_at=_T,
            first_observation_mode=NewsObservationMode.PROSPECTIVE,
        )


def test_first_seen_at_must_be_a_utc_timestamp() -> None:
    with pytest.raises(TypeError, match="first_seen_at"):
        NewsItem(
            news_item_key="FED:abc",
            first_seen_at=datetime(2026, 9, 29, tzinfo=UTC),  # type: ignore[arg-type]
            first_observation_mode=NewsObservationMode.PROSPECTIVE,
        )


def test_first_observation_mode_must_be_the_enum() -> None:
    with pytest.raises(TypeError, match="first_observation_mode"):
        NewsItem(
            news_item_key="FED:abc",
            first_seen_at=_T,
            first_observation_mode="PROSPECTIVE",  # type: ignore[arg-type]
        )


def test_is_frozen() -> None:
    item = NewsItem(
        news_item_key="FED:abc",
        first_seen_at=_T,
        first_observation_mode=NewsObservationMode.PROSPECTIVE,
    )
    with pytest.raises(AttributeError):
        item.news_item_key = "FED:xyz"  # type: ignore[misc]
