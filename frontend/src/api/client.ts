import type { JobDetail, JobFilters, JobListResponse, SourceHealth, StatsOut } from "../types";

const BASE_URL_KEY = "job_fetching_service.base_url";
const API_KEY_KEY = "job_fetching_service.api_key";

export function getBaseUrl(): string {
  return localStorage.getItem(BASE_URL_KEY) ?? "http://localhost:8000";
}

export function setBaseUrl(value: string): void {
  localStorage.setItem(BASE_URL_KEY, value);
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_KEY) ?? "";
}

export function setApiKey(value: string): void {
  localStorage.setItem(API_KEY_KEY, value);
}

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, getBaseUrl());
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const resp = await fetch(url.toString(), {
    headers: { "X-API-Key": getApiKey() },
  });

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    throw new ApiError(resp.status, `${resp.status} ${resp.statusText}: ${body}`.trim());
  }

  return resp.json() as Promise<T>;
}

export function listJobs(filters: JobFilters): Promise<JobListResponse> {
  return request<JobListResponse>("/jobs", { ...filters });
}

export function getJob(id: number): Promise<JobDetail> {
  return request<JobDetail>(`/jobs/${id}`);
}

export function listSources(): Promise<SourceHealth[]> {
  return request<SourceHealth[]>("/sources");
}

export function getStats(): Promise<StatsOut> {
  return request<StatsOut>("/stats");
}

export { ApiError };
