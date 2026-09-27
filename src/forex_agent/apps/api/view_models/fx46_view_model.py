"""FX-54V: pure builder converting a loaded `Fx46ResearchArtifact`
(FX-46's own committed research output) plus a caller-selected
(pair, semantics, experiment) filter into a JSON-safe dict for the
"Market Context" dashboard's forest/confidence-interval panel. No
recomputation, no network -- see `infrastructure.research.
fx46_research_artifact`'s own module docstring.

`RESEARCH_CONCLUSION_NOTE` mirrors `research_results/fx46/policy_rate_
differential_summary.md`'s own documented conclusion VERBATIM in
substance (FX-54V Section 12) -- this dashboard must never reinterpret
FX-46's two isolated confidence intervals that happened to exclude zero
as a trading signal; this constant is the one place that conclusion is
authored, so every consumer of this view model shows the identical,
correct wording.
"""

from typing import Any

from forex_agent.infrastructure.research.fx46_research_artifact import (
    Fx46ContrastHorizon,
    Fx46ExperimentResult,
    Fx46ResearchArtifact,
)

#: FX-54V Section 12 -- verbatim in substance with `policy_rate_
#: differential_summary.md`'s own "Limitations" conclusion. Never
#: reworded to imply a signal was found.
RESEARCH_CONCLUSION_NOTE = (
    "The available evidence does not establish a reliable general association "
    "between raw policy-rate differential (or its change) and subsequent "
    "short-horizon FX returns. A confidence interval that excludes zero at one "
    "pair/horizon/semantics combination is not validated alpha -- it is one "
    "isolated statistical result among many tested, and does not by itself "
    "establish a tradeable, general relationship."
)


def _horizon_view(horizon: Fx46ContrastHorizon) -> dict[str, Any]:
    return {
        "group_a": horizon.group_a,
        "group_b": horizon.group_b,
        "n_a": horizon.n_a,
        "n_b": horizon.n_b,
        "n_years_a": horizon.n_years_a,
        "n_years_b": horizon.n_years_b,
        "observed_diff": (None if horizon.observed_diff is None else str(horizon.observed_diff)),
        "lower_95": (None if horizon.lower_95 is None else str(horizon.lower_95)),
        "upper_95": (None if horizon.upper_95 is None else str(horizon.upper_95)),
        "fraction_le_zero": (
            None if horizon.fraction_le_zero is None else str(horizon.fraction_le_zero)
        ),
        "crosses_zero": horizon.crosses_zero,
        "note": horizon.note,
    }


def _result_view(result: Fx46ExperimentResult) -> dict[str, Any]:
    return {
        "disposition_counts": {
            "by_disposition": result.disposition_counts.by_disposition,
            "by_disposition_and_reason": result.disposition_counts.by_disposition_and_reason,
            "total": result.disposition_counts.total,
        },
        "primary_contrast": {
            "group_a": result.primary_contrast.group_a,
            "group_b": result.primary_contrast.group_b,
            "by_horizon": {
                horizon: _horizon_view(h)
                for horizon, h in result.primary_contrast.by_horizon.items()
            },
        },
    }


def build_fx46_view(
    artifact: Fx46ResearchArtifact, pair: str, rate_semantics: str, experiment: str
) -> dict[str, Any]:
    """The forest/CI panel's own JSON-safe read model for one selected
    (pair, semantics, experiment) filter -- `result` is `None` (never a
    fabricated empty result) when that combination is not present in
    the artifact at all."""
    result = artifact.result_for(pair, rate_semantics, experiment)
    return {
        "story": artifact.story,
        "generated_at": artifact.generated_at,
        "git_commit": artifact.git_commit,
        "total_sample_rows": artifact.total_sample_rows,
        "research_conclusion_note": RESEARCH_CONCLUSION_NOTE,
        "selected_pair": pair,
        "selected_rate_semantics": rate_semantics,
        "selected_experiment": experiment,
        "available_pairs": sorted(artifact.pairs),
        "result": None if result is None else _result_view(result),
    }
