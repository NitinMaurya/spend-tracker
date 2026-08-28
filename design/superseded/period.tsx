/**
 * Period picker. Every figure on a screen is scoped by the same window, and the
 * scoping happens in SQL — the client never slices money itself (D-029).
 */
"use client";

import type { Period } from "@/lib/api";

/** Built from the data's own range, so no option is ever empty. */
export function periodsFor(months: string[]): Period[] {
  const out: Period[] = [{ label: "All time" }];
  if (!months.length) return out;
  const [newest] = months;                       // months arrive newest-first
  const [y, m] = newest.split("-").map(Number);
  const end = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);

  const back = (n: number) => {
    const d = new Date(Date.UTC(y, m - n, 1));
    return d.toISOString().slice(0, 10);
  };
  out.push({ label: "This month", from: `${newest}-01`, to: end });
  if (months.length >= 3) out.push({ label: "Last 3 months", from: back(3), to: end });
  if (months.length >= 6) out.push({ label: "Last 6 months", from: back(6), to: end });
  return out;
}

export function PeriodPicker({
  periods, value, onChange, months,
}: {
  periods: Period[];
  value: Period;
  onChange: (p: Period) => void;
  months?: string[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {periods.map((p) => {
        const active = p.label === value.label;
        return (
          <button
            key={p.label}
            type="button"
            onClick={() => onChange(p)}
            aria-pressed={active}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              active
                ? "bg-accentSoft text-accentInk"
                : "border border-line bg-card text-ink2 hover:text-ink"
            }`}
          >
            {p.label}
          </button>
        );
      })}
      {months && months.length > 0 && (
        <select
          value={value.from && value.label.startsWith("20") ? value.label : ""}
          onChange={(e) => {
            const m = e.target.value;
            if (!m) return;
            const [y, mo] = m.split("-").map(Number);
            onChange({
              label: m,
              from: `${m}-01`,
              to: new Date(Date.UTC(y, mo, 0)).toISOString().slice(0, 10),
            });
          }}
          className="rounded-lg border border-line bg-card px-2.5 py-1.5 text-xs text-ink2"
          aria-label="Jump to a specific month"
        >
          <option value="">Pick a month…</option>
          {months.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      )}
    </div>
  );
}
