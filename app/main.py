from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import register_routes
from app.core.config import get_settings
from app.core.runtime import Runtime

settings = get_settings()
runtime = Runtime(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(
    title="ETF Radar",
    version="0.5.0",
    description="ETF low-buy, hold, take-profit, exit, direction-discovery, alert, and backtest radar with web authentication.",
    lifespan=lifespan,
)

register_routes(app, runtime, settings)
