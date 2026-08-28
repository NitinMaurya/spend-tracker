/**
 * Year → month navigation. Finances are reviewed by month and by year, so that is
 * the navigation, not an ad-hoc date range.
 *
 * The window lives in the URL, which keeps pages as server components (figures
 * arrive already scoped) and makes any view shareable and back-button friendly.
 */
"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { CalYear } from "@/lib/api";
import { formatAbs } from "@/lib/money";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthEnd(month: string) {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
}

export function PeriodBar({ years }: { years: CalYear[] }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const active = params.get("label") ?? "All time";

  // Which year's months to show: the one containing the selection, else the newest.
  const selectedYear = years.find((y) => active.startsWith(y.year)) ?? years[0];

  const href = (p: { from?: string; to?: string; label: string }) => {
    const s = new URLSearchParams();
    if (p.from) s.set("from", p.from);
    if (p.to) s.set("to", p.to);
    s.set("label", p.label);
    return `${pathname}?${s.toString()}`;
  };

  const pill = (on: boolean) =>
    `rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
      on ? "bg-accentSoft text-accentInk" : "border border-line bg-card text-ink2 hover:text-ink"
    }`;

  if (!years.length) return null;

  return (
    <div className="mb-7 flex flex-col gap-2.5">
      {/* Years + all-time */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">
          Year
        </span>
        <Link href={pathname} className={pill(active === "All time")}>All time</Link>
        {years.map((y) => (
          <Link
            key={y.year}
            href={href({ label: y.year, from: `${y.year}-01-01`, to: `${y.year}-12-31` })}
            className={pill(active === y.year)}
          >
            {y.year}
            <span className="ml-1.5 font-normal opacity-70">{formatAbs(y.spend)}</span>
          </Link>
        ))}
      </div>

      {/* Months of the year in view */}
      {selectedYear && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">
            Month
          </span>
          {selectedYear.months.map((m) => {
            const on = active === m.month;
            const name = MONTH_NAMES[Number(m.month.split("-")[1]) - 1];
            return (
              <Link
                key={m.month}
                href={href({ label: m.month, from: `${m.month}-01`, to: monthEnd(m.month) })}
                className={pill(on)}
                title={`${m.txns} transactions`}
              >
                {name}
                <span className="tnum ml-1.5 font-normal opacity-70">{formatAbs(m.spend)}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
