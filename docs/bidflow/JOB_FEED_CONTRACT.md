# Job Feed Contract (for the external job-fetch platform)

BidFlow owns the database. Your service connects as **`jobfeed_writer`** and may only
SELECT / INSERT / UPDATE `job_feed.jobs` and SELECT the tag catalog (`job_feed.tags`, `job_feed.tag_aliases`).
No DELETE. You have no access to any other schema.

You send each job's details **and its tags**: labels from BidFlow's shared tag list (AI, Python, Kubernetes…).
BidFlow uses the tags to show each engineer the best-matching jobs first.

Every rule in this document is executed by BidFlow's test suite (`backend/tests/test_feed_contract.py`,
which runs the SQL below verbatim as `jobfeed_writer`), so the document and the database cannot drift apart.

## Connecting

A BidFlow administrator gives you host, port, database name and the `jobfeed_writer` password.

```
postgresql://jobfeed_writer:<password>@<host>:<port>/<database>?sslmode=require
```

- TLS is required. Use a small pool (1–3 connections); the feed is not latency-sensitive.
- Passwords are rotated by BidFlow; on an authentication error, ask for the new one rather than retrying.
- Send timestamps with a time zone. A naive timestamp is read in the session time zone — UTC on BidFlow's
  servers unless your driver sets another — so sending the offset avoids surprises.

## Write rule

Upsert on `(source, source_job_id)`. Only write **verified US-remote** jobs.

```sql
INSERT INTO job_feed.jobs (
    source, source_job_id, job_url, jd_text, company, title,
    country_code, work_type, location_text, employment_type,
    posted_at, verified_at, salary_min, salary_max, salary_text,
    tags, status
) VALUES (...)
ON CONFLICT (source, source_job_id) DO UPDATE SET
    job_url = EXCLUDED.job_url, jd_text = EXCLUDED.jd_text, company = EXCLUDED.company,
    title = EXCLUDED.title, location_text = EXCLUDED.location_text,
    employment_type = EXCLUDED.employment_type, posted_at = EXCLUDED.posted_at,
    verified_at = EXCLUDED.verified_at, salary_min = EXCLUDED.salary_min,
    salary_max = EXCLUDED.salary_max, salary_text = EXCLUDED.salary_text,
    tags = EXCLUDED.tags, status = EXCLUDED.status;
```

To remove a job, set `status = 'CLOSED'` or `'EXPIRED'` — never delete.

Re-sending an unchanged job is harmless: the row is not rewritten and `updated_at` stays put, so you can
upsert your whole verified set on every run. But changing *any* value — `verified_at` included — marks the job as updated and
BidFlow tells its users about updated jobs, so refresh `verified_at` at most once a day.

Salaries are **annual USD**. If a source gives hourly pay or another currency you can't convert with
confidence, leave `salary_min` / `salary_max` null and keep the original in `salary_text`.

### Batching

Upsert in batches, but give **each row its own savepoint**, so one invalid row is skipped instead of
rolling back the whole batch:

```python
with engine.begin() as conn:                 # one transaction per batch
    for job in batch:
        try:
            with conn.begin_nested():        # SAVEPOINT per row
                conn.execute(UPSERT, job)
        except IntegrityError as exc:        # rejected by a constraint: log it and move on
            log.warning("skipped %s/%s: %s", job["source"], job["source_job_id"], exc.orig)
```

## Columns

| Column | Required | Notes |
|---|---|---|
| `id` | — | DB-generated UUID. Do not send. |
| `source` | yes | Your source name, e.g. `linkedin`. Part of the upsert key; not updatable. |
| `source_job_id` | yes | Stable id within the source. Part of the upsert key; not updatable. |
| `job_url` | yes | Must start with `http://` or `https://`. |
| `jd_text` | yes | Full job description, non-blank. |
| `company`, `title` | yes | Non-blank; trimmed by the DB. |
| `country_code` | yes | Must be `US` (case-insensitive input). |
| `work_type` | yes | Must be `REMOTE` (case-insensitive input). |
| `location_text` | no | Free text. |
| `employment_type` | no | e.g. `FULL_TIME`, `CONTRACT`. |
| `posted_at` | no | timestamptz. |
| `verified_at` | yes | When you verified the job as US-remote. |
| `salary_min`, `salary_max` | no | Non-negative, `min <= max`. |
| `salary_text` | no | Original salary string. |
| `tags` | yes | `text[]` of tag **codes** from `job_feed.tags` (aliases also accepted), at most 100. Case, spacing and duplicates are cleaned up by the DB. See [Tags](#tags). |
| `status` | yes | `ACTIVE`, `CLOSED`, or `EXPIRED`. |
| `created_at`, `updated_at` | — | DB-managed. `updated_at` changes only when a value you sent actually changes. |
| `tag_ids`, `tag_bits`, `unknown_tags`, `listed_at`, `company_key` | — | Derived by the DB from your row (read-only; you may SELECT them). `unknown_tags` lists terms no tag or alias covers. |

Invalid rows are rejected by constraints — non-US or non-remote, blank company/title/description, a URL
that is not http(s), negative or inverted salary range, an unknown status, a missing `verified_at`, more
than 100 tags. Log and skip them. (An unknown *tag* is not an error — see [Tags](#tags).)

## Tags

Read the catalog and label every job with the codes that fit it — the role/area (e.g. `ai`, `backend`,
`data engineering`) and the key technologies (e.g. `python`, `kubernetes`, `aws`):

```
SELECT code, label, is_active FROM job_feed.tags;          -- send `code`
SELECT alias, tag_id FROM job_feed.tag_aliases;             -- other spellings that also work ("k8s", "js")
```

- **Send codes from the catalog.** Aliases are accepted too and resolve to their tag.
- **Unknown terms never reject a job.** They are ignored for matching and listed in the row's `unknown_tags`
  until a BidFlow admin adds the tag or maps it as an alias — then your existing rows pick it up
  automatically (without changing their `updated_at`).
- **Skip tags with `is_active = false`.** The database still accepts them, but they are retired and do not
  count for matching.
- More tags that genuinely apply means better matching; tags that do not apply push the job in front of the
  wrong engineers. Stay under 100 per job.
- How BidFlow uses them: for each engineer it scores a job by the tags they share — an `IMPORTANT` (★) tag
  counts several times a `NORMAL` one (an admin setting, currently 5×) — then lists the newest first among
  equal scores. The ★ tags are role areas (`backend`, `ml`, `data engineering`…); give a job 1–2 of them for
  its main role, then the technologies it really requires. Most jobs need 4–15 tags.

## What BidFlow does with your rows

- For each engineer profile the job board lists every `ACTIVE` row whose `posted_at` (or, if absent,
  `verified_at`) is within the administrator's maximum job age — jobs sharing the most (and most important)
  tags with the profile first, then the newest. Jobs at the engineer's past employers are left out.
- Setting `CLOSED` or `EXPIRED` takes a job off the board. Work a bidder already claimed keeps a frozen
  copy of the job taken at claim time (and again at apply), so later edits never rewrite their records.
- BidFlow checks the feed every few minutes (admin setting) using `updated_at`, and alerts bidders only
  when something actually changed.

## Changes to this contract

The schema changes only through BidFlow migrations. New columns are added as optional first and
announced before they become required.
