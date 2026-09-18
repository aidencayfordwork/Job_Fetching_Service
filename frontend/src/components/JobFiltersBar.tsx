import type { JobFilters } from "../types";
import "./JobFiltersBar.css";

interface Props {
  filters: JobFilters;
  onChange: (next: JobFilters) => void;
}

const LEVELS = ["MID", "SENIOR", "STAFF", "LEAD"];

export function JobFiltersBar({ filters, onChange }: Props) {
  const set = (patch: Partial<JobFilters>) => onChange({ ...filters, ...patch, page: 1 });

  return (
    <div className="filters-bar">
      <input
        type="text"
        placeholder="Search title/company..."
        value={filters.q ?? ""}
        onChange={(e) => set({ q: e.target.value || undefined })}
      />

      <select value={filters.level ?? ""} onChange={(e) => set({ level: e.target.value || undefined })}>
        <option value="">All levels</option>
        {LEVELS.map((l) => (
          <option key={l} value={l}>
            {l}
          </option>
        ))}
      </select>

      <input
        type="text"
        placeholder="Role category"
        value={filters.role_category ?? ""}
        onChange={(e) => set({ role_category: e.target.value || undefined })}
      />

      <input
        type="text"
        placeholder="Technology"
        value={filters.technology ?? ""}
        onChange={(e) => set({ technology: e.target.value || undefined })}
      />

      <input
        type="text"
        placeholder="Company"
        value={filters.company ?? ""}
        onChange={(e) => set({ company: e.target.value || undefined })}
      />

      <input
        type="text"
        placeholder="Source"
        value={filters.source ?? ""}
        onChange={(e) => set({ source: e.target.value || undefined })}
      />

      <input
        type="number"
        placeholder="Min salary"
        value={filters.salary_min ?? ""}
        onChange={(e) => set({ salary_min: e.target.value ? Number(e.target.value) : undefined })}
      />

      <input
        type="number"
        placeholder="Max salary"
        value={filters.salary_max ?? ""}
        onChange={(e) => set({ salary_max: e.target.value ? Number(e.target.value) : undefined })}
      />

      <button
        type="button"
        onClick={() =>
          onChange({ page: 1, page_size: filters.page_size })
        }
      >
        Clear filters
      </button>
    </div>
  );
}
