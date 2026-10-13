from dataclasses import dataclass

from forex_agent.domain.forecast_attribution_kind import ForecastAttributionKind


@dataclass(frozen=True, slots=True)
class ForecastAttribution:
    """FX-64 Section 8: WHO originated a forecast, and WHO published
    it -- always kept structurally distinct, reusing FX-62's own
    `IntelligenceSource`/source identity keys for both roles. The
    `__post_init__` below makes every attribution kind's own
    structural invariant unconstructable to violate:

    - `NAMED_INSTITUTION`: `forecaster_source_key` REQUIRED (the FX-62
      identity issuing the forecast as its own); `anonymous_
      respondent_id` FORBIDDEN.
    - `AGGREGATE_SURVEY_CONSENSUS`: BOTH `forecaster_source_key` and
      `anonymous_respondent_id` FORBIDDEN -- an aggregate statistic
      has no forecaster identity of any kind, named or pseudonymous.
    - `ANONYMOUS_RESPONDENT`: `forecaster_source_key` FORBIDDEN (never
      a named FX-62 identity); `anonymous_respondent_id` OPTIONAL (set
      only when the source's own documentation establishes genuinely
      stable continuity, per Section 8 -- otherwise `None`).

    `publisher_source_key` is ALWAYS required, for every kind -- the
    survey/distribution channel's own FX-62 identity, which may or may
    not be the same actor as the forecaster (it never is, for
    `AGGREGATE_SURVEY_CONSENSUS`)."""

    kind: ForecastAttributionKind
    publisher_source_key: str
    forecaster_source_key: str | None = None
    anonymous_respondent_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ForecastAttributionKind):
            raise TypeError(
                f"kind must be a ForecastAttributionKind, got {type(self.kind).__name__}"
            )
        if not isinstance(self.publisher_source_key, str) or not self.publisher_source_key.strip():
            raise ValueError(
                f"publisher_source_key must be a non-empty string, got "
                f"{self.publisher_source_key!r}"
            )
        for optional_field in (self.forecaster_source_key, self.anonymous_respondent_id):
            if optional_field is not None and (
                not isinstance(optional_field, str) or not optional_field.strip()
            ):
                raise ValueError(
                    "forecaster_source_key/anonymous_respondent_id must be a non-empty string "
                    f"or None, got {optional_field!r}"
                )

        if self.kind is ForecastAttributionKind.NAMED_INSTITUTION:
            if self.forecaster_source_key is None:
                raise ValueError("forecaster_source_key is required for NAMED_INSTITUTION")
            if self.anonymous_respondent_id is not None:
                raise ValueError("anonymous_respondent_id must be None for NAMED_INSTITUTION")
        elif self.kind is ForecastAttributionKind.AGGREGATE_SURVEY_CONSENSUS:
            if self.forecaster_source_key is not None:
                raise ValueError(
                    "forecaster_source_key must be None for AGGREGATE_SURVEY_CONSENSUS -- an "
                    "aggregate statistic is not personally forecast by any one entity"
                )
            if self.anonymous_respondent_id is not None:
                raise ValueError(
                    "anonymous_respondent_id must be None for AGGREGATE_SURVEY_CONSENSUS"
                )
        elif self.kind is ForecastAttributionKind.ANONYMOUS_RESPONDENT:
            if self.forecaster_source_key is not None:
                raise ValueError(
                    "forecaster_source_key must be None for ANONYMOUS_RESPONDENT -- never a "
                    "named FX-62 identity"
                )
