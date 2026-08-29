import Link from "next/link";
import {
  api, ApiDown, defaultPeriod,
  type ByCategory, type LargestRow, type Overview, type Period,
  type Income, type Position, type RecurringRow, type Trend, type Txn,
} from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import {
  cardName, daysUntil, dueLabel, dueTone, formatPct, fullMonth, longDate, prettyCategory, shortDate,
} from "@/lib/format";
import { TrendArea } from "@/components/charts";
import { CountUp, Sparkline } from "@/components/figures";
import { CategoryDonutPanel } from "@/components/category-panel";
import { IncomePanel } from "@/components/income-panel";
import { CategoryTag } from "@/components/category-tag";
import { Traceable } from "@/components/evidence-drawer";
import { CardLink } from "@/components/card-drawer";
import { ScopeBar } from "@/components/scope-bar";
import { EngineDownPanel } from "@/components/engine-down";
import {
  Card, CardTitle, Chip, Code, Label, Meter, PageTitle, SectionTitle, State, TableWrap,
} from "@/components/ui";
import { Alert, ArrowRight, Check, Clock, Down, Up } from "@/components/icons";

export const dynamic = "force-dynamic";

/* ─────────────────────────────────────────────────────────────────────────
   Money — the dashboard.

   Fixed order, set by the user: the figure and the graphs lead, the cards sit
   below them, and the transaction table stays last as the deep detail. Urgency
   is not lost to the ordering because overdue cards still raise the alert strip
   at the top of the page.
   ───────────────────────────────────────────────────────────────────────── */

function utilTone(bps: number | null): "ok" | "warn" | "bad" {
  if (bps == null) return "ok";
  const pct = bps / 100;
  if (pct >= 80) return "bad";
  if (pct >= 50) return "warn";
  return "ok";
}

function magnitude(m: { minor: number; exponent: number } | null | undefined) {
  if (!m) return 0;
  return Math.abs(m.minor) / Math.pow(10, m.exponent);
}

export default async function MoneyPage({
  searchParams,
}: {
  searchParams: Promise<{ from?: string; to?: string; label?: string; category?: string; card?: string }>;
}) {
  const sp = await searchParams;
  const cal = await api.calendar().catch(() => null);
  const explicit = Boolean(sp.from || sp.to || sp.label);
  const period: Period = explicit
    ? { from: sp.from, to: sp.to, label: sp.label ?? "All time" }
    : defaultPeriod(cal?.default_year ?? null);

  let overview: Overview;
  let positions: Position[] = [];
  let trend: Trend;
  let byCategory: ByCategory;
  let largest: LargestRow[] = [];
  let recurring: RecurringRow[] = [];
  let txns: Txn[] = [];
  let income: Income | null = null;
  let gates: Overview | null = null;

  try {
    [overview, positions, trend, byCategory, largest, recurring, txns, income] = await Promise.all([
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
      // Income arrives from bank statements, which may not have been read at all.
      // Its absence is a normal state, not an error that should blank the page.
      api.income(period).catch(() => null),
    ]);
    // Readiness is a fact about ALL the data, never about the selected window.
    gates = period.label === "All time" ? overview : await api.overview().catch(() => null);
  } catch (err) {
    if (err instanceof ApiDown) return <EngineDown />;
    return <Failed message={err instanceof Error ? err.message : String(err)} />;
  }

  if (overview.transactions === 0 && overview.accounts.length === 0) return <NoData />;

  const scopeLabel =
    period.label === "All time" ? "across every statement"
      : /^\d{4}$/.test(period.label) ? period.label
      : fullMonth(period.label);
  const activeMonth = /^\d{4}-\d{2}$/.test(period.label) ? period.label : null;

  const current = activeMonth
    ? (trend.months.find((m) => m.month === activeMonth) ?? null)
    : (trend.current ?? trend.months[trend.months.length - 1] ?? null);
  const rising = (current?.change?.minor ?? 0) > 0;

  const due = positions
    .filter((p) => p.payment_due_date && p.total_payment_due && p.total_payment_due.minor !== 0)
    .sort((a, b) => (a.payment_due_date! < b.payment_due_date! ? -1 : 1));
  const quiet = positions.filter((p) => !due.includes(p) && p.account_type !== "BANK");

  const overdue = due.filter((p) => daysUntil(p.payment_due_date!) < 0);
  const soon = due.filter((p) => {
    const d = daysUntil(p.payment_due_date!);
    return d >= 0 && d <= 7;
  });
  const urgent = [...overdue, ...soon];

  const readiness = gates ?? overview;
  const failing = readiness.gates.filter((g) => g.failing);

  const catRows = byCategory.categories.map((c) => ({
    label: c.category, value: c.spend, pct: c.pct, txns: c.txns,
  }));
  const trendPoints = trend.months.map((m) => ({ month: m.month, value: m.spend }));
  const spark = trend.months.slice(-12).map((m) => Math.abs(m.spend.minor));

  const owe = (
    <section className="flex flex-col gap-4">
      <SectionTitle aside="balances ignore the period above, because a balance has no period">
        What you owe
      </SectionTitle>
      {due.length === 0 ? (
        <State title="Nothing is due." tone="ok">
          No statement on record carries an outstanding payment.
        </State>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          {due.map((p, i) => {
            const days = daysUntil(p.payment_due_date!);
            const tone = dueTone(days);
            const util = p.utilisation_bps;
            return (
              <Card key={p.account_id} className="flex flex-col gap-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <CardLink accountId={p.account_id} className="text-[15px] font-bold tracking-[-.01em]">
                      {cardName(p)}
                    </CardLink>
                    <span className="mono text-[11px] text-ink3">{p.account_id}</span>
                  </div>
                  <Chip tone={tone} icon={tone === "bad" ? <Alert size={12} /> : <Clock size={12} />}>
                    {dueLabel(days)}
                  </Chip>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Total payment due</Label>
                  <p className="figure text-[30px]">
                    {formatAbs(p.total_payment_due).replace(/^[A-Z]{3}\s/, "")}
                  </p>
                  <p className="text-[13px] text-ink2">
                    by {longDate(p.payment_due_date!)}
                    {p.minimum_due ? (
                      <> · minimum <span className="tnum">{formatAbs(p.minimum_due).replace(/^[A-Z]{3}\s/, "")}</span></>
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
                  <p className="text-[12.5px] text-ink3">Credit limit not printed on this statement.</p>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {quiet.length ? (
        <Card pad={false} className="overflow-hidden">
          <TableWrap>
            <table className="w-full min-w-[34rem] text-sm">
              <caption className="sr-only">Cards with nothing due</caption>
              <tbody>
                {quiet.map((p) => {
                  const days = p.payment_due_date ? daysUntil(p.payment_due_date) : null;
                  const util = p.utilisation_bps;
                  return (
                    <tr key={p.account_id} className="border-b border-hair last:border-0">
                      <td className="px-5 py-3.5">
                        <CardLink accountId={p.account_id} className="block text-[13.5px] font-semibold">
                          {cardName(p)}
                        </CardLink>
                        <span className="mono block text-[11px] text-ink3">{p.account_id}</span>
                      </td>
                      <td className="px-5 py-3.5 text-[12.5px]">
                        {days == null ? <span className="text-ink3">no statement yet</span>
                          : days < 0 ? <span className="font-bold text-bad">{dueLabel(days)}</span>
                          : <span className="font-bold text-ok">settled</span>}
                      </td>
                      <td className="tnum px-5 py-3.5 text-[12.5px] text-ink2">
                        {util != null && p.credit_limit
                          ? `${Math.round(util / 100)}% of ${formatAbs(p.credit_limit).replace(/^[A-Z]{3}\s/, "")}`
                          : "limit not printed"}
                      </td>
                      <td className="px-5 py-3.5 text-right text-[12.5px] text-ink3">
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
    </section>
  );

  const money = (
    <>
      {/* the glance */}
      <section className="grid gap-5 lg:grid-cols-[26rem_1fr]">
        <Card className="flex flex-col justify-between gap-6">
          <div className="flex flex-col gap-2">
            <Label>You spent</Label>
            <CountUp
              value={magnitude(overview.total_spend)}
              text={formatAbs(overview.total_spend)}
              className="figure text-[clamp(2.3rem,4.2vw,3.1rem)]"
            />
            <div className="mt-1 flex flex-wrap items-center gap-2.5">
              {activeMonth && current?.change ? (
                <Chip tone={rising ? "warn" : "ok"} icon={rising ? <Up size={12} /> : <Down size={12} />}>
                  <span className="tnum">
                    {formatMoney(current.change, { sign: true }).replace(/^([+−])[A-Z]{3}\s/, "$1")}
                    {current.change_pct != null ? ` · ${formatPct(current.change_pct)}` : ""}
                  </span>
                </Chip>
              ) : null}
              <span className="text-[13px] text-ink2">
                {activeMonth
                  ? "vs the month before"
                  : period.label === "All time"
                    ? `across ${trend.months.length} closed months`
                    : `in ${scopeLabel}`}
              </span>
            </div>
          </div>

          <div className="flex items-end justify-between gap-4 border-t border-hair pt-5">
            <div className="flex flex-col gap-1">
              <Label>Transactions</Label>
              <p className="tnum text-[20px] font-bold tracking-[-.02em]">{overview.transactions}</p>
            </div>
            <div className="flex flex-col gap-1">
              <Label>Monthly average</Label>
              <p className="tnum text-[20px] font-bold tracking-[-.02em]">
                {formatAbs(trend.average).replace(/^[A-Z]{3}\s/, "")}
              </p>
            </div>
            <Sparkline points={spark} className="mb-0.5 shrink-0" />
          </div>
        </Card>

        <Card className="flex flex-col gap-3">
          <CardTitle aside={`every closed statement · ${byCategory.total?.currency ?? "AED"}`}>
            Month by month
          </CardTitle>
          <TrendArea points={trendPoints} activeMonth={activeMonth} />
        </Card>
      </section>

      {/* where it went */}
      <section className="grid items-start gap-5 lg:grid-cols-[1.15fr_1fr]">
        <Card className="flex flex-col gap-6">
          <CardTitle aside={scopeLabel}>Where it went</CardTitle>
          <CategoryDonutPanel rows={catRows} total={byCategory.total} />
        </Card>

        <Card className="flex flex-col gap-4">
          <CardTitle aside="seen in 3+ months">Standing costs</CardTitle>
          {recurring.length === 0 ? (
            <p className="text-sm text-ink3">Nothing repeats often enough yet to count as a standing cost.</p>
          ) : (
            <>
              <div className="flex flex-col">
                {recurring.slice(0, 6).map((r) => (
                  <div key={r.merchant} className="flex items-center gap-3 border-b border-hair py-2.5 last:border-0">
                    <div className="flex min-w-0 flex-grow flex-col gap-0.5">
                      <span className="truncate text-[13.5px] font-semibold">{r.merchant}</span>
                      <span className="text-[11.5px] text-ink3">
                        {r.category ? prettyCategory(r.category) : "uncategorised"} · {r.months} months
                      </span>
                    </div>
                    <span className="tnum shrink-0 text-[13.5px] font-bold">
                      {formatAbs(r.typical).replace(/^[A-Z]{3}\s/, "")}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[12.5px] leading-relaxed text-ink3">
                The typical figure is the median month, so a one-off annual charge does not inflate it.
              </p>
            </>
          )}
        </Card>
      </section>
    </>
  );

  return (
    <>
      <ScopeBar
        years={cal?.years ?? []}
        label={period.label}
        note={period.label === "All time" ? "every statement on record" : undefined}
      />

      <main id="main" className="mx-auto flex max-w-[76rem] flex-col gap-10 px-6 pb-20 pt-7">
        {urgent.length ? (
          <div className="flex flex-wrap items-center gap-4 rounded-card border border-bad/25 bg-badSoft px-5 py-4">
            <Alert size={18} className="shrink-0 text-bad" />
            <p className="text-[14.5px] font-bold text-bad">
              {overdue.length
                ? `${overdue.length} card${overdue.length === 1 ? "" : "s"} overdue`
                : `${soon.length} card${soon.length === 1 ? "" : "s"} due this week`}
            </p>
            <p className="text-[13.5px] text-ink2">
              {urgent.map((p) => `${cardName(p)} ${dueLabel(daysUntil(p.payment_due_date!))}`).join(" · ")}
            </p>
          </div>
        ) : null}

        {failing.length ? (
          <Link
            href="/data"
            className="flex flex-wrap items-center gap-4 rounded-card border border-line bg-surface px-5 py-4 shadow-card transition-shadow hover:shadow-lift"
          >
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-warnSoft text-warn">
              <Alert size={17} />
            </span>
            <span className="flex flex-col">
              <span className="text-[14px] font-bold">
                Your plan is {failing.length} condition{failing.length === 1 ? "" : "s"} from ready
              </span>
              <span className="text-[12.5px] text-ink3">{failing[0].detail}</span>
            </span>
            <span className="ml-auto inline-flex items-center gap-1.5 text-[13px] font-bold text-accentInk">
              Clear it up <ArrowRight size={14} />
            </span>
          </Link>
        ) : null}

        {money}
        {income && income.months.length ? (
          <section className="flex flex-col gap-4">
            <SectionTitle aside="read from bank statements, not cards">
              What came in
            </SectionTitle>
            <IncomePanel income={income} scopeLabel={scopeLabel} />
          </section>
        ) : null}
        {owe}

        {/* every transaction */}
        <section className="flex flex-col gap-4">
          <SectionTitle aside="any row's category can be changed in place, and any figure opens its statement line">
            {sp.category ? prettyCategory(sp.category) : "Every transaction"}
          </SectionTitle>

          <Card pad={false} className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-2.5 border-b border-line bg-surface2 px-5 py-3.5">
              {sp.category || sp.card ? (
                <Link
                  href={`/?${scopeParams(period)}`}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full bg-accentSoft px-3.5 text-[13px] font-bold text-accentInk"
                >
                  {sp.category ? prettyCategory(sp.category) : sp.card} ×
                </Link>
              ) : (
                <span className="text-[12.5px] text-ink3">Filter by clicking a category or a card above.</span>
              )}
              <span className="ml-auto text-[12.5px] text-ink3">
                <span className="tnum">{overview.transactions}</span> in scope ·{" "}
                <span className="tnum">{formatAbs(overview.total_spend)}</span>
              </span>
            </div>

            {txns.length === 0 ? (
              <p className="px-5 py-10 text-center text-sm text-ink3">No transaction matches this scope.</p>
            ) : (
              <TableWrap>
                <table className="w-full min-w-[44rem] text-sm">
                  <thead>
                    <tr className="border-b border-hair text-left">
                      {["Date", "Merchant", "Category", "Card", "Amount"].map((h) => (
                        <th key={h} scope="col"
                            className={`px-5 py-3 text-[12.5px] font-semibold text-ink3 ${h === "Amount" ? "text-right" : ""}`}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {txns.map((t) => (
                      <tr key={t.txn_id} className="border-b border-hair transition-colors last:border-0 hover:bg-surface2">
                        <td className="tnum whitespace-nowrap px-5 py-3.5 text-[13px] text-ink3">{shortDate(t.txn_date)}</td>
                        <td className="px-5 py-3.5 text-[13.5px] font-semibold">
                          {t.merchant ?? <span className="font-normal text-ink3">not printed</span>}
                        </td>
                        <td className="px-5 py-3.5">
                          <CategoryTag txnId={t.txn_id} category={t.category} merchant={t.merchant} />
                        </td>
                        <td className="px-5 py-3.5 text-[12.5px] text-ink2">
                          <CardLink accountId={t.account_id}>{t.card}</CardLink>
                        </td>
                        <td className="px-5 py-3.5 text-right">
                          <Traceable txnId={t.txn_id} className="tnum text-[13.5px] font-bold">
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
            <p className="text-[12.5px] leading-relaxed text-ink3">
              The biggest single charge in scope is{" "}
              <span className="tnum font-bold text-ink2">{formatAbs(largest[0].amount)}</span>
              {largest[0].merchant ? ` at ${largest[0].merchant}` : ""} on {longDate(largest[0].txn_date)}.
            </p>
          ) : null}
        </section>

        <p className="max-w-[76ch] text-[12.5px] leading-relaxed text-ink3">
          {readiness.months_covered < 6
            ? `A card recommendation needs at least six months of spending. You have ${readiness.months_covered}.`
            : "There is enough history here to judge a card properly."}{" "}
          Every figure came off a statement and reconciles to its own printed total. Nothing left this machine.
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

/* ── states ─────────────────────────────────────────────────────────────── */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="mx-auto flex max-w-[76rem] flex-col gap-6 px-6 pb-20 pt-10">{children}</main>
  );
}

function EngineDown() {
  return (
    <Shell>
      <PageTitle sub="The interface is fine. The local engine is not answering.">
        Nothing to show right now
      </PageTitle>
      <EngineDownPanel />
      <p className="text-[12.5px] text-ink3">
        Nothing leaves this machine. The UI only ever talks to 127.0.0.1.
      </p>
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
      <PageTitle sub="Point the engine at a folder of statement PDFs and this becomes your dashboard.">
        Let&apos;s see where your money goes
      </PageTitle>
      <State title="Read your first statements">
        <p>
          Statements are parsed locally and reconciled against their own printed totals, so every
          figure here came off a real statement.
        </p>
        <Code>.venv/bin/python -m analyser.ingest ./statements</Code>
        <p className="mt-3 text-[12.5px] text-ink3">
          Spending, balances and due dates appear from the very first statement. Six months is the
          minimum before a card recommendation can be trusted.
        </p>
      </State>
    </Shell>
  );
}
