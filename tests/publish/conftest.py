"""Fixtures for publishing to BidFlow's job feed.

Replica tests run against a local copy of BidFlow's schema
(docs/bidflow/job_feed_schema.sql) as `jobfeed_writer`, exactly as
production will; they are skipped if that database isn't available:

    createdb bidflow_replica
    psql -d bidflow_replica -v ON_ERROR_STOP=1 -f docs/bidflow/job_feed_schema.sql
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.publish.catalog import CatalogTag, TagCatalog

_SCHEMA = Path(__file__).resolve().parents[2] / "docs" / "bidflow" / "job_feed_schema.sql"
WRITER_URL = os.environ.get(
    "BIDFLOW_TEST_WRITER_URL",
    "postgresql+asyncpg://jobfeed_writer:local-only-change-me@localhost:5432/bidflow_replica",
)
ADMIN_URL = os.environ.get(
    "BIDFLOW_TEST_ADMIN_URL", "postgresql+asyncpg://jobfetch:jobfetch@localhost:5432/bidflow_replica"
)
TEST_SOURCE_PREFIX = "pubtest-"


def snapshot_catalog() -> TagCatalog:
    """BidFlow's tag catalog as dumped in its schema file."""
    sql = _SCHEMA.read_text()
    tags = {
        int(m[0]): CatalogTag(code=m[1], important=m[2] == "IMPORTANT")
        for m in re.findall(r"VALUES \((\d+), '([^']+)', '[^']+', '(\w+)', true", sql)
    }
    aliases = {m[0]: tags[int(m[1])].code for m in re.findall(r"tag_aliases \(alias, tag_id, created_at\) VALUES \('([^']+)', (\d+)", sql)}
    return TagCatalog(tags={t.code: t for t in tags.values()}, aliases=aliases)


@pytest.fixture
def catalog() -> TagCatalog:
    return snapshot_catalog()


@pytest_asyncio.fixture
async def feed_engine():
    engine = create_async_engine(WRITER_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM job_feed.tags LIMIT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure means "no replica here"
        await engine.dispose()
        pytest.skip(f"BidFlow replica not available: {exc}")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def feed_admin():
    """Superuser connection to the replica, for reading and for cleanup only."""
    engine = create_async_engine(ADMIN_URL)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM job_feed.jobs WHERE source LIKE :p"), {"p": TEST_SOURCE_PREFIX + "%"})
    await engine.dispose()
