# Job Fetching Service — Architecture (Final)

Status: approved for implementation.

## 1. Goals & scope

A backend-first service that continuously discovers newly posted, **fully US-remote,
mid/senior/staff/lead software engineering jobs**, normalizes and classifies them,
tags them against a curated keyword taxonomy, deduplicates across sources, persists them in PostgreSQL, and
exposes them over a REST + streaming API for a separate Job Application Service.
A minimal React/Vite dev UI is built last, purely to eyeball data quality and
source health.

**Coverage goal and its honest limit**: the objective is to capture as close to
the full legitimately-accessible job supply as possible, every day, without
manual intervention. In practice that means maximizing two things: (a) the
number of official/public APIs and feeds connected, and (b) the number of
employer ATS boards tracked directly. Six platforms — LinkedIn, Indeed,
Glassdoor, ZipRecruiter, Built In, Otta/Welcome to the Jungle — are
confirmed to explicitly prohibit automated access in their ToS and are
**out of direct-connector scope**; most of what they'd contribute is
recovered indirectly, since employers who post there typically also run
their own Greenhouse/Lever/Ashby/SmartRecruiters board, or their own career
page. There is no version of this system that reaches literal 100% coverage
of the internet's job postings — the design goal is "as complete as the
legitimately-reachable supply allows, growing over time as more companies
are added," not an absolute guarantee.

Non-goals for v1: scraping the six restricted platforms above, auto-submitting
applications on the user's behalf (account-ban risk on personal accounts —
the service surfaces jobs, a human clicks apply), ML-based resume matching,
multi-tenant auth, horizontal fetch-worker scaling.

## 2. High-level architecture

```
        ┌───────────────────────────────────────────────────────┐
        │                    Source Connectors                    │
        │  Greenhouse | Lever | Ashby | SmartRecruiters            │
        │  RemoteOK | Himalayas | Jobicy | WWR | Remotive | YC     │
        │  (one adapter class per source, common interface)        │
        └───────────────────────┬───────────────────────────────┘
                                 │
        ┌───────────────────────┴───────────────────────────────┐
        │              ATS Company Discovery (feeds §5.4)          │
        │  seed lists → probe candidate boards → verified targets  │
        └───────────────────────┬───────────────────────────────┘
                                 │ raw payloads
                                 ▼
        ┌───────────────────────────────────────────────────────┐
        │           Scheduler / Fetch Workers                      │
        │  APScheduler jobs, per-source interval, async httpx,     │
        │  retry+backoff, rate limiting, circuit breaker/source     │
        └───────────────────────┬───────────────────────────────┘
                                 │ raw job dicts + raw_response JSON
                                 ▼
        ┌───────────────────────────────────────────────────────┐
        │                  Processing Pipeline                     │
        │  1. Normalize   → canonical JobDraft                     │
        │  2. Filter      → remote/US/role/seniority/clearance     │
        │  3. Classify    → level, role_category, tech stack       │
        │  4. Match keywords → matched_keywords (curated taxonomy) │
        │  5. Deduplicate → fingerprint + fuzzy cross-source match  │
        └───────────────────────┬───────────────────────────────┘
                                 │ upsert
                                 ▼
        ┌───────────────────────────────────────────────────────┐
        │                     PostgreSQL                           │
        │  jobs, job_raw_payloads, sources, source_runs,            │
        │  ats_companies, dedup index                              │
        └───────────────────────┬───────────────────────────────┘
                                 │
                                 ▼
        ┌───────────────────────────────────────────────────────┐
        │                       FastAPI                            │
        │  /jobs, /jobs/{id}, /sources, /stats, /stream (SSE)      │
        │  API-key auth, optional read-only DB role                │
        └───────────────────────┬───────────────────────────────┘
                                 │
                ┌────────────────┴────────────────┐
                ▼                                   ▼
     Job Application Service              React dev/monitoring UI
```

Everything left of PostgreSQL runs inside one Python process for v1 — no
message queue, no separate workers service. Module boundaries are drawn so
a queue (Redis/RQ, Celery) can be dropped in later without touching
connectors, filters, or the API.

## 3. Project structure

```
job-fetching-service/
├── architecture.md
├── docker-compose.yml               # Postgres + app, local dev/deploy target
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── app/
│   ├── main.py                      # FastAPI app factory
│   ├── config.py                    # settings (pydantic-settings), per-source config
│   ├── db/
│   │   ├── base.py                  # SQLAlchemy engine/session, async pool
│   │   └── models.py                 # ORM models
│   ├── api/
│   │   ├── deps.py                  # API-key auth dependency
│   │   ├── routes_jobs.py
│   │   ├── routes_sources.py
│   │   ├── routes_stats.py
│   │   └── routes_stream.py          # SSE endpoint
│   ├── schemas/
│   │   ├── job.py                    # Pydantic response/request models
│   │   └── source.py
│   ├── connectors/
│   │   ├── base.py                   # SourceConnector ABC + JobDraft dataclass
│   │   ├── registry.py               # source name -> connector instance
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── ashby.py
│   │   ├── smartrecruiters.py
│   │   ├── remoteok.py
│   │   ├── himalayas.py
│   │   ├── jobicy.py
│   │   ├── weworkremotely.py
│   │   ├── remotive.py
│   │   ├── adzuna.py                # live-verified with real credentials
│   │   └── jooble.py                # live-verified with real credentials
│   ├── discovery/
│   │   ├── seed_sources.py          # curated static seed-company list loader
│   │   └── probe.py                 # checks candidate co. for a live ATS board
│   ├── pipeline/
│   │   ├── normalize.py              # raw payload -> JobDraft
│   │   ├── filters.py                # remote/US/role/seniority gate
│   │   ├── clearance.py              # active-clearance detector
│   │   ├── classify_level.py         # MID/SENIOR/STAFF/LEAD
│   │   ├── classify_role.py          # role_category
│   │   ├── classify_stack.py         # tech stack extraction
│   │   ├── match_keywords.py         # matched_keywords (curated taxonomy match)
│   │   ├── dedupe.py                 # fingerprinting + cross-source matching
│   │   └── pipeline.py               # orchestrates the above per JobDraft
│   ├── scheduler/
│   │   ├── scheduler.py              # APScheduler setup, per-source jobs
│   │   ├── runner.py                 # fetch->pipeline->persist for one source
│   │   ├── discovery_job.py          # periodic re-scan for new ATS boards
│   │   └── health.py                 # source health/status tracking
│   ├── persistence/
│   │   └── repository.py             # idempotent upserts, active/expiry logic
│   └── core/
│       ├── logging.py                # structured logging (structlog)
│       └── http_client.py            # shared httpx client, retry/backoff, rate limiter
├── config/
│   ├── ats_seed_companies.yaml       # curated, user-extensible company list
│   └── keyword_taxonomy.yaml         # curated skill/domain vocabulary for matched_keywords
├── tests/
│   ├── connectors/
│   ├── pipeline/
│   └── api/
└── frontend/                          # built in phase 13
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── pages/JobsPage.tsx
        ├── pages/SourceStatusPage.tsx
        └── components/JobCard.tsx
```

## 4. Database schema (PostgreSQL)

### 4.1 `sources`
Static/config table, one row per connector.

| column | type | notes |
|---|---|---|
| id | smallint PK | |
| name | text unique | e.g. `greenhouse`, `remoteok` |
| kind | text | `ats` \| `aggregator_api` \| `rss` |
| fetch_interval_seconds | int | configurable per source, no global constant |
| enabled | boolean | |
| config | jsonb | per-source params (API keys, rate-limit overrides) |

### 4.2 `ats_companies`
Drives the Greenhouse/Lever/Ashby/SmartRecruiters connectors — this is the
table that scales coverage; growing it is the primary lever for the
"don't miss jobs" goal.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| company_name | text | |
| ats_platform | text | `greenhouse` \| `lever` \| `ashby` \| `smartrecruiters` |
| board_token | text | the slug used in the platform's public board URL |
| source_of_discovery | text | `organic` (found via an aggregator-observed company name) \| `seed_static` \| `manual` |
| verified | boolean | true once the board URL is confirmed live and returns jobs |
| enabled | boolean default true | |
| discovered_at | timestamptz | |
| last_verified_at | timestamptz | |

Index: `unique (ats_platform, board_token)`; `(enabled, ats_platform)` for
scheduler fan-out.

### 4.3 `source_runs`
Append-only run history, drives the Source Status page.

| column | type | notes |
|---|---|---|
| id | bigint PK | |
| source_id | smallint FK -> sources | |
| started_at | timestamptz | |
| finished_at | timestamptz | null while running |
| status | text | `success` \| `partial` \| `failed` \| `running` |
| jobs_fetched | int | |
| jobs_new | int | |
| jobs_updated | int | |
| jobs_filtered_out | int | |
| error_message | text null | |
| duration_ms | int null | |

Index: `(source_id, started_at desc)`.

### 4.4 `jobs`
The canonical, deduplicated, filtered table.

Identity
| column | type |
|---|---|
| id | bigint PK (identity) |
| company_name | text |
| job_title | text |
| source | text (FK -> sources.name) — the *canonical* source, i.e. the one this row's apply URL points to |
| source_job_id | text |
| source_url | text |
| direct_apply_url | text |

Classification
| level | text enum: MID, SENIOR, STAFF, LEAD |
| role_category | text | e.g. `Backend`, `ML`, `DevOps/SRE` |
| main_stack | text[] | 2-4 headline technologies for the card |
| full_technology_stack | text[] | full extracted tech set |
| required_years_experience | int null |
| employment_type | text null | full-time/contract |
| industry | text null |

Remote
| is_remote | boolean |
| us_eligible | boolean |
| remote_scope | text | `US`, `US-partial`, `Global`, `Unknown` |
| eligible_states | text[] null |
| excluded_states | text[] null |
| timezone_requirement | text null |
| original_location | text null |

Compensation
| salary_min | numeric null |
| salary_max | numeric null |
| currency | text null |
| salary_period | text null | `year`/`hour` |
| original_salary_text | text null |

Dates
| posted_at | timestamptz null |
| source_updated_at | timestamptz null |
| first_seen_at | timestamptz not null default now() |
| last_seen_at | timestamptz not null |
| expires_at | timestamptz null |

JD
| raw_job_description | text |
| cleaned_job_description | text |
| responsibilities | text[] null |
| required_skills | text[] null |
| preferred_skills | text[] null |
| **matched_keywords** | **text[]** | **canonical terms matched against `config/keyword_taxonomy.yaml` (languages, frameworks, domains — e.g. Python, React, Backend, Generative AI). A controlled vocabulary, not free-form NLP extraction — exists so the Job Application Service can compute a profile-match score via simple set overlap against a candidate's own keyword list.** |

Internal
| active | boolean default true |
| requires_active_clearance | boolean default false |
| canonical_fingerprint | text unique | dedup key, see §7 |
| created_at | timestamptz default now() |
| updated_at | timestamptz default now() |

Indexes:
- `unique (source, source_job_id)` — idempotent per-source upsert key
- `unique (canonical_fingerprint)` — cross-source dedup key
- btree `(active, posted_at desc)` — default listing/sort
- btree `(level)`, `(role_category)`, `(company_name)` — filter columns
- GIN `(main_stack)`, GIN `(full_technology_stack)`, GIN `(matched_keywords)` — tech/keyword filters
- btree `(salary_min, salary_max)` — salary range filter
- btree `(last_seen_at desc)` — "recently updated" / new-job detection
- full-text `to_tsvector('english', job_title || ' ' || company_name)` — search

### 4.5 `job_raw_payloads`
Keeps the original source response for reprocessing, separate from the hot
`jobs` table so raw JSON blobs don't bloat the main table/indexes.

| id | bigint PK |
| job_id | bigint FK -> jobs.id, null until matched |
| source | text |
| source_job_id | text |
| raw_payload | jsonb |
| fetched_at | timestamptz |

### 4.6 `job_alt_sources`
Records that the same job was also seen on another source, while `jobs`
keeps only the canonical (preferably ATS/original) entry.

| job_id | bigint FK -> jobs.id |
| source | text |
| source_job_id | text |
| source_url | text |
| first_seen_at | timestamptz |

## 5. Source strategy

### 5.1 Common connector interface

```python
class SourceConnector(ABC):
    name: str
    kind: Literal["ats", "aggregator_api", "rss"]

    async def fetch(self, since: datetime | None) -> AsyncIterator[RawJob]:
        """Yield raw records; incremental via `since` where the source supports it."""

    def normalize(self, raw: RawJob) -> JobDraft:
        """Map source-specific fields to the canonical JobDraft shape."""
```

Each connector is fully independent — a failure or schema change in one
never touches another (isolated try/except per source in the scheduler,
per-source circuit breaker after N consecutive failures).

### 5.2 Per-source connector table

| Source | Access method | Incremental strategy | Notes |
|---|---|---|---|
| Greenhouse | Public `boards-api.greenhouse.io/v1/boards/{token}/jobs` | `updated_at` per job | company list from `ats_companies` |
| Lever | Public `api.lever.co/v0/postings/{company}` | list diff on `createdAt` | company list from `ats_companies` |
| Ashby | Public job-board API | list diff | company list from `ats_companies` |
| SmartRecruiters | Public postings API | `releasedDate` filter | company list from `ats_companies` |
| RemoteOK | Public JSON feed | filter by `id`/`date` since last run | |
| Himalayas | Public API | filter by date | |
| Jobicy | Public API | filter by date | |
| We Work Remotely | RSS feed per category | RSS `pubDate` | |
| Remotive | Public API | filter by date | |
| Adzuna | Official free/paid API (`app_id`/`app_key`, instant self-serve signup) | filter by date | **live and enabled**; free tier ~1,000 calls/mo; queries `what=software engineer` to keep results relevant |
| Jooble | Official API (key on request) | filter by date | **live and enabled**; free tier capped at 500 calls lifetime — one request per fetch by design, no pagination |
| Y Combinator Jobs (Work at a Startup) | — | — | **Permanently out of scope, not "not yet built"**: confirmed no official public API exists (checked live — the jobs page 406s without JS, no documented `/api` endpoint; web search confirms only unofficial third-party scrapers and an unofficial Algolia-based community project exist). Consistent with the LinkedIn/Indeed/etc. policy below — not going to build an unauthorized scraper for it. |
| LinkedIn, Indeed, Glassdoor, ZipRecruiter, Built In, Otta/WTTJ | **Out of direct scope** | — | Confirmed no self-serve API exists (Indeed's Publisher API dead since 2022/2023, Glassdoor's API dead since 2022) or explicit ToS prohibition + enterprise-only partner programs not open to this project (LinkedIn, ZipRecruiter, Built In, Otta). Coverage recovered indirectly via §5.4 and via Adzuna/Jooble's own aggregation. |
| HiringCafe | **Out of direct scope** | — | Itself aggregates ~46 ATS platforms via their public APIs — its content is largely reachable directly through §5.4 instead of scraping it. |
| Google Jobs | Deferred | — | Requires official partner API; out of scope for v1 |

New sources are added by writing one connector module + a `sources` row;
nothing else changes.

### 5.3 Canonical-source preference

When a job is found both on an aggregator and the employer's own
Greenhouse/Lever/Ashby/SmartRecruiters/career page, the ATS/original posting
becomes the canonical `jobs` row (its URL is `direct_apply_url`); the
aggregator sighting is recorded in `job_alt_sources`. Priority order:
`employer career page` > `greenhouse/lever/ashby/smartrecruiters` >
aggregator APIs.

### 5.4 ATS company discovery — the primary coverage lever

There is no free, complete registry of "all US companies with remote
roles" to buy or import. Rather than trying to enumerate that in advance,
`ats_companies` **builds itself** from real hiring activity observed
across the pipeline — this is what makes "all US companies" tractable
without manual curation, and it's the mechanism that recovers most of the
coverage the six out-of-scope platforms would otherwise have provided.

1. **Organic discovery (primary source)**: every job ingested from *any*
   aggregator connector (RemoteOK, Himalayas, Jobicy, WWR, Remotive, YC,
   Adzuna, Jooble) carries a `company_name` (often a company domain/URL
   too). Each distinct company encountered this way is queued as a
   discovery candidate — this naturally covers exactly the population we
   care about ("companies that are actually posting remote software jobs
   right now"), growing every single day with zero manual maintenance.
2. **Probe step** (`discovery/probe.py`): for each candidate, derive
   likely slugs (from name/domain) and check the known public URL patterns
   for each ATS platform (e.g.
   `boards-api.greenhouse.io/v1/boards/{slug}/jobs`,
   `api.lever.co/v0/postings/{slug}`). A 200 response with job data marks
   the row `verified=true` and adds it to `ats_companies` for direct
   polling going forward — this gets the company's *full* current opening
   list, not just the single job the aggregator happened to surface, and
   is fetched faster/more completely than waiting for the aggregator to
   re-list it. A 404 is simply discarded, no retries needed — this is read
   access to explicitly public, documented endpoints, not scraping.
3. **Bootstrap seed (secondary, day-one only)**:
   `config/ats_seed_companies.yaml` (static, user-extensible, ~50 companies
   to start), so the system has meaningful coverage before the organic
   loop has had time to run. Not required for long-term coverage — organic
   discovery supersedes it within the first few fetch cycles. (A YC
   public-company-directory loader was considered but dropped: YC doesn't
   publish a documented public API for it, only an internal search backend
   their own site calls — pulling from that would cut against the
   "official/public APIs only" line drawn for every other source.)
4. **Scheduled discovery job** (`scheduler/discovery_job.py`): processes
   the queued candidates and periodically (e.g. weekly) re-verifies
   existing boards are still live; a board that starts 404ing gets
   `enabled=false` rather than deleted.
5. **Manual additions**: a company can still be added directly via
   `ats_seed_companies.yaml` or a small admin endpoint if you know of one
   the organic loop hasn't reached yet.

This makes total coverage self-reinforcing rather than dependent on a
fixed list: the more sources feed it, the more companies get discovered,
the more direct ATS coverage grows, compounding over time.

## 6. Processing pipeline

1. **Normalize** (`pipeline/normalize.py`): raw payload → `JobDraft`
   (superset of the `jobs` columns, all optional). Field mapping/type
   coercion only, no business rules.
2. **Classify** (runs *before* Filter — deliberate reorder from the
   original draft: the seniority and role gates in the Filter step need
   `level` and `role_category` already computed, so classifying first
   avoids building the same seniority/role detection logic twice):
   - `classify_level.py`: title keyword rules first (senior/staff/lead
     markers, explicit exclusion of principal/director/intern/junior/new
     grad), falling back to JD analysis (years-of-experience regex,
     scope-of-responsibility language) when the title is ambiguous.
   - `classify_role.py`: keyword/taxonomy match against the role-family
     list (AI/GenAI, ML, Backend, Full Stack, Frontend, Python, Java,
     C#/.NET, Data Engineering, Platform/Infra, Distributed Systems,
     MLOps, DevOps/SRE, Cloud, Security, Mobile/Android/iOS).
   - `classify_stack.py`: dictionary-based technology extraction from
     title + JD → `full_technology_stack`, with a heuristic picking 2-4
     headline items for `main_stack`.
3. **Filter** (`pipeline/filters.py` + `clearance.py`): reject unless
   `is_remote` and `us_eligible` are both confirmed true; reject on-site/
   hybrid, non-US-eligible, or undeterminable remote-US status; reject
   non-software roles (via `role_category` from Classify); reject by
   seniority (via `level` from Classify — outside MID/SENIOR/STAFF/LEAD);
   reject **active**-clearance requirements only (regex/keyword rules
   distinguishing "must currently hold" from "able to obtain" / "eligible
   for" / "public trust" / "background check" / "citizenship required",
   which are allowed); reject postings older than
   `settings.max_job_age_days` (default 7 - a job posted more than a week
   ago is excluded regardless of source, so the dataset stays current
   rather than accumulating a source's full historical catalog; a
   job with unknown `posted_at` is not penalized for missing data).
   Ambiguous remote/US-eligibility resolves to *exclude*, not include —
   false negatives (missing a job) are preferable to false positives
   (polluting results with jobs the candidate can't actually take). The
   age cutoff also applies retroactively: `deactivate_stale_by_posted_age`
   runs alongside the existing `mark_expired_jobs` after every source run,
   so a job that ages past the cutoff without being re-fetched still gets
   marked inactive rather than lingering as "active" indefinitely.
4. **Match keywords** (`pipeline/match_keywords.py`, implemented): matches
   job title + `cleaned_job_description` against the curated, versioned
   vocabulary in `config/keyword_taxonomy.yaml` (languages, frameworks,
   cloud/infra, AI/ML, data engineering, security, domains/role families,
   methodologies — ~230 canonical terms across 13 categories, each with
   aliases/synonyms, e.g. `k8s`→Kubernetes, `js`→JavaScript). This is
   **not** general NLP keyword extraction — every stored term comes from
   the fixed list, so `jobs.matched_keywords` is directly comparable
   (simple set overlap) against a candidate's own skill list in the Job
   Application Service to compute a match score. Short/ambiguous tokens
   (`Go`, `R`, `C`) are matched case-sensitively to avoid false positives
   against ordinary English words. Covered by unit tests
   (`tests/pipeline/test_match_keywords.py`).
5. **Deduplicate** (`pipeline/dedupe.py`): see §7.
6. **Persist** (`persistence/repository.py`): idempotent upsert keyed by
   `(source, source_job_id)` for per-source identity, and by
   `canonical_fingerprint` for cross-source identity; update
   `last_seen_at` on every sighting; jobs not re-seen within a grace
   window get `active = false` rather than deleted.

Pure function pipeline (`JobDraft -> ClassifiedJob -> FilteredJob | None ->
KeywordedJob -> DedupedJob`) — each stage independently unit-testable
without a database.

## 7. Deduplication strategy

`canonical_fingerprint` = hash of normalized `(company_name, job_title,
normalized_location_bucket)` plus a fuzzy pass:

1. Exact fingerprint match → same job, merge (prefer canonical source per
   §5.3, extend `job_alt_sources`).
2. No exact match → fuzzy match against recent (e.g. last 30 days) jobs
   from the same company using title similarity (`rapidfuzz` token-set
   ratio ≥ threshold) — catches "Senior Backend Engineer" vs "Senior
   Backend Engineer (Remote)".
3. No match → new job.

Company names are normalized (lowercase, strip Inc/LLC/Corp suffixes)
before hashing.

## 8. Scheduler & workers

- APScheduler (`AsyncIOScheduler`) inside the FastAPI process for v1 — one
  job per enabled source, interval read from `sources.fetch_interval_seconds`
  (default ~2-3h, per-source override supported).
- The ATS connectors fan out over `ats_companies`; with a large company
  list, requests are staggered across the poll interval window (not fired
  all at once) to stay within each platform's fair-use rate limits.
- Each run: acquire per-source lock (skip if previous run still active) →
  `source_runs` row created → connector `fetch(since=last_success)` →
  pipeline → repository upsert → `source_runs` row finalized with counts.
- Shared `httpx.AsyncClient` per source with source-specific timeout and a
  token-bucket rate limiter; tenacity-based retry with exponential backoff
  + jitter on transient errors (5xx/timeout), no retry on 4xx.
- A failing/broken source only marks its own `source_runs` row `failed`
  and trips its own circuit breaker; other sources are unaffected.
- Incremental fetching: connectors accept `since` and use it wherever the
  source API supports a date/updated filter; full-list sources still fetch
  everything but pipeline dedup/upsert makes this a cheap no-op for
  unchanged jobs.
- `discovery_job.py` runs on its own (longer) interval, independent of the
  per-source fetch schedule.

## 9. REST API (FastAPI)

- `GET /jobs` — paginated, filters: `level`, `role_category`, `technology`,
  `keyword` (matches `matched_keywords`), `company`,
  `salary_min`/`salary_max`, `source`, `q` (search); `sort=newest` default;
  cursor or offset pagination.
- `GET /jobs/{id}` — full record incl. cleaned/raw JD and extracted
  keywords.
- `GET /jobs/new?since=<ts>` — convenience for "what's new since I last
  checked" polling from the Job Application Service.
- `GET /sources` — status/config per source.
- `GET /sources/{name}/runs` — recent run history.
- `GET /ats-companies` — list/inspect discovered companies (debugging
  coverage growth).
- `GET /stats` — total active jobs, added today, added last 24h, last
  fetch time.
- `GET /stream` — SSE stream of `job.created` / `job.updated` /
  `job.deactivated` events, backed by Postgres `LISTEN/NOTIFY` from the
  repository layer.
- `POST /jobs/submit` — ingestion for a job found manually (e.g. a human
  browsing LinkedIn on the Job Application Service side) rather than
  fetched by a connector: `source_url`, `company_name`, `job_title`,
  `raw_job_description`, plus optional `source` (default `"linkedin"`),
  `direct_apply_url`, `original_location`, `posted_at`,
  `original_salary_text`. Runs through the same `process_job()` +
  `upsert_job()` pipeline as every scheduled fetch, so the same
  keep/exclude rules and dedup logic apply — a rejected submission comes
  back with a `reason` instead of a silent drop, and re-submitting the
  same `source_url` updates the existing row rather than duplicating it.
- All endpoints require an API key header (`X-API-Key`) for v1 — simple
  shared-secret auth between this service and the Job Application Service.
- Optional: a read-only Postgres role documented for the Job Application
  Service if it ever wants direct DB access — API remains the primary
  contract.

## 10. Tech stack

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + asyncpg,
  Alembic migrations.
- APScheduler for scheduling, httpx for fetching, tenacity for retry,
  structlog for structured logs.
- rapidfuzz for fuzzy dedup matching.
- pyyaml to load the curated `config/keyword_taxonomy.yaml` vocabulary used
  by `match_keywords.py` (no ML hosting, no per-job API cost).
- pytest + pytest-asyncio + respx (HTTP mocking) for tests.
- Frontend (phase 13): React + TypeScript + Vite, plain fetch/EventSource.
- Local dev/deploy: Docker Compose (Postgres + app).

## 11. Implementation phases

1. Architecture + DB schema — **done**
2. FastAPI/PostgreSQL foundation: settings, DB session, Alembic, base
   models, Docker Compose
3. Source-connector interface + registry + config model
4. First real connectors (Greenhouse, Lever, Ashby, RemoteOK, Remotive,
   WWR) + ATS company discovery (seed loader + probe step)
5. Normalization layer
6. Filtering (remote/US/role/seniority/clearance gate)
7. Classification: level, role category, stack + taxonomy keyword matching
8. Deduplication
9. Scheduler + fetch workers + discovery job + source health tracking
10. REST API (`/jobs`, `/sources`, `/ats-companies`, `/stats`) + API-key auth
11. Real-time layer: Postgres LISTEN/NOTIFY → SSE `/stream`
12. Tests (unit per pipeline stage, integration per connector, API tests)
13. React/Vite monitoring frontend (Jobs page, Source Status page)
14. End-to-end pass: run scheduler against real sources, verify data
    quality and coverage growth as `ats_companies` scales up

## 12. Decisions & defaults (see chat for rationale)

- Company seed data: static curated `config/ats_seed_companies.yaml`
  (~50 companies), extensible any time, plus organic discovery from every
  aggregator-observed company name — no external paid data source, and no
  dependency on YC's undocumented internal directory API.
- Hosting: local Docker Compose for now; containerized so a cloud move
  later is a deploy-target change, not a rewrite.
- API auth: shared API key header for v1.
- Keyword field: **not** free-form NLP extraction. `matched_keywords` is a
  controlled-vocabulary match against `config/keyword_taxonomy.yaml`
  (languages, frameworks, domains), purpose-built so the Job Application
  Service can score jobs against a candidate's own keyword list via set
  overlap.

## 13. Progress

- Phase 1 (architecture) — done.
- Phase 2 (FastAPI/PostgreSQL foundation) — done: async SQLAlchemy models
  for all 6 tables, Alembic migrations, Docker Compose Postgres, `/health`
  endpoint, verified end-to-end.
- Keyword taxonomy (`config/keyword_taxonomy.yaml`) + `match_keywords.py`
  — done, unit-tested.
- Phase 3 (source-connector interface + registry) — done: `SourceConnector`
  ABC, `JobDraft`, registry, idempotent `sources` seed script.
- Phase 4 (first real connectors + ATS discovery) — done: Greenhouse,
  Lever, Ashby, RemoteOK, Remotive, We Work Remotely all fetch + normalize
  against their real live APIs (field shapes verified against production
  responses, not guessed). Shared `clean_html`/`parse_salary` helpers in
  `pipeline/normalize.py`. ATS discovery (`discovery/probe.py` +
  `discovery/seed_sources.py`) verified live against real companies
  (Airbnb→Greenhouse, Ro→Lever, Linear→Ashby, unknown company→no hits).
  29 unit tests passing (respx-mocked, no live-network dependency for
  future runs). Remaining sources (SmartRecruiters, Jobicy, Himalayas, YC,
  Adzuna, Jooble) deferred to a later pass.
- Phase 6+7 (Filter + Classify, built together — see §6 reorder note) —
  done: `classify_level.py`, `classify_role.py`, `classify_stack.py`
  (reuses the keyword taxonomy instead of a second tech dictionary),
  `clearance.py`, `filters.py` (remote/US assessment with an
  ambiguous-resolves-to-exclude policy). 76 unit tests passing, plus a
  live end-to-end run against real Airbnb/Ro/Linear/Ramp postings that
  surfaced and fixed 4 real bugs before being trusted: a bare `\bus\b`
  regex colliding with the English pronoun "us" ("join us"), state names
  matched against incidental JD boilerplate ("offices in ... New York
  ...") rather than the actual location field, 2-letter state
  abbreviations colliding with common words ("in" = Indiana), and
  "Northern America" not matching a "North America" pattern that assumed
  no suffix.

- Phase 8 (Deduplication) — done: `dedupe.py` (fingerprint + rapidfuzz
  fuzzy title fallback, scoped to same-company candidates; source-priority
  ranking for canonical-source selection) plus `pipeline.py`, the
  orchestrator tying Classify → Filter → MatchKeywords → Dedupe into one
  `process_job()` call for the persistence layer to use. 89 unit tests
  passing.

- Phase 9 (Scheduler + fetch workers + discovery job + source health) —
  done: `persistence/repository.py` (idempotent 3-way upsert: same-source
  update, cross-source dedup/promotion via job_alt_sources, expiry
  marking), `scheduler/runner.py` (per-job commit + per-job exception
  isolation, so one bad job/company never rolls back a whole run's
  progress), `scheduler/scheduler.py` (APScheduler, one job per enabled
  source at its own interval, `max_instances=1` as the per-source lock),
  `scheduler/discovery_job.py`, `scheduler/health.py`. Wired into the
  FastAPI lifespan (toggleable via `scheduler_enabled`).
  Validated with a full live run against the real dev database: enabled
  greenhouse/lever/ashby/remoteok, ran each end-to-end against their real
  APIs, persisted 55 real jobs, then ran discovery, which organically
  found 3 new companies (from jobs.company_name) and validated 10 more
  from the static seed list - including a genuine edge case (Reddit
  turned out to have boards on both Greenhouse and Ashby, handled without
  conflict). 102 unit tests passing, all robust to a non-empty database
  (scoped assertions, not table-wide counts) after that live run
  surfaced 5 tests that had wrongly assumed an empty table.

- Phase 10 (REST API) — done: `GET /jobs` (filterable by level, role,
  technology, keyword, company, salary range, source, free-text `q`;
  paginated), `GET /jobs/new?since=`, `GET /jobs/{id}`, `GET /sources`,
  `GET /sources/{name}/runs`, `GET /sources/{name}/health`,
  `GET /ats-companies`, `GET /stats`. `X-API-Key` auth on every route.
  Two real bugs caught and fixed while wiring this up: `vars()` doesn't
  work on slotted dataclasses (`SourceHealth`) - switched to
  `dataclasses.asdict()`; and the `jobs` array columns (main_stack,
  matched_keywords, etc.) were nullable with no default, so a row without
  every field explicitly set produced `NULL` where the API schema
  required a list - migrated them to NOT NULL with an empty-array default
  (backfilling existing rows first). Verified against the live app and
  real persisted data (not just tests): auth enforcement, filtering,
  pagination, source health, and stats all confirmed working end-to-end.
  116 unit tests passing.

- Phase 11 (real-time layer) — done: `GET /stream` SSE endpoint backed by
  Postgres LISTEN/NOTIFY. `persistence/repository.py` emits
  `job.created`/`job.updated`/`job.deactivated` on every write (the
  deactivation one via an UPDATE...RETURNING so each expired job gets its
  own event). Verified live end-to-end, not just unit-tested: started the
  real app, connected an SSE client, persisted a job through the real
  repository layer in a separate call, and confirmed the client received
  the `job.created` event with the correct payload in real time.
  119 unit tests passing.

- Phase 13 (React/Vite monitoring frontend) — done: Jobs page (job cards,
  search, level/role/technology/company/source/salary filters, newest-
  first pagination, View JD modal, Apply button) and Source Status page
  (per-source health table + stats tiles), per architecture.md §2E/§5.
  API base URL + key configurable in-app (stored in localStorage, no
  build-time config needed). Real bug caught only by testing in an actual
  browser, not curl or unit tests: FastAPI had no `CORSMiddleware`, so
  the browser silently blocked every cross-origin request from the
  frontend's origin to the API's - added it (all origins, since every
  route already requires `X-API-Key`). Verified with a full live run,
  backend + frontend both actually running, driven by Playwright with
  screenshots: real job cards render correctly, level/technology filters
  narrow results, pagination advances pages, the JD modal loads the full
  description, and the Source Status page shows live per-source health
  and stats. (One cosmetic artifact spotted in a screenshot - a mangled
  "™" in a job title - traced back to RemoteOK's own raw API response
  before concluding it wasn't a bug in this pipeline.)

- Phase 14 (end-to-end testing) — done:
  - Backend: `tests/api/test_end_to_end.py` - a mocked Greenhouse HTTP
    response goes through the real `scheduler.run_source()` (classify →
    filter → match keywords → dedupe → persist) and is verified through
    the real REST API, including a job deliberately excluded for being
    hybrid and one for being an internship, proving the filters actually
    apply end-to-end and not just in isolated unit tests. Building it
    surfaced a real gap in test setup (not app behavior): `run_source`
    sources its company list from `ats_companies` filtered by
    `connector.name`, not from whatever's set directly on the connector
    instance - a useful reminder of how that wiring actually works.
  - Frontend: a proper `@playwright/test` suite (`frontend/e2e/`,
    `npm run test:e2e`) replacing the ad hoc driver script used earlier -
    covers loading real job cards, level filtering, pagination, and the
    View JD modal on the Jobs page, plus the stats tiles and source
    health table on the Source Status page. Run twice against the live
    app to confirm no flakiness.
  - 120 backend unit/integration tests + 5 frontend E2E tests, all
    passing.

- Requirement change: jobs posted more than a week ago are now excluded
  (was: no age cutoff at all). Added `settings.max_job_age_days` (default
  7), a new Filter-stage check (`posted_too_long_ago`), and a retroactive
  `deactivate_stale_by_posted_age` alongside the existing
  `mark_expired_jobs` so already-persisted jobs age out too, not just new
  ones. Applied immediately to the real dev database: 49 of the 56
  persisted jobs (most from the initial backfill runs, some over a month
  old) were deactivated, leaving 7 active. Also fixed a latent bug this
  surfaced: Remotive's `publication_date` has no UTC offset, producing a
  naive datetime that would have raised when compared against an aware
  cutoff - fixed at the source (assume UTC) and defensively in the filter
  itself (any naive `posted_at` from any connector is treated as UTC
  rather than crashing that job's processing). 127 tests passing.

- Bug fix: `classify_role.py`'s JD-body fallback was too loose - a
  recruiter's JD naturally mentions "hire great Software Engineers" and
  a product manager's JD naturally mentions "our Generative AI roadmap,"
  both of which matched the generic engineering patterns and got kept as
  engineering roles. This was visible in earlier live-testing output
  ("Senior Technical Recruiter" classified as Backend) but not fixed at
  the time. Added a non-engineering title gate (recruiter, sales/account/
  business development, marketing, HR/people/talent, legal, finance,
  program/project/product manager, design, editor/content, localization,
  etc.) checked *before* any positive role matching, and removed the
  riskiest fallback (the generic `software engineer` pattern) from JD-body
  matching entirely - it's title-only now, the more specific patterns
  (AI/ML/DevOps/etc.) still fall back to JD text since they're narrow
  enough phrases to be safe. Applied retroactively to the real dev
  database (2 more misclassified rows deactivated, on top of the 49 the
  age-cutoff pass already caught). 133 tests passing.

- The remaining 6 sources from §5.2: 3 implemented and live-tested
  (SmartRecruiters, Jobicy, Himalayas), 2 implemented but pending
  credentials only the user can provide (Adzuna, Jooble — free/instant
  and requested-key signups respectively, see §5.2), 1 permanently
  dropped after confirming live that no official API exists (Y
  Combinator/Work at a Startup — same policy as LinkedIn/Indeed/etc.,
  not scraping it). All 12 originally-planned connectors are now either
  built or explicitly, permanently out of scope for a documented reason
  — nothing left in a "maybe later" limbo state.
  - SmartRecruiters needed a two-step fetch (list, then a detail call
    per posting for the full JD) unlike the other ATS connectors, which
    return everything inline — cut the cost with a legitimate
    optimization: SmartRecruiters tells us `location.remote` directly in
    the list response, so non-remote postings never trigger the
    expensive detail fetch at all (verified live: Equinox's 736 postings
    → 1 detail fetch, since SmartRecruiters customers skew toward
    large retail/service companies with mostly in-person roles).
  - Himalayas has no server-side category or date filter and a 100k+
    job catalog — implemented bounded, cursor-based pagination that
    stops once results are older than `max_job_age_days` (verified
    newest-first ordering live first), rather than scanning the whole
    catalog every run.
  - Adzuna/Jooble are unit-tested against mocked responses built from
    documented API formats, not live responses like every other
    connector — flagged clearly in both files' docstrings as needing
    re-verification once real credentials are available. Jooble's
    connector deliberately makes exactly one request per fetch (no
    pagination) since its free tier is a 500-call **lifetime** cap, not
    monthly.
  - Real bug caught by the Himalayas live run, not by any test: a
    session shared across an entire source run (hundreds of sequential
    commits for a source like Himalayas, which can yield ~1000 jobs in
    one fetch) eventually crashed with a SQLAlchemy `MissingGreenlet`
    error from accumulated session state — and because the crash also
    broke `rollback()`, it escaped every isolation layer meant to
    contain a single bad job. Fixed by giving each job its own short-
    lived session in production (`scheduler/runner.py`), while tests
    still share one session for their rollback-based isolation via the
    existing `session=` override parameter. Also hardened the rollback
    path itself: if rolling back fails too, that's now caught and
    logged instead of propagating.
  - 9 of 11 buildable sources now enabled live (adzuna/jooble disabled
    pending credentials); total active jobs went from 4 → 142 in one
    live run across all newly-enabled sources.
  - 142 tests passing.

- Adzuna and Jooble now live-verified: the user obtained real credentials
  (Adzuna: free/instant signup; Jooble: requested key) and both
  connectors were re-tested against the real APIs. Every field name
  matched what was built from documented API format ahead of time,
  except two real gaps fixed after being found live:
  - Adzuna returns `salary_min`/`salary_max` as `0` rather than omitted
    when unstated (same placeholder pattern already handled for
    RemoteOK) - fixed with the same `or None` guard.
  - Jooble's `updated` timestamp has no UTC offset at all (confirmed
    live: `"2026-09-17T00:00:00.0000000"`) - fixed the same way as
    Remotive's equivalent gap (assume UTC for a naive parsed datetime).
  - Adzuna without a keyword filter returned 0 kept jobs out of the
    first 200 (newest-sorted results were dominated by trucking/
    logistics/healthcare postings) - added `what=software engineer` to
    the query, which alone lifted that to 81/500 kept while still
    surfacing a good mix of role families (backend, embedded, AI, etc.).
  - That same live run surfaced a second, more significant bug:
    `classify_role`'s JD-body fallback (already narrowed once, after the
    recruiter/PM false positives) was still unsafe even for the
    "specific" patterns kept in place - a company's generic "About us"
    boilerplate mentioning "Machine Learning and Software Engineering"
    as capabilities, not role descriptions, appeared at the top of every
    one of that company's postings and misclassified 8 clearly
    non-engineering roles (Power BI Analyst, Cloud Architect, etc.) as
    "Machine Learning". Removed JD-body fallback from `classify_role`
    entirely - it's title-only now. Confirmed live: all 8 previously-
    misclassified postings now correctly excluded
    (`not_a_target_role`); kept count went 81 -> 66 (the 15 lost were
    exactly the false positives).
  - Both sources enabled and run live through the real scheduler:
    Adzuna fetched=500 new=59, Jooble fetched=30 new=5 (deliberately
    capped at one request per fetch - free tier is a 500-call
    **lifetime**, not monthly, cap).
- **All 11 buildable sources are now enabled and healthy** (Y Combinator
  remains the one permanent exception, per its own entry above). Total
  active jobs: 4 → 142 → 206 across this session's connector work.
  143 tests passing.

- New feature: `POST /jobs/submit` — an ingestion endpoint for jobs found
  manually rather than fetched by a connector. Motivation: the separate
  Job Application Service the user is also building has a human browsing
  LinkedIn (no scraping — a person finds the link and chooses to submit
  it), and needs a way to hand a job link + company name + raw JD over to
  this service. Requirement was explicit that the exclusion rules must be
  identical to the fetch pipeline's, so the route is a thin adapter that
  builds a `JobDraft` from the submission (hashing the URL into a stable
  `source_job_id` so re-submitting the same link is idempotent rather than
  duplicating; salary parsed from `original_salary_text` if given, else
  from the JD text via the same `parse_salary()` every connector uses) and
  hands it to the exact same `pipeline.process_job()` +
  `repository.upsert_job()` used by every scheduled fetch — not a parallel
  reimplementation that could drift out of sync. Rejected jobs get a
  `reason` (e.g. `not_confirmed_remote`) instead of being silently
  dropped, since a human submitted this one and may want to know why.
  Added `"linkedin"` to `dedupe.SOURCE_PRIORITY` at the lowest tier (same
  as the other aggregators) — an ATS-sourced posting for the same job
  stays canonical over a manually-submitted one, and re-submitting the
  same URL updates the existing row in place rather than creating a
  duplicate. `X-API-Key` auth required, same as every other route.
  6 new tests in `tests/api/test_ingest.py` cover: auth required, request
  validation, a full create through the real pipeline (including verifying
  parsed salary), rejection with a reason, idempotent re-submission
  (update, not duplicate), and staying subordinate to an existing
  higher-priority ATS-sourced duplicate. 149 tests passing.

- The scheduler is now running continuously against the real dev
  environment (was previously only started for one-off manual/live-test
  runs, sometimes with `SCHEDULER_ENABLED=false` to keep those tests
  deterministic). Restarted the backend with the scheduler on: all 11
  enabled sources fired immediately on startup (each `source_runs` row
  `status=success`, `consecutive_failures=0`) and are now on their own
  recurring interval (mostly every 3h, `jobicy` hourly, one at 6h — see
  `sources.fetch_interval_seconds`), plus the independent discovery job
  on its own longer interval. This is what makes the service actually
  "continuous" end to end rather than needing a manual trigger per
  source. Confirmed via `/stats`: 211 active jobs, 262 added in the last
  24h.

- Expanded `config/ats_seed_companies.yaml` from 52 to 238 companies
  (biggest lever for coverage, per §5.4 — the static list is a bootstrap
  for direct ATS discovery, which is preferred over aggregator sources
  since Greenhouse/Lever/Ashby postings are the canonical, highest-
  dedup-priority source). Added real, known VC-backed/public tech
  companies across categories not well represented in the original list:
  infra/cloud, dev tools, AI/ML, security, fintech, HR tech, e-commerce,
  health tech, crypto, and robotics/hardware. Verified live: restarted
  the backend (which runs discovery immediately on startup) and it found
  66 new confirmed ATS boards in one run (100 → 166 known companies;
  greenhouse 55→91, ashby 38→59, lever 7→16) out of the 200 candidates
  it checks per run (`candidate_limit`) — organic candidates (company
  names already seen in fetched jobs) take priority over the static
  seed, so the remaining new seed entries not covered by this run will
  get probed on the next weekly discovery cycle rather than all at once.
  149 tests passing (unaffected — this is a config-only change).

Repo: https://github.com/aidencayfordwork/Job_Fetching_Service (commit +
push after each phase).
