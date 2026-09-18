from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_session
from app.config import get_settings
from app.main import app


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
def api_headers():
    return {"X-API-Key": get_settings().api_key}
