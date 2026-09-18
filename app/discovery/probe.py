"""Check whether a candidate company has a live, public ATS board.

This is read access to documented public endpoints (the same ones the
connectors themselves call) — not scraping. A 404 for an unknown/wrong
slug is the expected, common case and isn't logged as an error.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.core.http_client import default_client

_ATS_URL_TEMPLATES: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


@dataclass(frozen=True, slots=True)
class ProbeHit:
    ats_platform: str
    board_token: str


def candidate_slugs(company_name: str) -> list[str]:
    """Derive plausible board-token slugs from a company's display name.

    Best-effort only — a miss here just means the company doesn't get
    direct ATS coverage yet; it isn't a correctness problem.
    """
    normalized = unicodedata.normalize("NFKD", company_name).encode("ascii", "ignore").decode()
    lowered = normalized.lower().strip()

    words = re.findall(r"[a-z0-9]+", lowered)
    if not words:
        return []

    joined = "".join(words)
    hyphenated = "-".join(words)

    slugs = {joined, hyphenated}
    # Common corporate suffixes that companies often drop from their slug.
    for suffix in ("inc", "llc", "corp", "co", "ltd"):
        if words and words[-1] == suffix and len(words) > 1:
            slugs.add("".join(words[:-1]))
            slugs.add("-".join(words[:-1]))

    return sorted(slugs)


async def probe_company(company_name: str) -> list[ProbeHit]:
    """Try each candidate slug against each ATS platform.

    Returns every platform where a live board was found (a company can
    legitimately have boards on more than one platform, though that's
    rare in practice).
    """
    hits: list[ProbeHit] = []
    slugs = candidate_slugs(company_name)
    if not slugs:
        return hits

    async with default_client(timeout=8.0) as client:
        for platform, template in _ATS_URL_TEMPLATES.items():
            for slug in slugs:
                url = template.format(slug=slug)
                try:
                    resp = await client.get(url)
                except Exception:
                    continue
                if resp.status_code == 200:
                    hits.append(ProbeHit(ats_platform=platform, board_token=slug))
                    break  # first matching slug wins for this platform

    return hits
