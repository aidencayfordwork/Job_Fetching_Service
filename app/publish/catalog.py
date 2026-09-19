"""BidFlow's tag catalog (job_feed.tags + job_feed.tag_aliases), read fresh
every publish run - BidFlow's admins add, rename and retire tags."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SPACES_RE = re.compile(r"\s+")


def tag_key(term: str) -> str:
    """Same normalization as BidFlow's job_feed.tag_key()."""
    return _SPACES_RE.sub(" ", term.strip()).lower()


@dataclass(frozen=True)
class CatalogTag:
    code: str
    important: bool


@dataclass(frozen=True)
class TagCatalog:
    tags: dict[str, CatalogTag]  # code -> tag (active only)
    aliases: dict[str, str]  # alias -> code (active tags only)

    def resolve(self, term: str) -> CatalogTag | None:
        key = tag_key(term)
        code = key if key in self.tags else self.aliases.get(key)
        return self.tags.get(code) if code else None

    def lookup_terms(self) -> dict[str, str]:
        """Every spelling (code or alias) -> code."""
        return {**{code: code for code in self.tags}, **self.aliases}


async def load_catalog(conn: AsyncConnection) -> TagCatalog:
    rows = (await conn.execute(text("SELECT id, code, weight, is_active FROM job_feed.tags"))).all()
    active = {r.id: CatalogTag(code=r.code, important=r.weight == "IMPORTANT") for r in rows if r.is_active}
    aliases = {
        r.alias: active[r.tag_id].code
        for r in (await conn.execute(text("SELECT alias, tag_id FROM job_feed.tag_aliases"))).all()
        if r.tag_id in active
    }
    return TagCatalog(tags={t.code: t for t in active.values()}, aliases=aliases)
