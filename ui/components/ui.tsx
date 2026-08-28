import type { ReactNode } from "react";

/* ── surfaces ────────────────────────────────────────────────────────────
   One elevation for cards, one for sheets. Nothing else. Section separation
   comes from space and hairlines, not from nesting a card inside a card.    */

export function Card({
  children, className = "", pad = true,
}: { children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section
      className={`rounded-card border border-line bg-surface shadow-card ${pad ? "p-5" : ""} ${className}`}
    >
      {children}
    </section>
  );
}

/* ── type roles ──────────────────────────────────────────────────────────
   Serif for the voice, sans for the data. Three levels, unambiguous:
   page title (serif 32) · section title (serif 20/24) · eyebrow (caps 11).  */

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h1 className="serif text-[clamp(1.65rem,3vw,2rem)] leading-tight tracking-[-.01em] text-balance">
        {children}
      </h1>
      {sub ? <p className="max-w-[76ch] text-sm leading-relaxed text-ink2">{sub}</p> : null}
    </div>
  );
}

/** A major band on the page. */
export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 className="serif text-2xl leading-snug">{children}</h2>
      {aside ? <span className="text-[13px] text-ink3">{aside}</span> : null}
    </div>
  );
}

/** A card's own heading — one step down from a section. */
export function CardTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <h3 className="serif text-lg leading-snug">{children}</h3>
      {aside ? <span className="text-xs text-ink3">{aside}</span> : null}
    </div>
  );
}

export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`eyebrow ${className}`}>{children}</span>;
}

/* ── state ───────────────────────────────────────────────────────────────
   ok/warn/bad mean STATE, never magnitude, and always ship with a glyph so
   they survive colourblindness and greyscale print.                        */

export type Tone = "ok" | "warn" | "bad" | "neutral" | "accent";

const TONES: Record<Tone, string> = {
  ok:      "bg-okSoft text-ok",
  warn:    "bg-warnSoft text-warn",
  bad:     "bg-badSoft text-bad",
  accent:  "bg-accentSoft text-accentInk",
  neutral: "border border-line bg-surface2 text-ink2",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok", warn: "text-warn", bad: "text-bad",
  accent: "text-accentInk", neutral: "text-ink2",
};

export function Chip({
  tone = "neutral", icon, children,
}: { tone?: Tone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip px-2.5 py-1 text-xs font-semibold ${TONES[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}

export function Stat({
  label, value, hint, tone,
}: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="flex flex-col gap-1">
      <Eyebrow>{label}</Eyebrow>
      <p className={`tnum text-xl font-semibold ${tone ? TONE_TEXT[tone] : ""}`}>{value}</p>
      {hint ? <p className="text-xs text-ink3">{hint}</p> : null}
    </div>
  );
}

/** The one big number on a screen. Sans, proportional figures, exactly one. */
export function Hero({
  label, value, children,
}: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-col">
      <Eyebrow>{label}</Eyebrow>
      <p className="hero-figure mt-3">{value}</p>
      {children}
    </div>
  );
}

/* ── meter ───────────────────────────────────────────────────────────────
   A ratio against a limit. The track is a lighter step of the fill's own
   ramp so severity reads across the whole bar, not just the filled part.   */

export function Meter({
  pct, label, right, tone,
}: { pct: number; label: ReactNode; right?: ReactNode; tone: "ok" | "warn" | "bad" }) {
  const fill = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad" }[tone];
  const track = { ok: "bg-okSoft", warn: "bg-warnSoft", bad: "bg-badSoft" }[tone];
  const width = Math.max(0, Math.min(100, pct));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs text-ink2">{label}</span>
        {right ? <span className={`tnum text-xs font-semibold ${TONE_TEXT[tone]}`}>{right}</span> : null}
      </div>
      <div className={`h-2 overflow-hidden rounded-full ${track}`}>
        <div className={`bar h-full rounded-full ${fill}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

/* ── tables ──────────────────────────────────────────────────────────────
   Flush inside their card — no nested box — and they scroll in their own
   container so the page body never scrolls sideways.                       */

export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="scroll-x">{children}</div>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="mono inline-grid h-5 min-w-[1.25rem] place-items-center rounded-[5px] border border-b-2 border-line bg-surface2 px-1.5 text-[11px] font-medium text-ink2">
      {children}
    </kbd>
  );
}

/* ── empty / failure ─────────────────────────────────────────────────────
   One component, one copy source. Previously every route invented its own
   ApiDownCard / FailureCard / GettingStarted with different wording.        */

export function State({
  title, children, tone = "neutral", action,
}: { title: string; children?: ReactNode; tone?: Tone; action?: ReactNode }) {
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        {tone !== "neutral" ? <Chip tone={tone}>{tone === "bad" ? "error" : tone}</Chip> : null}
        <p className="font-medium">{title}</p>
      </div>
      {children ? <div className="max-w-[70ch] text-sm leading-relaxed text-ink2">{children}</div> : null}
      {action}
    </Card>
  );
}

export function Code({ children }: { children: ReactNode }) {
  return (
    <pre className="mono scroll-x rounded-control border border-line bg-surface2 px-3 py-2 text-[13px]">
      {children}
    </pre>
  );
}

/** A plain data table, flush inside its card. */
export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <TableWrap>
      <table className="w-full min-w-[36rem] text-sm">
        <thead>
          <tr className="border-b border-line text-left">
            {head.map((h) => (
              <th key={h} scope="col" className="eyebrow px-4 py-2.5 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </TableWrap>
  );
}

/** A long explanation that should not be the first thing you read. */
export function Aside({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group rounded-card border border-line bg-surface2 px-5 py-3.5">
      <summary className="cursor-pointer list-none text-[13px] font-semibold text-ink2 marker:content-none">
        <span className="group-open:hidden">{summary} →</span>
        <span className="hidden group-open:inline">{summary} ↓</span>
      </summary>
      <div className="mt-3 flex max-w-[78ch] flex-col gap-3 text-sm leading-relaxed text-ink2">
        {children}
      </div>
    </details>
  );
}
