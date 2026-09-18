import { useEffect, useState } from "react";
import { ApiError, getStats, listSources } from "../api/client";
import type { SourceHealth, StatsOut } from "../types";
import { timeAgo } from "../utils";

function statusLabel(health: SourceHealth): string {
  if (!health.enabled) return "disabled";
  if (health.last_status === null) return "never run";
  if (health.last_status === "failed" && health.consecutive_failures >= 3) return "down";
  if (health.last_status === "failed" || health.last_status === "partial") return "degraded";
  return "healthy";
}

function statusClass(label: string): string {
  switch (label) {
    case "healthy":
      return "status-healthy";
    case "degraded":
      return "status-degraded";
    case "down":
      return "status-down";
    default:
      return "status-neutral";
  }
}

export function SourceStatusPage() {
  const [sources, setSources] = useState<SourceHealth[] | null>(null);
  const [stats, setStats] = useState<StatsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    setError(null);
    Promise.all([listSources(), getStats()])
      .then(([sourcesResp, statsResp]) => {
        setSources(sourcesResp);
        setStats(statsResp);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : String(err)));
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div>
      {error && <p className="error-banner">Couldn't load source status: {error}</p>}

      {stats && (
        <div className="stats-row">
          <div className="stat-tile">
            <div className="stat-value">{stats.total_active_jobs}</div>
            <div className="stat-label">Total active jobs</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{stats.jobs_added_today}</div>
            <div className="stat-label">Added today</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{stats.jobs_added_last_24h}</div>
            <div className="stat-label">Added last 24h</div>
          </div>
          <div className="stat-tile">
            <div className="stat-value">{timeAgo(stats.last_fetch_at)}</div>
            <div className="stat-label">Last fetch</div>
          </div>
        </div>
      )}

      {sources && (
        <table className="source-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Last Fetch</th>
              <th>Last Successful Fetch</th>
              <th>Jobs Fetched</th>
              <th>New Jobs</th>
              <th>Updated Jobs</th>
              <th>Errors</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => {
              const label = statusLabel(s);
              return (
                <tr key={s.source}>
                  <td>{s.source}</td>
                  <td>{timeAgo(s.last_fetch_at)}</td>
                  <td>{timeAgo(s.last_successful_fetch_at)}</td>
                  <td>{s.jobs_fetched_last_run}</td>
                  <td>{s.jobs_new_last_run}</td>
                  <td>{s.jobs_updated_last_run}</td>
                  <td className="errors-cell">{s.errors_last_run ?? "-"}</td>
                  <td>
                    <span className={`status-pill ${statusClass(label)}`}>{label}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
