import Link from "next/link";
import {
  api, ApiDown, defaultPeriod,
  type ByCategory, type LargestRow, type Overview, type Period,
  type Position, type RecurringRow, type Trend, type Txn,
} from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import {
  cardName, daysUntil, dueLabel, dueTone, formatPct, fullMonth, longDate, prettyCategory, shortDate,
} from "@/lib/format";
import { TrendArea } from "@/components/charts";
import { CategoryPanel } from "@/components/category-panel";
import { CategoryTag } from "@/components/category-tag";
import { Traceable } from "@/components/evidence-drawer";
import { CardLink } from "@/components/card-drawer";
import { ScopeBar } from "@/components/scope-bar";
import {
  Card, CardTitle, Chip, Code, Eyebrow, Hero, Meter, PageTitle, SectionTitle, State, TableWrap,
} from "@/components/ui";
import { Alert, ArrowRight, Check, Clock, Info } from "@/components/icons";

export const dynamic = "force-dynamic";

/* ─────────────────────────────────────────────────────────────────────────
   Money — the only view of your spending.

   Today, Spending and Cards used to be three routes asking one question at
   three zoom levels, which forced you to carry the same period in your head
   across three screens. They are four sections of one page now:

     1  the glance      — one hero figure and the shape of the year
     2  what you owe    — the cards that want money; the rest go quiet
     3  where it went   — the ranking and the standing costs
     4  every transaction

   Cards are no longer a destination: a card's statements, limit history and
   reported rewards live in its drawer.
   ───────────────────────────────────────────────────────────────────────── */

function utilTone(bps: number | null): "ok" | "warn" | "bad" {
  if (bps == null) return "ok";
  const pct = bps / 100;
  if (pct >= 80) return "bad";
  if (pct >= 50) return "warn";
  return "ok";
}

export default async function MoneyPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string; label?: string; category?: string; card?: string }>;
}) {
  const sp = await searchParams;

  // The calendar has to land before the window can be resolved: the default view
  // is the current year (D-038) and only the engine knows which years hold data.
  const cal = await api.calendar().catch(() => null);
  const explicit = Boolean(sp.from || sp.to || sp.label);
  const period: Period = explicit
    ? { from: sp.from, to: sp.to, label: sp.label ?? "All time" }
    : defaultPeriod(cal?.default_year ?? null);

  let overview: Overview;
  // Readiness is a fact about ALL your data, so it is read UNSCOPED. Passing the
  // selected window made a one-month view report "1 of 6 months minimum", which
  // is a property of the filter, not of your ledger.
  let gates: Overview | null = null;
  let positions: Position[] = [];
  let trend: Trend;
  let byCategory: ByCategory;
  let largest: LargestRow[] = [];
  let recurring: RecurringRow[] = [];
  let txns: Txn[] = [];

  try {
    [overview, positions, trend, byCategory, largest, recurring, txns] = await Promise.all([
      api.overview(period),
      api.positions(),
      api.trend(),
      api.byCategory(period),
      api.largest(5, period),
      api.recurring(3).catch(() => []),
      api.transactionsIn(period, {
        limit: 12,
        ...(sp.category ? { category: sp.category } : {}),
        ...(sp.card ? { account_id: sp.card } : {}),
      }).catch(() => []),
    ]);
    gates = period.label === "All time" ? overview : await api.overview().catch(() => null);
  } catch (err) {
    if (err instanceof ApiDown) return <EngineDown />;
    return <Failed message={err instanceof Error ? err.message : String(err)} />;
  }

  if (overview.transactions === 0 && overview.accounts.length === 0) return <NoData />;

  const scopeLabel =
    period.label === "All time"
      ? "across every statement"
      : /^\d{4}$/.test(period.label)
        ? period.label
        : fullMonth(period.label);
  const activeMonth = /^\d{4}-\d{2}$/.test(period.label) ? period.label : null;

  const current = activeMonth
    ? (trend.months.find((m) => m.month === activeMonth) ?? null)
    : (trend.current ?? trend.months[trend.months.length - 1] ?? null);
  const hasHistory = trend.months.length >= 2;

  const due = positions
    .filter((p) => p.payment_due_date && p.total_payment_due && p.total_payment_due.minor !== 0)
    .sort((a, b) => (a.payment_due_date! < b.payment_due_date! ? -1 : 1));
  const quiet = positions.filter((p) => !due.includes(p) && p.account_type !== "BANK");
  const banks = positions.filter((p) => p.account_type === "BANK");

  const readiness = gates ?? overview;
  const failing = readiness.gates.filter((g) => g.failing);
  const met = readiness.gates.length - failing.length;

  const catRows = byCategory.categories.map((c) => ({
    label: c.category, value: c.spend, pct: c.pct, txns: c.txns,
  }));
  const trendPoints = trend.months.map((m) => ({ month: m.month, value: m.spend }));

  return (
    <>
      {/* The control must report the window the page ACTUALLY used. Reading the
          URL alone made it say "All time" while the default year was in force. */}
      <ScopeBar
        years={cal?.years ?? []}
        label={period.label}
        note={period.label === "All time" ? "every statement on record" : undefined}
      />

      <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-11 px-6 pb-16 pt-7">
        {/* ── readiness: shown only while something is blocking ───────────── */}
        {failing.length ? (
          <Card className="rise flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-3">
              <Ring met={met} total={readiness.gates.length} />
              <div className="flex flex-col">
                <p className="text-sm font-semibold">
                  Your plan is {failing.length} condition{failing.length === 1 ? "" : "s"} from ready
                </p>
                <p className="text-xs text-ink3">{failing[0].detail}</p>
              </div>
            </div>
            <Link
              href="/data"
              className="ml-auto inline-flex h-[34px] items-center gap-1.5 rounded-control bg-accent px-4 text-[13px] font-semibold text-white"
            >
              Clear it up
              <ArrowRight />
            </Link>
          </Card>
        ) : null}

        {/* ── 1 · the glance ──────────────────────────────────────────────── */}
        <section className="grid gap-5 lg:grid-cols-[25.5rem_1fr]">
          <Card className="rise flex flex-col p-6">
            <Hero label="You spent" value={formatAbs(overview.total_spend)}>
              <div className="mt-4 flex flex-wrap items-center gap-2.5">
                {/* A month-on-month delta beside a YEAR total described a change the
                    hero figure does not contain. It only appears in month scope now. */}
                {activeMonth && hasHistory && current?.change ? (
                  <Chip
                    tone={current.change.minor > 0 ? "warn" : "ok"}
                    icon={current.change.minor > 0 ? <Alert size={12} /> : <Check size={12} />}
                  >
                    <span className="tnum">
                      {formatMoney(current.change, { sign: true }).replace(/^([+−])[A-Z]{3}\s/, "$1")}
                      {current.change_pct != null ? ` · ${formatPct(current.change_pct)}` : ""}
                    </span>
                  </Chip>
                ) : null}
                <span className="text-[13px] text-ink2">
                  {activeMonth ? "vs the month before" : scopeLabel}
                </span>
                {!activeMonth && trend.months.length ? (
                  <span className="text-[13px] text-ink3">
                    across {trend.months.length} closed month
                    {trend.months.length === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
              <div className="mt-6 grid grid-cols-2 gap-4 border-t border-hair pt-5">
                <div className="flex flex-col gap-1">
                  <Eyebrow>Transactions</Eyebrow>
                  <p className="tnum text-lg font-semibold">{overview.transactions}</p>
                </div>
                <div className="flex flex-col gap-1">
                  <Eyebrow>Monthly average</Eyebrow>
                  <p className="tnum text-lg font-semibold">
                    {formatAbs(trend.average).replace(/^[A-Z]{3}\s/, "")}
                  </p>
                </div>
              </div>
            </Hero>
          </Card>

          <Card className="rise flex flex-col gap-1 p-6 pb-3" >
            <CardTitle aside={`every closed statement · ${byCategory.total?.currency ?? "AED"}`}>
              Month by month
            </CardTitle>
            <TrendArea points={trendPoints} activeMonth={activeMonth} />
          </Card>
        </section>

        {/* ── 2 · what you owe ────────────────────────────────────────────── */}
        <section className="flex flex-col gap-4">
          <SectionTitle aside="click a card for its statements and reported rewards · balances ignore the period above, because a balance has no period">
            What you owe
          </SectionTitle>

          {due.length === 0 ? (
            <State title="Nothing is due.">
              No statement on record carries an outstanding payment. New statements land here the
              moment they are read.
            </State>
          ) : (
            <div className="grid gap-5 md:grid-cols-2">
              {due.map((p, i) => {
                const days = daysUntil(p.payment_due_date!);
                const tone = dueTone(days);
                const util = p.utilisation_bps;
                return (
                  <Card
                    key={p.account_id}
                    className="rise flex flex-col gap-4 p-[22px]"
                   
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex flex-col gap-0.5">
                        <CardLink accountId={p.account_id} className="text-[15px] font-semibold">
                          {cardName(p)}
                        </CardLink>
                        <p className="mono text-[11px] text-ink3">{p.account_id}</p>
                      </div>
                      <Chip tone={tone} icon={<Clock size={12} />}>{dueLabel(days)}</Chip>
                    </div>
                    <div className="flex flex-col gap-1">
                      <Eyebrow>Total payment due</Eyebrow>
                      <p className="tnum text-3xl font-semibold leading-none tracking-[-.02em]">
                        {formatAbs(p.total_payment_due).replace(/^[A-Z]{3}\s/, "")}
                      </p>
                      <p className="text-[13px] text-ink2">
                        by {longDate(p.payment_due_date!)}
                        {p.minimum_due ? (
                          <>
                            {" · minimum "}
                            <span className="tnum">
                              {formatAbs(p.minimum_due).replace(/^[A-Z]{3}\s/, "")}
                            </span>
                          </>
                        ) : null}
                      </p>
                    </div>
                    {util != null && p.credit_limit ? (
                      <Meter
                        pct={util / 100}
                        tone={utilTone(util)}
                        label="Limit in use"
                        right={`${Math.round(util / 100)}% of ${formatAbs(p.credit_limit).replace(/^[A-Z]{3}\s/, "")}`}
                      />
                    ) : (
                      <p className="text-xs text-ink3">Credit limit not printed on this statement.</p>
                    )}
                  </Card>
                );
              })}
            </div>
          )}

          {/* the cards with nothing urgent: one row each, so nothing shouts */}
          {quiet.length ? (
            <Card pad={false} className="rise py-1.5">
              <TableWrap>
                <table className="w-full min-w-[36rem] text-sm">
                  <caption className="sr-only">Cards with nothing due</caption>
                  <tbody>
                    {quiet.map((p) => {
                      const days = p.payment_due_date ? daysUntil(p.payment_due_date) : null;
                      const util = p.utilisation_bps;
                      return (
                        <tr key={p.account_id} className="border-b border-hair last:border-0">
                          <td className="px-5 py-3">
                            <CardLink accountId={p.account_id} className="block text-[13.5px] font-medium">
                              {cardName(p)}
                            </CardLink>
                            <span className="mono block text-[11px] text-ink3">{p.account_id}</span>
                          </td>
                          <td className="px-5 py-3 text-[12.5px]">
                            {days == null ? (
                              <span className="text-ink3">no statement yet</span>
                            ) : days < 0 ? (
                              <span className="font-semibold text-bad">{dueLabel(days)}</span>
                            ) : (
                              <span className="font-semibold text-ok">settled</span>
                            )}
                          </td>
                          <td className="tnum px-5 py-3 text-[12.5px] text-ink2">
                            {util != null && p.credit_limit
                              ? `${Math.round(util / 100)}% of ${formatAbs(p.credit_limit).replace(/^[A-Z]{3}\s/, "")}`
                              : "limit not printed"}
                          </td>
                          <td className="px-5 py-3 text-right text-[12.5px] text-ink3">
                            {p.statement_date ? longDate(p.statement_date) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
            </Card>
          ) : null}

          {banks.length ? (
            <p className="text-xs leading-relaxed text-ink3">
              {banks.length} settlement account{banks.length === 1 ? "" : "s"} on record. Card
              repayments that appear on both a card and its funding account are matched into one
              transfer, so they are never counted as spending.
            </p>
          ) : null}
        </section>

        {/* ── 3 · where it went ───────────────────────────────────────────── */}
        <section className="flex flex-col gap-4">
          <SectionTitle aside={scopeLabel}>Where it went</SectionTitle>
          <div className="grid items-start gap-5 lg:grid-cols-2">
            <Card className="rise flex flex-col gap-4">
              <CardTitle aside="one hue, ranked">By category</CardTitle>
              <CategoryPanel rows={catRows} />
              {overview.uncategorized_pct > 0 ? (
                <p className="flex items-start gap-2 border-t border-hair pt-3 text-xs leading-relaxed text-ink3">
                  <Info size={13} className="mt-px shrink-0" />
                  <span>
                    {formatPct(overview.uncategorized_pct)} of this is still uncategorised
                    {overview.uncategorized_spend ? (
                      <>
                        {" — "}
                        <span className="tnum">{formatAbs(overview.uncategorized_spend)}</span>
                      </>
                    ) : null}
                    .{" "}
                    <Link href="/data" className="font-semibold text-accentInk underline underline-offset-2">
                      Assign it
                    </Link>
                  </span>
                </p>
              ) : null}
            </Card>

            <Card className="rise flex flex-col gap-4">
              <CardTitle aside="seen in 3+ months">Standing costs</CardTitle>
              {recurring.length === 0 ? (
                <p className="text-sm text-ink3">
                  Nothing repeats often enough yet to count as a standing cost.
                </p>
              ) : (
                <>
                  <div className="flex flex-col">
                    {recurring.slice(0, 6).map((r) => (
                      <div
                        key={r.merchant}
                        className="flex items-center gap-3 border-b border-hair py-2.5 last:border-0"
                      >
                        <div className="flex min-w-0 flex-grow flex-col gap-0.5">
                          <span className="truncate text-[13.5px] font-medium">{r.merchant}</span>
                          <span className="text-[11.5px] text-ink3">
                            {r.category ? prettyCategory(r.category) : "uncategorised"} · {r.months} months
                          </span>
                        </div>
                        <span className="tnum shrink-0 text-[13.5px] font-semibold">
                          {formatAbs(r.typical).replace(/^[A-Z]{3}\s/, "")}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs leading-relaxed text-ink3">
                    The typical figure is the median month, so a one-off annual charge does not
                    inflate it.
                  </p>
                </>
              )}
            </Card>
          </div>
        </section>

        {/* ── 4 · every transaction ───────────────────────────────────────── */}
        <section className="flex flex-col gap-4">
          <SectionTitle aside="any row's category can be changed in place">
            {sp.category ? prettyCategory(sp.category) : "Every transaction"}
          </SectionTitle>

          <Card pad={false} className="rise overflow-hidden">
            <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-surface2 px-5 py-3">
              {sp.category ? (
                <Filter href={`/?${scopeParams(period)}`} on>
                  {prettyCategory(sp.category)} ×
                </Filter>
              ) : null}
              {sp.card ? (
                <Filter href={`/?${scopeParams(period)}`} on>
                  {sp.card} ×
                </Filter>
              ) : null}
              {!sp.category && !sp.card ? (
                <span className="text-xs text-ink3">
                  Filter by clicking a category bar or a card above.
                </span>
              ) : null}
              <span className="ml-auto text-xs text-ink3">
                <span className="tnum">{overview.transactions}</span> in scope ·{" "}
                <span className="tnum">{formatAbs(overview.total_spend)}</span>
              </span>
            </div>

            {txns.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-ink3">
                No transaction matches this scope.
              </p>
            ) : (
              <TableWrap>
                <table className="w-full min-w-[44rem] text-sm">
                  <thead>
                    <tr className="border-b border-hair text-left">
                      <th scope="col" className="eyebrow px-5 py-2.5 font-semibold">Date</th>
                      <th scope="col" className="eyebrow px-5 py-2.5 font-semibold">Merchant</th>
                      <th scope="col" className="eyebrow px-5 py-2.5 font-semibold">Category</th>
                      <th scope="col" className="eyebrow px-5 py-2.5 font-semibold">Card</th>
                      <th scope="col" className="eyebrow px-5 py-2.5 text-right font-semibold">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txns.map((t) => (
                      <tr key={t.txn_id} className="border-b border-hair last:border-0">
                        <td className="tnum whitespace-nowrap px-5 py-3 text-[13px] text-ink2">
                          {shortDate(t.txn_date)}
                        </td>
                        <td className="px-5 py-3 text-[13.5px] font-medium">
                          {t.merchant ?? <span className="text-ink3">not printed</span>}
                        </td>
                        <td className="px-5 py-3">
                          <CategoryTag txnId={t.txn_id} category={t.category} merchant={t.merchant} />
                        </td>
                        <td className="px-5 py-3 text-[12.5px] text-ink2">
                          <CardLink accountId={t.account_id}>{t.card}</CardLink>
                        </td>
                        <td className="px-5 py-3 text-right">
                          <Traceable txnId={t.txn_id} className="tnum text-[13.5px] font-semibold">
                            {formatAbs(t.amount).replace(/^[A-Z]{3}\s/, "")}
                          </Traceable>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </Card>

          {largest.length ? (
            <p className="text-xs leading-relaxed text-ink3">
              The biggest single charge in scope is{" "}
              <span className="tnum font-semibold text-ink2">{formatAbs(largest[0].amount)}</span>
              {largest[0].merchant ? ` at ${largest[0].merchant}` : ""} on{" "}
              {longDate(largest[0].txn_date)}.
            </p>
          ) : null}
        </section>

        <p className="max-w-[80ch] text-xs leading-relaxed text-ink3">
          {readiness.months_covered < 6
            ? `A card recommendation needs at least six months of spending — you have ${readiness.months_covered}.`
            : "There is enough history here to judge a card properly."}{" "}
          Every figure came off a statement and reconciles to its own printed total. Nothing left
          this machine.
        </p>
      </main>
    </>
  );
}

function scopeParams(p: Period): string {
  const s = new URLSearchParams();
  if (p.from) s.set("from", p.from);
  if (p.to) s.set("to", p.to);
  if (p.label !== "All time") s.set("label", p.label);
  return s.toString();
}

function Filter({ href, on, children }: { href: string; on?: boolean; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={`inline-flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-[13px] font-semibold ${
        on ? "bg-accentSoft text-accentInk" : "border border-line bg-surface text-ink2"
      }`}
    >
      {children}
    </Link>
  );
}

/** Readiness as a figure, not a paragraph. */
function Ring({ met, total }: { met: number; total: number }) {
  const r = 15, c = 2 * Math.PI * r;
  const done = total ? (met / total) * c : 0;
  return (
    <svg width="34" height="34" viewBox="0 0 36 36" className="-rotate-90" aria-hidden>
      <circle cx="18" cy="18" r={r} fill="none" stroke="var(--hair)" strokeWidth="3" />
      <circle
        cx="18" cy="18" r={r} fill="none" stroke="var(--warn)" strokeWidth="3"
        strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c - done}
      />
    </svg>
  );
}

/* ── states: one component, one copy source ──────────────────────────────── */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-6 px-6 pb-16 pt-9">
      {children}
    </main>
  );
}

function EngineDown() {
  return (
    <Shell>
      <PageTitle sub="The interface is fine; the local engine is not answering.">
        Nothing to show right now
      </PageTitle>
      <State title="Start the engine from the project root, then reload.">
        <Code>.venv/bin/python -m analyser.api</Code>
        <p className="mt-3 text-xs text-ink3">
          Nothing leaves this machine — the UI only ever talks to 127.0.0.1.
        </p>
      </State>
    </Shell>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <Shell>
      <PageTitle sub="The engine answered, but not with data this screen can show.">
        Could not load your money
      </PageTitle>
      <State title={message} tone="bad" />
    </Shell>
  );
}

function NoData() {
  return (
    <Shell>
      <PageTitle sub="Point the engine at a folder of statement PDFs and this becomes your money dashboard.">
        Let&apos;s see where your money goes
      </PageTitle>
      <State title="Read your first statements">
        <p>
          Statements are parsed locally and reconciled against their own printed totals, so every
          figure here came off a real statement.
        </p>
        <Code>.venv/bin/python -m analyser.ingest ./statements</Code>
        <p className="mt-3 text-xs text-ink3">
          Spending, balances and due dates appear from the very first statement. Six months is the
          minimum before a card recommendation can be trusted.
        </p>
      </State>
    </Shell>
  );
}
