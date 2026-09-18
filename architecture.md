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
│   │   ├── ycombinator.py
│   │   ├── adzuna.py
│   │   └── jooble.py
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
| Y Combinator Jobs | Public API/listing | filter by date | |
| Adzuna | Official free/paid API (`app_id`/`app_key`, instant self-serve signup) | filter by date | aggregates from thousands of sites incl. many employer boards; free tier ~1,000 calls/mo |
| Jooble | Official API (key on request) | filter by date | free tier capped at 500 calls lifetime — fine to start, paid arrangement needed for volume |
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
2. **Filter** (`pipeline/filters.py` + `clearance.py`): reject unless
   `is_remote` and `us_eligible` are both confirmed true; reject on-site/
   hybrid, non-US-eligible, or undeterminable remote-US status; reject
   non-software roles; reject by seniority (§ below); reject **active**-
   clearance requirements only (regex/keyword rules distinguishing "must
   currently hold" from "able to obtain" / "eligible for" / "public trust"
   / "background check" / "citizenship required", which are allowed).
3. **Classify**:
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

Pure function pipeline (`JobDraft -> FilteredJob | None -> ClassifiedJob ->
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

Repo: https://github.com/aidencayfordwork/Job_Fetching_Service (commit +
push after each phase).
