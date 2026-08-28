"use client";

/**
 * ONE scope control for the whole app.
 *
 * The old PeriodBar rendered on 2 of 7 routes as thirteen pills with amounts
 * baked into them — a data table wearing the costume of a control — and the
 * selection died the moment you clicked a nav link.
 *
 * The window still lives in the URL, so pages stay server components (figures
 * arrive already scoped) and any view is shareable and back-button friendly.
 */

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import type { CalYear } from "@/lib/api";
import { formatAbs } from "@/lib/money";
import { fullMonth, shortMonth } from "@/lib/format";
import { modeOf, periodForMonth, periodForYear, scopeQuery, type ScopeMode } from "./scope";

const MODES: { id: ScopeMode; label: string }[] = [
  { id: "month", label: "Month" },
  { id: "year", label: "Year" },
  { id: "all", label: "All time" },
];

export function ScopeBar({
  years, note, label: resolved,
}: { years: CalYear[]; note?: string; label?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // The page resolves the window (the default is the current year), so its
  // label wins. Falling back to the URL alone made the control lie.
  const label = params.get("label") ?? resolved ?? "All time";
  const mode = modeOf(label);

  // The calendar arrives newest-first, so indexing from the end picked the
  // OLDEST year and month. Sort explicitly rather than trust the order.
  const months = years.flatMap((y) => y.months).slice()
    .sort((a, b) => (a.month < b.month ? -1 : 1));
  const sortedYears = years.slice().sort((a, b) => (a.year < b.year ? -1 : 1));
  const newestMonth = months.length ? months[months.length - 1].month : null;
  const newestYear = sortedYears.length ? sortedYears[sortedYears.length - 1].year : null;

  const go = (q: string) => router.push(`${pathname}${q}`, { scroll: false });

  const switchMode = (m: ScopeMode) => {
    if (m === mode) return;
    if (m === "all") return go("");
    if (m === "year") {
      const y = /^\d{4}/.exec(label)?.[0] ?? newestYear;
      if (y) go(scopeQuery(periodForYear(y)));
      return;
    }
    const inYear = months.filter((x) => x.month.startsWith(/^\d{4}/.exec(label)?.[0] ?? ""));
    const pick = inYear.length ? inYear[inYear.length - 1].month : newestMonth;
    if (pick) go(scopeQuery(periodForMonth(pick)));
  };

  if (!years.length) return null;

  // The strip is an emphasis form, not a control: twelve months of context with
  // the scoped one in the accent. It replaces twelve buttons.
  const stripYear =
    sortedYears.find((y) => label.startsWith(y.year)) ?? sortedYears[sortedYears.length - 1];
  const peak = stripYear.months.reduce((n, m) => Math.max(n, Math.abs(m.spend.minor)), 1);

  return (
    <div className="border-b border-hair bg-surface shadow-card">
      <div className="mx-auto flex max-w-[70rem] flex-wrap items-center gap-3 px-6 py-3">
        <div
          role="group"
          aria-label="Period"
          className="inline-flex gap-0.5 rounded-[8px] border border-line bg-surface2 p-[3px]"
        >
          {MODES.map((m) => {
            const on = m.id === mode;
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => switchMode(m.id)}
                aria-pressed={on}
                className={`rounded-control px-3.5 py-[5px] text-[13px] transition-colors ${
                  on ? "bg-surface font-semibold text-ink shadow-card" : "font-medium text-ink2 hover:text-ink"
                }`}
              >
                {m.label}
              </button>
            );
          })}
        </div>

        {mode === "month" ? (
          <label className="inline-flex h-8 items-center rounded-[8px] border border-line bg-surface pl-3 pr-1 text-[13px] font-semibold">
            <span className="sr-only">Month</span>
            <select
              value={label}
              onChange={(e) => go(scopeQuery(periodForMonth(e.target.value)))}
              className="cursor-pointer appearance-none bg-transparent pr-6 font-semibold text-ink outline-none"
            >
              {months
                .slice()
                .reverse()
                .map((m) => (
                  <option key={m.month} value={m.month}>
                    {fullMonth(m.month)}
                  </option>
                ))}
            </select>
          </label>
        ) : null}

        {mode === "year" ? (
          <label className="inline-flex h-8 items-center rounded-[8px] border border-line bg-surface pl-3 pr-1 text-[13px] font-semibold">
            <span className="sr-only">Year</span>
            <select
              value={/^\d{4}$/.test(label) ? label : (newestYear ?? "")}
              onChange={(e) => go(scopeQuery(periodForYear(e.target.value)))}
              className="cursor-pointer appearance-none bg-transparent pr-6 font-semibold text-ink outline-none"
            >
              {sortedYears
                .slice()
                .reverse()
                .map((y) => (
                  <option key={y.year} value={y.year}>
                    {y.year}
                  </option>
                ))}
            </select>
          </label>
        ) : null}

        {note ? <span className="text-xs text-ink3">{note}</span> : null}

        <div className="ml-auto hidden items-end gap-[3px] md:flex" aria-hidden>
          {stripYear.months.slice().sort((a, b) => (a.month < b.month ? -1 : 1)).map((m) => {
            const on = label === m.month;
            const h = Math.max(4, Math.round((Math.abs(m.spend.minor) / peak) * 26));
            return (
              <span
                key={m.month}
                title={`${shortMonth(m.month)} · ${formatAbs(m.spend)}`}
                className={`w-[13px] rounded-t-[2px] ${on ? "bg-accent" : "bg-mute opacity-[.34]"}`}
                style={{ height: `${h}px` }}
              />
            );
          })}
        </div>
        <span className="mono hidden text-[11px] text-ink3 lg:inline">
          {months.length} month{months.length === 1 ? "" : "s"} on record
        </span>
      </div>
    </div>
  );
}
