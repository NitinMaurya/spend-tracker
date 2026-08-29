"use client";

/**
 * The ledger's filters.
 *
 * Everything lives in the URL, exactly like the scope bar, so the page stays a
 * server component (the engine has already summed every figure before the HTML
 * exists) and any view of the ledger is shareable and back-button friendly.
 *
 * Changing a filter always resets the page offset. Landing on page 4 of a
 * different result set is the classic table bug and it is not worth inheriting.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Ledger } from "@/lib/api";
import { prettyCategory } from "@/lib/format";

const DIRECTIONS = [
  { id: "", label: "Everything" },
  { id: "in", label: "Money in" },
  { id: "out", label: "Money out" },
];

/** Plain words for the effect axis; the enum values are engine vocabulary. */
const FLOW_LABEL: Record<string, string> = {
  EARNED: "Earned", SPENT: "Spent", MOVED: "Moved between accounts",
  BORROWED: "Borrowed", REPAID: "Repaid debt", REFUNDED: "Refunded",
  UNKNOWN: "Unnamed", NEUTRAL: "Nets to zero",
};

const PILL =
  "inline-flex h-9 items-center rounded-full border border-line bg-surface pl-4 pr-2 text-[13px] font-semibold";

export function LedgerFilters({ facets }: { facets: Ledger["facets"] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const set = useCallback(
    (patch: Record<string, string>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      next.delete("offset");
      const query = next.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const direction = params.get("direction") ?? "";
  const account = params.get("account") ?? "";
  const type = params.get("type") ?? "";
  const flow = params.get("flow") ?? "";
  const active = Boolean(direction || account || type || flow || params.get("q"));

  return (
    <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-surface2 px-5 py-3.5">
      <div
        role="group"
        aria-label="Direction"
        className="inline-flex gap-1 rounded-full border border-line bg-surface p-1"
      >
        {DIRECTIONS.map((d) => {
          const on = d.id === direction;
          return (
            <button
              key={d.id || "all"}
              type="button"
              aria-pressed={on}
              onClick={() => set({ direction: d.id })}
              className={`rounded-full px-3.5 py-1 text-[12.5px] transition-colors ${
                on ? "bg-accent font-bold text-white" : "font-semibold text-ink2 hover:text-ink"
              }`}
            >
              {d.label}
            </button>
          );
        })}
      </div>

      <label className={PILL}>
        <span className="sr-only">Account</span>
        <select
          value={account}
          onChange={(e) => set({ account: e.target.value })}
          className="cursor-pointer appearance-none bg-transparent pr-6 font-semibold text-ink outline-none"
        >
          <option value="">All accounts</option>
          {facets.accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.card} · {a.txns}
            </option>
          ))}
        </select>
      </label>

      {/* Effect before type. "Show me only what I actually earned" is the
          question this ledger was getting wrong, so it gets its own control. */}
      <label className={PILL}>
        <span className="sr-only">Effect on net worth</span>
        <select
          value={flow}
          onChange={(e) => set({ flow: e.target.value })}
          className="cursor-pointer appearance-none bg-transparent pr-6 font-semibold text-ink outline-none"
        >
          <option value="">Any effect</option>
          {facets.flows.map((f) => (
            <option key={f.flow} value={f.flow}>
              {FLOW_LABEL[f.flow] ?? prettyCategory(f.flow)} · {f.txns}
            </option>
          ))}
        </select>
      </label>

      <label className={PILL}>
        <span className="sr-only">Transaction type</span>
        <select
          value={type}
          onChange={(e) => set({ type: e.target.value })}
          className="cursor-pointer appearance-none bg-transparent pr-6 font-semibold text-ink outline-none"
        >
          <option value="">All types</option>
          {/* Straight from the engine's own facet counts, so a type that only
              starts existing tomorrow appears here without a code change. */}
          {facets.types.map((t) => (
            <option key={t.txn_type} value={t.txn_type}>
              {prettyCategory(t.txn_type)} · {t.txns}
            </option>
          ))}
        </select>
      </label>

      <Search onCommit={(q) => set({ q })} />

      {active ? (
        <button
          type="button"
          onClick={() => set({ direction: "", account: "", type: "", flow: "", q: "" })}
          className="inline-flex h-9 items-center rounded-full bg-accentSoft px-3.5 text-[12.5px] font-bold text-accentInk"
        >
          Clear filters ×
        </button>
      ) : null}
    </div>
  );
}

/** Typing should not fire a request per keystroke, nor swallow the last one. */
function Search({ onCommit }: { onCommit: (q: string) => void }) {
  const params = useSearchParams();
  const initial = params.get("q") ?? "";
  const [value, setValue] = useState(initial);
  const committed = useRef(initial);

  // The URL is the source of truth: a Clear elsewhere must empty this box too.
  useEffect(() => {
    committed.current = initial;
    setValue(initial);
  }, [initial]);

  useEffect(() => {
    if (value === committed.current) return;
    const id = window.setTimeout(() => {
      committed.current = value;
      onCommit(value);
    }, 300);
    return () => window.clearTimeout(id);
  }, [value, onCommit]);

  return (
    <label className="inline-flex h-9 min-w-[13rem] flex-grow items-center rounded-full border border-line bg-surface px-4 text-[13px] sm:flex-grow-0">
      <span className="sr-only">Search the ledger</span>
      <input
        type="search"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search merchant or statement line…"
        className="w-full bg-transparent font-medium text-ink outline-none placeholder:text-ink3"
      />
    </label>
  );
}
