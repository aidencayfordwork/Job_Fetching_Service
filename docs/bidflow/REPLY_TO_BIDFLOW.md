# Reply to BidFlow — from the job-fetch platform

**Status.** The publisher is built and tested against a local replica loaded from your `job_feed_schema.sql`, connected as `jobfeed_writer`. It uses your upsert verbatim, with one savepoint per row. It is not connected to production yet; your admin needs to send host, port, database and the `jobfeed_writer` password.

Real run against the replica (2026-09-19): 102 jobs `ACTIVE`, 5.9 catalog tags per job on average, 102/102 with `posted_at`, 37/102 with an annual-USD salary. A second run sent 0 rows because nothing had changed.

---

## 1. Schema and field mapping

The platform runs its own PostgreSQL 16 with Alembic migrations. It never touches your schema.

```
sources ─┬─< source_runs              (append-only run log per source)
         └─ ats_companies             (discovered Greenhouse/Lever/Ashby boards)
jobs ────┬─< job_alt_sources          (same opening seen on other sources)
         ├── feed_publications        (1:1, pinned feed key + what BidFlow holds)
         └─< feed_publish_log         (append-only, every publish attempt)
```

| Your §12 suggestion | Mine | Notes |
|---|---|---|
| `sources`, `fetch_runs` | `sources`, `source_runs` | Per-source interval, health and counts. |
| `postings` | `jobs` | One row per canonical opening. Holds the raw description, so I can re-extract without re-fetching. |
| `raw_postings` | none | `job_raw_payloads` exists but isn't written yet. Only the raw description is kept, not the full payload. |
| `duplicate_groups` | `job_alt_sources` | Canonical row plus other sightings. The employer ATS is preferred over aggregators. |
| `verifications`, `posting_tags` | none | Both are recomputed from the stored description on every publish; the evidence and tag reasons aren't stored yet (§6, Q4). |
| `tag_catalog_cache` | none | The catalog is read live from `job_feed.tags` / `tag_aliases` at the start of every publish run. |
| `publish_log` | `feed_publish_log` + `feed_publications` | `INSERTED` / `UPDATED` / `UNCHANGED` / `REJECTED`, constraint name, and a hash of the last row sent. |

**Identity.** My cross-source dedup can later switch a job's canonical source (e.g. an aggregator posting that turns out to have a Greenhouse original). Your key must never change, so the platform pins `(source, source_job_id)` in `feed_publications` at the first publish. Later updates always go to that same row, and it's never re-keyed.

**Field mapping:**

| Column | Source and normalization |
|---|---|
| `source`, `source_job_id` | Pinned at first publish. ATS ids as given. Manual submissions: `source='linkedin'` plus SHA-256 of the URL. |
| `job_url` | Posting URL, forced to https. `utm_*`, `ref`, `gh_src`, `source`, `src`, `lever-*` and `#fragment` stripped. |
| `jd_text` | Full description, HTML converted to plain text. Headings and paragraphs keep their line breaks; list items become `- ` lines. Never truncated. |
| `company` | Display name as given by the source. |
| `title` | As posted, minus trailing "(Remote)" / "- Remote, US" / requisition ids / emoji. |
| `country_code`, `work_type` | Always `US`, `REMOTE`. |
| `location_text` | The posting's own location wording. |
| `employment_type` | `FULL_TIME` etc. when the source says so; mostly null. |
| `posted_at` | Source publish time, UTC. |
| `verified_at` | See Q1. |
| `salary_min/max` | Annual USD only. A single figure gives min = max. Anything else stays null. |
| `salary_text` | Original string, unchanged. |
| `tags` | §4 below. |
| `status` | `ACTIVE` while listed. Unlisted and over 7 days old: `EXPIRED`. Otherwise unlisted: `CLOSED`. A published job that later fails verification is sent `CLOSED`. |

## 2. Sources, volume, cadence

All sources are official APIs or feeds. No scraping, no logins. LinkedIn, Indeed and similar boards are never fetched. LinkedIn jobs arrive only when a person submits a link to my `POST /jobs/submit`.

| Source | Publishable, posted in the last 24 h | Notes |
|---|---|---|
| Himalayas | 34 | Aggregator; `job_url` is the Himalayas page (see Q3). |
| Greenhouse | 7 | 82 boards. Grows as weekly discovery adds companies. |
| Jobicy | 4 | Aggregator. |
| Ashby | 1 | 59 boards. |
| Lever | 0 | 12 boards. |
| We Work Remotely / Remotive | about 1 | Aggregators. |
| SmartRecruiters | 0 | No boards discovered yet. |
| Adzuna, Jooble | **held back** | Their APIs return only 300–500-character snippets, which breaks your "never truncate" rule. |
| LinkedIn (manual) | depends on your bidders | Same checks and tagging as fetched jobs. |

That's about 45 publishable new jobs a day. The figure is from the first day after a database reset, so treat it as a rough estimate. It should rise as ATS discovery adds boards.

**Cadence.** Each source is fetched every 1–6 h (most every 3 h), and ATS boards are re-fetched in full every time. ATS discovery runs weekly. Publishing runs every 10 min and sends only rows whose content changed.

**Closing jobs.** A job not seen for 5 days is closed. That's slower than your "2 consecutive misses" (see §6).

## 3. US-remote verification

Verification is rule-based and deterministic. It runs when a job is stored and again at publish time.

1. An explicit "not open to US" style exclusion → reject.
2. US states in the location field → US-eligible, states kept in `location_text`.
3. The location field decides next: US / U.S. / United States → yes. North America → ambiguous. Any non-US country, region or major city → no. "Global" / "Anywhere in the world" → no: only jobs explicitly for the US are published (the owner's rule, stricter than your §5).
4. Only when the location field names no place ("Remote", empty): "must be based in <non-US>" → no; a US mention in the first 1,500 characters of the description → yes; "worldwide" / "work from anywhere" → no.
5. Hybrid, on-site, in-office or "N days a week in the office" anywhere in the location or opening text → not remote.
6. Anything else is ambiguous and not published.

**Rates on the current data** (153 jobs with full descriptions): 102 published, 34 definite non-US or not remote (22%), 16 ambiguous (10%, the equivalent of your `NEEDS_REVIEW`). Ambiguous jobs are held, not queued for review, and the evidence isn't stored yet.

Writing this surfaced a real bug in my own filter. The word "global" in marketing text ("a global company") was read as worldwide-remote, and a "US" mention in a description overrode a non-US location field. Jobs located in Mexico, Germany, Portugal and Japan had been kept. That's fixed and covered by regression tests, and every job is re-verified at publish time, so nothing verified under the old rules gets through.

Also held back: unfilled HR template postings, jobs with no named employer, and jobs requiring clearance (JD rules plus "clearance" / "TS/SCI" in the title).

## 4. Tagging

Tagging is rule-based and deterministic, run against your live catalog every run.

- **★ role tags (at most 2)** come only from the title and my role classifier, never from the description, so an "AI company" doesn't turn every job into `ai`. Title rules cover `mlops`, `genai`, `ai`, `ml`, `data engineering`, `data platform`, `data science`, `android` and `backend`. A generic "Software Engineer" title gets `backend` only if its requirements name 2+ backend technologies and at most one frontend one. If both sides are strong it gets `fullstack` instead.
- **Role-type NORMAL tags** (`fullstack`, `frontend`, `mobile`, `ios`, `devops`, `cloud`) also come only from the title or role category.
- **Technology tags (at most 13)** are matched only in the requirement parts of the description. Before matching, the tagger removes:
  - "Nice to have", "Preferred" and "Bonus" sections;
  - "About <company>" sections;
  - benefits, compensation and EEO sections;
  - any sentence containing "a plus", "nice to have", "ideally" or "preferred".

  Terms are ranked by frequency, and a title mention counts 3×. Ambiguous words (`go`, `swift`, `cloud`, `mobile`, `node`, `ts`/`js`, `evaluation`, `streaming`…) need specific phrasing, e.g. "Golang" or "in Go"; "model evaluation"; "stream processing".
- **Unknown terms (at most 5)** are real skills from my 167-term taxonomy that your catalog lacks. They're sent as-is, per your rule 3.

Your §9 example comes out exactly as specified: `backend` ★, `python`, `fastapi`, `postgresql`, `aws`, `kubernetes`, `api design`, with no `kafka`. That example is a unit test.

**10 real jobs** (codes as sent; a trailing ★ marks IMPORTANT; *italics* are unknown terms):

| Job | Tags |
|---|---|
| Sr. Data Engineer — Carrot | data engineering★, etl, snowflake, airflow, aws, dbt, gcp, python, data modeling, sql, *redshift* |
| Android Engineer, Social — Robinhood | android★, mobile, kotlin, spark, java, jetpack compose |
| Senior Software Engineer, AI Enablement — Chime | ai★, llm, distributed systems, javascript, python, typescript, go |
| Senior Software Engineer — AccuLynx | backend★, api design, sql, *c#, elasticsearch, microsoft sql server, redis, vue.js* |
| Senior Software Engineer, Tech Foundations — Airbnb | backend★, kotlin, python, typescript, experimentation, go |
| Sr DevOps Engineer — Ascensus | devops, ci/cd, kubernetes, microservices, python, terraform, *gitlab ci, jenkins* |
| Infrastructure Engineer — Bayesian Health | devops, ci/cd, terraform, aws, kubernetes, postgresql, *circleci, datadog, mysql* |
| Senior Data Engineer (Contract) — Concurrency | data engineering★, azure, etl, sql, data modeling, python, ci/cd, spark, data governance |
| Staff Security Engineer, Enterprise AI — Affirm | ai★, llm, python, aws, kubernetes, rag, terraform, openai, *vector database* |
| Senior Software Engineer II, Full-Stack — Braze | fullstack |

Known weaknesses: a company pitch *before* the first heading can still add a stray tag (one job got `experimentation` from "we empower our customers… experimentation"). The rare "We Go deep" style sentence reads as Go. Security roles get no tags because the catalog has none (Q2).

## 5. Optional columns I'd like on `job_feed.jobs`

| Column | Why |
|---|---|
| `seniority text` (`MID`/`SENIOR`/`STAFF`/`LEAD`) | Already classified for every job. Lets you filter the board by level. |
| `eligible_states text[]` | "Remote in CA, NY or TX" jobs: without it, an engineer in another state is shown jobs they can't take. `location_text` has the words, but you can't filter on them. |
| `min_years_experience int` | Already extracted where stated. |
| `apply_url text` | For some ATSs (e.g. Ashby) the application form differs from the posting page. |

## 6. Questions

1. **`verified_at`.** I set it at first publish and refresh it only alongside a real content change, at most once a day. An unchanged open job therefore keeps its original `verified_at`, and I never send "heartbeat" updates. Is that what you want? Or should I refresh it daily, which re-announces every job daily? (Every published job currently has `posted_at`, so the board-age fallback rarely matters.)
2. **Catalog gaps.** Real skills most often in `unknown_tags` right now: rust, databricks, grpc, mongodb, c++, scala, mysql, ruby, graphql, bigquery, jenkins, vector database, microsoft sql server, angular, redis, elasticsearch. There is also no security tag, so security-engineering jobs arrive untagged. Please add a `security` tag, or tell me to stop publishing those roles.
3. **Aggregator-only jobs.** For Himalayas, Jobicy, WWR and Remotive, `job_url` is the aggregator's page unless I've also seen the employer's ATS posting (then the ATS version wins). Following aggregator links to the employer page is possible later. Until then, publish with the aggregator URL, or hold them back?
4. **Evidence storage.** Do you need the verification evidence and tag reasons stored now (§5, §9 rule 5), or later?
5. **Faster closing.** For ATS sources I refetch the whole board every 3 h, so I could close after 2 consecutive misses instead of 5 days. I plan to do that unless you see a reason not to.
6. **LinkedIn submissions.** They go through my `POST /jobs/submit` (API key) with `source='linkedin'` and the same checks and tags. Will your bidders' tool call that endpoint, or should manual jobs come in some other way?
