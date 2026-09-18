import type { JobCard as JobCardType } from "../types";
import { formatSalary, timeAgo } from "../utils";
import "./JobCard.css";

interface Props {
  job: JobCardType;
  onViewJd: (id: number) => void;
}

export function JobCard({ job, onViewJd }: Props) {
  const salary = formatSalary(job.salary_min, job.salary_max, job.currency, job.salary_period);
  const applyUrl = job.direct_apply_url ?? job.source_url;

  return (
    <div className="job-card">
      <div className="job-card-header">
        <h3>{job.job_title}</h3>
        <div className="job-card-subtitle">
          {job.company_name}
          {job.industry ? ` | ${job.industry}` : ""}
        </div>
      </div>

      <div className="job-card-badges">
        {job.level && <span className="badge badge-level">{job.level}</span>}
        {job.role_category && <span className="badge badge-role">{job.role_category}</span>}
        <span className="badge badge-source">{job.source}</span>
      </div>

      {job.main_stack.length > 0 && (
        <div className="job-card-stack">{job.main_stack.join(" | ")}</div>
      )}

      <div className="job-card-facts">
        {salary && <div>{salary}</div>}
        {job.required_years_experience != null && <div>{job.required_years_experience}+ years</div>}
        <div>
          {job.remote_scope ?? "Remote"}
          {job.eligible_states.length > 0 ? ` (${job.eligible_states.join(", ").toUpperCase()})` : ""}
        </div>
        <div>Posted {timeAgo(job.posted_at)}</div>
        <div>Updated {timeAgo(job.last_seen_at)}</div>
      </div>

      <div className="job-card-actions">
        <button type="button" onClick={() => onViewJd(job.id)}>
          View JD
        </button>
        <a href={applyUrl} target="_blank" rel="noreferrer" className="apply-button">
          Apply
        </a>
      </div>
    </div>
  );
}
