from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # pool_pre_ping=True is deliberately NOT used here: its ping check
    # crashed with "MissingGreenlet... was IO attempted in an unexpected
    # place" mid-run against a long-lived session (seen live during a
    # ~1000-job Himalayas fetch) - a known SQLAlchemy/asyncpg async
    # incompatibility. pool_recycle avoids the same stale-connection
    # problem without relying on that ping.
    pool_recycle=1800,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
