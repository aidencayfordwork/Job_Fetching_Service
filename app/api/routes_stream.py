"""SSE stream of job.created / job.updated / job.deactivated events,
backed by Postgres LISTEN/NOTIFY (architecture.md §9). The repository
layer emits NOTIFY on JOB_EVENTS_CHANNEL whenever it writes a job; this
endpoint just relays those to connected clients.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import require_api_key
from app.config import get_settings
from app.core.logging import get_logger
from app.persistence.repository import JOB_EVENTS_CHANNEL

router = APIRouter(dependencies=[Depends(require_api_key)])

log = get_logger(__name__)

_KEEPALIVE_SECONDS = 15


def _asyncpg_dsn() -> str:
    # asyncpg.connect() wants a plain postgresql:// DSN, not the
    # SQLAlchemy-style postgresql+asyncpg:// URL.
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _event_stream(request: Request) -> AsyncIterator[bytes]:
    conn = await asyncpg.connect(_asyncpg_dsn())
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(connection, pid, channel, payload) -> None:
        queue.put_nowait(payload)

    await conn.add_listener(JOB_EVENTS_CHANNEL, _on_notify)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                yield f"event: job\ndata: {payload}\n\n".encode()
            except TimeoutError:
                yield b": keep-alive\n\n"
    finally:
        await conn.remove_listener(JOB_EVENTS_CHANNEL, _on_notify)
        await conn.close()


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
