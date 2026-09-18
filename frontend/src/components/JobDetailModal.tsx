import { useEffect, useState } from "react";
import { getJob } from "../api/client";
import type { JobDetail } from "../types";
import { formatSalary, timeAgo } from "../utils";
import "./JobDetailModal.css";

interface Props {
  jobId: number;
  onClose: () => void;
}

export function JobDetailModal({ jobId, onClose }: Props) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setJob(null);
    setError(null);
    getJob(jobId)
      .then((data) => {
        if (!cancelled) setJob(data);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const salary = job ? formatSalary(job.salary_min, job.salary_max, job.currency, job.salary_period) : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="modal-close" onClick={onClose}>
          &times;
        </button>

        {error && <p className="modal-error">Failed to load job: {error}</p>}
        {!job && !error && <p>Loading...</p>}

        {job && (
          <>
            <h2>{job.job_title}</h2>
            <p className="modal-subtitle">
              {job.company_name} | {job.source} | {job.level ?? "n/a"} | {job.role_category ?? "n/a"}
            </p>

            <div className="modal-facts">
              {salary && <span>{salary}</span>}
              {job.original_location && <span>{job.original_location}</span>}
              <span>Posted {timeAgo(job.posted_at)}</span>
              <span>Updated {timeAgo(job.last_seen_at)}</span>
              {job.requires_active_clearance && <span className="clearance-flag">Requires active clearance</span>}
            </div>

            {job.full_technology_stack.length > 0 && (
              <p>
                <strong>Tech stack:</strong> {job.full_technology_stack.join(", ")}
              </p>
            )}
            {job.matched_keywords.length > 0 && (
              <p>
                <strong>Matched keywords:</strong> {job.matched_keywords.join(", ")}
              </p>
            )}

            <h3>Job Description</h3>
            <pre className="modal-jd">{job.cleaned_job_description || "No description available."}</pre>

            <div className="modal-actions">
              <a href={job.source_url} target="_blank" rel="noreferrer">
                Original posting
              </a>
              <a
                href={job.direct_apply_url ?? job.source_url}
                target="_blank"
                rel="noreferrer"
                className="apply-button"
              >
                Apply
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
