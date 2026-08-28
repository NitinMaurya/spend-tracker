/**
 * Category detail, as a side sheet.
 *
 * A category total only means something if you can open it and see what is inside.
 * Grouped by month, because that is how the rest of the app is organised (D-038),
 * and each charge shows the card it was paid on and stays editable — you often
 * spot a wrong category precisely while reading the list.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, type CategoryDetail, type Period } from "@/lib/api";
import { formatAbs } from "@/lib/money";
import { CategoryTag } from "@/components/category-tag";
import { prettyCategory } from "@/lib/format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthName(m: string) {
  const [y, mo] = m.split("-");
  return `${MONTHS[Number(mo) - 1]} ${y}`;
}

export function CategorySheet({
  category, period, onClose,
}: {
  category: string | null;
  period?: Period;
  onClose: () => void;
}) {
  const [data, setData] = useState<CategoryDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!category) return;
    setData(null);
    setError(null);
    try {
      setData(await api.categoryDetail(category, period));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [category, period]);

  useEffect(() => { void load(); }, [load]);

  // Escape closes; the sheet is a transient view, never a place you get stuck.
  useEffect(() => {
    if (!category) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [category, onClose]);

  // Lock the page behind the sheet so the background does not scroll under it.
  useEffect(() => {
    if (!category) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [category]);

  if (!category) return null;

  // Rendered into document.body via a portal. `position: fixed` is measured against
  // the nearest TRANSFORMED ancestor rather than the viewport, and the category bars
  // sit inside a `.rise` section whose entrance animation uses transform -- so
  // without the portal the sheet was trapped inside that card instead of covering
  // the window.
  return createPortal((
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="flex-1 bg-black/25 backdrop-blur-[1px]"
      />
      <aside className="slide-in flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-line bg-bg shadow-lift">
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-line bg-bg/90 px-6 py-5 backdrop-blur">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">
              Category
            </p>
            <h2 className="display mt-0.5 text-xl font-semibold">
              {prettyCategory(category)}
            </h2>
            {data && (
              <p className="tnum mt-1 text-sm text-ink2">
                {formatAbs(data.total)} · {data.count} charge{data.count === 1 ? "" : "s"}
                {period?.label && period.label !== "All time" && ` · ${period.label}`}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink2 hover:text-ink"
          >
            Close
          </button>
        </header>

        {error && <p className="px-6 py-4 text-sm" style={{ color: "var(--bad)" }}>{error}</p>}
        {!data && !error && <p className="px-6 py-6 text-sm text-ink3">Loading…</p>}

        {data && data.count === 0 && (
          <p className="px-6 py-6 text-sm text-ink2">
            Nothing in this category for the selected period.
          </p>
        )}

        {data && data.merchants.length > 1 && (
          <section className="border-b border-line px-6 py-4">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">
              Where it goes
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {data.merchants.slice(0, 8).map((m) => (
                <li key={m.merchant}
                    className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs">
                  {m.merchant}
                  <span className="tnum ml-1.5 text-ink3">{formatAbs(m.spend)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {data?.months.map((m) => (
          <section key={m.month} className="border-b border-line last:border-0">
            <div className="flex items-baseline justify-between gap-3 bg-surface2 px-6 py-2.5">
              <span className="text-sm font-semibold">
                {monthName(m.month)}
                <span className="tnum ml-1.5 font-normal text-ink3">({m.count})</span>
              </span>
              <span className="tnum text-sm text-ink2">{formatAbs(m.spend)}</span>
            </div>
            <ul>
              {m.charges.map((ch) => (
                <li key={ch.txn_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line2 px-6 py-2.5 last:border-0">
                  <span className="tnum w-20 shrink-0 text-xs text-ink3">
                    {ch.txn_date.slice(5)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{ch.merchant ?? "—"}</span>
                    {ch.raw_description && ch.raw_description !== ch.merchant && (
                      <span className="mono block truncate text-[11px] text-ink3">
                        {ch.raw_description}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-[11px] text-ink3">{ch.card}</span>
                  <CategoryTag txnId={ch.txn_id} category={ch.category}
                               merchant={ch.merchant} onChanged={() => void load()} />
                  <span className="tnum shrink-0 text-sm font-medium">
                    {formatAbs(ch.amount)}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </aside>
    </div>
  ), document.body);
}
