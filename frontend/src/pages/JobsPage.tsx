import { useEffect, useState } from "react";
import { ApiError, listJobs } from "../api/client";
import { JobCard } from "../components/JobCard";
import { JobDetailModal } from "../components/JobDetailModal";
import { JobFiltersBar } from "../components/JobFiltersBar";
import type { JobFilters, JobListResponse } from "../types";

const PAGE_SIZE = 20;

export function JobsPage() {
  const [filters, setFilters] = useState<JobFilters>({ page: 1, page_size: PAGE_SIZE });
  const [data, setData] = useState<JobListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [viewingJobId, setViewingJobId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listJobs(filters)
      .then((resp) => {
        if (!cancelled) setData(resp);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  const page = filters.page ?? 1;
  const totalPages = data ? Math.max(1, Math.ceil(data.total / (data.page_size || PAGE_SIZE))) : 1;

  return (
    <div>
      <JobFiltersBar filters={filters} onChange={setFilters} />

      {error && (
        <p className="error-banner">
          Couldn't load jobs: {error}. Check the API base URL and key above.
        </p>
      )}

      {loading && <p>Loading...</p>}

      {data && !loading && (
        <>
          <p className="results-count">{data.total} job(s) found</p>
          <div className="job-grid">
            {data.items.map((job) => (
              <JobCard key={job.id} job={job} onViewJd={setViewingJobId} />
            ))}
          </div>

          {data.items.length === 0 && <p>No jobs match these filters.</p>}

          <div className="pagination">
            <button type="button" disabled={page <= 1} onClick={() => setFilters({ ...filters, page: page - 1 })}>
              Previous
            </button>
            <span>
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setFilters({ ...filters, page: page + 1 })}
            >
              Next
            </button>
          </div>
        </>
      )}

      {viewingJobId !== null && (
        <JobDetailModal jobId={viewingJobId} onClose={() => setViewingJobId(null)} />
      )}
    </div>
  );
}
