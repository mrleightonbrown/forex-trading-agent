"""FX-54V: integration tests for the "Market Context" dashboard's HTTP
routes -- httpx `AsyncClient` + `ASGITransport` against the real
FastAPI app (mirrors `tests/integration/test_health.py`'s own
established pattern), against live Postgres for PIT-sensitive routes.

Deterministic only -- no route here calls a live external calendar/
FRED/ECB/BoC source; every route reads already-persisted evidence or
the already-committed FX-46 artifact from local disk.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forex_agent.apps.api.main import app
from forex_agent.domain.availability_confidence import AvailabilityConfidence
from forex_agent.domain.economic_event_occurrence import EconomicEventOccurrence
from forex_agent.domain.economic_event_schedule_vintage import EconomicEventScheduleVintage
from forex_agent.domain.economic_event_status import EconomicEventStatus
from forex_agent.domain.news_currency_relevance import NewsCurrencyRelevance
from forex_agent.domain.news_currency_relevance_reason import NewsCurrencyRelevanceReason
from forex_agent.domain.news_entity_annotation import NewsEntityAnnotation
from forex_agent.domain.news_entity_evidence_kind import NewsEntityEvidenceKind
from forex_agent.domain.news_entity_type import NewsEntityType
from forex_agent.domain.news_evidence_disposition import NewsEvidenceDisposition
from forex_agent.domain.news_item_vintage import NewsItemVintage
from forex_agent.domain.news_observation_mode import NewsObservationMode
from forex_agent.domain.news_semantic_annotation_vintage import NewsSemanticAnnotationVintage
from forex_agent.domain.news_semantic_classification import NewsSemanticClassification
from forex_agent.domain.news_source_identity import NewsSourceIdentity
from forex_agent.domain.news_source_status import NewsSourceStatus
from forex_agent.domain.timestamps import UtcTimestamp
from forex_agent.infrastructure.db.economic_event_repository import (
    SqlAlchemyEconomicEventRepository,
)
from forex_agent.infrastructure.db.models.economic_event_occurrence import (
    EconomicEventOccurrenceRow,
)
from forex_agent.infrastructure.db.models.economic_event_schedule_vintage import (
    EconomicEventScheduleVintageRow,
)
from forex_agent.infrastructure.db.models.news_item import NewsItemRow
from forex_agent.infrastructure.db.models.news_item_vintage import NewsItemVintageRow
from forex_agent.infrastructure.db.models.news_semantic_annotation_vintage import (
    NewsSemanticAnnotationVintageRow,
)
from forex_agent.infrastructure.db.models.news_source_mapping import NewsSourceMappingRow
from forex_agent.infrastructure.db.news_repository import SqlAlchemyNewsRepository
from forex_agent.infrastructure.db.news_semantic_repository import SqlAlchemyNewsSemanticRepository
from forex_agent.infrastructure.db.session import get_engine

TEST_OCCURRENCE_PREFIX = "__fx54v_route_test__"


def _ts(year: int, month: int, day: int, hour: int = 0) -> UtcTimestamp:
    return UtcTimestamp(datetime(year, month, day, hour, tzinfo=UTC))


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        await cleanup_session.execute(
            delete(EconomicEventScheduleVintageRow).where(
                EconomicEventScheduleVintageRow.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)
            )
        )
        await cleanup_session.execute(
            delete(EconomicEventOccurrenceRow).where(
                EconomicEventOccurrenceRow.occurrence_key.startswith(TEST_OCCURRENCE_PREFIX)
            )
        )
        await cleanup_session.commit()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fundamentals_route_returns_evidence_for_supported_pair(client: AsyncClient) -> None:
    response = await client.get("/api/market-context/GBP_USD/fundamentals")

    assert response.status_code == 200
    body = response.json()
    assert body["pair"] == "GBP/USD"
    assert body["rate_semantics"] == "ANNOUNCED"
    assert "base" in body and "quote" in body and "differential" in body


@pytest.mark.asyncio
async def test_fundamentals_route_accepts_explicit_as_of(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/fundamentals", params={"as_of": "2020-01-01T00:00:00+00:00"}
    )

    assert response.status_code == 200
    assert response.json()["as_of"] == "2020-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_fundamentals_route_rejects_unsupported_pair(client: AsyncClient) -> None:
    response = await client.get("/api/market-context/AUD_USD/fundamentals")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fundamentals_route_rejects_malformed_as_of(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/fundamentals", params={"as_of": "not-a-timestamp"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_fundamentals_route_rejects_naive_as_of(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/fundamentals", params={"as_of": "2026-01-01T00:00:00"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_fundamentals_route_rejects_invalid_rate_semantics(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/fundamentals", params={"rate_semantics": "NOT_REAL"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_policy_rate_history_route_returns_both_legs(client: AsyncClient) -> None:
    response = await client.get("/api/market-context/USD_CAD/policy-rate-history")

    assert response.status_code == 200
    body = response.json()
    assert body["base_currency"] == "USD"
    assert body["quote_currency"] == "CAD"
    assert "base_history" in body and "quote_history" in body


# ---------------------------------------------------------------------------
# Economic Events (PIT-sensitive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_route_empty_window_uses_restrained_wording(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/EUR_USD/events",
        params={"lookahead_hours": 1, "lookback_hours": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["upcoming_schedule_groups"] == []
    assert "No tracked PIT-visible" in body["empty_schedule_window_message"]
    for forbidden in ("all clear", "safe", "no event risk"):
        assert forbidden not in str(body).lower()


@pytest.mark.asyncio
async def test_events_route_eur_usd_reports_eur_as_untracked(client: AsyncClient) -> None:
    response = await client.get("/api/market-context/EUR_USD/events")

    assert response.status_code == 200
    coverage = response.json()["coverage"]
    assert coverage["untracked_pair_currencies"] == ["EUR"]


@pytest.mark.asyncio
async def test_events_route_rejects_negative_horizons(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/events", params={"lookahead_hours": -1}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_events_route_reflects_persisted_schedule_evidence_with_correct_pair_role(
    client: AsyncClient, session: AsyncSession
) -> None:
    repo = SqlAlchemyEconomicEventRepository(session)
    key = f"{TEST_OCCURRENCE_PREFIX}GBP_GDP"
    as_of = _ts(2026, 9, 1)
    await repo.add_occurrence(
        EconomicEventOccurrence(occurrence_key=key, indicator_key="GBP_GDP_QOQ")
    )
    await repo.add_schedule_vintage(
        EconomicEventScheduleVintage(
            occurrence_key=key,
            revision_sequence=0,
            scheduled_date=date(2026, 9, 2),
            scheduled_time=time(7, 0),
            schedule_timezone="Europe/London",
            status=EconomicEventStatus.SCHEDULED,
            availability=as_of,
            availability_confidence=AvailabilityConfidence.VERIFIED,
            source="test",
        )
    )

    response = await client.get(
        "/api/market-context/GBP_USD/events",
        params={"as_of": "2026-09-01T00:00:00+00:00", "lookahead_hours": 48, "lookback_hours": 0},
    )

    assert response.status_code == 200
    groups = response.json()["upcoming_schedule_groups"]
    matching = [g for g in groups if g["group_key"] == key]
    assert len(matching) == 1
    member = matching[0]["members"][0]
    assert member["pair_role"] == "BASE"
    assert member["currency"] == "GBP"


# ---------------------------------------------------------------------------
# FX-46 research
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fx46_route_returns_committed_research_result(client: AsyncClient) -> None:
    response = await client.get(
        "/api/research/fx46",
        params={"pair": "GBP_USD", "rate_semantics": "ANNOUNCED", "experiment": "LEVEL"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["story"] == "FX-46"
    assert "does not establish" in body["research_conclusion_note"]
    assert body["result"] is not None


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_context_page_renders_for_every_supported_pair(client: AsyncClient) -> None:
    for pair in ("EUR_USD", "GBP_USD", "USD_CAD"):
        response = await client.get("/market-context", params={"pair": pair})

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        body = response.text
        assert "<title>Market Context</title>" in body
        assert 'id="fundamentals-card"' in body
        assert 'id="event-timeline"' in body
        assert 'id="coverage-content"' in body
        # FX-61: existing sections keep working, and the new News
        # Evidence section is present for every supported pair too.
        assert 'id="news-evidence-heading"' in body
        assert 'id="news-active-stories"' in body
        assert 'id="news-withdrawn-stories"' in body
        assert 'id="news-accounting"' in body
        assert f'value="{pair}" selected' in body


@pytest.mark.asyncio
async def test_market_context_page_rejects_unsupported_pair(client: AsyncClient) -> None:
    response = await client.get("/market-context", params={"pair": "AUD_USD"})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# News Evidence (FX-61)
# ---------------------------------------------------------------------------

TEST_NEWS_SOURCE_KEY = "__fx61_route_test__"


@pytest.fixture
async def news_session() -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(bind=get_engine(), expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session

    async with session_factory() as cleanup_session:
        item_keys = (
            (
                await cleanup_session.execute(
                    delete(NewsSourceMappingRow)
                    .where(NewsSourceMappingRow.source_key == TEST_NEWS_SOURCE_KEY)
                    .returning(NewsSourceMappingRow.news_item_key)
                )
            )
            .scalars()
            .all()
        )
        for key in item_keys:
            await cleanup_session.execute(
                delete(NewsSemanticAnnotationVintageRow).where(
                    NewsSemanticAnnotationVintageRow.news_item_key == key
                )
            )
            await cleanup_session.execute(
                delete(NewsItemVintageRow).where(NewsItemVintageRow.news_item_key == key)
            )
            await cleanup_session.execute(
                delete(NewsItemRow).where(NewsItemRow.news_item_key == key)
            )
        await cleanup_session.commit()


async def _make_news_item(
    session: AsyncSession,
    suffix: str,
    *,
    first_seen_at: UtcTimestamp,
    headline: str = "Headline",
) -> str:
    news_repo = SqlAlchemyNewsRepository(session)
    registration = await news_repo._register_source_item_for_test_setup(
        NewsSourceIdentity(source_key=TEST_NEWS_SOURCE_KEY, external_item_id=suffix),
        first_seen_at,
        NewsObservationMode.PROSPECTIVE,
    )
    vintage = NewsItemVintage(
        news_item_key=registration.news_item_key,
        revision_sequence=0,
        availability=first_seen_at,
        observation_mode=NewsObservationMode.PROSPECTIVE,
        headline=headline,
        source_channel="test_channel",
        observed_source_channels=("test_channel",),
        source_status=NewsSourceStatus.ACTIVE,
        evidence_disposition=NewsEvidenceDisposition.EVIDENCE_ELIGIBLE,
        canonical_url="javascript:alert(1)",
    )
    await news_repo.add_vintage(vintage)
    semantic_repo = SqlAlchemyNewsSemanticRepository(session, news_repo)
    await semantic_repo.add_annotation_vintage(
        NewsSemanticAnnotationVintage(
            news_item_key=registration.news_item_key,
            revision_sequence=0,
            availability=first_seen_at,
            basis_news_item_revision_sequence=0,
            algorithm_version="fx59_v1",
            classification=NewsSemanticClassification(
                entities=(
                    NewsEntityAnnotation(
                        entity_type=NewsEntityType.INSTITUTION,
                        entity_key="FEDERAL_RESERVE",
                        evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
                    ),
                    NewsEntityAnnotation(
                        entity_type=NewsEntityType.JURISDICTION,
                        entity_key="UNITED_STATES",
                        evidence=(NewsEntityEvidenceKind.SOURCE_PROFILE,),
                    ),
                ),
                topics=(),
                currency_relevance=(
                    NewsCurrencyRelevance(
                        currency_code="USD",
                        reasons=(NewsCurrencyRelevanceReason.SOURCE_JURISDICTION,),
                    ),
                ),
            ),
        )
    )
    return registration.news_item_key


@pytest.mark.asyncio
async def test_news_route_returns_schema_for_supported_pair(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/EUR_USD/news",
        params={"as_of": "2026-01-01T00:00:00+00:00", "news_lookback_hours": 1},
    )

    assert response.status_code == 200
    body = response.json()
    for key in (
        "presentation_version",
        "snapshot_policy_version",
        "pair",
        "as_of",
        "window_start",
        "coverage",
        "accounting",
        "active_entries",
        "withdrawn_only_entries",
        "semantic_gaps",
    ):
        assert key in body
    assert body["pair"]["base_currency"] == "EUR"
    assert body["pair"]["quote_currency"] == "USD"


@pytest.mark.asyncio
async def test_news_route_rejects_unsupported_pair(client: AsyncClient) -> None:
    response = await client.get("/api/market-context/AUD_USD/news")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_news_route_accepts_explicit_as_of_with_no_hidden_default(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/news",
        params={"as_of": "2020-01-01T00:00:00+00:00", "news_lookback_hours": 24},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["as_of"] == "2020-01-01T00:00:00+00:00"
    assert body["window_start"] == "2019-12-31T00:00:00+00:00"


@pytest.mark.asyncio
async def test_news_route_rejects_malformed_as_of(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/news", params={"as_of": "not-a-timestamp"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_news_route_rejects_naive_as_of(client: AsyncClient) -> None:
    response = await client.get(
        "/api/market-context/GBP_USD/news", params={"as_of": "2026-01-01T00:00:00"}
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_news_route_rejects_non_positive_lookback(client: AsyncClient) -> None:
    for bad_value in (0, -5):
        response = await client.get(
            "/api/market-context/USD_CAD/news", params={"news_lookback_hours": bad_value}
        )
        assert response.status_code == 400


# --- FX-61H H1: robust lookback validation -----------------------------------


@pytest.mark.asyncio
async def test_news_route_rejects_non_finite_lookback_with_controlled_400(
    client: AsyncClient,
) -> None:
    """`NaN <= 0` is `False` in Python -- a bare non-positive check
    alone would let NaN/+-inf slip through into `timedelta()`
    construction, which raises an UNHANDLED `ValueError`/`OverflowError`
    (a 500), not a controlled 400. Every non-finite value must be
    rejected explicitly, before it ever reaches `timedelta()`."""
    for bad_value in ("nan", "inf", "-inf", "infinity", "-infinity"):
        response = await client.get(
            "/api/market-context/USD_CAD/news", params={"news_lookback_hours": bad_value}
        )
        assert response.status_code == 400, f"{bad_value!r} must be rejected with 400"
        assert "finite" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_news_route_rejects_unrepresentable_lookback_with_controlled_400(
    client: AsyncClient,
) -> None:
    """A finite but astronomically large lookback -- one whose own
    `timedelta()` construction, or whose subtraction from `as_of`,
    would overflow Python's representable datetime range -- must still
    resolve to a controlled 400, never an unhandled 500."""
    for bad_value in (1e20, 1e15, 1e13):
        response = await client.get(
            "/api/market-context/USD_CAD/news",
            params={"as_of": "2026-01-01T00:00:00+00:00", "news_lookback_hours": bad_value},
        )
        assert response.status_code == 400, f"{bad_value!r} must be rejected with 400, not 500"


@pytest.mark.asyncio
async def test_news_route_accepts_a_large_but_representable_lookback(
    client: AsyncClient,
) -> None:
    """A large, but genuinely representable, lookback must NOT be
    rejected -- H1 closes the NaN/overflow gap without introducing an
    arbitrary trading-policy maximum on top of it."""
    response = await client.get(
        "/api/market-context/USD_CAD/news",
        params={"as_of": "2026-01-01T00:00:00+00:00", "news_lookback_hours": 1_000_000},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_news_evidence_page_rejects_non_finite_lookback_with_controlled_400(
    client: AsyncClient,
) -> None:
    """The SAME validation applies through the HTML page route, which
    shares the one `_resolve_news_window_start` resolver with the JSON
    route -- never a second, divergent validation path."""
    response = await client.get(
        "/market-context", params={"pair": "USD_CAD", "news_lookback_hours": "nan"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_news_route_reflects_persisted_evidence_with_correct_pair_relevance(
    client: AsyncClient, news_session: AsyncSession
) -> None:
    await _make_news_item(news_session, "GBP_STORY", first_seen_at=_ts(2026, 9, 1))

    response = await client.get(
        "/api/market-context/GBP_USD/news",
        params={"as_of": "2026-09-02T00:00:00+00:00", "news_lookback_hours": 48},
    )

    assert response.status_code == 200
    body = response.json()
    matching = [
        e for e in body["active_entries"] if any(m["headline"] == "Headline" for m in e["members"])
    ]
    assert len(matching) == 1
    entry = matching[0]
    assert entry["pair_relevance_side"] == "QUOTE_ONLY"
    # FX-61 Section 4.6: an unsafe `javascript:` URL round-trips through
    # real Postgres and the real view model as None -- never reaching
    # the JSON response as a renderable link.
    assert entry["members"][0]["canonical_url"] is None


@pytest.mark.asyncio
async def test_news_route_empty_corpus_window_renders_valid_empty_state(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/market-context/EUR_USD/news",
        params={"as_of": "2015-01-01T00:00:00+00:00", "news_lookback_hours": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["active_entries"] == []
    assert body["empty_state"] is not None
    assert body["empty_state_message"] is not None


@pytest.mark.asyncio
async def test_news_evidence_section_controls_retain_query_params(client: AsyncClient) -> None:
    response = await client.get(
        "/market-context",
        params={"pair": "GBP_USD", "news_lookback_hours": 36},
    )

    assert response.status_code == 200
    assert 'name="news_lookback_hours" value="36"' in response.text


@pytest.mark.asyncio
async def test_news_evidence_page_escapes_headline_and_never_breaks_script_boundary(
    client: AsyncClient, news_session: AsyncSession
) -> None:
    """A headline containing a literal `</script>` sequence must never
    allow the embedded JSON payload to break out of its own `<script>`
    block -- the page's own JSON-embedding logic must neutralize this,
    exactly like every other section's payload already relies on."""
    await _make_news_item(
        news_session,
        "XSS_STORY",
        first_seen_at=_ts(2026, 9, 1),
        headline="</script><script>window.__pwned__=1</script>",
    )

    response = await client.get(
        "/market-context",
        params={
            "pair": "GBP_USD",
            "as_of": "2026-09-02T00:00:00+00:00",
            "news_lookback_hours": 48,
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "window.__pwned__" not in body or "<\\/script>" in body
    assert "</script><script>window.__pwned__" not in body


@pytest.mark.asyncio
async def test_news_evidence_withdrawn_entries_distinct_key_from_active(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/api/market-context/EUR_USD/news",
        params={"as_of": "2026-12-31T00:00:00+00:00", "news_lookback_hours": 99999},
    )

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["active_entries"], list)
    assert isinstance(body["withdrawn_only_entries"], list)
    active_keys = {e["canonical_group_key"] for e in body["active_entries"]}
    withdrawn_keys = {e["canonical_group_key"] for e in body["withdrawn_only_entries"]}
    assert active_keys.isdisjoint(withdrawn_keys)


# --- FX-61H H3: complete provenance detail presentation ----------------------


@pytest.mark.asyncio
async def test_news_evidence_page_renders_previously_omitted_provenance_fields(
    client: AsyncClient,
) -> None:
    """The view model already carried relation revisions/endpoint
    revisions, `source_content_type`, `source_published_at`, and
    entity evidence categories (Section 4.5/6) -- FX-61H's own finding
    was that the SERVED page's own client-side detail renderer never
    referenced them. Asserts the served page's own script text now
    references every one of these fields, so the expandable story
    detail can actually display them (no browser automation available
    in this environment to execute the script and inspect the DOM
    directly -- this is the strongest available automated check)."""
    response = await client.get("/market-context", params={"pair": "GBP_USD"})

    assert response.status_code == 200
    body = response.text

    # H3.1: canonical relationship revision and endpoint revisions.
    assert "r.revision_sequence" in body
    assert "r.left_item_revision_sequence" in body
    assert "r.right_item_revision_sequence" in body

    # H3.2: source content type.
    assert "m.source_content_type" in body

    # H3.3: source publication timestamp, clearly labelled as provider
    # publication time -- never conflated with FTA's own first-seen/
    # availability instants.
    assert "m.source_published_at" in body
    assert "provider publication time" in body.lower()
    assert "never used for pit filtering" in body.lower()

    # H3.4: entity evidence categories.
    assert "e.evidence" in body


@pytest.mark.asyncio
async def test_news_evidence_page_provenance_fields_render_with_real_data(
    client: AsyncClient, news_session: AsyncSession
) -> None:
    """An end-to-end confirmation that the underlying DATA for each
    newly-surfaced field is genuinely present in the embedded payload
    for a real, persisted item -- not merely that the script text
    mentions the right property names."""
    await _make_news_item(news_session, "H3_STORY", first_seen_at=_ts(2026, 9, 1))

    response = await client.get(
        "/api/market-context/GBP_USD/news",
        params={"as_of": "2026-09-02T00:00:00+00:00", "news_lookback_hours": 48},
    )

    assert response.status_code == 200
    body = response.json()
    matching = [
        e for e in body["active_entries"] if any(m["headline"] == "Headline" for m in e["members"])
    ]
    assert len(matching) == 1
    member = matching[0]["members"][0]
    assert "source_content_type" in member
    assert "source_published_at" in member
    assert all("evidence" in entity for entity in member["classification"]["entities"])
