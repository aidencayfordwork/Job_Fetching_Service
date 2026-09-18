"""Shared behavior for ATS connectors that fan out over many company boards.

The connector itself stays DB-agnostic: the scheduler (Phase 9) is
responsible for querying `ats_companies` and setting `board_targets`
before each run. A failure fetching one company's board must never abort
the whole run — errors are caught and logged per company.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from app.connectors.base import RawJob, SourceConnector
from app.core.logging import get_logger

log = get_logger(__name__)


class AtsTarget(NamedTuple):
    company_name: str
    board_token: str


@dataclass
class AtsMultiCompanyConnector(SourceConnector):
    board_targets: Sequence[AtsTarget] = ()

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        for target in self.board_targets:
            try:
                async for raw in self._fetch_company(target, since):
                    raw["_company_name"] = target.company_name
                    raw["_board_token"] = target.board_token
                    yield raw
            except Exception:
                log.warning(
                    "ats_company_fetch_failed",
                    source=self.name,
                    company=target.company_name,
                    board_token=target.board_token,
                    exc_info=True,
                )
                continue

    async def _fetch_company(self, target: AtsTarget, since: datetime | None) -> AsyncIterator[RawJob]:
        raise NotImplementedError
        yield  # pragma: no cover
