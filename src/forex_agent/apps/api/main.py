"""FastAPI composition root.

Constructing `Settings` here (module import time) means the app fails to
start at all if configuration would permit live trading — see
`forex_agent.apps.settings`.
"""

from fastapi import FastAPI

from forex_agent.apps.api.routers import health
from forex_agent.apps.settings import get_settings

get_settings()  # fail closed before the app is even constructed

app = FastAPI(title="Forex Trading Agent", version="0.1.0")
app.include_router(health.router)
