# Field mapping: platform → `job_feed.jobs`

Code: `app/publish/feed_row.py` (row), `app/publish/tagging.py` (tags), `app/publish/publisher.py` (key, `verified_at`, sending).

| `job_feed.jobs` | From (platform `jobs` table) | Normalization |
|---|---|---|
| `source` | `feed_publications.feed_source` | `jobs.source` at the first publish, then pinned forever (cross-source dedup can later change `jobs.source` on the same row). |
| `source_job_id` | `feed_publications.feed_source_job_id` | `jobs.source_job_id` at the first publish, pinned. ATS/board ids as given; manual submissions (`POST /jobs/submit`) use SHA-256 of the URL. |
| `job_url` | `source_url`, else `direct_apply_url` | Must be http(s); forced to `https`; `utm_*`, `ref`, `gh_src`, `source`, `src`, `lever-*` params and `#fragment` removed. |
| `jd_text` | `raw_job_description` | HTML → plain text: headings/paragraphs on their own lines, list items as `- ` lines, scripts/styles dropped, entities decoded (double-escaped Greenhouse HTML handled). Never truncated. |
| `company` | `company_name` | Trimmed display name as the source gives it. |
| `title` | `job_title` | Only trailing noise removed: "(Remote)", "- Remote, US", "US Remote", "(US)", requisition ids, trailing emoji. |
| `country_code` | — | Always `US` (only verified US-remote jobs are published). |
| `work_type` | — | Always `REMOTE`. |
| `location_text` | `original_location` | As posted; if empty, "Remote (US)" / "Remote (worldwide)" / "Remote (US, some states)" from the verified scope. |
| `employment_type` | `employment_type` | `full_time` → `FULL_TIME` etc.; null if unknown (most sources don't say). |
| `posted_at` | `posted_at` | Source publish time, UTC (naive source timestamps are read as UTC). |
| `verified_at` | publisher | Time of the first publish; refreshed only together with a real content change and at most once a day. |
| `salary_min` / `salary_max` | `salary_min` / `salary_max` | Only when currency is USD and the period is annual (or unstated with figures ≥ 20,000). Single figure → min = max. Otherwise both null. |
| `salary_text` | `original_salary_text` | Original string, unchanged. |
| `tags` | `choose_tags()` | 1–2 ★ role codes from the title, then up to 13 technology codes from the requirement parts of the description, then up to 5 real skills the catalog lacks (land in `unknown_tags`). |
| `status` | `active`, `posted_at` | Active → `ACTIVE`; inactive and older than 7 days → `EXPIRED`; otherwise inactive → `CLOSED`. A published job that no longer passes the checks below is sent as `CLOSED`. |

## Not published (held back)

| Reason | Rule |
|---|---|
| `description_truncated` | Source only returns snippets (Adzuna, Jooble). |
| `description_too_short` | Plain-text description under 400 characters. |
| `template_posting` | Unfilled HR template (placeholder text, or the same bullet 3+ times). |
| `no_named_employer` | Company blank / "Confidential" / "Stealth". |
| `requires_clearance` | Active clearance required (JD rules), or "clearance" / "TS/SCI" / "polygraph" in the title. |
| `not_verified_us_remote` | Re-verified at publish time: must be remote (no hybrid/on-site wording) and US-eligible from the location field, falling back to the description only when the location names no place. |
| `duplicate_of_published_job` | Its (source, id) key is already pinned to another published job. |
