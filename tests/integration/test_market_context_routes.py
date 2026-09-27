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
        assert f'value="{pair}" selected' in body


@pytest.mark.asyncio
async def test_market_context_page_rejects_unsupported_pair(client: AsyncClient) -> None:
    response = await client.get("/market-context", params={"pair": "AUD_USD"})

    assert response.status_code == 404
