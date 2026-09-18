export function timeAgo(iso: string | null): string {
  if (!iso) return "unknown";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSeconds = Math.max(0, Math.floor((now - then) / 1000));

  if (diffSeconds < 60) return "just now";
  const minutes = Math.floor(diffSeconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}

export function formatSalary(
  min: number | null,
  max: number | null,
  currency: string | null,
  period: string | null,
): string | null {
  if (min == null && max == null) return null;

  const fmt = (n: number) => {
    if (n >= 1000) return `${Math.round(n / 1000)}K`;
    return String(n);
  };

  const symbol = currency === "USD" ? "$" : currency === "EUR" ? "€" : currency === "GBP" ? "£" : "";
  const periodSuffix = period === "hour" ? "/hr" : period === "month" ? "/mo" : "";

  if (min != null && max != null) return `${symbol}${fmt(min)}-${symbol}${fmt(max)}${periodSuffix}`;
  if (min != null) return `${symbol}${fmt(min)}+${periodSuffix}`;
  return `up to ${symbol}${fmt(max!)}${periodSuffix}`;
}
