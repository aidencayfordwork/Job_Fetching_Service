# Job-fetch platform ↔ BidFlow: collaboration guide

**For:** BidFlow's Claude (and anyone maintaining BidFlow).
**From:** the job-fetch platform (this repo), maintained with Claude.
**Date:** 2026-09-19. This file is kept current. When anything below changes, it is updated in the same push.

**Status:**
- **Built:** the publisher, tested against a local copy of BidFlow's `job_feed` schema, connected as `jobfeed_writer`.
- **Not yet connected** to BidFlow production (§13 lists what's left).
- **Runs in a dev studio** whose database has been wiped twice. The code is safe in Git; the data isn't.

---

## 1. Reading this repo

**Repo:** https://github.com/aidencayfordwork/Job_Fetching_Service (branch `main`). It is **public**, so any Claude with web or git access can read it at any time, and it shows the latest push.
**Raw files:** `https://raw.githubusercontent.com/aidencayfordwork/Job_Fetching_Service/main/<path>`

| Read this | For |
|---|---|
| `docs/bidflow/COLLABORATION.md` | This guide: start here. |
| `docs/bidflow/JOB_FEED_CONTRACT.md`, `job_feed_schema.sql`, `JOB_PLATFORM_DB_PROMPT.md` | BidFlow's three documents, stored verbatim. |
| `docs/bidflow/FIELD_MAPPING.md` | Platform field → `job_feed.jobs` column, one page. |
| `docs/bidflow/REPLY_TO_BIDFLOW.md` | The platform's reply to your §15, including 6 open questions. |
| `app/publish/publisher.py` | The publisher: upsert, savepoints, change detection, `verified_at`, status. |
| `app/publish/feed_row.py` | Row building and the hold-back rules. |
| `app/publish/tagging.py` | How tags are chosen from your catalog. |
| `app/publish/catalog.py` | Reads `job_feed.tags` / `tag_aliases` every run. |
| `app/pipeline/filters.py` | US-remote verification, age, role and level gate. |
| `app/pipeline/dedupe.py`, `app/persistence/repository.py` | Cross-source dedup, upsert, expiry. |
| `app/db/models.py`, `alembic/versions/` | The platform's own schema. |
| `app/api/routes_ingest.py` | `POST /jobs/submit` (manual LinkedIn jobs). |
| `tests/publish/` | Publisher tests against the replica, plus tagging and row tests. |
| `architecture.md` | Full design and dated progress log. |

**Not in the repo:** secrets (`.env` is gitignored), database contents and chat history.

---

## 2. Who owns what

| Area | Owner |
|---|---|
| `job_feed` schema, triggers, tag catalog, ranking, bidders, resumes, applications | **BidFlow** |
| Sources, fetching, parsing, US-remote verification, dedup, tag *choice*, lifecycle, publishing | **Platform** |
| Platform database (separate PostgreSQL) | **Platform** |
| Adding a column to `job_feed.jobs` | **BidFlow**, on the platform's request, optional first |

**Integration surface:**
1. **Main path:** the platform upserts into `job_feed.jobs` as `jobfeed_writer`. It reads `job_feed.tags` / `job_feed.tag_aliases`. It never deletes, and never touches anything else.
2. **Manual jobs:** `POST /jobs/submit` on the platform's API. A person found the job (e.g. on LinkedIn), and the platform checks it and publishes it through the main path (§9).

BidFlow never needs to call the platform to read jobs. The row in `job_feed.jobs` is the job.

---

## 3. Blueprint

```
 official APIs/feeds ──► fetch ──► normalize ──► classify ──► filter ──► keyword-match ──► dedupe ──► platform DB
 ATS discovery (weekly) ─┘                                                                              │
 POST /jobs/submit (manual) ──────────────────────────────────────────────────────────────────────────┘
                                                                                                         ▼
                                    publish every 10 min: re-verify → tag (BidFlow catalog) → upsert changed rows ──► job_feed.jobs
```

| Stage | What happens |
|---|---|
| Fetch | One connector per source, async HTTP, up to 4 attempts with exponential backoff and jitter on 5xx, 429 and network errors (never other 4xx), honest User-Agent (`job-fetching-service/0.1 (+repo URL)`). |
| Normalize | HTML → plain text with line structure, salary parsed, timestamps to UTC. |
| Classify | Level (MID/SENIOR/STAFF/LEAD); role category from the **title only**; tech stack from a curated 167-term taxonomy. No LLM anywhere. |
| Filter | Keep/exclude rules (§5). |
| Dedupe | Same opening across sources is merged into one canonical row, preferring the employer ATS. |
| Store | Idempotent upsert into the platform DB; each job commits separately, so one bad job can't break a run. |
| Publish | §8. |

---

## 4. Sources and cadence

| Source | Type | Every | Published to BidFlow? |
|---|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters | Employer ATS public APIs (per company board) | 3 h | Yes |
| Himalayas, Jobicy, Remotive, RemoteOK | Remote-job aggregator APIs | 3 h | Yes (see Q3 about `job_url`) |
| We Work Remotely | RSS | 1 h | Yes |
| Adzuna | Aggregator API (`what=software engineer`) | 3 h | **No**: the API returns 500-char snippets |
| Jooble | Aggregator API (500-call lifetime quota, 1 call/run) | 6 h | **No**: the API returns ~300-char snippets |
| LinkedIn | Manual only, via `POST /jobs/submit` | on submit | Yes, same checks |

- **ATS discovery (weekly, 200 candidates per run):** probes company names against the public Greenhouse, Lever and Ashby board APIs.
  - Candidates come from company names seen on the aggregators, plus a 238-company seed list.
  - Last measured: 82 Greenhouse, 59 Ashby and 12 Lever boards. SmartRecruiters has no auto-discovery.
- **ATS boards are re-fetched in full on every run.** Aggregators use incremental fetching. Himalayas pagination stops once results are older than 7 days.
- **Never fetched (terms-of-service or no public API):** LinkedIn, Indeed, Glassdoor, ZipRecruiter, Built In, Otta/Welcome to the Jungle, HiringCafe, Y Combinator/Work at a Startup. No logins, no paywalls, no CAPTCHA solving.

---

## 5. What qualifies

| Rule | Detail |
|---|---|
| Role | Software engineering only, decided from the **title**. Recruiters, sales, PM, design, marketing, HR, finance and similar are excluded before anything else. |
| Level | MID, SENIOR, STAFF or LEAD, from title markers. With no marker, from "N+ years" in the description. Junior, intern, new-grad and principal/director-and-above are excluded. |
| Age | `posted_at` within 7 days. An unknown `posted_at` isn't penalized. |
| Clearance | Jobs requiring an active clearance are excluded. "Ability to obtain", public trust, background check and citizenship requirements are allowed. |
| Fully remote | "Hybrid", "on-site", "in office" or "N days a week in the office" → not remote. |
| US-eligible | Decision order below. |

**US-eligibility order.** The location field decides first; the description counts only when the location names no place.
1. "Excluding / not available in the US" anywhere → **no**.
2. US states in the location field → **yes**, US-partial (the states stay in `location_text`).
3. Location field says US / U.S. / United States → **yes**.
4. Location field says North America → **ambiguous** (not published).
5. Location field names any non-US country, region or major city → **no**.
6. Location field says Global / Anywhere / Anywhere in the World / worldwide → **yes** (worldwide includes the US).
7. Location field names no place:
   - "must be based in <non-US>" → **no**;
   - a US mention in the first 1,500 characters of the description → **yes**;
   - "worldwide" / "work from anywhere" → **yes**;
   - "<region> only" → **no**.
8. Anything else → **ambiguous**, not published.

**Held back at publish time** even when stored:

| Reason | Rule |
|---|---|
| `description_truncated` | Adzuna and Jooble (snippet-only APIs). |
| `description_too_short` | Plain-text description under 400 characters. |
| `template_posting` | Unfilled HR template (placeholder markers, or the same bullet 3+ times). |
| `no_named_employer` | Company blank, "Confidential", "Undisclosed", "Stealth" or "N/A". |
| `requires_clearance` | Active clearance, or "clearance", "TS/SCI" or "polygraph" in the title. |
| `not_verified_us_remote` | Every job is re-checked against the **current** rules at publish time. |
| `duplicate_of_published_job` | Its key is already pinned to another published job. |

---

## 6. Platform database

This is a separate PostgreSQL 16 database with Alembic migrations. Timestamps are `timestamptz` (UTC); primary keys are integer/bigint.

```
sources ─┬─< source_runs                 ats_companies
         │
jobs ────┼─< job_alt_sources             (other sightings of the same opening)
         ├── feed_publications (1:1)     (pinned BidFlow key + what BidFlow holds)
         ├─< feed_publish_log            (append-only, every attempt)
         └─< job_raw_payloads            (exists, not written yet)
```

| Table | Purpose | Key columns |
|---|---|---|
| `sources` | One row per source | `name` (never renamed), `kind`, `fetch_interval_seconds`, `enabled` |
| `source_runs` | Append-only run log | started/finished, `status`, fetched / new / updated / filtered-out counts, error |
| `ats_companies` | Discovered employer boards | `ats_platform`, `board_token`, `source_of_discovery`, `enabled` |
| `jobs` | **One row per canonical opening** | `source`, `source_job_id` (unique together), company, title, URLs, level, role_category, stacks, remote/US scope, eligible_states, salary fields, `posted_at`, first/last_seen, raw and cleaned description, `matched_keywords`, `active`, `canonical_fingerprint` |
| `job_alt_sources` | Other (source, id, url) sightings merged into a job | unique (`source`, `source_job_id`) |
| `feed_publications` | Publish state per job | `feed_source` + `feed_source_job_id` (**pinned**, unique), `sent_hash`, `last_result`, `feed_status` (what BidFlow holds), `verified_at`, first published |
| `feed_publish_log` | Append-only | `result` (INSERTED/UPDATED/UNCHANGED/REJECTED), status sent, `constraint_name`, message |

**Identity and dedup:**
- **Within a source:** `(source, source_job_id)` identifies a job. A re-fetch updates the row in place.
- **Across sources:** jobs are matched by fingerprint (normalized company, title and remote scope), falling back to fuzzy title matching (≥90) within the same company. Employer ATS (priority 10) beats aggregators and manual submissions (priority 1). A better source **rewrites `jobs.source`/`source_job_id` on the same row**, and the old sighting moves to `job_alt_sources`.
- **Pinned key:** because promotion changes `jobs.source`, the BidFlow key is taken at the first publish and stored in `feed_publications`. It is never changed afterwards, so BidFlow keeps one row per opening.

**Lifecycle in the platform DB:**
- A job not seen for 5 days → inactive.
- `posted_at` older than 7 days → inactive.
- Nothing is deleted.

---

## 7. Classification and keywords, platform side

The platform keeps its own 167-term taxonomy (`config/keyword_taxonomy.yaml`, 14 categories) in `jobs.matched_keywords`, for its own dashboard and API. This is **separate from BidFlow's tags**. BidFlow tags are chosen fresh from BidFlow's live catalog at publish time (§8).

---

## 8. Publishing into `job_feed.jobs`

**Each run (every 10 min, when `BIDFLOW_DATABASE_URL` is set):**
1. Read the active tag catalog and its aliases from BidFlow. Retired (`is_active = false`) tags are ignored.
2. Build a row for every active job and every job BidFlow currently holds.
3. Hash the writer columns, excluding `verified_at`. If the hash equals the last one sent, **don't send** (a rejected row isn't retried until the job changes).
4. Upsert changed rows with **the contract's SQL verbatim**, adding only `RETURNING (xmax = 0) AS inserted, (updated_at = now()) AS touched`. Up to 200 rows per transaction, **one savepoint per row**.
5. Record the result in `feed_publications` and `feed_publish_log`.

**Field mapping** (full version in `FIELD_MAPPING.md`):

| Column | Value |
|---|---|
| `source`, `source_job_id` | Pinned key: ATS or board id; manual jobs use `linkedin` + SHA-256 of the URL |
| `job_url` | Posting URL, forced to https; `utm_*`, `ref`, `gh_src`, `source`, `src`, `lever-*` and the fragment removed |
| `jd_text` | Full description as plain text: headings and paragraphs on their own lines, list items as `- ` lines. Never truncated. |
| `company` | Display name as the source gives it (see risk R6) |
| `title` | As posted, minus trailing "(Remote)" / "- Remote, US" / requisition ids / emoji |
| `country_code`, `work_type` | `US`, `REMOTE` |
| `location_text` | The posting's own wording; if empty, "Remote (US)" / "Remote (worldwide)" |
| `employment_type` | `FULL_TIME` etc. when stated, else null |
| `posted_at` | Source publish time, UTC |
| `verified_at` | Set at first publish. Changed only when a real content change is sent **and** the previous value is at least 24 h old. |
| `salary_min/max` | Annual USD only (a single figure gives min = max); otherwise null |
| `salary_text` | Original string |
| `status` | Active → `ACTIVE`; inactive and posted > 7 days ago → `EXPIRED`; else `CLOSED`. A published job that fails re-verification → `CLOSED`. A job that comes back → `ACTIVE` again. |

**Tags** (rule-based, deterministic):
- **Role tags (★, at most 2) come only from the title** (e.g. "Backend Engineer" → `backend`, "ML Engineer" → `ml`). Never from the description, so an "AI company" doesn't make a backend job an `ai` job.
- **Generic "Software Engineer" titles:**
  - requirements name 2+ backend technologies and ≤1 frontend technology → `backend`;
  - both backend and frontend are strong → `fullstack`;
  - otherwise no role tag.
- **Role-type NORMAL tags** come from the title or role category only: `fullstack`, `frontend`, `mobile`, `ios`, `devops`, `cloud`.
- **Technology tags (at most 13)** come from the requirement parts of the description only. Before matching, the tagger removes:
  - "Nice to have", "Preferred" and "Bonus" sections;
  - "About <company>" sections;
  - benefits, compensation and EEO sections;
  - any sentence containing "a plus", "nice to have", "preferred" or "ideally".

  Ranking is by frequency, with a title mention counting 3×. Ambiguous words (`go`, `swift`, `cloud`, `mobile`, `node`, `ts`/`js`, `evaluation`, `streaming`…) need specific phrasing.
- **Unknown terms (at most 5):** real skills from the platform taxonomy that your catalog lacks (e.g. `rust`, `graphql`). They're sent as-is, per your rule 3, and land in `unknown_tags`.
- **Your §9 worked example** produces exactly `backend`★, `python`, `fastapi`, `postgresql`, `aws`, `kubernetes`, `api design`. It's a unit test.
- **Last measured:** 5.9 catalog tags per job on average. 3 jobs had none: security roles, because the catalog has no security tag.

**Errors:**

| Case | Behaviour |
|---|---|
| Constraint or data rejection | Logged (`REJECTED` plus constraint name); the rest of the batch lands; not retried until the job changes |
| Connection error | The run aborts; the platform DB isn't updated; the next run (10 min) retries the same rows |
| Auth error (28P01 / 28000) | `FeedAuthError` is raised and logged as `bidflow_auth_failed`. The run stops, and the owner asks BidFlow's admin for the new password. |

**Connection:** SQLAlchemy asyncpg, pool size 2 (max 3), `pool_pre_ping`, TLS set by `BIDFLOW_SSL` (default `require`; `disable` only for the local replica). The password lives only in `.env`.

---

## 9. Manual jobs (LinkedIn): `POST /jobs/submit`

A person finds a job and submits it; the platform **never fetches LinkedIn**.

```
POST /jobs/submit                     header  X-API-Key: <platform API key>
{
  "source_url": "https://www.linkedin.com/jobs/view/123",   // required, http(s)
  "company_name": "Acme Robotics",                          // required
  "job_title": "Senior Backend Engineer",                   // required
  "raw_job_description": "<full JD, text or HTML>",         // required, full text
  "source": "linkedin",                                     // optional, default "linkedin"
  "direct_apply_url": "https://...",                        // optional
  "original_location": "Remote - US",                       // optional, strongly recommended
  "posted_at": "2026-09-18T12:00:00Z",                      // optional
  "original_salary_text": "$150k - $180k"                   // optional
}
→ 200 {"status": "created" | "updated" | "duplicate" | "rejected", "reason": "...", "job_id": 123}
```

- **Same pipeline and filters** as fetched jobs, so a submission can be `rejected` with a reason such as `not_confirmed_remote` or `not_a_target_role`. HTTP 401 means a bad key; 422 means missing fields.
- **Key:** `source` plus the SHA-256 of `source_url`. Re-submitting the same URL returns `updated`, not a new job.
- **Duplicates:** if the same opening already exists from an employer ATS, the ATS row stays canonical and the response is `duplicate` with that job's id.
- **Timing:** accepted jobs reach `job_feed.jobs` on the next publish run (≤10 min), after the same hold-back checks. That includes the 400-character minimum, so **send the full description**.
- **The `source` value is published as BidFlow's `source`.** Callers should always send `linkedin`, or another name agreed with the platform owner, never ad-hoc values.

---

## 10. Other interfaces (BidFlow doesn't need these)

All of these require `X-API-Key`; CORS allows all origins.
- `GET /jobs`, `/jobs/new`, `/jobs/{id}`, `/stats`, `/sources`, `/sources/{name}/runs`, `/sources/{name}/health`, `/ats-companies`.
- `GET /stream`: server-sent events (`job.created` / `updated` / `deactivated`), driven by Postgres `LISTEN/NOTIFY`.
- A React dev dashboard. It's used for monitoring only.

---

## 11. Contract compliance

| BidFlow requirement | Status | Note |
|---|---|---|
| Write only through `jobfeed_writer`, only writer columns, no DELETE, nothing outside `job_feed` | Met | Verified by a replica test (DELETE refused) |
| Contract upsert verbatim | Met | Plus a `RETURNING` clause only |
| Batches with one savepoint per row; rejected row logged and skipped | Met | Tested (bad salary rejected, rest of the batch lands) |
| Publish only changed rows (hash) | Met | Second run sent 0 of 102 |
| `verified_at` refreshed at most once a day | Met | Refreshed only together with a real change (see Q1) |
| TLS, pool of 1–3, stop and alert on auth error | Met | `BIDFLOW_SSL=require`, pool 2+1, `FeedAuthError` |
| Connection error → retry with backoff | Partial | Retried on the next 10-min run, with no backoff in between |
| Only verified US-remote jobs | Met | Re-verified at publish time |
| `NEEDS_REVIEW` state and stored evidence | Not met | Ambiguous jobs are simply not published; evidence isn't stored (Q4) |
| Full description, never truncated, line structure kept | Met | Snippet sources held back |
| `job_url` canonical https, tracking removed | Met | |
| Aggregator → publish the employer's version | Partial | Only when the employer ATS was also fetched (Q3) |
| Title noise only removed | Met | |
| `company` = real employer, one spelling per employer | Partial | Real names; spelling not unified across sources (R6) |
| `employment_type` values | Met | Mostly null (sources rarely state it) |
| `posted_at` with offset | Met | 102/102 had it |
| Salary annual USD only | Met | |
| Tags: 1–2 ★ role, required tech only, catalog codes, skip inactive, 4–15 | Met | Average 5.9; some jobs have fewer than 4 |
| Tags stable across runs | Met | Deterministic; changes only when description or catalog changes |
| Tag reasons stored (if AI) | Not needed | No AI used; rules are in code |
| Read catalog every run, no stale cache | Met | |
| Status lifecycle; never delete; reactivation → `ACTIVE` | Met | |
| Close after gone on 2 consecutive checks | Deviation | Closed after 5 days unseen (R4) |
| Re-check every `ACTIVE` job daily | Met for ATS | Full boards every 3 h; aggregators rely on the 5-day unseen rule |
| Keep raw postings for re-extraction | Partial | Raw description kept on `jobs`; full payload table not written |
| Cross-source dedup, publish one member, ATS preferred | Met | |
| Reposts under a new id → new job | Partial | New job unless the old one is still active with the same company + title (then merged) |
| Quality filters §6 (expired, templates, unnamed employer, unreadable) | Partial | No explicit "no longer accepting" / evergreen detection |
| Platform DB style §12 (uuid PKs, CHECK status, named constraints, own schema, models-match-migrations test, separate crawler role) | Deviation | Integer/bigint PKs, no CHECK on status columns, default `public` schema, no such test, one app DB role. Doesn't affect BidFlow's data. |
| Never write derived columns, never send scores | Met | |
| Robots/ToS, honest User-Agent, backoff on 429/5xx | Met | Official APIs only; up to 4 attempts with exponential backoff and jitter |

---

## 12. Risks and mismatch points

| # | Risk | Effect on BidFlow | Mitigation | Status |
|---|---|---|---|---|
| R1 | Platform DB wiped (dev studio) | Pinned keys lost: re-found jobs may get a new key (a **second live row**; the old row is never closed), and every job is re-sent with a new `verified_at` (**re-announcement burst**) | Durable hosting with backups; on startup, rebuild `feed_publications` from the platform's own rows in `job_feed.jobs` | **Open, go-live blocker** |
| R2 | Stored jobs not re-checked when rules tighten | None for BidFlow (publish-time re-check closes them); the platform's own dashboard shows stale jobs | Re-verification sweep each fetch cycle | Open |
| R3 | First publish inserts ~100 rows at once | One burst of "new job" alerts | BidFlow may want to mute alerts for the first import, or the platform trickles the first load | **Needs BidFlow decision** |
| R4 | Closing is slow (5 days unseen) | Filled jobs stay on the board up to ~5 days | Close ATS jobs after 2 consecutive misses (full boards every 3 h) | Open (planned) |
| R5 | Aggregator-only jobs link to the aggregator page | Bidder lands on Himalayas, Jobicy, etc., not the employer | Follow aggregator links to the employer later, or hold these back | **Needs BidFlow decision (Q3)** |
| R6 | Company spelling differs by source ("Chime Financial, Inc" vs "Chime") | `company_key` differs, so past-employer exclusion and same-company warnings can miss | Strip legal suffixes and unify spelling per employer before publishing | Open |
| R7 | Catalog gaps (no security tag; rust, mongodb, graphql, c++, scala, mysql, redis…) | Those jobs rank low or have no tags | BidFlow adds tags or aliases; existing rows pick them up automatically | **Needs BidFlow decision (Q2)** |
| R8 | Rule-based tagging edge cases | A stray tag from a company pitch before the first heading; "We Go deep" read as Go | Section filtering; ★ from title only; report bad tags (§14) | Accepted, monitored |
| R9 | `POST /jobs/submit` callers send ad-hoc `source` values | New source names appear in BidFlow | Callers use `linkedin` only | **Needs agreement (Q6)** |
| R10 | Adzuna/Jooble never published | Fewer jobs | Only fixable with full descriptions from the employer | Accepted |
| R11 | Password rotation | Publishing stops until a new password is set | Clean stop plus `bidflow_auth_failed` log | Accepted |

---

## 13. Go-live checklist

**Platform:**
- [ ] Durable hosting for the app and its Postgres, with backups (R1)
- [ ] Startup reconciliation of `feed_publications` from `job_feed.jobs` (R1)
- [ ] Unified company display names (R6)
- [ ] Faster ATS closing, 2 misses (R4)
- [ ] Set `BIDFLOW_DATABASE_URL` + `BIDFLOW_SSL=require` in `.env`; run one publish; spot-check 20 rows together with BidFlow

**BidFlow:**
- [ ] Send host, port, database and the `jobfeed_writer` password to the owner
- [ ] Answer Q1–Q6 (`REPLY_TO_BIDFLOW.md`) and Q7–Q8 below
- [ ] Decide how to handle the first-import alert burst (R3)
- [ ] Add the missing catalog tags (R7)

---

## 14. Working together

- **Channel:** the owner relays messages between the two Claudes. Each side keeps its docs in its own repo; this repo's `docs/bidflow/` holds everything exchanged.
- **Schema changes (BidFlow):** through BidFlow migrations, optional columns first, announced before they become required. Send the new `job_feed_schema.sql`. The platform updates its replica and tests, then its mapping.
- **Catalog changes (BidFlow):** no coordination needed. They're read every run; existing rows are retagged by BidFlow's trigger.
- **Platform changes:** pushed to `main` with this file and `docs/bidflow/*` updated in the same push. Each dated entry below says what changed for BidFlow.
- **Reporting a bad job or tag:** send the `job_feed.jobs` row's `source` + `source_job_id`, plus what's wrong. The platform traces it via `feed_publications` → `jobs` and fixes the rule, and the corrected row is re-sent automatically.
- **Source names are stable forever:** `greenhouse`, `lever`, `ashby`, `smartrecruiters`, `himalayas`, `jobicy`, `weworkremotely`, `remotive`, `remoteok`, `linkedin`. New sources get new names; existing ones are never renamed.

**Changelog:**
- 2026-09-19: publisher built and replica-tested; US-remote verification tightened (location field decides first); this guide created.

---

## 15. Open questions for BidFlow

1. **`verified_at`:** set at first publish and refreshed only together with a real change (≤ once a day). OK, or refresh daily (which re-announces every job daily)?
2. **Catalog:** add `security` and the frequent unknown tags (rust, databricks, grpc, mongodb, c++, scala, mysql, ruby, graphql, bigquery, jenkins, redis, elasticsearch…)?
3. **Aggregator-only jobs:** publish with the aggregator `job_url`, or hold them back until the employer URL is resolved?
4. **Evidence storage:** do you need stored verification evidence and a `NEEDS_REVIEW` queue now, or later?
5. **Closing:** OK to switch ATS jobs to "closed after 2 consecutive misses"?
6. **Manual jobs:** will BidFlow's tools call `POST /jobs/submit` (they'd need the platform API key), and with `source = "linkedin"` only?
7. **First import:** mute alerts for the first bulk insert, or should the platform trickle it in (e.g. 20 jobs per run)?
8. **Optional columns:** add `seniority`, `eligible_states`, `min_years_experience`, `apply_url` to `job_feed.jobs`? The platform already has these values.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| Platform | This job-fetch service (repo above) |
| Feed | BidFlow's `job_feed.jobs` table |
| Pinned key | The `(source, source_job_id)` fixed at first publish, stored in `feed_publications` |
| Held back | Stored by the platform but deliberately not published (§5) |
| ATS | Employer applicant-tracking system (Greenhouse, Lever, Ashby, SmartRecruiters) |
| Replica | Local database loaded from `job_feed_schema.sql`, used for tests |
