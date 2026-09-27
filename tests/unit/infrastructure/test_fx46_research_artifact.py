"""FX-54V: unit tests for `load_fx46_research_artifact` -- both against
the REAL committed artifact (deterministic, no network, no
recomputation) and against deliberately malformed fixtures (fail
closed, never a silently missing field)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from forex_agent.infrastructure.research.fx46_research_artifact import (
    DEFAULT_FX46_ARTIFACT_PATH,
    MalformedFx46ArtifactError,
    load_fx46_research_artifact,
)


def test_default_artifact_path_points_at_the_committed_file() -> None:
    assert DEFAULT_FX46_ARTIFACT_PATH.exists()
    assert DEFAULT_FX46_ARTIFACT_PATH.name == "policy_rate_differential_research.json"


def test_loads_the_real_committed_artifact() -> None:
    artifact = load_fx46_research_artifact()

    assert artifact.story == "FX-46"
    assert set(artifact.pairs) == {"EUR_USD", "GBP_USD", "USD_CAD"}
    assert artifact.total_sample_rows > 0


def test_result_for_resolves_a_known_combination() -> None:
    artifact = load_fx46_research_artifact()

    result = artifact.result_for("GBP_USD", "ANNOUNCED", "LEVEL")

    assert result is not None
    assert result.disposition_counts.total > 0
    horizon_1 = result.primary_contrast.by_horizon["1"]
    assert isinstance(horizon_1.observed_diff, Decimal)
    assert isinstance(horizon_1.lower_95, Decimal)
    assert isinstance(horizon_1.upper_95, Decimal)


def test_result_for_returns_none_for_unknown_combination() -> None:
    artifact = load_fx46_research_artifact()

    assert artifact.result_for("XXX_YYY", "ANNOUNCED", "LEVEL") is None


def test_not_computable_cell_has_all_none_bounds_and_a_note() -> None:
    # GBP EFFECTIVE has zero usable observations at every horizon
    # (FX-46's own documented coverage gap) -- verified against the
    # REAL artifact, not a synthetic fixture.
    artifact = load_fx46_research_artifact()

    result = artifact.result_for("GBP_USD", "EFFECTIVE", "LEVEL")

    assert result is not None
    horizon_1 = result.primary_contrast.by_horizon["1"]
    assert horizon_1.observed_diff is None
    assert horizon_1.lower_95 is None
    assert horizon_1.upper_95 is None
    assert horizon_1.note is not None
    assert horizon_1.crosses_zero is None  # never a guess when not computable


def test_crosses_zero_true_when_interval_spans_zero() -> None:
    artifact = load_fx46_research_artifact()
    result = artifact.result_for("GBP_USD", "ANNOUNCED", "LEVEL")
    assert result is not None
    horizon_1 = result.primary_contrast.by_horizon["1"]

    assert horizon_1.lower_95 is not None and horizon_1.lower_95 < 0
    assert horizon_1.upper_95 is not None and horizon_1.upper_95 > 0
    assert horizon_1.crosses_zero is True


# --- Malformed artifact fixtures (fail closed) -------------------------------

_VALID_MINIMAL_HORIZON = {
    "group_a": "POSITIVE",
    "group_b": "NEGATIVE",
    "n_a": 1,
    "n_b": 1,
    "n_years_a": 1,
    "n_years_b": 1,
    "observed_diff": "0.001",
    "lower_95": "-0.001",
    "upper_95": "0.003",
    "fraction_le_zero": "0.5",
    "note": None,
}


def _valid_minimal_artifact() -> dict[str, object]:
    experiment_result = {
        "disposition_counts": {
            "by_disposition": {"USABLE": 1},
            "by_disposition_and_reason": {},
            "total": 1,
        },
        "primary_contrast": {
            "group_a": "POSITIVE",
            "group_b": "NEGATIVE",
            "by_horizon": {
                "1": _VALID_MINIMAL_HORIZON,
                "5": _VALID_MINIMAL_HORIZON,
                "20": _VALID_MINIMAL_HORIZON,
            },
        },
    }
    experiments = {"LEVEL": experiment_result, "CHANGE": experiment_result}
    semantics = {"ANNOUNCED": experiments, "EFFECTIVE": experiments}
    return {
        "story": "FX-46",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "git_commit": "abc123",
        "total_sample_rows": 1,
        "pairs": {"GBP_USD": semantics},
    }


def test_loads_a_valid_minimal_fixture(tmp_path: Path) -> None:
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(_valid_minimal_artifact()))

    artifact = load_fx46_research_artifact(path)

    assert artifact.story == "FX-46"
    result = artifact.result_for("GBP_USD", "ANNOUNCED", "LEVEL")
    assert result is not None
    assert result.primary_contrast.by_horizon["1"].observed_diff == Decimal("0.001")


def test_missing_file_raises_malformed_error(tmp_path: Path) -> None:
    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(tmp_path / "does_not_exist.json")


def test_invalid_json_raises_malformed_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_missing_top_level_field_raises_malformed_error(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    del data["total_sample_rows"]
    path = tmp_path / "missing_field.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_missing_semantics_dimension_raises_malformed_error(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    del data["pairs"]["GBP_USD"]["EFFECTIVE"]  # type: ignore[index]
    path = tmp_path / "missing_semantics.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_missing_experiment_dimension_raises_malformed_error(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    del data["pairs"]["GBP_USD"]["ANNOUNCED"]["CHANGE"]  # type: ignore[index]
    path = tmp_path / "missing_experiment.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_missing_horizon_dimension_raises_malformed_error(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    del data["pairs"]["GBP_USD"]["ANNOUNCED"]["LEVEL"]["primary_contrast"]["by_horizon"]["20"]  # type: ignore[index]
    path = tmp_path / "missing_horizon.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_non_string_numeric_field_raises_malformed_error(tmp_path: Path) -> None:
    # FX-46 stores every numeric quantity as a JSON STRING (to preserve
    # exact Decimal precision) -- a raw JSON number here must be
    # rejected, never silently coerced.
    data = _valid_minimal_artifact()
    data["pairs"]["GBP_USD"]["ANNOUNCED"]["LEVEL"]["primary_contrast"]["by_horizon"]["1"][  # type: ignore[index]
        "observed_diff"
    ] = 0.001
    path = tmp_path / "non_string_numeric.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_malformed_decimal_string_raises_malformed_error(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    data["pairs"]["GBP_USD"]["ANNOUNCED"]["LEVEL"]["primary_contrast"]["by_horizon"]["1"][  # type: ignore[index]
        "observed_diff"
    ] = "not-a-decimal"
    path = tmp_path / "malformed_decimal.json"
    path.write_text(json.dumps(data))

    with pytest.raises(MalformedFx46ArtifactError):
        load_fx46_research_artifact(path)


def test_non_null_note_round_trips(tmp_path: Path) -> None:
    data = _valid_minimal_artifact()
    horizon = data["pairs"]["GBP_USD"]["ANNOUNCED"]["LEVEL"]["primary_contrast"]["by_horizon"][  # type: ignore[index]
        "1"
    ]
    horizon["note"] = "not computable: one or both groups have zero usable observations"
    horizon["observed_diff"] = None
    horizon["lower_95"] = None
    horizon["upper_95"] = None
    horizon["fraction_le_zero"] = None
    path = tmp_path / "with_note.json"
    path.write_text(json.dumps(data))

    artifact = load_fx46_research_artifact(path)

    result = artifact.result_for("GBP_USD", "ANNOUNCED", "LEVEL")
    assert result is not None
    parsed_horizon = result.primary_contrast.by_horizon["1"]
    assert parsed_horizon.note == "not computable: one or both groups have zero usable observations"
    assert parsed_horizon.observed_diff is None
    assert parsed_horizon.crosses_zero is None
