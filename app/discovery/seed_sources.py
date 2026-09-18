"""Candidate company names for ATS discovery to probe.

Per architecture.md §5.4, this static/curated list is a day-one bootstrap
only. The primary, long-term coverage mechanism is organic discovery: every
company name observed via the aggregator connectors (RemoteOK, Himalayas,
Jobicy, WWR, Remotive, YC, Adzuna, Jooble) becomes a probe candidate too —
that wiring lives in the scheduler's discovery job (Phase 9), since it
needs to read company names out of freshly-fetched jobs.

A YC public-company-directory loader was considered here but intentionally
left out: YC doesn't publish a documented public API for it (their site
calls an internal search backend that isn't meant for third-party use),
and pulling from it would cut against the same "official/public APIs
only" line drawn for every other source. The static list plus organic
discovery cover the bootstrap need without it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_SEED_PATH = Path(__file__).resolve().parents[2] / "config" / "ats_seed_companies.yaml"


def load_static_seed_companies() -> list[str]:
    data = yaml.safe_load(_SEED_PATH.read_text())
    return list(data.get("companies", []))
