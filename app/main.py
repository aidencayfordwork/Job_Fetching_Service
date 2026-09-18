from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

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


@app.get("/health")
async def health() -> dict:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
