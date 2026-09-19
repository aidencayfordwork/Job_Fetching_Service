-- One-time setup of BidFlow's database for the job-fetch platform
-- (docs/bidflow/COLLABORATION.md §15a). Run it as the database owner, after
-- BidFlow's own migrations have created the job_feed schema:
--
--   psql "<BidFlow Postgres URL>" -v ON_ERROR_STOP=1 \
--        -v jobfetch_password='<secret-1>' -v writer_password='<secret-2>' \
--        -f bidflow_db_setup.sql
--
-- On Railway the Postgres URL is the Postgres service's DATABASE_PUBLIC_URL
-- (or run it from `railway connect Postgres`). Safe to re-run: it creates only
-- what is missing and sets the two passwords.

-- 1. The platform's own login. It owns the `platform` schema and nothing else;
--    it gets no access to any BidFlow table.
SELECT format('CREATE ROLE jobfetch_app LOGIN PASSWORD %L', :'jobfetch_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobfetch_app') \gexec
SELECT format('ALTER ROLE jobfetch_app LOGIN PASSWORD %L', :'jobfetch_password') \gexec
CREATE SCHEMA IF NOT EXISTS platform AUTHORIZATION jobfetch_app;

-- 2. The feed writer from BidFlow's contract, with exactly the privileges in
--    job_feed_schema.sql: write the writer columns of job_feed.jobs, read the
--    tag catalog, no DELETE.
SELECT format('CREATE ROLE jobfeed_writer LOGIN PASSWORD %L', :'writer_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobfeed_writer') \gexec
SELECT format('ALTER ROLE jobfeed_writer LOGIN PASSWORD %L', :'writer_password') \gexec
GRANT USAGE ON SCHEMA job_feed TO jobfeed_writer;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA job_feed TO jobfeed_writer;
GRANT SELECT ON job_feed.jobs, job_feed.tags, job_feed.tag_aliases TO jobfeed_writer;
GRANT INSERT (company, country_code, employment_type, jd_text, job_url, location_text, posted_at, salary_max, salary_min, salary_text, source, source_job_id, status, tags, title, verified_at, work_type) ON job_feed.jobs TO jobfeed_writer;
GRANT UPDATE (company, country_code, employment_type, jd_text, job_url, location_text, posted_at, salary_max, salary_min, salary_text, status, tags, title, verified_at, work_type) ON job_feed.jobs TO jobfeed_writer;

-- 3. Check: jobfetch_app can create only in `platform`; jobfeed_writer can
--    use job_feed but not delete.
SELECT r.rolname,
       has_schema_privilege(r.rolname, 'platform', 'CREATE') AS creates_in_platform,
       has_schema_privilege(r.rolname, 'job_feed', 'USAGE') AS uses_job_feed,
       has_table_privilege(r.rolname, 'job_feed.jobs', 'DELETE') AS can_delete_jobs
FROM pg_roles r
WHERE r.rolname IN ('jobfetch_app', 'jobfeed_writer')
ORDER BY 1;
