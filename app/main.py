from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.routes_jobs import router as jobs_router
from app.api.routes_sources import router as sources_router
from app.api.routes_stats import router as stats_router
from app.api.routes_stream import router as stream_router
from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("startup")

    if get_settings().scheduler_enabled:
        from app.scheduler.scheduler import shutdown_scheduler, start_scheduler

        await start_scheduler()

    yield

    if get_settings().scheduler_enabled:
        await shutdown_scheduler()

    await engine.dispose()
    log.info("shutdown")


app = FastAPI(title="Job Fetching Service", lifespan=lifespan)

app.include_router(jobs_router)
app.include_router(sources_router)
app.include_router(stats_router)
app.include_router(stream_router)


@app.get("/health")
async def health() -> dict:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
