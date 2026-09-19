"""SQL from BidFlow's job feed contract (docs/bidflow/JOB_FEED_CONTRACT.md)."""

from sqlalchemy import text

# The contract's upsert, verbatim, plus a RETURNING clause to tell
# inserted / updated / unchanged apart (updated_at only moves when a value
# really changed, and now() is the transaction's timestamp).
UPSERT_SQL = text("""
INSERT INTO job_feed.jobs (
    source, source_job_id, job_url, jd_text, company, title,
    country_code, work_type, location_text, employment_type,
    posted_at, verified_at, salary_min, salary_max, salary_text,
    tags, status
) VALUES (
    :source, :source_job_id, :job_url, :jd_text, :company, :title,
    :country_code, :work_type, :location_text, :employment_type,
    :posted_at, :verified_at, :salary_min, :salary_max, :salary_text,
    :tags, :status
)
ON CONFLICT (source, source_job_id) DO UPDATE SET
    job_url = EXCLUDED.job_url, jd_text = EXCLUDED.jd_text, company = EXCLUDED.company,
    title = EXCLUDED.title, location_text = EXCLUDED.location_text,
    employment_type = EXCLUDED.employment_type, posted_at = EXCLUDED.posted_at,
    verified_at = EXCLUDED.verified_at, salary_min = EXCLUDED.salary_min,
    salary_max = EXCLUDED.salary_max, salary_text = EXCLUDED.salary_text,
    tags = EXCLUDED.tags, status = EXCLUDED.status
RETURNING (xmax = 0) AS inserted, (updated_at = now()) AS touched
""")
