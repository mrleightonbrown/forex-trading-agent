"""FX-54V: the "Market Context" dashboard -- a READ-ONLY visualization
surface over evidence FX-EPIC-06 (policy-rate/macro PIT infrastructure,
FX-46's own committed research) and FX-EPIC-07 (FX-51..FX-54's PIT
economic-event model/evidence snapshot) already produce. See `docs/
ARCHITECTURE.md`'s own FX-54V section for the full layering rationale.

This router is the ONLY place in this story that resolves a "current
UTC" convenience default into an explicit `UtcTimestamp` (`_resolve_as_
of`) -- every use case below still receives that already-resolved,
explicit instant; none of them ever calls `datetime.now()` themselves
(FX-54V Section 4). It is also the ONLY place `SUPPORTED_PAIRS`/pair
validation happens for this dashboard specifically (`apps.api.pairs`,
a presentation-facing concept, not a domain one).

Performs NO live-source polling of any kind (FX-54V Section 6/24):
every route below reads already-persisted/already-ingested evidence
through `MacroObservationRepository`/`EconomicEventRepository`, or the
already-committed FX-46 artifact from local disk -- never BLS, ONS,
Bank of Canada, FRED, or any central-bank/commercial endpoint.
"""

import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from forex_agent.application.use_cases.get_event_risk_evidence_snapshot import (
    GetEventRiskEvidenceSnapshot,
)
from forex_agent.application.use_cases.get_fundamental_rate_evidence import (
    GetFundamentalRateEvidence,
)
from forex_agent.application.use_cases.get_pair_news_evidence_snapshot import (
    GetPairNewsEvidenceSnapshot,
)
from forex_agent.application.use_cases.get_policy_rate_history import GetPolicyRateHistory
from forex_agent.apps.api.market_context_page import render_market_context_page
from forex_agent.apps.api.pairs import SUPPORTED_PAIRS, resolve_pair
from forex_agent.apps.api.view_models.events_view_model import build_events_view
from forex_agent.apps.api.view_models.fundamentals_view_model import (
    build_fundamentals_view,
    build_policy_rate_history_view,
)
from forex_agent.apps.api.view_models.fx46_view_model import build_fx46_view
from forex_agent.apps.api.view_models.news_evidence_view_model import build_news_evidence_view
from forex_agent.domain.instrument import Instrument
from forex_agent.domain.policy_rate_differential import RateSemantics
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.economic_event_repository import (
    SqlAlchemyEconomicEventRepository,
)
from forex_agent.infrastructure.db.macro_observation_repository import (
    SqlAlchemyMacroObservationRepository,
)
from forex_agent.infrastructure.db.news_canonicalization_repository import (
    SqlAlchemyNewsCanonicalizationRepository,
)
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_session
from forex_agent.infrastructure.research.fx46_research_artifact import (
    Fx46ResearchArtifact,
    MalformedFx46ArtifactError,
    load_fx46_research_artifact,
)

router = APIRouter(tags=["market-context"])

#: FX-54V Section 17: presentation defaults ONLY -- always visible/
#: editable via query params, never trading policy (Section 16).
_DEFAULT_LOOKAHEAD = timedelta(hours=24)
_DEFAULT_LOOKBACK = timedelta(hours=48)
_DEFAULT_RATE_SEMANTICS = RateSemantics.ANNOUNCED
_DEFAULT_FX46_EXPERIMENT = "LEVEL"

#: FX-61 Section 4.1: a PRESENTATION convenience default only, never a
#: trading or news-importance policy -- independently configurable,
#: and deliberately NOT shared with `_DEFAULT_LOOKBACK` above (the
#: existing economic-event lookback must never be silently repurposed
#: for news, Section 4.1's own explicit requirement).
_DEFAULT_NEWS_LOOKBACK = timedelta(days=7)

#: FX-46's own committed research artifact never changes at runtime
#: (FX-54V Section 41: "may be cached in-process after validated
#: loading... since it is immutable research output"). Loaded once, on
#: first request, and reused -- explicit, testable cache semantics: a
#: module-level `| None` set exactly once, never invalidated, since a
#: NEW artifact would be a NEW committed file requiring a process
#: restart to pick up anyway (deployment already restarts on deploy).
_fx46_artifact_cache: Fx46ResearchArtifact | None = None


def _get_fx46_artifact() -> Fx46ResearchArtifact:
    global _fx46_artifact_cache
    if _fx46_artifact_cache is None:
        try:
            _fx46_artifact_cache = load_fx46_research_artifact()
        except MalformedFx46ArtifactError as exc:
            raise HTTPException(
                status_code=500, detail=f"FX-46 research artifact is unavailable: {exc}"
            ) from exc
    return _fx46_artifact_cache


def _resolve_as_of(as_of: str | None) -> UtcTimestamp:
    """The ONE place this whole story calls `datetime.now()` (FX-54V
    Section 4) -- only when the caller omits `as_of` entirely, as an
    explicit UI convenience default. Once resolved, this instant is
    passed EXPLICITLY into every use case below; nothing downstream
    ever resolves "now" for itself. An explicitly-supplied `as_of` must
    parse as ISO 8601 or this raises `HTTPException(400)` -- never
    silently falls back to "now" on a malformed value."""
    if as_of is None:
        return UtcTimestamp(datetime.now(UTC).replace(microsecond=0))
    try:
        parsed = datetime.fromisoformat(as_of)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"as_of must be ISO 8601, got {as_of!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail=f"as_of must be timezone-aware, got {as_of!r}")
    return UtcTimestamp(parsed)


def _resolve_rate_semantics(rate_semantics: str) -> RateSemantics:
    try:
        return RateSemantics(rate_semantics)
    except ValueError as exc:
        allowed = [s.value for s in RateSemantics]
        raise HTTPException(
            status_code=400,
            detail=f"rate_semantics must be one of {allowed}, got {rate_semantics!r}",
        ) from exc


def _resolve_supported_pair(pair: str) -> Instrument:
    instrument = resolve_pair(pair)
    if instrument is None:
        supported = sorted(SUPPORTED_PAIRS)
        raise HTTPException(
            status_code=404,
            detail=f"unsupported pair {pair!r} -- this dashboard supports {supported}",
        )
    return instrument


@router.get("/api/market-context/{pair}/fundamentals")
async def get_fundamentals(
    pair: str,
    as_of: str | None = Query(default=None),
    rate_semantics: str = Query(default=_DEFAULT_RATE_SEMANTICS.value),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    instrument = _resolve_supported_pair(pair)
    resolved_as_of = _resolve_as_of(as_of)
    resolved_semantics = _resolve_rate_semantics(rate_semantics)
    repository = SqlAlchemyMacroObservationRepository(session)
    use_case = GetFundamentalRateEvidence(repository=repository)
    evidence = await use_case(instrument, resolved_as_of, resolved_semantics)
    return build_fundamentals_view(evidence)


@router.get("/api/market-context/{pair}/policy-rate-history")
async def get_policy_rate_history_route(
    pair: str,
    as_of: str | None = Query(default=None),
    rate_semantics: str = Query(default=_DEFAULT_RATE_SEMANTICS.value),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    instrument = _resolve_supported_pair(pair)
    resolved_as_of = _resolve_as_of(as_of)
    resolved_semantics = _resolve_rate_semantics(rate_semantics)
    repository = SqlAlchemyMacroObservationRepository(session)
    use_case = GetPolicyRateHistory(repository=repository)
    history = await use_case(instrument, resolved_as_of, resolved_semantics)
    return build_policy_rate_history_view(history)


@router.get("/api/market-context/{pair}/events")
async def get_events(
    pair: str,
    as_of: str | None = Query(default=None),
    lookahead_hours: float = Query(default=_DEFAULT_LOOKAHEAD.total_seconds() / 3600),
    lookback_hours: float = Query(default=_DEFAULT_LOOKBACK.total_seconds() / 3600),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    instrument = _resolve_supported_pair(pair)
    resolved_as_of = _resolve_as_of(as_of)
    if lookahead_hours < 0 or lookback_hours < 0:
        raise HTTPException(
            status_code=400, detail="lookahead_hours/lookback_hours must not be negative"
        )
    repository = SqlAlchemyEconomicEventRepository(session)
    use_case = GetEventRiskEvidenceSnapshot(repository=repository)
    snapshot = await use_case(
        instrument,
        resolved_as_of,
        timedelta(hours=lookahead_hours),
        timedelta(hours=lookback_hours),
    )
    return build_events_view(snapshot)


def _resolve_news_window_start(
    resolved_as_of: UtcTimestamp, news_lookback_hours: float
) -> UtcTimestamp:
    """FX-61H Section H1: validates `news_lookback_hours` AND computes
    `window_start` in ONE place, entirely before any repository/
    session work -- a non-finite (`NaN`/`+-inf`), non-positive, or
    unrepresentable value (one whose `timedelta` construction or
    `window_start` subtraction would overflow Python's own datetime
    range) always raises a controlled `HTTPException(400)`, never an
    unhandled 500. `news_lookback_hours <= 0` alone does NOT catch
    `NaN` (`NaN <= 0` is `False` in Python), so finiteness is checked
    FIRST, explicitly. No arbitrary trading-policy maximum is imposed
    here -- only Python's own representable-datetime boundary is
    enforced, which is a technical constraint, not a business one."""
    if not math.isfinite(news_lookback_hours):
        raise HTTPException(status_code=400, detail="news_lookback_hours must be a finite number")
    if news_lookback_hours <= 0:
        raise HTTPException(status_code=400, detail="news_lookback_hours must be positive")
    try:
        news_lookback = timedelta(hours=news_lookback_hours)
        return UtcTimestamp(resolved_as_of.value - news_lookback)
    except (OverflowError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"news_lookback_hours is too large to represent: {news_lookback_hours!r}",
        ) from exc


async def _build_news_evidence_view(
    instrument: Instrument,
    resolved_as_of: UtcTimestamp,
    window_start: UtcTimestamp,
    session: AsyncSession,
) -> dict[str, object]:
    """FX-61 Section 3: the ONLY place this story constructs `GetPair
    NewsEvidenceSnapshot` -- both the JSON route and the HTML page
    call this SAME function, so there is never a second, independently
    -interpreting code path (Section 6's own explicit prohibition)."""
    news_repository = SqlAlchemyNewsRepository(session)
    canonicalization_repository = SqlAlchemyNewsCanonicalizationRepository(session, news_repository)
    semantic_repository = SqlAlchemyNewsSemanticRepository(session, news_repository)
    use_case = GetPairNewsEvidenceSnapshot(
        news_repository, canonicalization_repository, semantic_repository
    )
    snapshot = await use_case(instrument, window_start, resolved_as_of)
    return build_news_evidence_view(snapshot)


@router.get("/api/market-context/{pair}/news")
async def get_news_evidence(
    pair: str,
    as_of: str | None = Query(default=None),
    news_lookback_hours: float = Query(default=_DEFAULT_NEWS_LOOKBACK.total_seconds() / 3600),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    instrument = _resolve_supported_pair(pair)
    resolved_as_of = _resolve_as_of(as_of)
    window_start = _resolve_news_window_start(resolved_as_of, news_lookback_hours)
    return await _build_news_evidence_view(instrument, resolved_as_of, window_start, session)


@router.get("/api/research/fx46")
async def get_fx46_research(
    pair: str = Query(default="GBP_USD"),
    rate_semantics: str = Query(default=_DEFAULT_RATE_SEMANTICS.value),
    experiment: str = Query(default=_DEFAULT_FX46_EXPERIMENT),
) -> dict[str, object]:
    artifact = _get_fx46_artifact()
    return build_fx46_view(artifact, pair, rate_semantics, experiment)


@router.get("/market-context", response_class=HTMLResponse)
async def market_context_page(
    pair: str = Query(default="GBP_USD"),
    as_of: str | None = Query(default=None),
    rate_semantics: str = Query(default=_DEFAULT_RATE_SEMANTICS.value),
    lookahead_hours: float = Query(default=_DEFAULT_LOOKAHEAD.total_seconds() / 3600),
    lookback_hours: float = Query(default=_DEFAULT_LOOKBACK.total_seconds() / 3600),
    fx46_experiment: str = Query(default=_DEFAULT_FX46_EXPERIMENT),
    news_lookback_hours: float = Query(default=_DEFAULT_NEWS_LOOKBACK.total_seconds() / 3600),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """The full server-rendered dashboard page -- computes every
    section's view model via the SAME builders/use cases the JSON
    routes above use (never a separate, divergent code path), then
    embeds them into the page for the page's own inline JS to render
    charts from. See `apps.api.market_context_page` for the actual HTML
    assembly."""
    instrument = _resolve_supported_pair(pair)
    resolved_as_of = _resolve_as_of(as_of)
    resolved_semantics = _resolve_rate_semantics(rate_semantics)

    macro_repository = SqlAlchemyMacroObservationRepository(session)
    fundamentals = await GetFundamentalRateEvidence(repository=macro_repository)(
        instrument, resolved_as_of, resolved_semantics
    )
    history = await GetPolicyRateHistory(repository=macro_repository)(
        instrument, resolved_as_of, resolved_semantics
    )

    event_repository = SqlAlchemyEconomicEventRepository(session)
    snapshot = await GetEventRiskEvidenceSnapshot(repository=event_repository)(
        instrument,
        resolved_as_of,
        timedelta(hours=lookahead_hours),
        timedelta(hours=lookback_hours),
    )

    artifact = _get_fx46_artifact()
    fx46_pair_code = pair if pair in artifact.pairs else next(iter(sorted(artifact.pairs)), pair)

    news_window_start = _resolve_news_window_start(resolved_as_of, news_lookback_hours)
    news_view = await _build_news_evidence_view(
        instrument, resolved_as_of, news_window_start, session
    )

    html = render_market_context_page(
        selected_pair=pair,
        as_of_param=as_of,
        rate_semantics_param=rate_semantics,
        lookahead_hours=lookahead_hours,
        lookback_hours=lookback_hours,
        fx46_experiment=fx46_experiment,
        news_lookback_hours=news_lookback_hours,
        fundamentals_view=build_fundamentals_view(fundamentals),
        history_view=build_policy_rate_history_view(history),
        events_view=build_events_view(snapshot),
        fx46_view=build_fx46_view(
            artifact, fx46_pair_code, resolved_semantics.value, fx46_experiment
        ),
        news_view=news_view,
    )
    return HTMLResponse(content=html)
