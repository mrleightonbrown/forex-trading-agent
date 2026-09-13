import pytest
from httpx import ASGITransport, AsyncClient

from forex_agent.apps.api.main import app


@pytest.mark.asyncio
async def test_health_reports_safe_paper_mode() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["trading_mode"] == "PAPER"
    assert body["broker_environment"] == "PRACTICE"
