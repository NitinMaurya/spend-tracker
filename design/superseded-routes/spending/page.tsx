"use client";

/**
 * Spending — "where does my money actually go".
 *
 * Every figure on this screen arrives already computed by the engine (D-029).
 * Nothing here sums, averages, or divides money: TypeScript only formats Money
 * via formatAbs/formatMoney, and filters strings. Ordering is the API's.
 */

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PeriodBar } from "@/components/period-bar";
import { CategoryTag } from "@/components/category-tag";
import { useCategorySheet } from "@/components/category-sheet-provider";
import {
  api,
  ApiDown,
  type ByCategory,
  type LargestRow,
  type MerchantRow,
  type Trend,
  type Txn,
  type CalYear,
  type Period,
  defaultPeriod,
} from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import { CategoryBars, TrendArea, prettyCategory, monthLabel, seriesColor } from "@/components/charts";
import { Card, Chip, Empty, H1, H2, Table } from "@/components/ui";

type Data = {
  byCategory: ByCategory;
  merchants: MerchantRow[];
  largest: LargestRow[];
  trend: Trend;
  txns: Txn[];
};

type Load =
  | { phase: "loading" }
  | { phase: "down"; message: string }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: Data };

function dayLabel(d: string): string {
  const [y, m, day] = d.split("-").map(Number);
  if (!y || !m || !day) return d;
  return new Date(y, m - 1, day).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
  });
}

function periodFromUrl(sp: URLSearchParams, defaultYear: string | null): Period {
  // No window in the URL -> open on the current calendar year (D-038).
  if (!sp.get("from") && !sp.get("to") && !sp.get("label")) {
    return defaultPeriod(defaultYear);
  }
  return {
    from: sp.get("from") ?? undefined,
    to: sp.get("to") ?? undefined,
    label: sp.get("label") ?? "All time",
  };
}

function SpendingInner() {
  const [load, setLoad] = useState<Load>({ phase: "loading" });
  // Money moving between your own accounts is not spending (D-007). Off by default.
  const [showRepayments, setShowRepayments] = useState(false);
  const search = useSearchParams();
  const [calendar, setCalendar] =
    useState<{ years: CalYear[]; default_year: string | null } | null>(null);
  const period = periodFromUrl(new URLSearchParams(search.toString()),
                               calendar?.default_year ?? null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [byCategory, merchants, largest, trend, cal, txns] = await Promise.all([
          api.byCategory(period),
          api.merchants(12, period),
          api.largest(10, period),
          api.trend(),
          api.calendar(),
          api.transactionsIn(period, { limit: 500, include_repayments: String(showRepayments) }),
        ]);
        if (alive) { setCalendar(cal); setLoad({ phase: "ready", data: { byCategory, merchants, largest, trend, txns } }); }
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiDown) setLoad({ phase: "down", message: err.message });
        else setLoad({ phase: "error", message: err instanceof Error ? err.message : String(err) });
      }
    })();
    return () => {
      alive = false;
    };
  }, [showRepayments, period.from, period.to, calendar?.default_year]);

  if (load.phase === "loading") return <Skeleton />;
  if (load.phase === "down") return <ApiDownCard />;
  if (load.phase === "error") return <FailureCard message={load.message} />;
  return (
    <>
      {calendar && <PeriodBar years={calendar.years} />}
      <Spending
      data={load.data}
      showRepayments={showRepayments}
      onToggleRepayments={setShowRepayments}
      />
    </>
  );
}

/* ── the screen ─────────────────────────────────────────────────────────── */

function Spending({
  data,
  showRepayments,
  onToggleRepayments,
}: {
  data: Data;
  showRepayments: boolean;
  onToggleRepayments: (v: boolean) => void;
}) {
  const { byCategory, merchants, largest, trend, txns } = data;
  const sheet = useCategorySheet();

  const months = trend.months.length;
  const points = trend.months.map((m) => ({ month: m.month, value: m.spend }));
  const period =
    months === 0
      ? "no statements yet"
      : months === 1
        ? monthLabel(trend.months[0].month)
        : `${monthLabel(trend.months[0].month)} – ${monthLabel(trend.months[months - 1].month)}`;

  if (!byCategory.categories.length && !txns.length) {
    return (
      <div className="space-y-8">
        <H1 sub="Once a statement is ingested, this screen shows every category, merchant and transaction behind your spending.">
          Where your money goes
        </H1>
        <Empty title="Nothing to show yet">
          <p>Drop a statement PDF into the ingest folder and this fills itself in.</p>
        </Empty>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      {/* 1 ── hero ─────────────────────────────────────────────────────── */}
      <section className="rise">
        <H1 sub="Everything you spent, grouped the way you actually live: by category, by merchant, and the standing costs that repeat every month.">
          Where your money goes
        </H1>

        <Card className="shadow-card">
          <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                Total spend · {period}
              </p>
              <p className="hero-figure mt-2 text-[clamp(2.4rem,7vw,4rem)]">
                {formatAbs(byCategory.total)}
              </p>
              <p className="mt-2 text-sm text-ink2">
                across{" "}
                <span className="tnum font-medium text-ink">{txns.length}</span>{" "}
                transactions in{" "}
                <span className="tnum font-medium text-ink">{byCategory.categories.length}</span>{" "}
                categories
              </p>
            </div>
            <div className="min-w-[16rem] grow">
              <TrendArea points={points} />
            </div>
          </div>
        </Card>
      </section>

      {/* 2 ── by category ──────────────────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "60ms" }}>
        <H2>By category</H2>
        <Card className="shadow-card">
          <CategoryBars
            rows={byCategory.categories.map((c) => ({
              label: c.category,
              value: c.spend,
              pct: c.pct,
              txns: c.txns,
            }))}
          />
        </Card>
      </section>

      {/* 3 ── top merchants ───────────────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "120ms" }}>
        <H2>Top merchants</H2>
        {merchants.length === 0 ? (
          <Empty title="No named merchants yet">
            <p>Merchants appear once descriptions on your statements are recognised.</p>
          </Empty>
        ) : (
          <Table head={["Merchant", "Category", "Spend", "Txns"]}>
            {merchants.map((m, i) => (
              <tr key={`${m.merchant}-${i}`} className="border-b border-line last:border-0">
                <td className="px-3 py-2.5 font-medium">{m.merchant}</td>
                <td className="px-3 py-2.5">
                  {m.category ? (
                    <Chip tone="neutral">{prettyCategory(m.category)}</Chip>
                  ) : (
                    <span className="text-xs text-ink3">uncategorised</span>
                  )}
                </td>
                <td className="tnum px-3 py-2.5 font-semibold">{formatAbs(m.spend)}</td>
                <td className="tnum px-3 py-2.5 text-ink2">{m.txns}</td>
              </tr>
            ))}
          </Table>
        )}
      </section>


      {/* 4b ── biggest single charges ─────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "220ms" }}>
        <H2>Biggest single charges</H2>
        {largest.length === 0 ? (
          <Empty title="No charges to rank yet" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {largest.slice(0, 6).map((l, i) => (
              <Card key={l.txn_id} className="shadow-card">
                <div className="flex items-start gap-2.5">
                  <span
                    aria-hidden
                    className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-[3px]"
                    style={{ background: seriesColor(i) }}
                  />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{l.merchant ?? "Unnamed"}</p>
                    <p className="mt-0.5 text-xs text-ink3">
                      {dayLabel(l.txn_date)} ·{" "}
                      {l.category ? prettyCategory(l.category) : "uncategorised"}
                    </p>
                  </div>
                </div>
                <p className="tnum display mt-3 text-xl font-semibold">{formatAbs(l.amount)}</p>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* 5 ── all transactions ────────────────────────────────────────── */}
      <TransactionList txns={txns} showRepayments={showRepayments} onToggleRepayments={onToggleRepayments} />
    </div>
  );
}

/* ── filterable transaction list ───────────────────────────────────────── */

const ALL = "__all__";
const NONE = "__none__";

function TransactionList({
  txns,
  showRepayments,
  onToggleRepayments,
}: {
  txns: Txn[];
  showRepayments: boolean;
  onToggleRepayments: (v: boolean) => void;
}) {
  const [category, setCategory] = useState<string>(ALL);
  const [query, setQuery] = useState("");

  const categories = useMemo(() => {
    const seen = new Set<string>();
    for (const t of txns) if (t.category) seen.add(t.category);
    return [...seen].sort();
  }, [txns]);

  const hasUncategorised = useMemo(() => txns.some((t) => !t.category), [txns]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return txns.filter((t) => {
      if (category === NONE && t.category) return false;
      if (category !== ALL && category !== NONE && t.category !== category) return false;
      if (!q) return true;
      return (
        (t.merchant ?? "").toLowerCase().includes(q) ||
        (t.raw_description ?? "").toLowerCase().includes(q) ||
        (t.account_id ?? "").toLowerCase().includes(q)
      );
    });
  }, [txns, category, query]);

  return (
    <section className="rise" style={{ animationDelay: "260ms" }}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <H2>All transactions</H2>
        <span className="tnum text-xs text-ink3">
          {rows.length === txns.length ? `${txns.length} shown` : `${rows.length} of ${txns.length}`}
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        {/* Money moving between your own accounts is not spending (D-007), so it is
            excluded unless explicitly asked for. */}
        <label className="flex cursor-pointer select-none items-center gap-2 rounded-lg border border-line bg-card2 px-3 py-2 text-xs">
          <input
            type="checkbox"
            checked={showRepayments}
            onChange={(e) => onToggleRepayments(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--accent)]"
          />
          <span className="font-medium text-ink">Show repayments</span>
        </label>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search merchant or description…"
          aria-label="Search transactions"
          className="min-w-[14rem] grow rounded-card border border-line bg-card px-3.5 py-2 text-sm text-ink placeholder:text-ink3 sm:max-w-[24rem]"
        />
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Filter by category"
          className="rounded-card border border-line bg-card px-3 py-2 text-sm text-ink"
        >
          <option value={ALL}>All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {prettyCategory(c)}
            </option>
          ))}
          {hasUncategorised ? <option value={NONE}>Uncategorised</option> : null}
        </select>
        {(query || category !== ALL) && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setCategory(ALL);
            }}
            className="rounded-card px-3 py-2 text-sm font-medium text-ink2 transition-colors hover:bg-card hover:text-ink"
          >
            Clear
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <Empty title="Nothing matches that filter">
          <p>Try a shorter search, or clear the category filter.</p>
        </Empty>
      ) : (
        <Table head={["Date", "Merchant", "Category", "Account", "Amount"]}>
          {rows.map((t) => (
            <tr key={t.txn_id} className="border-b border-line last:border-0 align-top">
              <td className="tnum whitespace-nowrap px-3 py-2.5 text-ink2">{dayLabel(t.txn_date)}</td>
              <td className="px-3 py-2.5">
                <span className="font-medium">{t.merchant ?? "Unnamed"}</span>
                {t.raw_description ? (
                  <span className="mono mt-0.5 block text-[11px] leading-snug text-ink3">
                    {t.raw_description}
                  </span>
                ) : null}
              </td>
              <td className="px-3 py-2.5">
                {t.category ? (
                  <CategoryTag txnId={t.txn_id} category={t.category} merchant={t.merchant} />
                ) : (
                  <span className="text-xs text-ink3">not categorised yet</span>
                )}
              </td>
              <td className="mono px-3 py-2.5 text-xs text-ink3">{t.account_id}</td>
              <td className="tnum whitespace-nowrap px-3 py-2.5 text-right font-semibold">
                {formatMoney(t.amount, { sign: true })}
              </td>
            </tr>
          ))}
        </Table>
      )}

      <p className="mt-3 max-w-[70ch] text-xs text-ink3">
        The grey line under each merchant is the raw description exactly as it appeared on the
        statement — the evidence behind the tidy name. Amounts are shown as they were recorded:
        a minus is money leaving, a plus is money coming back.
      </p>
    </section>
  );
}

/* ── states ─────────────────────────────────────────────────────────────── */

function Skeleton() {
  return (
    <div className="space-y-8">
      <H1 sub="Reading your statements…">Where your money goes</H1>
      <Card className="shadow-card">
        <div className="h-6 w-40 rounded-full bg-line2" />
        <div className="mt-4 h-12 w-64 rounded-card bg-line2" />
        <div className="mt-6 h-32 w-full rounded-card bg-line2" />
      </Card>
    </div>
  );
}

function ApiDownCard() {
  return (
    <div className="space-y-8">
      <H1>Where your money goes</H1>
      <Empty title="The analyser isn’t running">
        <p>Start it and this screen fills itself in:</p>
        <p className="mono mt-2 rounded-card bg-bg2 px-3 py-2 text-xs">
          .venv/bin/python -m analyser.api
        </p>
      </Empty>
    </div>
  );
}

function FailureCard({ message }: { message: string }) {
  return (
    <div className="space-y-8">
      <H1>Where your money goes</H1>
      <Empty title="That request didn’t come back">
        <p>The analyser is running but returned an error, so nothing is shown rather than a guess.</p>
        <p className="mono mt-2 rounded-card bg-bg2 px-3 py-2 text-xs">{message}</p>
      </Empty>
    </div>
  );
}

/**
 * useSearchParams needs a Suspense boundary — the period lives in the URL so the
 * page can be linked to and shared (see components/period-bar).
 */
export default function SpendingPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink3">Loading…</p>}>
      <SpendingInner />
    </Suspense>
  );
}
