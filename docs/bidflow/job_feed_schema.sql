-- BidFlow `job_feed` schema: an exact local replica for the job-fetch platform's development and tests.
--
-- This is BidFlow's publish target, dumped from BidFlow's database (Alembic head 0016, 2026-09-19).
-- In production BidFlow owns and migrates these objects; the platform never runs this file there.
-- Locally: createdb bidflow_replica && psql -d bidflow_replica -v ON_ERROR_STOP=1 -f job_feed_schema.sql
-- Then connect as jobfeed_writer (password below, local only) exactly as production will.

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
-- Functions refer to each other; let them be created in file order.
SET check_function_bodies = false;

\restrict apDHFCpIouLpbElhD9Bwr4AhvuAVgyY1Z34Z4whSU2WlHaSqAHJctZQbZx5adBe
CREATE SCHEMA job_feed;
CREATE FUNCTION job_feed.company_key(name text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT lower(regexp_replace(btrim(name), '\s+', ' ', 'g')) $$;
CREATE FUNCTION job_feed.forbid_tag_delete() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            RAISE EXCEPTION 'tags are never deleted; set is_active = false' USING ERRCODE = 'restrict_violation';
        END
        $$;
CREATE FUNCTION job_feed.jobs_before_write() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.country_code  := upper(btrim(NEW.country_code));
            NEW.work_type     := upper(btrim(NEW.work_type));
            NEW.status        := upper(btrim(NEW.status));
            NEW.source        := btrim(NEW.source);
            NEW.source_job_id := btrim(NEW.source_job_id);
            NEW.job_url       := btrim(NEW.job_url);
            NEW.company       := btrim(NEW.company);
            NEW.title         := btrim(NEW.title);
            NEW.tags          := job_feed.normalize_tags(NEW.tags);
            IF TG_OP = 'INSERT' THEN
                NEW.created_at := now();
                NEW.updated_at := now();
            ELSE
                NEW.id         := OLD.id;
                NEW.created_at := OLD.created_at;
                NEW.updated_at := OLD.updated_at;
                -- Compare with the derived columns as they were: only writer-supplied changes move
                -- updated_at, so a catalog retag never re-announces jobs as changed.
                NEW.tag_ids      := OLD.tag_ids;
                NEW.tag_bits     := OLD.tag_bits;
                NEW.unknown_tags := OLD.unknown_tags;
                NEW.listed_at    := OLD.listed_at;
                NEW.company_key  := OLD.company_key;
                IF NEW IS DISTINCT FROM OLD THEN
                    NEW.updated_at := now();
                END IF;
            END IF;
            SELECT r.tag_ids, r.unknown_tags INTO NEW.tag_ids, NEW.unknown_tags FROM job_feed.resolve_tags(NEW.tags) r;
            NEW.tag_bits    := job_feed.tag_bitmap(NEW.tag_ids);
            NEW.listed_at   := coalesce(NEW.posted_at, NEW.verified_at);
            NEW.company_key := job_feed.company_key(NEW.company);
            RETURN NEW;
        END
        $$;
CREATE FUNCTION job_feed.normalize_tags(terms text[]) RETURNS text[]
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$
            SELECT coalesce(array_agg(k ORDER BY first_pos), '{}')
            FROM (
                SELECT job_feed.tag_key(t) AS k, min(pos) AS first_pos
                FROM unnest(coalesce(terms, '{}'::text[])) WITH ORDINALITY AS u(t, pos)
                WHERE job_feed.tag_key(t) IS NOT NULL
                GROUP BY 1
            ) s
        $$;
CREATE FUNCTION job_feed.resolve_tags(terms text[], OUT tag_ids integer[], OUT unknown_tags text[]) RETURNS record
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$
            SELECT coalesce(array_agg(DISTINCT r.id ORDER BY r.id) FILTER (WHERE r.id IS NOT NULL), '{}'),
                   coalesce(array_agg(u.term ORDER BY u.pos) FILTER (WHERE r.id IS NULL), '{}')
            FROM unnest(terms) WITH ORDINALITY AS u(term, pos)
            LEFT JOIN LATERAL (
                SELECT t.id FROM job_feed.tags t WHERE t.code = u.term
                UNION ALL
                SELECT a.tag_id FROM job_feed.tag_aliases a WHERE a.alias = u.term
                LIMIT 1
            ) r ON true
        $$;
CREATE FUNCTION job_feed.retag_jobs(terms text[]) RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
        DECLARE
            n integer;
        BEGIN
            UPDATE job_feed.jobs SET tags = tags WHERE tags && job_feed.normalize_tags(terms);
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN n;
        END
        $$;
CREATE FUNCTION job_feed.tag_bitmap(ids integer[]) RETURNS bit
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT coalesce(bit_or(set_bit(B'0'::bit(1024), i, 1)), B'0'::bit(1024)) FROM unnest(ids) AS i $$;
CREATE FUNCTION job_feed.tag_key(term text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $$ SELECT nullif(lower(regexp_replace(btrim(term), '\s+', ' ', 'g')), '') $$;
CREATE FUNCTION job_feed.touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$;
CREATE TABLE job_feed.jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    source text NOT NULL,
    source_job_id text NOT NULL,
    job_url text NOT NULL,
    jd_text text NOT NULL,
    company text NOT NULL,
    title text NOT NULL,
    country_code text DEFAULT 'US'::text NOT NULL,
    work_type text DEFAULT 'REMOTE'::text NOT NULL,
    location_text text,
    employment_type text,
    posted_at timestamp with time zone,
    verified_at timestamp with time zone NOT NULL,
    salary_min numeric(12,2),
    salary_max numeric(12,2),
    salary_text text,
    status text DEFAULT 'ACTIVE'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tags text[] DEFAULT '{}'::text[] NOT NULL,
    tag_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    tag_bits bit(1024) DEFAULT '0'::bit(1024) NOT NULL,
    unknown_tags text[] DEFAULT '{}'::text[] NOT NULL,
    listed_at timestamp with time zone NOT NULL,
    company_key text NOT NULL,
    CONSTRAINT ck_jobs_company_not_blank CHECK ((btrim(company) <> ''::text)),
    CONSTRAINT ck_jobs_country_us CHECK ((country_code = 'US'::text)),
    CONSTRAINT ck_jobs_jd_text_not_blank CHECK ((btrim(jd_text) <> ''::text)),
    CONSTRAINT ck_jobs_job_url_http CHECK ((job_url ~* '^https?://\S+$'::text)),
    CONSTRAINT ck_jobs_salary_non_negative CHECK ((((salary_min IS NULL) OR (salary_min >= (0)::numeric)) AND ((salary_max IS NULL) OR (salary_max >= (0)::numeric)))),
    CONSTRAINT ck_jobs_salary_range CHECK (((salary_min IS NULL) OR (salary_max IS NULL) OR (salary_min <= salary_max))),
    CONSTRAINT ck_jobs_source_job_id_not_blank CHECK ((btrim(source_job_id) <> ''::text)),
    CONSTRAINT ck_jobs_source_not_blank CHECK ((btrim(source) <> ''::text)),
    CONSTRAINT ck_jobs_status CHECK ((status = ANY (ARRAY['ACTIVE'::text, 'CLOSED'::text, 'EXPIRED'::text]))),
    CONSTRAINT ck_jobs_tags_limit CHECK ((cardinality(tags) <= 100)),
    CONSTRAINT ck_jobs_title_not_blank CHECK ((btrim(title) <> ''::text)),
    CONSTRAINT ck_jobs_work_type_remote CHECK ((work_type = 'REMOTE'::text))
)
WITH (autovacuum_vacuum_scale_factor='0.02', autovacuum_vacuum_insert_scale_factor='0.02');
CREATE TABLE job_feed.tag_aliases (
    alias text NOT NULL,
    tag_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tag_aliases_alias_normalized CHECK (((alias = job_feed.tag_key(alias)) AND (length(alias) <= 60)))
);
CREATE TABLE job_feed.tags (
    id integer NOT NULL,
    code text NOT NULL,
    label text NOT NULL,
    weight text DEFAULT 'NORMAL'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_tags_code_normalized CHECK (((code = job_feed.tag_key(code)) AND (length(code) <= 60))),
    CONSTRAINT ck_tags_id_fits_bitmap CHECK (((id >= 1) AND (id <= 1023))),
    CONSTRAINT ck_tags_label_not_blank CHECK (((btrim(label) <> ''::text) AND (length(label) <= 80))),
    CONSTRAINT ck_tags_weight CHECK ((weight = ANY (ARRAY['NORMAL'::text, 'IMPORTANT'::text])))
);
ALTER TABLE job_feed.tags ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME job_feed.tags_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
ALTER TABLE ONLY job_feed.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY job_feed.tag_aliases
    ADD CONSTRAINT tag_aliases_pkey PRIMARY KEY (alias);
ALTER TABLE ONLY job_feed.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);
ALTER TABLE ONLY job_feed.jobs
    ADD CONSTRAINT uq_jobs_source_source_job_id UNIQUE (source, source_job_id);
ALTER TABLE ONLY job_feed.tags
    ADD CONSTRAINT uq_tags_code UNIQUE (code);
CREATE INDEX ix_jobs_active_company_key ON job_feed.jobs USING btree (company_key) WHERE (status = 'ACTIVE'::text);
CREATE INDEX ix_jobs_board ON job_feed.jobs USING btree (listed_at DESC, id DESC) INCLUDE (tag_bits, company_key) WHERE ((status = 'ACTIVE'::text) AND (country_code = 'US'::text) AND (work_type = 'REMOTE'::text));
CREATE INDEX ix_jobs_company_trgm ON job_feed.jobs USING gin (company public.gin_trgm_ops);
CREATE INDEX ix_jobs_status_posted_at ON job_feed.jobs USING btree (status, posted_at DESC);
CREATE INDEX ix_jobs_title_trgm ON job_feed.jobs USING gin (title public.gin_trgm_ops);
CREATE INDEX ix_jobs_unknown_tags ON job_feed.jobs USING gin (unknown_tags) WHERE (unknown_tags <> '{}'::text[]);
CREATE INDEX ix_jobs_updated_at ON job_feed.jobs USING btree (updated_at);
CREATE INDEX ix_tag_aliases_tag_id ON job_feed.tag_aliases USING btree (tag_id);
CREATE UNIQUE INDEX uq_tags_label ON job_feed.tags USING btree (lower(label));
CREATE TRIGGER trg_jobs_before_write BEFORE INSERT OR UPDATE ON job_feed.jobs FOR EACH ROW EXECUTE FUNCTION job_feed.jobs_before_write();
CREATE TRIGGER trg_tags_forbid_delete BEFORE DELETE ON job_feed.tags FOR EACH ROW EXECUTE FUNCTION job_feed.forbid_tag_delete();
CREATE TRIGGER trg_tags_touch_updated_at BEFORE UPDATE ON job_feed.tags FOR EACH ROW EXECUTE FUNCTION job_feed.touch_updated_at();
ALTER TABLE ONLY job_feed.tag_aliases
    ADD CONSTRAINT fk_tag_aliases_tag_id_tags FOREIGN KEY (tag_id) REFERENCES job_feed.tags(id);
\unrestrict apDHFCpIouLpbElhD9Bwr4AhvuAVgyY1Z34Z4whSU2WlHaSqAHJctZQbZx5adBe

-- ---------------------------------------------------------------- the platform's role (local copy)
-- Production: BidFlow creates this role and gives you its password. Same privileges as below.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jobfeed_writer') THEN
        CREATE ROLE jobfeed_writer LOGIN PASSWORD 'local-only-change-me';
    END IF;
END $$;
GRANT USAGE ON SCHEMA job_feed TO jobfeed_writer;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA job_feed TO jobfeed_writer;
GRANT SELECT ON job_feed.jobs, job_feed.tags, job_feed.tag_aliases TO jobfeed_writer;
GRANT INSERT (company, country_code, employment_type, jd_text, job_url, location_text, posted_at, salary_max, salary_min, salary_text, source, source_job_id, status, tags, title, verified_at, work_type) ON job_feed.jobs TO jobfeed_writer;
GRANT UPDATE (company, country_code, employment_type, jd_text, job_url, location_text, posted_at, salary_max, salary_min, salary_text, status, tags, title, verified_at, work_type) ON job_feed.jobs TO jobfeed_writer;
-- No DELETE, no TRUNCATE, nothing outside job_feed.

-- ---------------------------------------------------------------- tag catalog snapshot (2026-09-19)
-- In production read the live catalog (it changes); this snapshot is only for local tests.
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (1, 'ai', 'AI', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (2, 'genai', 'GenAI', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (3, 'ml', 'ML', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (4, 'data engineering', 'Data Engineering', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (5, 'data science', 'Data Science', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (6, 'data platform', 'Data Platform', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (7, 'backend', 'Backend', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (8, 'mlops', 'MLOps', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (9, 'android', 'Android', 'IMPORTANT', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (10, 'fullstack', 'Fullstack', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (11, 'frontend', 'Frontend', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (12, 'mobile', 'Mobile', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (13, 'ios', 'iOS', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (14, 'devops', 'DevOps', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (15, 'cloud', 'Cloud', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (16, 'python', 'Python', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (17, 'javascript', 'JavaScript', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (18, 'typescript', 'TypeScript', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (19, 'java', 'Java', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (20, 'go', 'Go', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (21, 'kotlin', 'Kotlin', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (22, 'swift', 'Swift', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (23, 'react', 'React', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (24, 'node.js', 'Node.js', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (25, 'aws', 'AWS', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (26, 'gcp', 'GCP', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (27, 'azure', 'Azure', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (28, 'docker', 'Docker', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (29, 'kubernetes', 'Kubernetes', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (30, 'sql', 'SQL', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (31, 'postgresql', 'PostgreSQL', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (32, 'llm', 'LLM', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (33, 'nlp', 'NLP', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (34, 'computer vision', 'Computer Vision', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (35, 'pytorch', 'PyTorch', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (36, 'tensorflow', 'TensorFlow', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (37, 'spark', 'Spark', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (38, 'airflow', 'Airflow', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (39, 'api design', 'api design', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (40, 'ci/cd', 'ci/cd', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (41, 'data governance', 'data governance', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (42, 'data modeling', 'data modeling', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (43, 'dbt', 'dbt', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (44, 'distributed systems', 'distributed systems', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (45, 'etl', 'etl', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (46, 'evaluation', 'evaluation', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (47, 'event-driven', 'event-driven', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (48, 'experimentation', 'experimentation', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (49, 'fastapi', 'fastapi', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (50, 'feature engineering', 'feature engineering', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (51, 'firebase', 'firebase', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (52, 'jetpack compose', 'jetpack compose', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (53, 'kafka', 'kafka', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (54, 'langchain', 'langchain', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (55, 'microservices', 'microservices', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (56, 'mlflow', 'mlflow', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (57, 'mobile architecture', 'mobile architecture', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (58, 'model monitoring', 'model monitoring', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (59, 'model training', 'model training', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (60, 'openai', 'openai', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (61, 'prompt engineering', 'prompt engineering', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (62, 'rag', 'rag', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (63, 'scikit-learn', 'scikit-learn', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (64, 'snowflake', 'snowflake', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (65, 'statistics', 'statistics', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (66, 'streaming', 'streaming', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tags (id, code, label, weight, is_active, created_at, updated_at) OVERRIDING SYSTEM VALUE VALUES (67, 'terraform', 'terraform', 'NORMAL', true, '2026-09-18 14:09:39.172445+00', '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ai engineer', 1, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ai_engineer', 1, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('artificial intelligence', 1, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('gen ai', 2, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('generative ai', 2, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('genai engineer', 2, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('genai_engineer', 2, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('machine learning', 3, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ml engineer', 3, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ml_engineer', 3, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('data engineer', 4, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('data_engineer', 4, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('data_scientist', 5, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('data scientist', 5, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('data_platform', 6, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('back-end', 7, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('backend_engineer', 7, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('backend engineer', 7, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('back end', 7, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('mlops', 8, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ml ops', 8, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('android_engineer', 9, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('android engineer', 9, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('full stack', 10, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('full-stack', 10, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('front end', 11, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('front-end', 11, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('js', 17, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('ts', 18, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('golang', 20, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('react.js', 23, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('reactjs', 23, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('node', 24, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('nodejs', 24, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('amazon web services', 25, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('google cloud', 26, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('k8s', 29, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('postgres', 31, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('llms', 32, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('large language models', 32, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('apache spark', 37, '2026-09-18 14:09:39.172445+00');
INSERT INTO job_feed.tag_aliases (alias, tag_id, created_at) VALUES ('apache airflow', 38, '2026-09-18 14:09:39.172445+00');
SELECT setval(pg_get_serial_sequence('job_feed.tags', 'id'), (SELECT max(id) FROM job_feed.tags));
