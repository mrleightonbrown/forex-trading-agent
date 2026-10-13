"""FX-64 Section 8: tests for `ForecastAttribution` -- the architect's
own explicit concern (institution-as-publisher vs. institution-as-
forecaster vs. anonymous/aggregate attribution) enforced structurally."""

import pytest

from forex_agent.domain.forecast_attribution import ForecastAttribution
from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind


def test_named_institution_valid() -> None:
    attribution = ForecastAttribution(
        kind=ForecastAttributionKind.NAMED_INSTITUTION,
        publisher_source_key="ECB",
        forecaster_source_key="ECB",
    )
    assert attribution.forecaster_source_key == "ECB"


def test_named_institution_requires_forecaster_source_key() -> None:
    with pytest.raises(ValueError, match="forecaster_source_key"):
        ForecastAttribution(
            kind=ForecastAttributionKind.NAMED_INSTITUTION, publisher_source_key="ECB"
        )


def test_named_institution_rejects_anonymous_respondent_id() -> None:
    with pytest.raises(ValueError, match="anonymous_respondent_id"):
        ForecastAttribution(
            kind=ForecastAttributionKind.NAMED_INSTITUTION,
            publisher_source_key="ECB",
            forecaster_source_key="ECB",
            anonymous_respondent_id="R1",
        )


def test_aggregate_survey_consensus_valid() -> None:
    """The architect's own worked example: the Bank of Canada
    publishes a median forecast without itself being the forecaster."""
    attribution = ForecastAttribution(
        kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
        publisher_source_key="BANK_OF_CANADA",
    )
    assert attribution.forecaster_source_key is None
    assert attribution.publisher_source_key == "BANK_OF_CANADA"


def test_aggregate_survey_consensus_rejects_forecaster_source_key() -> None:
    with pytest.raises(ValueError, match="forecaster_source_key must be None"):
        ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="BANK_OF_CANADA",
            forecaster_source_key="BANK_OF_CANADA",
        )


def test_aggregate_survey_consensus_rejects_anonymous_respondent_id() -> None:
    with pytest.raises(ValueError, match="anonymous_respondent_id must be None"):
        ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS,
            publisher_source_key="BANK_OF_CANADA",
            anonymous_respondent_id="R1",
        )


def test_anonymous_respondent_without_identifier_valid() -> None:
    attribution = ForecastAttribution(
        kind=ForecastAttributionKind.ANONYMOUS_RESPONDENT,
        publisher_source_key="BANK_OF_CANADA",
    )
    assert attribution.anonymous_respondent_id is None


def test_anonymous_respondent_with_stable_pseudonymous_id_valid() -> None:
    attribution = ForecastAttribution(
        kind=ForecastAttributionKind.ANONYMOUS_RESPONDENT,
        publisher_source_key="BANK_OF_CANADA",
        anonymous_respondent_id="RESPONDENT-7",
    )
    assert attribution.anonymous_respondent_id == "RESPONDENT-7"


def test_anonymous_respondent_rejects_forecaster_source_key() -> None:
    """Never a named FX-62 identity for an anonymous respondent."""
    with pytest.raises(ValueError, match="forecaster_source_key must be None"):
        ForecastAttribution(
            kind=ForecastAttributionKind.ANONYMOUS_RESPONDENT,
            publisher_source_key="BANK_OF_CANADA",
            forecaster_source_key="SOME_INVENTED_NAME",
        )


def test_publisher_distinct_from_forecaster_for_named_institution() -> None:
    """A publisher may distribute a forecast it did not itself issue
    -- publisher and forecaster are independent fields even for
    NAMED_INSTITUTION."""
    attribution = ForecastAttribution(
        kind=ForecastAttributionKind.NAMED_INSTITUTION,
        publisher_source_key="REUTERS",
        forecaster_source_key="ECB",
    )
    assert attribution.publisher_source_key != attribution.forecaster_source_key


def test_empty_publisher_source_key_rejected() -> None:
    with pytest.raises(ValueError, match="publisher_source_key"):
        ForecastAttribution(
            kind=ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS, publisher_source_key=""
        )


def test_wrong_kind_type_rejected() -> None:
    with pytest.raises(TypeError, match="kind"):
        ForecastAttribution(kind="NAMED_INSTITUTION", publisher_source_key="ECB")  # type: ignore[arg-type]
