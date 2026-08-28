"use client";

/**
 * Charts.
 *
 * Two rules decide everything here, and both correct what this app used to do:
 *
 * 1. CATEGORIES ARE NOMINAL, so every bar in a ranking is the SAME hue. The old
 *    CategoryBars painted a different colour per category, which double-encodes
 *    bar length as hue, burns the only free channel on information the chart
 *    already shows, and fails the categorical colour checks by design.
 * 2. A single series over time gets ONE hue — a 10% wash under a 2px line — not
 *    a slot from the categorical palette.
 *
 * Categorical hues are reserved for the Plan comparison, where the cards
 * genuinely are the subject. See app/globals.css for the palette contract.
 */

import { formatAbs } from "@/lib/money";
import type { Money } from "@/lib/money";
import { prettyCategory, shortMonth } from "@/lib/format";

/* ── trend ───────────────────────────────────────────────────────────────── */

const W = 640, H = 192, L = 40, R = 620, BASE = 150, TOP = 20;

/** Round a maximum up to something whose halfway point is also clean. */
function niceMax(v: number): number {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const step = mag / 2;
  return Math.ceil(v / step) * step;
}

function compact(v: number): string {
  // Round to one decimal below 10k: an axis reading "7k" against a 6,500
  // gridline is a wrong label, not a tidy one.
  if (v >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}m`;
  if (v >= 10_000) return `${Math.round(v / 1_000)}k`;
  if (v >= 1_000) return `${+(v / 1_000).toFixed(1)}k`;
  return String(Math.round(v));
}

export function TrendArea({
  points, activeMonth,
}: {
  points: { month: string; value: Money }[];
  activeMonth?: string | null;
}) {
  if (points.length === 0) {
    return <p className="text-sm text-ink3">No month has closed yet.</p>;
  }

  const exp = points[0].value.exponent;
  const vals = points.map((p) => Math.abs(p.value.minor) / Math.pow(10, exp));
  const top = niceMax(Math.max(...vals));
  const n = points.length;

  const x = (i: number) => (n === 1 ? (L + R) / 2 : L + (i * (R - L)) / (n - 1));
  const y = (v: number) => BASE - (v / top) * (BASE - TOP);

  const pts = vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  const line = `M${pts.join(" L")}`;
  const area = `${line} L${x(n - 1).toFixed(1)},${BASE} L${x(0).toFixed(1)},${BASE} Z`;

  // The path length is unknown before layout, so overshoot the dash so the draw
  // always starts fully hidden.
  const dash = Math.ceil((R - L) * 1.6);

  const lastI = n - 1;
  const peakI = vals.indexOf(Math.max(...vals));
  const activeI = activeMonth ? points.findIndex((p) => p.month === activeMonth) : lastI;
  const markI = activeI >= 0 ? activeI : lastI;

  // Label every month when there is room, else roughly every other one.
  const stride = n > 14 ? Math.ceil(n / 12) : 1;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full overflow-visible"
      role="img"
      aria-label={`Monthly spend, ${points.length} months, peaking at ${formatAbs(points[peakI].value)}.`}
    >
      {/* recessive grid: solid hairlines one step off the surface, never dashed */}
      <line x1={L} y1={BASE} x2={R} y2={BASE} stroke="var(--line)" strokeWidth="1" />
      <line x1={L} y1={(BASE + TOP) / 2} x2={R} y2={(BASE + TOP) / 2} stroke="var(--hair)" strokeWidth="1" />
      <line x1={L} y1={TOP} x2={R} y2={TOP} stroke="var(--hair)" strokeWidth="1" />
      <text x={L - 6} y={BASE + 4} textAnchor="end" className="tnum" style={{ fontSize: 10, fill: "var(--ink-3)" }}>0</text>
      <text x={L - 6} y={(BASE + TOP) / 2 + 4} textAnchor="end" className="tnum" style={{ fontSize: 10, fill: "var(--ink-3)" }}>
        {compact(top / 2)}
      </text>
      <text x={L - 6} y={TOP + 4} textAnchor="end" className="tnum" style={{ fontSize: 10, fill: "var(--ink-3)" }}>
        {compact(top)}
      </text>

      {/* A wash, never a saturated block. The fade lives on a WRAPPER: putting
          it on the path itself let the keyframe animate opacity to 1, so the
          10% wash rendered as a solid slab that swallowed the line. */}
      <g className="washed">
        <path d={area} fill="var(--accent)" opacity=".10" />
      </g>
      <path
        className="drawn"
        d={line}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{ strokeDasharray: dash, strokeDashoffset: dash }}
      />

      {/* the scoped month, marked once */}
      <g className="washed">
        <line
          x1={x(markI)} y1={y(vals[markI])} x2={x(markI)} y2={BASE}
          stroke="var(--accent)" strokeWidth="1" opacity=".3"
        />
      </g>
      {/* 8px marker with a 2px surface ring so it stays legible over the line */}
      <circle className="dot" cx={x(markI)} cy={y(vals[markI])} r="4.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />

      {/* ONE direct label — the endpoint. Never a number on every point. */}
      <g className="dot">
        <rect
          x={Math.min(R - 88, Math.max(L, x(markI) - 44))} y={Math.max(0, y(vals[markI]) - 30)}
          width="88" height="22" rx="6" fill="var(--surface)" stroke="var(--line)"
        />
        <text
          x={Math.min(R - 44, Math.max(L + 44, x(markI)))} y={Math.max(15, y(vals[markI]) - 15)}
          textAnchor="middle" className="tnum"
          style={{ fontSize: 11, fontWeight: 600, fill: "var(--ink)" }}
        >
          {formatAbs(points[markI].value).replace(/^[A-Z]{3}\s/, "")}
        </text>
      </g>

      {points.map((p, i) =>
        i % stride === 0 || i === lastI ? (
          <text
            key={p.month}
            x={x(i)} y={BASE + 22} textAnchor="middle"
            style={{
              fontSize: 10,
              fill: i === markI ? "var(--ink)" : "var(--ink-3)",
              fontWeight: i === markI ? 600 : 400,
            }}
          >
            {shortMonth(p.month)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

/* ── category ranking ────────────────────────────────────────────────────── */

/** How many categories keep their own row before the tail folds into one. */
const KEEP = 7;

export function CategoryBars({
  rows, onSelect,
}: {
  rows: { label: string; value: Money; pct: number; txns?: number }[];
  onSelect?: (category: string) => void;
}) {
  if (rows.length === 0) return <p className="text-sm text-ink3">Nothing categorised yet.</p>;

  const sorted = rows.slice().sort((a, b) => Math.abs(b.value.minor) - Math.abs(a.value.minor));
  const head = sorted.slice(0, KEEP);
  const tail = sorted.slice(KEEP);
  const peak = Math.abs(sorted[0].value.minor) || 1;

  const tailTotal = tail.reduce((n, r) => n + Math.abs(r.value.minor), 0);
  const exp = sorted[0].value.exponent;
  const currency = sorted[0].value.currency;

  return (
    <div className="flex flex-col gap-3">
      {head.map((r, i) => {
        const w = (Math.abs(r.value.minor) / peak) * 100;
        const body = (
          <>
            <span className="w-[7.5rem] shrink-0 truncate text-[13px] text-ink2">
              {prettyCategory(r.label)}
            </span>
            <span className="h-3.5 flex-grow">
              <span
                className="bar block h-3.5 rounded-r-[4px] bg-accent"
                style={{ width: `${w}%`, animationDelay: `${120 + i * 60}ms` }}
              />
            </span>
            <span className="tnum w-16 shrink-0 text-right text-[13px] font-semibold">
              {formatAbs(r.value).replace(/^[A-Z]{3}\s/, "")}
            </span>
          </>
        );
        return onSelect ? (
          <button
            key={r.label}
            type="button"
            onClick={() => onSelect(r.label)}
            title={r.txns != null ? `${r.txns} transaction${r.txns === 1 ? "" : "s"}` : undefined}
            className="flex items-center gap-3 rounded-control text-left transition-opacity hover:opacity-80"
          >
            {body}
          </button>
        ) : (
          <div key={r.label} className="flex items-center gap-3">
            {body}
          </div>
        );
      })}

      {tail.length ? (
        <div className="flex items-center gap-3">
          <span className="w-[7.5rem] shrink-0 text-[13px] text-ink3">
            Everything else
            <span className="text-ink3"> · {tail.length}</span>
          </span>
          <span className="h-3.5 flex-grow">
            <span
              className="bar block h-3.5 rounded-r-[4px] bg-mute opacity-50"
              style={{ width: `${(tailTotal / peak) * 100}%`, animationDelay: `${120 + KEEP * 60}ms` }}
            />
          </span>
          <span className="tnum w-16 shrink-0 text-right text-[13px] font-semibold text-ink2">
            {formatAbs({ minor: tailTotal, currency, exponent: exp }).replace(/^[A-Z]{3}\s/, "")}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/* ── comparison bars — the ONE place categorical hues are used ───────────── */

export const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"] as const;

export function SeriesLegend({ items }: { items: { label: string; note?: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((it, i) => (
        <span key={it.label} className="inline-flex items-center gap-2 text-xs text-ink2">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-[3px]"
            style={{ background: SERIES[i % SERIES.length] }}
          />
          {it.label}
          {it.note ? <span className="font-semibold text-accentInk">{it.note}</span> : null}
        </span>
      ))}
    </div>
  );
}

/** Grouped horizontal bars, direct-labelled — mandatory above 3 series. */
export function CompareBars({
  rows,
}: {
  rows: { label: string; value: Money; emphasis?: boolean }[];
}) {
  if (!rows.length) return null;
  const peak = Math.max(...rows.map((r) => Math.abs(r.value.minor))) || 1;
  return (
    <div className="flex flex-col gap-3.5">
      {rows.map((r, i) => (
        <div key={r.label} className="flex items-center gap-3.5">
          <span className={`w-28 shrink-0 truncate text-[13px] ${r.emphasis ? "font-semibold" : "text-ink2"}`}>
            {r.label}
          </span>
          <span className="h-5 flex-grow">
            <span
              className="bar block h-5 rounded-r-[4px]"
              style={{
                width: `${(Math.abs(r.value.minor) / peak) * 100}%`,
                background: SERIES[i % SERIES.length],
                animationDelay: `${140 + i * 90}ms`,
              }}
            />
          </span>
          <span className="tnum w-[4.75rem] shrink-0 text-right text-sm font-semibold">
            {formatAbs(r.value).replace(/^[A-Z]{3}\s/, "")}
          </span>
        </div>
      ))}
    </div>
  );
}
