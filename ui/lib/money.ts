/**
 * Money crosses the wire as {minor, currency, exponent} and is formatted using the
 * STORED exponent (D-020a). Never divide by 100: KWD/BHD/OMR use 3 decimals and
 * JPY/KRW use 0, so a hardcoded 100 corrupts them silently.
 *
 * No arithmetic on money happens in TypeScript. The Python engine is the single
 * source of truth for every figure (D-002, D-008, D-029).
 */
export type Money = { minor: number; currency: string; exponent: number };

export function formatMoney(m: Money | null | undefined, opts?: { sign?: boolean }): string {
  if (!m) return "—";
  const value = m.minor / Math.pow(10, m.exponent);
  const body = new Intl.NumberFormat("en-AE", {
    minimumFractionDigits: m.exponent,
    maximumFractionDigits: m.exponent,
  }).format(Math.abs(value));
  const negative = m.minor < 0;
  const prefix = opts?.sign ? (negative ? "−" : "+") : negative ? "−" : "";
  return `${prefix}${m.currency} ${body}`;
}

/** Magnitude only — for spend tables where the direction is already implied. */
export function formatAbs(m: Money | null | undefined): string {
  if (!m) return "—";
  return formatMoney({ ...m, minor: Math.abs(m.minor) });
}

export function isNegative(m?: Money | null): boolean {
  return !!m && m.minor < 0;
}
