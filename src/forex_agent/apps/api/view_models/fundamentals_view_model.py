"""FX-54V: pure builders converting `FundamentalRateEvidence`/
`PolicyRateHistory` (already-fetched domain results) into JSON-safe
dict structures for the "Market Context" dashboard's Fundamentals
card/history chart. No I/O, no repository access -- everything here
takes an already-resolved domain object and returns plain
dicts/lists/strings/None; the HTTP/HTML layer decides how to render
them.

Every `Decimal` is rendered via `str(...)`, never `float(...)` --
JSON's own lossy float representation must never be allowed to corrupt
an exact policy-rate value on its way to the browser. `differential`
is always labelled "Raw policy-rate differential" here -- never
"fundamental advantage"/"strength"/"bias" (FX-54V Section 7/15): this
is this story's own single enforcement point for that label, so a
future edit accidentally introducing a directional label would have
to change this file specifically to do so.
"""

from typing import Any

from forex_agent.domain.macro_observation_vintage import MacroObservationVintage
from forex_agent.domain.policy_rate_differential import (
    CurrencyRateState,
    FundamentalRateEvidence,
    PolicyRateHistory,
)

#: FX-54V Section 7: this label is deliberate and must never be
#: replaced with a directional/interpretive one anywhere this view
#: model is consumed.
RAW_DIFFERENTIAL_LABEL = "Raw policy-rate differential"


def _currency_state_view(state: CurrencyRateState | None, reason: str | None) -> dict[str, Any]:
    if state is None:
        return {
            "available": False,
            "unavailable_reason": reason,
        }
    return {
        "available": True,
        "currency": state.currency,
        "rate_percent": str(state.rate),
        "series_key": state.series_key,
        "observation_period": state.observation_period.value.isoformat(),
        "revision_sequence": state.revision_sequence,
        "released_at": state.released_at.value.isoformat(),
        "effective_at": (
            None if state.effective_at is None else state.effective_at.value.isoformat()
        ),
        "released_at_is_verified": state.released_at_is_verified,
        "released_at_is_conservative_bound": state.released_at_is_conservative_bound,
    }


def build_fundamentals_view(evidence: FundamentalRateEvidence) -> dict[str, Any]:
    """The Fundamentals card's own JSON-safe read model."""
    differential_view: dict[str, Any]
    if evidence.differential is None:
        differential_view = {"available": False, "label": RAW_DIFFERENTIAL_LABEL}
    else:
        differential_view = {
            "available": True,
            "label": RAW_DIFFERENTIAL_LABEL,
            "value_pp": str(evidence.differential),
        }
    return {
        "pair": evidence.pair,
        "as_of": evidence.as_of.value.isoformat(),
        "rate_semantics": evidence.rate_semantics.value,
        "base_currency": evidence.base_currency,
        "quote_currency": evidence.quote_currency,
        "base": _currency_state_view(evidence.base, evidence.base_unavailable_reason),
        "quote": _currency_state_view(evidence.quote, evidence.quote_unavailable_reason),
        "differential": differential_view,
    }


def _history_points(history: tuple[MacroObservationVintage, ...]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for vintage in history:
        points.append(
            {
                "observation_period": vintage.observation_period.value.isoformat(),
                "rate_percent": str(vintage.value),
                "released_at": vintage.released_at.value.isoformat(),
                "effective_at": (
                    None if vintage.effective_at is None else vintage.effective_at.value.isoformat()
                ),
            }
        )
    return points


def build_policy_rate_history_view(history: PolicyRateHistory) -> dict[str, Any]:
    """The policy-rate history chart's own JSON-safe read model --
    `base_history`/`quote_history` are each already-ordered,
    already-PIT-filtered, never smoothed or interpolated (see
    `PolicyRateHistory`'s own docstring); this builder only reshapes
    each point into plain, display-safe fields."""
    return {
        "base_currency": history.base_currency,
        "quote_currency": history.quote_currency,
        "rate_semantics": history.rate_semantics.value,
        "base_history": _history_points(history.base_history),
        "quote_history": _history_points(history.quote_history),
    }
