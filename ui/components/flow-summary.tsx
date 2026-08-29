/**
 * The period read by economic effect, next to the same period read by direction.
 *
 * A consolidated ledger naturally answers "did money enter or leave this
 * account". That is a bookkeeping question, and it gets read as an economic one.
 * They disagree constantly: paying your own card bill is money arriving on the
 * card, a wire to your family is money leaving without anything being bought,
 * and drawing a loan is money arriving that you now owe. On one axis a ledger
 * reports borrowed money as income and rent as a purchase.
 *
 * So both axes are shown, and the one that answers "was this mine" leads.
 */
import { formatMoney } from "@/lib/money";
import { Card, CardTitle, Label } from "@/components/ui";
import type { LedgerFlow, LedgerFlowTotal } from "@/lib/api";

/** Fixed order: what you earned, what it cost, then what merely moved. */
const ORDER: LedgerFlow[] = [
  "EARNED", "SPENT", "REPAID", "BORROWED", "MOVED", "REFUNDED", "UNKNOWN", "NEUTRAL",
];

const COPY: Record<LedgerFlow, { label: string; hint: string; tone: string }> = {
  EARNED:   { label: "Earned",   tone: "text-ok",   hint: "arrived from outside — yours to keep" },
  SPENT:    { label: "Spent",    tone: "",          hint: "left for good, at a merchant or in fees" },
  REPAID:   { label: "Repaid",   tone: "text-ink2", hint: "loan instalments — servicing what you already borrowed" },
  BORROWED: { label: "Borrowed", tone: "text-warn", hint: "arrived, but you owe it" },
  MOVED:    { label: "Moved",    tone: "text-ink2", hint: "between your own accounts, card bills included — earns nothing" },
  REFUNDED: { label: "Refunded", tone: "text-ok",   hint: "earlier spending reversed" },
  UNKNOWN:  { label: "Unnamed",  tone: "text-ink3", hint: "the statement never said what this was" },
  NEUTRAL:  { label: "Neutral",  tone: "text-ink3", hint: "matched adjustments — gross shown, net zero" },
};

function bare(s: string) {
  return s.replace(/^([+−-])?[A-Z]{3}\s/, "$1");
}

/** The magnitude that means something for this effect.
 *
 *  Always the larger side, never a side chosen by the effect's name. Borrowing
 *  posts as a DEBIT on the card that created the debt, so reading "money in"
 *  for it printed a confident 0.00 against a real loan. And a movement is the
 *  same money seen twice, so one side is the amount that moved -- never the sum
 *  of both.
 */
function figure(t: LedgerFlowTotal) {
  return t.money_out.minor >= t.money_in.minor ? t.money_out : t.money_in;
}

export function FlowSummary({
  totals, basis, scopeLabel,
}: { totals: LedgerFlowTotal[]; basis: string; scopeLabel: string }) {
  if (totals.length === 0) return null;

  // One currency at a time: a single sum across two currencies is a lie.
  const currency = totals[0].currency;
  const here = totals.filter((t) => t.currency === currency);
  const shown = ORDER.map((f) => here.find((t) => t.flow === f)).filter(
    (t): t is LedgerFlowTotal => Boolean(t && t.txns > 0),
  );
  if (shown.length === 0) return null;

  return (
    <Card className="flex flex-col gap-6">
      <CardTitle aside={`${currency} · ${scopeLabel}`}>Was this money mine?</CardTitle>

      <div className="grid gap-x-6 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((t) => {
          const c = COPY[t.flow];
          return (
            <div key={t.flow} className="flex flex-col gap-1">
              <Label>{c.label}</Label>
              <p className={`tnum text-[22px] font-bold tracking-[-.02em] ${c.tone}`}>
                {bare(formatMoney(figure(t)))}
              </p>
              <p className="text-[12px] leading-snug text-ink3">
                <span className="tnum">{t.txns}</span>
                {t.txns === 1 ? " row" : " rows"} · {c.hint}
              </p>
            </div>
          );
        })}
      </div>

      <p className="max-w-[76ch] border-t border-hair pt-4 text-[12.5px] leading-relaxed text-ink3">
        {basis}
      </p>
    </Card>
  );
}
