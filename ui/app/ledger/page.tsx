import Link from "next/link";
import {
  ApiDown, defaultPeriod, fetchLedger, fetchLedgerCalendar,
  type Ledger, type Period,
} from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { fullMonth, longDate, prettyCategory, shortDate } from "@/lib/format";
import { Traceable } from "@/components/evidence-drawer";
import { CardLink } from "@/components/card-drawer";
import { ScopeBar } from "@/components/scope-bar";
import { EngineDownPanel } from "@/components/engine-down";
import { LedgerFilters } from "@/components/ledger-filters";
import {
  Card, CardTitle, Chip, Label, PageTitle, SectionTitle, State, TableWrap,
} from "@/components/ui";
import { FlowSummary } from "@/components/flow-summary";
import { TypePill } from "@/components/type-pill";
import { ArrowRight, Down, Up } from "@/components/icons";

export const dynamic = "force-dynamic";

/* ─────────────────────────────────────────────────────────────────────────
   Ledger — every transaction, everywhere, in one chronological list.

   The dashboard answers "what did I buy", so it sits on v_spend and can afford
   to print magnitudes. This screen answers "what happened", so it sits on
   v_transactions and prints SIGNS: a salary credit, a card repayment, a
   telegraphic transfer out of a current account and a restaurant bill are four
   different events, and flattening them into one column of positive numbers
   would be the single worst thing this page could do.

   Nothing here adds money. Money in, money out and the net are summed by the
   engine, per currency, with transfer legs left out so a card payment that
   appears on both the card and the funding account is never counted twice.
   ───────────────────────────────────────────────────────────────────────── */

const PAGE_SIZE = 100;

const ACCOUNT_KIND: Record<string, string> = {
  CREDIT_CARD: "Credit card",
  BANK: "Bank account",
  CREDIT_FACILITY: "Credit facility",
};

/**
 * Drop the currency code from an already-formatted figure. Purely typographic:
 * the code is printed once, on the heading above, and this never touches minor
 * units or the exponent (D-029).
 */
function bare(formatted: string): string {
  return formatted.replace(/^([+\u2212]?)[A-Z]{3}\s/, "$1");
}

/** Unknown kinds are titled, not dropped: the engine may learn a new one. */
function accountKind(t: string): string {
  return ACCOUNT_KIND[t] ?? prettyCategory(t);
}

export default async function LedgerPage({
  searchParams,
}: {
  searchParams: Promise<{
    from?: string; to?: string; label?: string;
    account?: string; type?: string; flow?: string; direction?: string;
    q?: string; offset?: string;
  }>;
}) {
  const sp = await searchParams;
  const cal = await fetchLedgerCalendar().catch(() => null);
  const explicit = Boolean(sp.from || sp.to || sp.label);
  const period: Period = explicit
    ? { from: sp.from, to: sp.to, label: sp.label ?? "All time" }
    : defaultPeriod(cal?.default_year ?? null);

  const offset = Math.max(0, Number(sp.offset ?? 0) || 0);
  const direction = sp.direction === "in" || sp.direction === "out" ? sp.direction : undefined;

  let ledger: Ledger;
  try {
    ledger = await fetchLedger(period, {
      account_id: sp.account,
      txn_type: sp.type,
      flow: sp.flow,
      direction,
      q: sp.q,
      limit: PAGE_SIZE,
      offset,
    });
  } catch (err) {
    if (err instanceof ApiDown) return <EngineDown />;
    return <Failed message={err instanceof Error ? err.message : String(err)} />;
  }

  const { page, totals, facets } = ledger;
  // One currency in scope means the code can live in the column header instead of
  // on all hundred rows. Two means every row has to say which it is.
  const oneCurrency = totals.by_currency.length <= 1;
  const currency = totals.by_currency[0]?.currency ?? "AED";

  const scopeLabel =
    period.label === "All time" ? "every statement on record"
      : /^\d{4}$/.test(period.label) ? period.label
      : fullMonth(period.label);

  const first = page.total === 0 ? 0 : page.offset + 1;
  const last = page.offset + page.returned;

  const pageHref = (nextOffset: number) => {
    const s = new URLSearchParams();
    if (period.from) s.set("from", period.from);
    if (period.to) s.set("to", period.to);
    if (period.label !== "All time") s.set("label", period.label);
    if (sp.account) s.set("account", sp.account);
    if (sp.type) s.set("type", sp.type);
    if (sp.flow) s.set("flow", sp.flow);
    if (direction) s.set("direction", direction);
    if (sp.q) s.set("q", sp.q);
    if (nextOffset > 0) s.set("offset", String(nextOffset));
    const query = s.toString();
    return query ? `/ledger?${query}` : "/ledger";
  };

  return (
    <>
      <ScopeBar
        years={cal?.years ?? []}
        label={period.label}
        note={period.label === "All time" ? "every account, every statement" : undefined}
      />

      <main id="main" className="mx-auto flex max-w-[76rem] flex-col gap-8 px-6 pb-20 pt-7">
        <PageTitle sub="Every transaction on every account in one chronological list — credit cards, bank accounts and the credit facility together. Money leaving and money arriving are kept apart, and nothing is filtered out of the list.">
          Ledger
        </PageTitle>

        {/* what it MEANT — the axis that answers "was this mine" leads, because
            direction alone reads a card repayment as income. */}
        {totals.by_flow.length ? (
          <section className="enter flex flex-col gap-4">
            <SectionTitle aside={scopeLabel}>Where the money stood</SectionTitle>
            <FlowSummary
              totals={totals.by_flow}
              basis={totals.flow_basis}
              scopeLabel={scopeLabel}
            />
          </section>
        ) : null}

        {/* what moved */}
        <section className="enter flex flex-col gap-4">
          <SectionTitle aside={scopeLabel}>The period in two directions</SectionTitle>

          {totals.by_currency.length === 0 ? (
            <State title="Nothing moved in this window.">
              No transaction on any account falls inside {scopeLabel}.
            </State>
          ) : (
            <div className={`grid gap-5 ${
              totals.by_currency.length > 1 ? "lg:grid-cols-2" : ""}`}>
              {totals.by_currency.map((t) => (
                <Card key={t.currency} className="flex flex-col gap-6">
                  {/* The code sits in the card's heading, so the three figures
                      below can be read as one column of digits rather than
                      wrapping "AED" onto its own line. */}
                  <CardTitle aside={`${t.currency} · ${t.counted_rows} rows counted`}>
                    What moved
                  </CardTitle>
                  <div className="grid gap-6 sm:grid-cols-3">
                    <Flow
                      label="Money in"
                      value={bare(formatMoney(t.money_in))}
                      hint={`${t.in_count} credit${t.in_count === 1 ? "" : "s"}`}
                      inbound
                    />
                    <Flow
                      label="Money out"
                      value={bare(formatMoney(t.money_out))}
                      hint={`${t.out_count} debit${t.out_count === 1 ? "" : "s"}`}
                    />
                    <div className="flex flex-col gap-1 sm:border-l sm:border-hair sm:pl-6">
                      <Label>Net</Label>
                      <p className={`tnum text-[22px] font-bold tracking-[-.02em] ${
                        t.net.minor >= 0 ? "text-ok" : ""}`}>
                        {bare(formatMoney(t.net, { sign: true }))}
                      </p>
                      <p className="text-[12.5px] text-ink3">
                        {t.net.minor >= 0 ? "more arrived than left" : "more left than arrived"}
                      </p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {page.total === 0 ? null : (
          <p className="max-w-[76ch] text-[12.5px] leading-relaxed text-ink3">
            {totals.basis}{" "}
            {totals.omitted_rows > 0 ? (
              <>
                <span className="tnum font-bold text-ink2">{totals.omitted_rows}</span>{" "}
                row{totals.omitted_rows === 1 ? " is" : "s are"} left out of the figures on
                that basis
                {totals.transfer_legs > 0
                  ? ` (${totals.transfer_legs} transfer leg${totals.transfer_legs === 1 ? "" : "s"})`
                  : ""}
                {totals.excluded_rows > 0
                  ? `${totals.transfer_legs > 0 ? " and" : ""} ${totals.excluded_rows} struck out`
                  : ""}
                . They are still listed below, labelled.
              </>
            ) : (
              "No transfer leg or struck-out row falls in this window, so every row below is counted."
            )}{" "}
            A debit on a bank account is not card spending, which is why the account and the
            type sit in their own columns rather than being netted into one figure.
          </p>
          )}
        </section>

        {/* the ledger */}
        <section className="flex flex-col gap-4">
          <SectionTitle aside="any row's category can be changed in place, and any amount opens its statement line">
            Every transaction
          </SectionTitle>

          <Card pad={false} className="overflow-hidden">
            <LedgerFilters facets={facets} />

            {page.total === 0 ? (
              <p className="px-5 py-12 text-center text-sm text-ink3">
                No transaction matches this scope and these filters.
              </p>
            ) : (
              <TableWrap>
                <table className="w-full min-w-[46rem] text-sm">
                  <caption className="sr-only">
                    Every transaction across every account, newest first
                  </caption>
                  <thead>
                    <tr className="border-b border-hair text-left">
                      {["Date", "Account", "Type", "Description"].map((h) => (
                        <th key={h} scope="col"
                            className="px-5 py-3 text-[12.5px] font-semibold text-ink3">
                          {h}
                        </th>
                      ))}
                      <th scope="col"
                          className="px-5 py-3 text-right text-[12.5px] font-semibold text-ink3">
                        {oneCurrency ? `Amount (${currency})` : "Amount"}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.rows.map((r) => {
                      const inbound = r.direction === "IN";
                      const dimmed = !r.counted;
                      return (
                        <tr
                          key={r.txn_id}
                          className={`border-b border-hair transition-colors last:border-0 hover:bg-surface2 ${
                            dimmed ? "opacity-70" : ""}`}
                        >
                          <td className="tnum whitespace-nowrap px-5 py-3.5 text-[13px] text-ink3">
                            <span title={longDate(r.txn_date)}>{shortDate(r.txn_date)}</span>
                            <span className="ml-1.5 text-[11px] text-ink3">
                              &rsquo;{r.txn_date.slice(2, 4)}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-5 py-3.5">
                            <CardLink accountId={r.account_id}
                                      className="block text-[13px] font-semibold">
                              {r.card}
                            </CardLink>
                            <span className="block text-[11px] text-ink3">
                              {accountKind(r.account_type)}
                            </span>
                          </td>
                          <td className="whitespace-nowrap px-5 py-3.5">
                            <TypePill txnType={r.txn_type} flow={r.flow} />
                          </td>
                          <td className="px-5 py-3.5">
                            <div className="flex max-w-[28rem] items-center gap-2">
                              <span
                                className="truncate text-[13.5px] font-semibold"
                                title={r.raw_description ?? r.merchant ?? undefined}
                              >
                                {r.merchant ?? r.raw_description ?? (
                                  <span className="font-normal text-ink3">not printed</span>
                                )}
                              </span>
                              {r.is_transfer ? <Chip tone="neutral">transfer leg</Chip> : null}
                              {r.excluded ? <Chip tone="warn">struck out</Chip> : null}
                            </div>
                          </td>
                          <td className="whitespace-nowrap px-5 py-3.5 text-right">
                            <Traceable
                              txnId={r.txn_id}
                              className={`tnum inline-flex items-center gap-1.5 text-[13.5px] font-bold ${
                                inbound ? "text-ok" : ""}`}
                            >
                              {inbound ? <Up size={12} /> : <Down size={12} />}
                              {oneCurrency
                                ? formatMoney(r.amount, { sign: true })
                                    .replace(/^([+−])[A-Z]{3}\s/, "$1")
                                : formatMoney(r.amount, { sign: true })}
                            </Traceable>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </TableWrap>
            )}

            {page.total > 0 ? (
              <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface2 px-5 py-3.5">
                <span className="text-[12.5px] text-ink3">
                  Showing <span className="tnum font-bold text-ink2">{first}–{last}</span> of{" "}
                  <span className="tnum font-bold text-ink2">{page.total}</span>
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <PageLink
                    href={pageHref(Math.max(0, page.offset - page.limit))}
                    disabled={page.offset === 0}
                  >
                    Newer
                  </PageLink>
                  <PageLink
                    href={pageHref(page.offset + page.limit)}
                    disabled={!page.has_more}
                    trailing
                  >
                    Older
                  </PageLink>
                </div>
              </div>
            ) : null}
          </Card>

          {ledger.range.first && ledger.range.last ? (
            <p className="text-[12.5px] leading-relaxed text-ink3">
              This window runs from {longDate(ledger.range.first)} to{" "}
              {longDate(ledger.range.last)}. Every row came off a statement, and clicking an
              amount shows the line it was read from.
            </p>
          ) : null}
        </section>
      </main>
    </>
  );
}

/** Label above a value, with the direction carried by colour, glyph AND word. */
function Flow({
  label, value, hint, inbound = false,
}: { label: string; value: string; hint: string; inbound?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      <p className={`tnum flex items-center gap-1.5 text-[22px] font-bold tracking-[-.02em] ${
        inbound ? "text-ok" : ""}`}>
        {inbound ? <Up size={15} /> : <Down size={15} />}
        {value}
      </p>
      <p className="text-[12.5px] text-ink3">{hint}</p>
    </div>
  );
}

function PageLink({
  href, disabled, trailing = false, children,
}: { href: string; disabled: boolean; trailing?: boolean; children: React.ReactNode }) {
  const cls =
    "inline-flex h-8 items-center gap-1.5 rounded-full border border-line px-3.5 text-[12.5px] font-bold";
  if (disabled) {
    return <span className={`${cls} bg-surface text-ink3 opacity-50`} aria-disabled>{children}</span>;
  }
  return (
    <Link href={href} className={`${cls} bg-surface text-ink2 transition-colors hover:border-accent hover:text-ink`}>
      {trailing ? null : <ArrowRight size={13} className="rotate-180" />}
      {children}
      {trailing ? <ArrowRight size={13} /> : null}
    </Link>
  );
}

/* ── states ─────────────────────────────────────────────────────────────── */

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="mx-auto flex max-w-[76rem] flex-col gap-6 px-6 pb-20 pt-10">
      {children}
    </main>
  );
}

function EngineDown() {
  return (
    <Shell>
      <PageTitle sub="The interface is fine. The local engine is not answering.">
        The ledger needs the engine
      </PageTitle>
      <EngineDownPanel />
    </Shell>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <Shell>
      <PageTitle sub="The engine answered, but not with a ledger this screen can show.">
        Could not load the ledger
      </PageTitle>
      <State title={message} tone="bad" />
    </Shell>
  );
}
