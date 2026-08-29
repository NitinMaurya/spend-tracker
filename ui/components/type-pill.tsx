/**
 * What a ledger row IS, as a pill.
 *
 * The label is the transaction type; the tint is its effect on net worth. That
 * pairing is deliberate — the type alone cannot tell you whether a row mattered,
 * and the effect alone is too coarse to identify a row. Together the column
 * answers both at a glance.
 *
 * Restraint is the whole design here. Ordinary spending is the overwhelming
 * majority of any ledger — 458 rows out of 476 on the author's own data — so if
 * every row were tinted the table would read as stripes and the two rows that
 * genuinely deserve attention would be lost in them. Spending therefore gets the
 * quietest possible treatment and colour is spent only where it says something:
 * money earned, money borrowed, money that never got named.
 *
 * Identity is never colour alone — every pill carries its word.
 */
import type { LedgerFlow } from "@/lib/api";

/** Shorter than the enum, and in the words a statement would use. */
const LABEL: Record<string, string> = {
  PURCHASE: "Purchase",
  PAYMENT: "Card payment",
  TRANSFER: "Transfer",
  CHEQUE: "Cheque",
  CASH_WITHDRAWAL: "Cash out",
  CASH_ADVANCE: "Cash advance",
  LOAN_DISBURSED: "Loan drawn",
  LOAN_REPAYMENT: "Instalment",
  SALARY: "Salary",
  INCOME: "Income",
  FEE: "Fee",
  INTEREST: "Interest",
  REFUND: "Refund",
  REVERSAL: "Reversal",
  ADJUSTMENT: "Adjustment",
  UNKNOWN: "Unnamed",
};

/** Tint by effect, not by type. Spending stays deliberately silent. */
const TINT: Record<LedgerFlow, string> = {
  SPENT:    "border-hair bg-transparent text-ink2",
  EARNED:   "border-transparent bg-okSoft text-ok",
  REFUNDED: "border-transparent bg-okSoft text-ok",
  BORROWED: "border-transparent bg-warnSoft text-warn",
  UNKNOWN:  "border-transparent bg-warnSoft text-warn",
  MOVED:    "border-transparent bg-surface2 text-ink2",
  REPAID:   "border-transparent bg-surface2 text-ink2",
  NEUTRAL:  "border-transparent bg-surface2 text-ink3",
};

/** Fall back to the raw value rather than hiding a type added after this file. */
function label(txnType: string) {
  return LABEL[txnType]
    ?? txnType.replace(/_/g, " ").toLowerCase().replace(/^\w/, (m) => m.toUpperCase());
}

export function TypePill({ txnType, flow }: { txnType: string; flow: LedgerFlow }) {
  return (
    <span
      className={`inline-flex h-[22px] max-w-full items-center truncate whitespace-nowrap rounded-full border px-2.5 text-[11.5px] font-semibold ${
        TINT[flow] ?? TINT.SPENT
      }`}
      title={`${label(txnType)} · ${flow.toLowerCase()}`}
    >
      {label(txnType)}
    </span>
  );
}
