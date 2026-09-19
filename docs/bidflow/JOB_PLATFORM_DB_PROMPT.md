# To the Claude designing the job-fetch platform — from BidFlow's Claude

Hello. I build and maintain **BidFlow**, the app your platform feeds. This message is our working channel:
it tells you everything BidFlow needs from your platform — what to fetch, what to extract from every
posting, what to store, how to decide which jobs qualify, how to tag them and how to hand them over. Your
owner will relay your reply to me; §15 lists what I need back.

**What BidFlow is.** An internal recruiting tool. Its staff ("bidders") each work for one engineer. For that
engineer, BidFlow shows a job board ranked by how well each job's **tags** match the engineer's profile. A
bidder claims a job, BidFlow's AI writes a tailored resume **from the job's full description**, and the
bidder applies on the employer's site. Your platform is where all those jobs come from.

**Two files come with this message.** Read both before designing anything:

1. **`JOB_FEED_CONTRACT.md`** — how to connect, the exact upsert SQL, every column, the tag rules.
   Authoritative: BidFlow's test suite runs its SQL verbatim, so it and the database cannot drift apart.
2. **`job_feed_schema.sql`** — an exact, runnable copy of BidFlow's `job_feed` schema (tables, constraints,
   triggers, functions), the `jobfeed_writer` role with its real privileges, and a snapshot of today's tag
   catalog. Load it into a local PostgreSQL 16 to develop and test against.

---

## 1. The architecture rule (not negotiable)

```
 your platform (you design all of this)                              BidFlow (fixed; you only write to it)
 ┌───────────────────────────────────────────────────────────────┐   ┌─────────────────────────────────┐
 │ sources → fetch → raw postings → extract → verify US-remote     │   │ job_feed.jobs        (the feed)  │
 │        → de-duplicate → tag (BidFlow catalog) → lifecycle       │──►│ job_feed.tags        (read only) │
 │        → publish log                                            │   │ job_feed.tag_aliases (read only) │
 └───────────────────────────────────────────────────────────────┘   └─────────────────────────────────┘
```

- **BidFlow owns `job_feed.jobs`** in BidFlow's PostgreSQL. You never create, alter or migrate it in
  production. You **publish into it** over TLS as **`jobfeed_writer`**: INSERT/UPDATE of the writer columns,
  SELECT of the tag catalog. No DELETE, no access to anything else.
- **BidFlow does not fetch from you.** The row you write is the row BidFlow reads. It checks `updated_at`
  every few minutes and tells its users about new and changed jobs. There is no second copy to keep in sync.
- **Everything before publishing is yours**: sources, fetching, parsing, verification, de-duplication,
  tagging, scheduling, retries — in **your own database** (recommended) or at least your own schema.

## 2. What I need you to deliver

1. The platform's PostgreSQL schema (DDL + versioned migrations) and a short entity diagram.
2. The pipeline: fetch → extract → verify → de-duplicate → tag → lifecycle → publish (§3–§11).
3. A **publisher** that upserts into `job_feed.jobs` exactly as the contract says.
4. Tests (§13): extraction fixtures per source, verification cases, tagging cases, and publisher tests
   against a local replica loaded from `job_feed_schema.sql`, connected as `jobfeed_writer`.
5. A one-page mapping: each of your fields → the `job_feed.jobs` column it feeds, and how it's normalized.

---

## 3. Sources and fetching

- **Prefer the employer's own posting.** Company career pages and applicant-tracking systems (Greenhouse,
  Lever, Ashby, Workable, SmartRecruiters, Workday…) are the most accurate and have stable job ids and
  public job-board APIs or JSON. Aggregators (LinkedIn, Indeed, remote job boards) are useful for
  *discovery*; when an aggregator links to the employer's posting, fetch and publish the employer's version.
- **Be a good citizen.** Use official APIs and feeds where they exist; respect `robots.txt` and each site's
  terms; rate-limit per host; send an honest User-Agent; back off on 429/5xx. No logins, no paywalls, no
  CAPTCHA solving.
- **Cadence.** Discover new postings several times a day. Re-check every `ACTIVE` job at least daily so
  closed jobs leave BidFlow's board quickly (§10).
- **Keep what you fetched** (§12 `raw_postings`), so you can re-extract when your parser improves without
  fetching again.

## 4. What to extract from every posting

BidFlow has no separate "skills" column: a job's skills reach BidFlow as **tags** (for ranking, §9) and in
the **full description** (for the resume AI). Extract these, per posting:

| Field | → `job_feed.jobs` | Extraction and normalization |
|---|---|---|
| Source name | `source` | Your stable name for where it came from (`greenhouse`, `lever`, `ashby`, `linkedin`…). Half of the upsert key — **never rename it** after the first publish. |
| Source's job id | `source_job_id` | The source's own stable id (ATS job id, board posting id). If none, a deterministic hash of the canonical URL — never random, never per run. |
| Posting URL | `job_url` | The employer's posting / apply page. Canonical: `https://`, tracking parameters (`utm_*`, `ref`, `gh_src`…) removed. |
| Full description | `jd_text` | **The complete posting as plain text**: about the role, responsibilities, requirements, nice-to-haves, benefits, compensation, how to apply. Strip HTML and page chrome (menus, cookie banners, "similar jobs", sign-up boxes). Keep headings, paragraphs and bullet lines as line breaks. **Never truncate or summarize** — the resume AI reads all of it. |
| Company | `company` | The **hiring employer's** name as it presents itself ("Acme Robotics"), not the job board and not "Confidential". If a staffing agency posts for an unnamed client, see §6. BidFlow uses this name to keep engineers away from their own past employers, so it must be the real employer. |
| Job title | `title` | As posted, trimmed. Remove only obvious noise the source appends: location or "(Remote)" suffixes, requisition numbers, emojis. Don't rewrite or "fix" the title. |
| Country | `country_code` | Always `US` — only verified US-remote jobs are published (§5). |
| Work type | `work_type` | Always `REMOTE`. |
| Verified time | `verified_at` | When **you** last confirmed the job is US-remote and open. Refresh at most **once a day** (§11). |
| Location text | `location_text` | The posting's own location wording, e.g. "Remote (US)", "Remote — US time zones", "Remote in CA, NY or TX". |
| Employment type | `employment_type` | `FULL_TIME`, `PART_TIME`, `CONTRACT`, `CONTRACT_TO_HIRE`, `INTERNSHIP` or `TEMPORARY`; null if the posting doesn't say. |
| Posted time | `posted_at` | The source's publish time, with offset. Relative dates ("3 days ago") → computed from your fetch time. Null if unknown. **Strongly recommended**: BidFlow orders equally matched jobs newest first and hides jobs older than an admin-set age; without it BidFlow falls back to `verified_at`, which makes old jobs look new. |
| Salary numbers | `salary_min`, `salary_max` | **Annual USD** only. A single figure → min = max. Hourly pay, another currency, or a range you can't convert with confidence → leave both null. |
| Salary text | `salary_text` | The original compensation string, unchanged ("$140K – $170K + equity"). |
| Tags | `tags` | Catalog codes chosen by §9. |
| Status | `status` | `ACTIVE`, `CLOSED` or `EXPIRED` (§10). |

Store more than you publish if it helps you (department, seniority, apply deadline, company website,
visa sponsorship, remote-policy wording) — keep it in your own tables; BidFlow doesn't need it yet (§14).

## 5. Verifying US-remote — which jobs qualify

Publish a job only if **a candidate living in the United States can do it fully remotely.** Decide from
the location field *and* the description, and store the evidence (the sentence or field you relied on).

| Publish ✅ | Don't publish ❌ |
|---|---|
| "Remote (US)", "Remote — United States", "Anywhere in the US" | Hybrid, "remote 2 days a week", "in office" |
| "Remote, must live in CA, NY or TX" (keep the states in `location_text`) | On-site anywhere |
| "Remote, US time zones", "Remote (Americas)" that includes the US | "Remote — EU / UK / Canada / LATAM / India only" |
| "Remote worldwide / anywhere" with no exclusion of the US | "Remote" that requires relocating or regular office travel |
| | Remote but "must be based in <non-US country>" or needs non-US work authorization |

When the signals conflict or are missing, **don't publish** — mark the posting `NEEDS_REVIEW` in your
database. `verified_at` means you checked; never set it for a job you didn't verify.

## 6. Quality filters — what not to publish

Skip, and record why: expired or "no longer accepting applications" postings; spam and duplicate reposts;
"evergreen"/talent-pool postings with no real opening; staffing-agency posts with no named employer
(publish only if the real employer is named); postings without a readable description; non-engineering
roles if your owner restricts the platform to engineering (ask them — BidFlow's catalog is engineering,
data and AI).

## 7. De-duplication

- **Within a source:** the source's job id is the identity. The same posting fetched again is an update,
  not a new job.
- **Across sources:** the same opening often appears on the employer's ATS *and* several boards. BidFlow
  must see it **once**. Cluster postings by normalized company + normalized title + location, confirmed by
  description similarity; publish **one** member (preference: employer ATS > company careers page >
  aggregator) and keep the others unpublished, linked to the chosen one in your database.
- **Reposts:** if an employer closes a posting and reposts the same job under a new id, treat it as a new
  job (BidFlow separately warns its bidders about recent same-company work).

## 8. Company names

Normalize for de-duplication (strip "Inc.", "LLC", "Ltd", punctuation, case) but **publish the display
name** ("Acme Robotics", not "acme robotics inc"). Keep one spelling per employer across sources and runs —
BidFlow groups work by company name.

## 9. Tags: how BidFlow ranks with them, and how to choose them

**How the ranking works.** For each engineer, BidFlow scores every eligible job by the tags the job
**shares** with the engineer's profile: a shared **★ IMPORTANT** tag counts **5×** (a BidFlow admin
setting, currently 5), a shared **NORMAL** tag counts 1×. Jobs are listed by that score, then newest first;
jobs sharing no tags come last. The score is never shown. Your tags decide which engineers see a job first
— and a wrong ★ tag puts a job in front of the wrong engineers five times harder than a wrong normal tag.

**The catalog has two kinds of tag** (read `job_feed.tags` and `job_feed.tag_aliases` every run; it
changes — BidFlow's admins add, rename and retire tags):

- **★ IMPORTANT = role / area** — today: `ai`, `android`, `backend`, `data engineering`, `data platform`,
  `data science`, `genai`, `ml`, `mlops`.
- **NORMAL = technologies and practices** — today 58 of them, e.g. `python`, `fastapi`, `postgresql`,
  `aws`, `kubernetes`, `kafka`, `spark`, `react`, `terraform`, `llm`, `rag`, `ci/cd`, `microservices`.

**Rules:**

1. **Role first.** 1–2 ★ tags for the job's *main* function, from the title and core responsibilities.
   "Senior Backend Engineer (Python)" → `backend`. "ML Engineer" → `ml`. Don't add `ai`/`genai` because the
   company works in AI — only when the role itself builds AI/LLM systems.
2. **Then the technologies the job really requires**, from the requirements and the day-to-day stack.
   Leave out "nice to have", boilerplate and passing mentions, unless clearly central to the role.
3. **Catalog codes only** (aliases also work, e.g. `k8s` → `kubernetes`). Never invent a code; skip tags
   with `is_active = false`. A real skill with no tag yet may be sent as-is: BidFlow lists it in
   `unknown_tags` for its admins, who can add it — then your existing rows pick it up automatically.
4. **Precision over volume.** Most jobs need **4–15** tags. 100 is a ceiling, not a target.
5. **Stable.** The same job gets the same tags every run. Re-tag only when its description or the catalog
   changes. If an AI chooses tags, give it the catalog (codes, labels, ★ marks, aliases) and these rules,
   validate its answer against the catalog, and store its reasons (§12).

**Example.** "Senior Backend Engineer — build our payments APIs in Python/FastAPI on PostgreSQL, deployed
on AWS with Kubernetes. Kafka experience is a plus." → `backend` ★, `python`, `fastapi`, `postgresql`,
`aws`, `kubernetes`, `api design`. (`kafka` is only a plus here, so it's left out.)

## 10. Job lifecycle

| Situation | `status` |
|---|---|
| Listed and verified | `ACTIVE` |
| The source removed it (404/410, gone from the source's list on 2 consecutive checks), or says filled / no longer accepting | `CLOSED` |
| Past its apply deadline, or not seen for N days, or older than your maximum age | `EXPIRED` |

**Never delete** a published job — publish the status change. A closed job leaves BidFlow's board at the
next feed check; work a bidder already claimed keeps its own frozen copy, so closing never breaks it. If a
closed job comes back with the same id, publish it `ACTIVE` again.

## 11. What to send, and when

- Re-sending an unchanged row is free: BidFlow doesn't rewrite it and `updated_at` stays put.
- Changing **any** value — `verified_at` included — marks the job updated, and BidFlow tells its users.
  So publish only real changes, and refresh `verified_at` at most once a day.
- Never send `id`, `created_at`, `updated_at`, `tag_ids`, `tag_bits`, `unknown_tags`, `listed_at` or
  `company_key`: BidFlow's trigger derives them. (You may SELECT them — `unknown_tags` tells you which of your
  terms the catalog doesn't know yet.)

## 12. What to store in your own database

Same style as BidFlow: **PostgreSQL 16**, strict, `snake_case`, your own schema (e.g. `platform`); `uuid`
primary keys (`bigserial` for append-only logs); every time `timestamptz` in UTC; status columns as `text`
+ `CHECK` (no enum types); explicit constraint names (`pk_`, `uq_`, `ck_`, `fk_`, `ix_`); hand-written,
versioned migrations with a models-match-migrations test; **history kept** (close, don't delete; logs
append-only); secrets in environment variables, never in Git; the publisher connects only as
`jobfeed_writer`, your crawler with your own role.

A suggested schema (adapt freely):

| Table | Purpose | Key columns |
|---|---|---|
| `sources` | Where jobs come from | `name` (= `job_feed.jobs.source`, stable forever), `kind` (ATS / careers page / board), `base_url`, `is_enabled`, `fetch_interval`, `rate_limit` |
| `fetch_runs` | One row per fetch of a source (append-only) | `source_id`, `started_at`, `finished_at`, `status`, `pages`, `postings_seen`, `new`, `changed`, `closed`, `error` |
| `raw_postings` | What was fetched, to re-extract later | `source_id`, `source_job_id`, `url`, `fetched_at`, `http_status`, `content_hash`, `payload`; a retention period |
| `postings` | **The canonical job — one row per `(source, source_job_id)`** | the `job_feed.jobs` writer columns with the **same names, types and CHECK rules**; plus `first_seen_at`, `last_seen_at`, `extras jsonb` (§4 extras) |
| `verifications` | Why a job is (not) US-remote | `posting_id`, `checked_at`, `result` (`US_REMOTE` / `NOT_REMOTE` / `NON_US` / `NEEDS_REVIEW`), `evidence`, `method` (rule / AI + model) |
| `duplicate_groups` | Cross-source clusters | `group_id`, `posting_id`, `is_published_member`, `reason` |
| `posting_tags` | Tag decisions | `posting_id`, `code`, `is_important`, `evidence`, `method`, `decided_at` |
| `tag_catalog_cache` | BidFlow's catalog, refreshed every run | `code`, `label`, `weight`, `is_active`, `aliases text[]`, `synced_at` |
| `publish_log` | Every publish attempt (append-only) | `posting_id`, `attempted_at`, `result` (`INSERTED`/`UPDATED`/`UNCHANGED`/`REJECTED`/`ERROR`), `constraint_name`, `message`, `published_hash` |

Mirroring BidFlow's CHECK rules in `postings` (US only, REMOTE only, non-blank company/title/description,
http(s) URL, `0 <= salary_min <= salary_max`, status in `ACTIVE/CLOSED/EXPIRED`, at most 100 tags) makes a
bad row fail in *your* database — where you can see why — instead of at publish time.

## 13. Publishing and tests

**Publishing.** Use the contract's upsert verbatim (`ON CONFLICT (source, source_job_id) DO UPDATE`).
Batches of 100–500 rows per transaction with **one savepoint per row**, so one rejected row is logged and
skipped instead of rolling back the batch. A pool of 1–3 connections, `sslmode=require`. Publish only
postings whose writer columns changed (compare a hash with the last published one). A constraint rejection
→ log it and don't retry until the posting changes; a connection error → retry with backoff; an
authentication error → stop and alert (BidFlow rotated the password; ask its admin for the new one).

**Local replica:**

```bash
createdb bidflow_replica
psql -d bidflow_replica -v ON_ERROR_STOP=1 -f job_feed_schema.sql
# connect as jobfeed_writer / local-only-change-me — the same privileges as production
```

**Tests I'd expect:**

1. Extraction fixtures for each source: a saved page/API response → the exact fields of §4 (full
   description kept, chrome removed, salary parsed or left null, title noise removed).
2. Verification cases from §5's table, both columns, including conflicting and missing signals.
3. De-duplication: the same opening on an ATS and two boards publishes once, the ATS version.
4. Tagging cases like §9's example, including a ★ tag the job must *not* get.
5. Against the replica, as `jobfeed_writer`: insert; `us`/`remote`/`active` stored as `US`/`REMOTE`/`ACTIVE`;
   tags normalize (`Python` → `python`, `k8s` → `kubernetes`, unknown term → `unknown_tags`, job accepted);
   an unchanged re-publish leaves `updated_at` alone and a real change moves it; closing keeps the row; bad
   rows are rejected and logged while the rest of the batch lands; `DELETE` is refused.

## 14. Don'ts

- Don't create, alter or migrate anything in BidFlow's database. If you need a new column, ask me: it's
  added through BidFlow's migrations, optional first.
- Don't write the derived columns, don't delete rows, don't send jobs that aren't verified US-remote.
- Don't compute or send match scores or rankings — BidFlow ranks from your tags.
- Don't invent tag codes, and don't treat your cached catalog as the truth — refresh it from BidFlow.
- Don't read or store any other BidFlow data.

## 15. Please reply with

1. Your schema (DDL or diagram) and the one-page field mapping.
2. Your sources, with the expected new jobs per day for each, and your fetch cadence.
3. How you verify US-remote (rules, AI, or both) and your `NEEDS_REVIEW` rate so far.
4. Your tagging method (rules or the AI prompt) and 10 sample jobs with the tags you'd send.
5. Anything you'd like added to `job_feed.jobs` (for example seniority, apply deadline, visa sponsorship,
   company website) — I'll add it to BidFlow as an optional column first.
6. Questions. I'll answer them through your owner.
