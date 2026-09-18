export interface JobCard {
  id: number;
  company_name: string;
  job_title: string;
  source: string;
  level: string | null;
  role_category: string | null;
  main_stack: string[];
  industry: string | null;
  required_years_experience: number | null;
  salary_min: number | null;
  salary_max: number | null;
  currency: string | null;
  salary_period: string | null;
  remote_scope: string | null;
  eligible_states: string[];
  posted_at: string | null;
  last_seen_at: string;
  source_url: string;
  direct_apply_url: string | null;
}

export interface JobDetail extends JobCard {
  source_job_id: string;
  full_technology_stack: string[];
  employment_type: string | null;
  is_remote: boolean | null;
  us_eligible: boolean | null;
  excluded_states: string[];
  timezone_requirement: string | null;
  original_location: string | null;
  original_salary_text: string | null;
  source_updated_at: string | null;
  first_seen_at: string;
  cleaned_job_description: string | null;
  responsibilities: string[];
  required_skills: string[];
  preferred_skills: string[];
  matched_keywords: string[];
  requires_active_clearance: boolean;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface JobListResponse {
  items: JobCard[];
  total: number;
  page: number;
  page_size: number;
}

export interface SourceHealth {
  source: string;
  enabled: boolean;
  last_fetch_at: string | null;
  last_successful_fetch_at: string | null;
  last_status: string | null;
  consecutive_failures: number;
  jobs_fetched_last_run: number;
  jobs_new_last_run: number;
  jobs_updated_last_run: number;
  errors_last_run: string | null;
}

export interface StatsOut {
  total_active_jobs: number;
  jobs_added_today: number;
  jobs_added_last_24h: number;
  last_fetch_at: string | null;
}

export interface JobFilters {
  q?: string;
  level?: string;
  role_category?: string;
  technology?: string;
  company?: string;
  salary_min?: number;
  salary_max?: number;
  source?: string;
  page?: number;
  page_size?: number;
}
