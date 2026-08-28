/**
 * Every date and label helper the app uses, in one place.
 *
 * These were previously copy-pasted across page.tsx, cards/page.tsx and
 * cards/[card]/page.tsx, which is how three screens ended up formatting the
 * same date three slightly different ways.
 *
 * Dates are not money, so arithmetic on them is fine — D-029 governs figures,
 * and every figure arrives already computed by the engine.
 */

/** Whole days from today to an ISO date. Negative means overdue. */
export function daysUntil(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  const due = Date.UTC(y, m - 1, d);
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((due - today) / 86_400_000);
}

export function dueLabel(days: number): string {
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days < 0) return `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} overdue`;
  return `in ${days} days`;
}

/** The tone a due date deserves. Overdue is bad, this week is a warning. */
export function dueTone(days: number): "bad" | "warn" | "neutral" {
  if (days < 0) return "bad";
  if (days <= 7) return "warn";
  return "neutral";
}

/**
 * Month names are a fixed three letters, not Intl's `month: "short"`.
 * en-GB renders September as "Sept" — four characters — which knocks a whole
 * column of dates out of alignment in a table set in tabular numerals.
 */
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** 12 Sep 2026 */
export function longDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MON[m - 1]} ${y}`;
}

/** 12 Sep — for dense table columns where the year is implied by the scope. */
export function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${MON[m - 1]}`;
}

/** "2026-08" → "August 2026" */
export function fullMonth(month: string): string {
  const [y, mo] = month.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleString("en", { month: "long", year: "numeric" });
}

/** "2026-08" → "Aug" */
export function shortMonth(month: string): string {
  return MON[Number(month.split("-")[1]) - 1];
}

/** GROCERIES → Groceries · HOME_SERVICES → Home services */
export function prettyCategory(c: string): string {
  return c.replace(/_/g, " ").toLowerCase().replace(/^\w/, (m) => m.toUpperCase());
}

export function formatPct(pct: number | null | undefined, digits = 1): string {
  if (pct == null) return "";
  return `${new Intl.NumberFormat("en-AE", { maximumFractionDigits: digits }).format(Math.abs(pct))}%`;
}

/** basis points → "2.5%" */
export function bpsPct(bps: number | null | undefined): string {
  if (bps == null) return "—";
  return `${new Intl.NumberFormat("en-AE", { maximumFractionDigits: 2 }).format(bps / 100)}%`;
}

/** The name to put on a card. Falls back to a de-underscored issuer. */
export function cardName(p: { product_name?: string | null; issuer: string }): string {
  return p.product_name ?? p.issuer.replace(/_/g, " ");
}

export function issuerLabel(issuer: string): string {
  return issuer.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase());
}
