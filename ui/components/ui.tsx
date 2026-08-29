import type { ReactNode } from "react";

/* ── surfaces ────────────────────────────────────────────────────────────
   One card radius, one elevation for cards and one for sheets. Cards group
   related figures; they are never nested and never the page's only structure. */

export function Card({
  children, className = "", pad = true,
}: { children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`rounded-card border border-line bg-surface shadow-card ${pad ? "p-6" : ""} ${className}`}>
      {children}
    </section>
  );
}

/* ── type ────────────────────────────────────────────────────────────────
   Headings carry their own weight. Nothing sits above them. */

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="text-[clamp(1.6rem,2.6vw,2.05rem)] font-extrabold leading-tight tracking-[-.03em] text-balance">
        {children}
      </h1>
      {sub ? <p className="max-w-[68ch] text-[15px] leading-relaxed text-ink2">{sub}</p> : null}
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 className="text-[19px] font-bold leading-snug tracking-[-.02em]">{children}</h2>
      {aside ? <span className="text-[13px] text-ink3">{aside}</span> : null}
    </div>
  );
}

export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h3 className="text-[15px] font-bold tracking-[-.01em]">{children}</h3>
      {aside ? <span className="text-[12.5px] text-ink3">{aside}</span> : null}
    </div>
  );
}

/**
 * The label above a VALUE in a stat tile, never above a heading. Sentence case,
 * because the uppercase wide-tracked variant is the this design refuses.
 */
export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`text-[12.5px] font-medium text-ink3 ${className}`}>{children}</span>;
}

/* ── state ───────────────────────────────────────────────────────────────
   Always colour plus a glyph plus a word, so it survives CVD and greyscale. */

export type Tone = "ok" | "warn" | "bad" | "neutral" | "accent";

const TONES: Record<Tone, string> = {
  ok:      "bg-okSoft text-ok",
  warn:    "bg-warnSoft text-warn",
  bad:     "bg-badSoft text-bad",
  accent:  "bg-accentSoft text-accentInk",
  neutral: "border border-line bg-surface2 text-ink2",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok", warn: "text-warn", bad: "text-bad", accent: "text-accentInk", neutral: "text-ink2",
};

export function Chip({
  tone = "neutral", icon, children,
}: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-bold ${TONES[tone]}`}>
      {icon}
      {children}
    </span>
  );
}

/** Label above value. The tile is the dashboard's atom. */
export function Stat({
  label, value, hint, tone,
}: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="flex flex-col gap-1">
      <Label>{label}</Label>
      <p className={`tnum text-[22px] font-bold tracking-[-.02em] ${tone ? TONE_TEXT[tone] : ""}`}>{value}</p>
      {hint ? <p className="text-[12.5px] text-ink3">{hint}</p> : null}
    </div>
  );
}

/* ── meter ───────────────────────────────────────────────────────────────
   The track is a lighter step of the fill's own ramp, so severity reads across
   the whole bar rather than only the filled part. */

export function Meter({
  pct, label, right, tone,
}: { pct: number; label: ReactNode; right?: ReactNode; tone: "ok" | "warn" | "bad" }) {
  const fill = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad" }[tone];
  const track = { ok: "bg-okSoft", warn: "bg-warnSoft", bad: "bg-badSoft" }[tone];
  const width = Math.max(0, Math.min(100, pct));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12.5px] text-ink2">{label}</span>
        {right ? <span className={`tnum text-[12.5px] font-bold ${TONE_TEXT[tone]}`}>{right}</span> : null}
      </div>
      <div className={`h-2 overflow-hidden rounded-full ${track}`}>
        <div className={`barGrow h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

/* ── tables ─────────────────────────────────────────────────────────────── */

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="scroll-x">{children}</div>;
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <TableWrap>
      <table className="w-full min-w-[36rem] text-sm">
        <thead>
          <tr className="border-b border-line text-left">
            {head.map((h) => (
              <th key={h} scope="col" className="px-4 py-3 text-[12.5px] font-semibold text-ink3">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </TableWrap>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="mono inline-grid h-5 min-w-[1.25rem] place-items-center rounded-[6px] border border-line bg-surface2 px-1.5 text-[11px] font-medium text-ink2 shadow-[0_1px_0_var(--line)]">
      {children}
    </kbd>
  );
}

/* ── states: one component, one copy source ─────────────────────────────── */

export function State({
  title, children, tone = "neutral", action,
}: { title: string; children?: ReactNode; tone?: Tone; action?: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        {tone !== "neutral" ? <Chip tone={tone}>{tone === "bad" ? "error" : tone}</Chip> : null}
        <p className="text-[15px] font-bold">{title}</p>
      </div>
      {children ? <div className="max-w-[68ch] text-sm leading-relaxed text-ink2">{children}</div> : null}
      {action}
    </Card>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="mono scroll-x rounded-control border border-line bg-surface2 px-3 py-2.5 text-[13px]">
      {children}
    </pre>
  );
}

export function Aside({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group rounded-card border border-line bg-surface2 px-5 py-4">
      <summary className="cursor-pointer list-none text-[13.5px] font-bold text-ink2 marker:content-none">
        <span className="group-open:hidden">{summary}</span>
        <span className="hidden group-open:inline">{summary}</span>
      </summary>
      <div className="mt-3 flex max-w-[70ch] flex-col gap-3 text-sm leading-relaxed text-ink2">
        {children}
      </div>
    </details>
  );
}
