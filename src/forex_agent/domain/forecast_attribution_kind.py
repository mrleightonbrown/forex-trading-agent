from enum import Enum


class ForecastAttributionKind(Enum):
    """FX-64 Section 8: WHO a forecast is attributed to, as a closed
    set of structurally distinct cases -- the architect's own explicit
    concern: "the Bank of Canada publishing a median forecast does not
    make the Bank of Canada the forecaster." `ForecastAttribution`'s
    own `__post_init__` makes it impossible to construct an attribution
    that conflates these."""

    NAMED_INSTITUTION = "NAMED_INSTITUTION"
    """The institution explicitly issues the forecast AS ITS OWN
    (Section 8's own "institutional forecast") -- e.g. a central
    bank's own staff projection published under its own name."""

    AGGREGATE_SURVEY_CONSENSUS = "AGGREGATE_SURVEY_CONSENSUS"
    """An aggregate statistic (e.g. a median or mean) over many survey
    respondents -- NOT a forecast made personally by any one entity,
    including the survey's own publisher/operator. Carries no
    forecaster identity at all, named or pseudonymous."""

    ANONYMOUS_RESPONDENT = "ANONYMOUS_RESPONDENT"
    """One individual survey respondent whose identity the source
    itself keeps anonymous -- never assigned an invented name or
    institution. A stable pseudonymous identifier may be attached ONLY
    when the source's own documentation establishes that identifiers
    are genuinely stable across rounds (Section 8); otherwise this
    respondent is attributed with no identifier at all."""
