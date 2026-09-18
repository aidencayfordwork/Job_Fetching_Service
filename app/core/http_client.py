"""Shared HTTP client helpers: retry/backoff and a simple rate limiter.

Connectors build their own `httpx.AsyncClient` (so they can set their own
base URL / headers / timeout) but should wrap outbound calls with
`with_retry` and, for sources that fan out many requests (e.g. per-company
ATS polling), throttle via `RateLimiter`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # Retry server errors and rate-limiting; never retry a plain 4xx.
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


def with_retry[T](func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator: exponential backoff + jitter on transient errors, up to
    4 attempts total. Never retries a plain 4xx (client-side) error."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=20),
        retry=retry_if_exception(_is_retryable),
    )(func)


class RateLimiter:
    """Minimum-interval throttle for connectors that issue many requests
    in a single run (e.g. one call per ATS company)."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


def default_client(*, timeout: float = 15.0, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    merged_headers = {"User-Agent": "job-fetching-service/0.1 (+https://github.com/aidencayfordwork/Job_Fetching_Service)"}
    if headers:
        merged_headers.update(headers)
    return httpx.AsyncClient(timeout=timeout, headers=merged_headers, follow_redirects=True)
