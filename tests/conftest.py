"""Shared test fixtures. `db_session` runs each test inside a transaction
that's rolled back afterward, against the real local Postgres (the same
one docker-compose brings up for dev) - repository.py is exercised for
real rather than mocked, since idempotent-upsert correctness is exactly
the kind of thing that's easy to get subtly wrong.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import engine


@pytest_asyncio.fixture
async def db_session():
    async with engine.connect() as conn:
        trans = await conn.begin()
        # join_transaction_mode="create_savepoint": code under test is
        # free to call session.commit() (repository/discovery/runner all
        # do) without ending the outer transaction this fixture rolls
        # back at the end - commit() becomes a SAVEPOINT release instead.
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()
