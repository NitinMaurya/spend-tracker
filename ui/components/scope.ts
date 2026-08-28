import type { CalYear, Period } from "@/lib/api";

export type ScopeMode = "month" | "year" | "all";

export function modeOf(label: string): ScopeMode {
  if (/^\d{4}-\d{2}$/.test(label)) return "month";
  if (/^\d{4}$/.test(label)) return "year";
  return "all";
}

export function monthEnd(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}

export function periodForMonth(month: string): Period {
  return { label: month, from: `${month}-01`, to: monthEnd(month) };
}

export function periodForYear(year: string): Period {
  return { label: year, from: `${year}-01-01`, to: `${year}-12-31` };
}

/** Every month that holds data, newest first. */
export function allMonths(years: CalYear[]): { month: string; spend: unknown }[] {
  return years.flatMap((y) => y.months).slice().reverse();
}

export function scopeQuery(p: Period): string {
  const s = new URLSearchParams();
  if (p.from) s.set("from", p.from);
  if (p.to) s.set("to", p.to);
  if (p.label !== "All time") s.set("label", p.label);
  const out = s.toString();
  return out ? `?${out}` : "";
}
