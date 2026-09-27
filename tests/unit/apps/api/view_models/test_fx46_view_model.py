"""FX-54V: unit tests for `build_fx46_view` -- pure, no I/O, no
recomputation of FX-46's own research."""

from forex_agent.apps.api.view_models.fx46_view_model import (
    RESEARCH_CONCLUSION_NOTE,
    build_fx46_view,
)
from forex_agent.infrastructure.research.fx46_research_artifact import (
    load_fx46_research_artifact,
)


def test_build_fx46_view_known_combination() -> None:
    artifact = load_fx46_research_artifact()

    view = build_fx46_view(artifact, "GBP_USD", "ANNOUNCED", "LEVEL")

    assert view["result"] is not None
    assert view["selected_pair"] == "GBP_USD"
    assert view["available_pairs"] == ["EUR_USD", "GBP_USD", "USD_CAD"]
    horizon_1 = view["result"]["primary_contrast"]["by_horizon"]["1"]
    assert isinstance(horizon_1["observed_diff"], str)  # exact Decimal string, never a float
    assert horizon_1["crosses_zero"] in (True, False, None)


def test_build_fx46_view_unknown_combination_returns_none_result() -> None:
    artifact = load_fx46_research_artifact()

    view = build_fx46_view(artifact, "XXX_YYY", "ANNOUNCED", "LEVEL")

    assert view["result"] is None


def test_research_conclusion_note_is_never_reworded_as_a_signal() -> None:
    # FX-54V Section 12: the conclusion must remain the null/general-
    # negative finding, never implying a validated signal.
    assert "does not establish" in RESEARCH_CONCLUSION_NOTE
    for forbidden in ("signal", "validated alpha", "profitable", "winner"):
        # "not validated alpha"/"is not validated alpha" is permitted --
        # only a POSITIVE claim of these terms is forbidden.
        if forbidden == "validated alpha":
            assert "not validated alpha" in RESEARCH_CONCLUSION_NOTE
        else:
            assert forbidden not in RESEARCH_CONCLUSION_NOTE.lower()


def test_not_computable_cell_reported_with_note_not_a_fabricated_number() -> None:
    artifact = load_fx46_research_artifact()

    view = build_fx46_view(artifact, "GBP_USD", "EFFECTIVE", "LEVEL")

    horizon_1 = view["result"]["primary_contrast"]["by_horizon"]["1"]
    assert horizon_1["observed_diff"] is None
    assert horizon_1["note"] is not None
    assert horizon_1["crosses_zero"] is None
