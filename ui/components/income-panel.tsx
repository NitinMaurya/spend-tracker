/**
 * What came in.
 *
 * Income is deliberately NOT presented as the mirror image of spending, because
 * the two are not symmetrical here. Spending is known for every month a card
 * statement was read; income is known only for months a BANK statement was read.
 * Any headline that nets one against the other silently assumes the windows match.
 * They do not, so the comparison is drawn strictly over the overlap, and the
 * months left out are named on the page rather than quietly dropped.
 *
 * There is no "saved" or "left over" figure anywhere in this component, and the
 * engine does not produce one. Rent, transfers and cheques leave the current
 * account without ever touching a card, so earnings minus card spending is not
 * money kept — it is the most flattering number this dataset could produce, and
 * the least true.
 */
import { formatAbs } from "@/lib/money";
import { fullMonth, shortMonth } from "@/lib/format";
import { CountUp } from "@/components/figures";
import { Card, CardTitle, Label } from "@/components/ui";
import type { Income } from "@/lib/api";

function bare(m: Parameters<typeof formatAbs>[0]) {
  return formatAbs(m).replace(/^[A-Z]{3}\s/, "");
}

function magnitude(m: { minor: number; exponent: number } | null | undefined) {
  if (!m) return 0;
  return Math.abs(m.minor) / Math.pow(10, m.exponent);
}

/** "2026-03" -> "Mar" / "Mar ’26" at a year boundary. */
function tick(month: string, prev: string | null) {
  const y = month.slice(0, 4);
  const label = shortMonth(month);
  return prev && prev.slice(0, 4) === y ? label : `${label} ’${y.slice(2)}`;
}

export function IncomePanel({ income, scopeLabel }: { income: Income; scopeLabel: string }) {
  const months = income.months;
  if (months.length === 0) return null;

  // Geometry only — the heights are pixels, never money. Every figure printed
  // below arrives already summed by the engine (D-002, D-029).
  const peak = Math.max(...months.map((m) => Math.abs(m.earned.minor)));
  const typicalMinor = income.typical ? Math.abs(income.typical.minor) : 0;

  // A month well clear of the median is a bonus or a back-payment, not the new
  // normal. It is marked rather than smoothed away.
  const unusual = (minor: number) => typicalMinor > 0 && Math.abs(minor) > typicalMinor * 1.25;

  const pct = income.compared.card_spend_pct;
  const overlap = income.compared.months.length;

  return (
    <section className="grid gap-5 lg:grid-cols-[26rem_1fr]">
      <Card className="flex flex-col justify-between gap-6">
        <div className="flex flex-col gap-2">
          <Label>You earned</Label>
          <CountUp
            value={magnitude(income.total)}
            text={formatAbs(income.total)}
            className="figure text-[clamp(2.3rem,4.2vw,3.1rem)] text-accentInk"
          />
          <p className="text-[13px] text-ink2">
            {income.sources.length === 1 && income.sources[0].kind === "SALARY"
              ? "salary"
              : income.sources.map((s) => s.kind.toLowerCase()).join(" · ")}{" "}
            · <span className="tnum">{income.months_covered}</span>{" "}
            {income.months_covered === 1 ? "month" : "months"} on record
          </p>
        </div>

        <div className="flex items-end justify-between gap-4 border-t border-hair pt-5">
          <div className="flex flex-col gap-1">
            <Label>Typical month</Label>
            <p className="tnum text-[20px] font-bold tracking-[-.02em]">
              {income.typical ? bare(income.typical) : "—"}
            </p>
          </div>
          <div className="flex flex-col gap-1">
            <Label>Average month</Label>
            <p className="tnum text-[20px] font-bold tracking-[-.02em] text-ink2">
              {income.average ? bare(income.average) : "—"}
            </p>
          </div>
        </div>
        {income.typical && income.average
          && Math.abs(income.average.minor) > Math.abs(income.typical.minor) * 1.05 ? (
          <p className="-mt-3 text-[12px] leading-relaxed text-ink3">
            The average sits above the typical month because at least one month carried
            more than an ordinary pay cheque. The typical figure is the median, so a
            single large month cannot pass itself off as the new normal.
          </p>
        ) : null}
      </Card>

      <Card className="flex flex-col gap-4">
        <CardTitle aside={scopeLabel}>Every pay cheque</CardTitle>

        {/* The bars are scaled to the tallest month, so when one month carries a
            bonus every ordinary pay cheque is squashed into an identical stub.
            The median rule gives those months something to be read against
            without rescaling — the outlier stays visibly an outlier. */}
        <div className="relative flex flex-grow items-end gap-2" role="list">
          {typicalMinor > 0 && peak > 0 && months.length > 2 ? (
            <div aria-hidden className="pointer-events-none absolute inset-x-0"
                 style={{ bottom: 26 + Math.round((typicalMinor / peak) * 104) }}>
              <div className="border-t border-dashed border-mute" />
              <span className="absolute -top-[8px] left-0 bg-surface pr-1.5 text-[10.5px] text-ink3">
                typical
              </span>
            </div>
          ) : null}
          {months.map((m, i) => {
            const h = peak ? Math.max(3, Math.round((Math.abs(m.earned.minor) / peak) * 100)) : 3;
            const big = unusual(m.earned.minor);
            return (
              <div key={m.month} role="listitem"
                   className="flex min-w-0 flex-1 flex-col items-center justify-end gap-2"
                   title={`${fullMonth(m.month)} — ${bare(m.earned)}`}>
                <span className="tnum text-[11px] font-semibold text-ink2">
                  {bare(m.earned)}
                </span>
                <div className="flex w-full items-end justify-center" style={{ height: 104 }}>
                  <div
                    className="barGrow w-full rounded-t-[3px]"
                    style={{
                      height: `${h}%`,
                      background: big ? "var(--c2)" : "var(--accent)",
                      animationDelay: `${i * 45}ms`,
                    }}
                  />
                </div>
                <span className="whitespace-nowrap text-[11px] text-ink3">
                  {tick(m.month, i > 0 ? months[i - 1].month : null)}
                </span>
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-2 border-t border-hair pt-4">
          {pct != null && overlap > 0 ? (
            <p className="text-[13px] leading-relaxed text-ink2">
              Across the <span className="tnum font-bold">{overlap}</span>{" "}
              {overlap === 1 ? "month" : "months"} where both sides are on record, card
              spending came to{" "}
              <span className="tnum font-bold text-ink">{pct}%</span> of what you earned
              — <span className="tnum">{bare(income.compared.spent)}</span> against{" "}
              <span className="tnum">{bare(income.compared.earned)}</span>.
            </p>
          ) : null}
          <p className="text-[12px] leading-relaxed text-ink3">
            That share covers cards only. Rent, transfers and cheques leave the current
            account without touching a card, so the rest is not money kept.
            {income.spend_only_months.length ? (
              <>
                {" "}
                {income.spend_only_months.length}{" "}
                {income.spend_only_months.length === 1 ? "month has" : "months have"} card
                spending but no bank statement yet
                {" "}({income.spend_only_months.map((m) => fullMonth(m)).join(", ")}), so
                {income.spend_only_months.length === 1 ? " it is" : " they are"} left out
                of the comparison.
              </>
            ) : null}
          </p>
        </div>
      </Card>
    </section>
  );
}
