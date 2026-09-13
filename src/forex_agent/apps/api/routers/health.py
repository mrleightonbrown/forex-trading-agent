from fastapi import APIRouter

from forex_agent.apps.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "broker_environment": settings.broker_environment,
    }
