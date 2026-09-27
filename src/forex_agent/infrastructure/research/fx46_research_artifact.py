"""FX-54V: a typed, validating loader for FX-46's already-committed
research artifact (`research_results/fx46/policy_rate_differential_
research.json`). Read-only, local-file, no network -- FX-46's own
research is NEVER rerun by this loader or by anything downstream of it
(FX-54V Section 10/29): the dashboard visualizes what FX-46 already
concluded, nothing more.

The artifact stores every statistical quantity (means, confidence
bounds, differences) as a JSON STRING, not a JSON number -- FX-46's
own choice to preserve exact `Decimal` precision through JSON's lossy
float representation. This loader parses every such field via
`Decimal(...)`, never `float(...)`, and never assumes a field exists:
a field genuinely absent or malformed raises `MalformedFx46ArtifactError`
immediately (fail closed, mirroring this project's own `MalformedIcsError`/
`MalformedFeedError` convention for a document that does not match its
expected shape) rather than silently defaulting to `None`/`0`.

Deliberately does NOT model every nested field the raw JSON contains
(`groups`/`by_era`/`stats`/`censored_count` are read but not exposed on
these typed containers) -- this loader's own scope is exactly what
FX-54V's forest/CI visualization and its coverage panel need
(`disposition_counts`, `primary_contrast`), not a complete schema
mirror. A future story needing the full per-group/per-era breakdown
can extend this loader; it must not need to change the committed
artifact's own format to do so.
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FX46_ARTIFACT_PATH = (
    _REPO_ROOT / "research_results" / "fx46" / "policy_rate_differential_research.json"
)

#: The exact experiment/semantics dimensions FX-46's own artifact declares
#: (`config.rate_semantics`) -- used only to validate the loaded artifact
#: actually has the shape this loader expects, never to filter results.
_EXPECTED_SEMANTICS = ("ANNOUNCED", "EFFECTIVE")
_EXPECTED_EXPERIMENTS = ("LEVEL", "CHANGE")
_EXPECTED_HORIZONS = ("1", "5", "20")


class MalformedFx46ArtifactError(ValueError):
    """Raised when the FX-46 artifact file does not parse as JSON, or
    parses but is missing a field this loader requires, or a numeric
    field is not a well-formed decimal string -- never silently
    defaulted, per this module's own docstring."""


@dataclass(frozen=True, slots=True)
class Fx46DispositionCounts:
    """How many of a (pair, semantics, experiment) combination's raw
    sample rows FX-46 actually used vs. excluded, and why -- FX-54V
    Section 13's own "sample/coverage information," never converted to
    zero or hidden."""

    by_disposition: dict[str, int]
    by_disposition_and_reason: dict[str, dict[str, int]]
    total: int


@dataclass(frozen=True, slots=True)
class Fx46ContrastHorizon:
    """One forward-horizon's worth of FX-46's own primary bootstrap
    contrast (`observed_diff`/`lower_95`/`upper_95` -- FX-54V Section
    11's forest-plot data) between `group_a` and `group_b`. Every
    Decimal field is `None` together (never partially) when FX-46's
    own artifact marks the cell `not computable` (e.g. a group with
    zero usable observations at this horizon) -- `note` then carries
    FX-46's own explanation verbatim, never replaced by a fabricated
    number."""

    group_a: str
    group_b: str
    n_a: int
    n_b: int
    n_years_a: int
    n_years_b: int
    observed_diff: Decimal | None
    lower_95: Decimal | None
    upper_95: Decimal | None
    fraction_le_zero: Decimal | None
    note: str | None

    @property
    def crosses_zero(self) -> bool | None:
        """Whether the 95% interval spans zero -- `None` (never a
        guess) when the interval itself was not computable. FX-54V
        Section 11: the visualization must make this obvious; it must
        NEVER be colored/labelled as a "signal" either way."""
        if self.lower_95 is None or self.upper_95 is None:
            return None
        return self.lower_95 <= Decimal(0) <= self.upper_95


@dataclass(frozen=True, slots=True)
class Fx46PrimaryContrast:
    group_a: str
    group_b: str
    by_horizon: dict[str, Fx46ContrastHorizon]


@dataclass(frozen=True, slots=True)
class Fx46ExperimentResult:
    """One (pair, semantics, experiment) cell of FX-46's own results."""

    disposition_counts: Fx46DispositionCounts
    primary_contrast: Fx46PrimaryContrast


@dataclass(frozen=True, slots=True)
class Fx46ResearchArtifact:
    """The whole committed FX-46 artifact, typed -- `pairs[pair][semantics]
    [experiment]` mirrors the raw JSON's own nesting exactly."""

    story: str
    generated_at: str
    git_commit: str
    total_sample_rows: int
    pairs: dict[str, dict[str, dict[str, Fx46ExperimentResult]]]

    def result_for(
        self, pair: str, rate_semantics: str, experiment: str
    ) -> Fx46ExperimentResult | None:
        """`None` (never a `KeyError`) if `pair`/`rate_semantics`/
        `experiment` is not a combination this artifact contains --
        callers must treat that as "not available," never as a bug."""
        return self.pairs.get(pair, {}).get(rate_semantics, {}).get(experiment)


def load_fx46_research_artifact(
    path: Path = DEFAULT_FX46_ARTIFACT_PATH,
) -> Fx46ResearchArtifact:
    """Parses and validates the committed FX-46 artifact at `path` --
    deterministic, no network, no recomputation. Raises
    `MalformedFx46ArtifactError` (never returns a partial/best-effort
    result) if the file is missing, is not valid JSON, or is missing a
    field/has a malformed numeric field this loader requires."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MalformedFx46ArtifactError(f"could not read FX-46 artifact at {path}: {exc}") from exc

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact at {path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise MalformedFx46ArtifactError(f"FX-46 artifact at {path} top level is not an object")

    try:
        pairs_raw = _as_dict(raw["pairs"], "pairs")
        pairs = {
            pair: {
                semantics: {
                    experiment: _parse_experiment_result(
                        experiment_raw, pair, semantics, experiment
                    )
                    for experiment, experiment_raw in _require_keys(
                        _as_dict(semantics_raw, f"{pair}/{semantics}"),
                        _EXPECTED_EXPERIMENTS,
                        f"{pair}/{semantics}",
                    ).items()
                }
                for semantics, semantics_raw in _require_keys(
                    _as_dict(pair_raw, pair), _EXPECTED_SEMANTICS, pair
                ).items()
            }
            for pair, pair_raw in pairs_raw.items()
        }
        return Fx46ResearchArtifact(
            story=_as_str(raw["story"], "story"),
            generated_at=_as_str(raw["generated_at"], "generated_at"),
            git_commit=_as_str(raw["git_commit"], "git_commit"),
            total_sample_rows=_as_int(raw["total_sample_rows"], "total_sample_rows"),
            pairs=pairs,
        )
    except KeyError as exc:
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact at {path} is missing required field {exc}"
        ) from exc


def _as_dict(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact entry {context} must be an object, got {type(value).__name__}"
        )
    return value


def _as_str(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact field {context} must be a string, got {type(value).__name__}"
        )
    return value


def _as_optional_str(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _as_str(value, context)


def _as_int(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact field {context} must be an integer, got {type(value).__name__}"
        )
    return value


def _require_keys(
    raw: dict[str, object], expected_keys: tuple[str, ...], context: str
) -> dict[str, object]:
    """Fails closed if `raw` does not have EXACTLY `expected_keys`
    (FX-46's own declared `config.rate_semantics`/hardcoded LEVEL/
    CHANGE experiment pair/1-5-20 horizon dimensions) -- a truncated or
    reshaped artifact must never silently present as "fewer results,"
    it must be rejected outright."""
    actual_keys = set(raw)
    if actual_keys != set(expected_keys):
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact entry {context} has keys {sorted(actual_keys)}, expected exactly "
            f"{sorted(expected_keys)}"
        )
    return raw


def _parse_experiment_result(
    raw_obj: object, pair: str, semantics: str, experiment: str
) -> Fx46ExperimentResult:
    context = f"{pair}/{semantics}/{experiment}"
    raw = _as_dict(raw_obj, context)
    try:
        disposition_raw = _as_dict(raw["disposition_counts"], f"{context}/disposition_counts")
        disposition_counts = Fx46DispositionCounts(
            by_disposition=_as_int_dict(
                disposition_raw["by_disposition"], f"{context}/disposition_counts/by_disposition"
            ),
            by_disposition_and_reason=_as_nested_int_dict(
                disposition_raw["by_disposition_and_reason"],
                f"{context}/disposition_counts/by_disposition_and_reason",
            ),
            total=_as_int(disposition_raw["total"], f"{context}/disposition_counts/total"),
        )

        contrast_raw = _as_dict(raw["primary_contrast"], f"{context}/primary_contrast")
        by_horizon_raw = _as_dict(
            contrast_raw["by_horizon"], f"{context}/primary_contrast/by_horizon"
        )
        by_horizon = {
            horizon: _parse_contrast_horizon(horizon_raw, pair, semantics, experiment, horizon)
            for horizon, horizon_raw in _require_keys(
                by_horizon_raw, _EXPECTED_HORIZONS, f"{context}/primary_contrast/by_horizon"
            ).items()
        }
        primary_contrast = Fx46PrimaryContrast(
            group_a=_as_str(contrast_raw["group_a"], f"{context}/primary_contrast/group_a"),
            group_b=_as_str(contrast_raw["group_b"], f"{context}/primary_contrast/group_b"),
            by_horizon=by_horizon,
        )
    except KeyError as exc:
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact entry {context} is missing field {exc}"
        ) from exc
    return Fx46ExperimentResult(
        disposition_counts=disposition_counts, primary_contrast=primary_contrast
    )


def _as_int_dict(value: object, context: str) -> dict[str, int]:
    raw = _as_dict(value, context)
    return {k: _as_int(v, f"{context}/{k}") for k, v in raw.items()}


def _as_nested_int_dict(value: object, context: str) -> dict[str, dict[str, int]]:
    raw = _as_dict(value, context)
    return {k: _as_int_dict(v, f"{context}/{k}") for k, v in raw.items()}


def _parse_contrast_horizon(
    raw_obj: object, pair: str, semantics: str, experiment: str, horizon: str
) -> Fx46ContrastHorizon:
    context = f"{pair}/{semantics}/{experiment}/{horizon}"
    raw = _as_dict(raw_obj, context)
    try:
        return Fx46ContrastHorizon(
            group_a=_as_str(raw["group_a"], f"{context}/group_a"),
            group_b=_as_str(raw["group_b"], f"{context}/group_b"),
            n_a=_as_int(raw["n_a"], f"{context}/n_a"),
            n_b=_as_int(raw["n_b"], f"{context}/n_b"),
            n_years_a=_as_int(raw["n_years_a"], f"{context}/n_years_a"),
            n_years_b=_as_int(raw["n_years_b"], f"{context}/n_years_b"),
            observed_diff=_as_decimal_or_none(raw["observed_diff"], f"{context}/observed_diff"),
            lower_95=_as_decimal_or_none(raw["lower_95"], f"{context}/lower_95"),
            upper_95=_as_decimal_or_none(raw["upper_95"], f"{context}/upper_95"),
            fraction_le_zero=_as_decimal_or_none(
                raw["fraction_le_zero"], f"{context}/fraction_le_zero"
            ),
            note=_as_optional_str(raw["note"], f"{context}/note"),
        )
    except KeyError as exc:
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact entry {context} is missing field {exc}"
        ) from exc


def _as_decimal_or_none(value: object, context: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact field {context} must be a string or null, got {type(value).__name__}"
        )
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise MalformedFx46ArtifactError(
            f"FX-46 artifact field {context} is not a well-formed decimal string: {value!r}"
        ) from exc
