"""FX-57AH Section 1: `NewsSourceFetchOutcome` now ENFORCES, not just
documents, that every observation in `observations` shares the exact
same `retrieved_at` as the outcome itself -- a violating adapter must
be fixed, never silently corrected here."""

from datetime import UTC, datetime

import pytest

from forex_agent.application.ports.news_source import (
    NewsSourceFetchContractError,
    NewsSourceFetchOutcome,
    NormalizedNewsObservation,
)
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp

_RETRIEVED_AT = UtcTimestamp(datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC))
_OTHER_TIME = UtcTimestamp(datetime(2026, 10, 3, 13, 0, 0, tzinfo=UTC))


def _observation(
    external_item_id: str = "item-1",
    observed_at: UtcTimestamp = _RETRIEVED_AT,
    source_published_at: UtcTimestamp | None = None,
) -> NormalizedNewsObservation:
    return NormalizedNewsObservation(
        source_key="FED",
        external_item_id=external_item_id,
        observed_at=observed_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline="A headline",
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        source_published_at=source_published_at,
    )


def test_all_matching_observations_are_accepted() -> None:
    outcome = NewsSourceFetchOutcome(
        source_channel="press_monetary",
        retrieved_at=_RETRIEVED_AT,
        observations=(
            _observation("item-1", _RETRIEVED_AT),
            _observation("item-2", _RETRIEVED_AT),
            _observation("item-3", _RETRIEVED_AT),
        ),
        items_invalid=0,
    )
    assert len(outcome.observations) == 3


def test_one_mismatched_observation_is_rejected() -> None:
    with pytest.raises(NewsSourceFetchContractError):
        NewsSourceFetchOutcome(
            source_channel="press_monetary",
            retrieved_at=_RETRIEVED_AT,
            observations=(
                _observation("item-1", _RETRIEVED_AT),
                _observation("item-2", _OTHER_TIME),
            ),
            items_invalid=0,
        )


def test_source_published_at_is_irrelevant_to_this_check() -> None:
    # A plausible, DIFFERENT source_published_at must never satisfy
    # or interfere with the retrieved_at/observed_at check -- only
    # observed_at is compared.
    outcome = NewsSourceFetchOutcome(
        source_channel="speeches",
        retrieved_at=_RETRIEVED_AT,
        observations=(_observation("item-1", _RETRIEVED_AT, source_published_at=_OTHER_TIME),),
        items_invalid=0,
    )
    assert outcome.observations[0].source_published_at == _OTHER_TIME
    assert outcome.observations[0].observed_at == _RETRIEVED_AT

    with pytest.raises(NewsSourceFetchContractError):
        NewsSourceFetchOutcome(
            source_channel="speeches",
            retrieved_at=_RETRIEVED_AT,
            observations=(_observation("item-1", _OTHER_TIME, source_published_at=_RETRIEVED_AT),),
            items_invalid=0,
        )


def test_multiple_observations_all_use_the_exact_same_retrieved_at() -> None:
    outcome = NewsSourceFetchOutcome(
        source_channel="testimony",
        retrieved_at=_RETRIEVED_AT,
        observations=tuple(_observation(f"item-{i}", _RETRIEVED_AT) for i in range(5)),
        items_invalid=0,
    )
    assert all(o.observed_at == outcome.retrieved_at for o in outcome.observations)
