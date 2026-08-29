"use client";

/**
 * Charts.
 *
 * Colour is assigned by FIXED SLOT, never by rank, so filtering a category out
 * never repaints the survivors. Six slots exist and no seventh: the palette is
 * validated for colour-vision deficiency in both modes at exactly that count,
 * and the tail folds into a neutral. Every slice and bar is direct-labelled,
 * which is the secondary encoding the palette's CVD band requires.
 */

import { useState } from "react";
import { formatAbs } from "@/lib/money";
import type { Money } from "@/lib/money";
import { prettyCategory, shortMonth } from "@/lib/format";

export const SLOTS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"] as const;
const TAIL = "var(--mute)";
const KEEP = 6;

function bare(m: Money | null | undefined) {
  return formatAbs(m).replace(/^[A-Z]{3}\s/, "");
}

type Row = { label: string; value: Money; pct: number; txns?: number };

function split(rows: Row[]) {
  const sorted = rows.slice().sort((a, b) => Math.abs(b.value.minor) - Math.abs(a.value.minor));
  const head = sorted.slice(0, KEEP);
  const tail = sorted.slice(KEEP);
  const tailMinor = tail.reduce((n, r) => n + Math.abs(r.value.minor), 0);
  const tailPct = tail.reduce((n, r) => n + r.pct, 0);
  return { head, tail, tailMinor, tailPct, sorted };
}

/* ── donut ──────────────────────────────────────────────────────────────── */

export function CategoryDonut({
  rows, total, onSelect,
}: { rows: Row[]; total: Money | null; onSelect?: (category: string) => void }) {
  const [hot, setHot] = useState<string | null>(null);
  if (rows.length === 0) return <p className="text-sm text-ink3">Nothing categorised yet.</p>;

  const { head, tail, tailMinor, tailPct } = split(rows);
  const exp = head[0].value.exponent;
  const currency = head[0].value.currency;

  const segs = [
    ...head.map((r, i) => ({
      key: r.label,
      name: prettyCategory(r.label),
      pct: r.pct,
      value: r.value,
      colour: SLOTS[i],
      selectable: true,
    })),
    ...(tail.length
      ? [{
          key: "__tail",
          name: `${tail.length} more`,
          pct: tailPct,
          value: { minor: tailMinor, currency, exponent: exp } as Money,
          colour: TAIL,
          selectable: false,
        }]
      : []),
  ];

  // Geometry: a 2px surface gap separates touching arcs, per the mark spec.
  const R = 76, STROKE = 26, C = 2 * Math.PI * R;
  const GAP = 2.2;
  let cursor = 0;

  return (
    <div className="flex flex-col items-center gap-7 sm:flex-row sm:items-center sm:gap-8">
      <div className="relative shrink-0">
        <svg width="196" height="196" viewBox="0 0 196 196" role="img"
             aria-label={`Spending by category, ${segs.length} groups, largest ${segs[0].name}.`}>
          <g transform="translate(98,98) rotate(-90)">
            <circle r={R} fill="none" stroke="var(--hair)" strokeWidth={STROKE} />
            {segs.map((s) => {
              const len = Math.max(0, (s.pct / 100) * C - GAP);
              const off = -cursor;
              cursor += (s.pct / 100) * C;
              const dim = hot !== null && hot !== s.key;
              return (
                <circle
                  key={s.key}
                  className="sweep"
                  r={R}
                  fill="none"
                  stroke={s.colour}
                  strokeWidth={STROKE}
                  strokeLinecap="butt"
                  strokeDasharray={`${len} ${C - len}`}
                  strokeDashoffset={off}
                  opacity={dim ? 0.28 : 1}
                  style={{
                    // sweep animates dashoffset from a fully-closed ring
                    ["--dash-to" as string]: String(off),
                    strokeDashoffset: off + C,
                    animationDelay: "180ms",
                    transition: "opacity .18s ease-out",
                  }}
                />
              );
            })}
          </g>
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="tnum text-[22px] font-bold tracking-[-.025em]">{bare(total)}</span>
          <span className="text-[12px] text-ink3">{total?.currency ?? "AED"} total</span>
        </div>
      </div>

      <ul className="flex w-full min-w-0 flex-col gap-[7px]">
        {segs.map((s) => {
          const body = (
            <>
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: s.colour }} />
              <span className="min-w-0 flex-grow truncate text-[13px] text-ink2">{s.name}</span>
              <span className="tnum shrink-0 text-[13px] font-semibold">{bare(s.value)}</span>
              <span className="tnum w-9 shrink-0 text-right text-[12px] text-ink3">
                {Math.round(s.pct)}%
              </span>
            </>
          );
          return (
            <li key={s.key}>
              {s.selectable && onSelect ? (
                <button
                  type="button"
                  onMouseEnter={() => setHot(s.key)}
                  onMouseLeave={() => setHot(null)}
                  onFocus={() => setHot(s.key)}
                  onBlur={() => setHot(null)}
                  onClick={() => onSelect(s.key)}
                  className="flex w-full items-center gap-2.5 rounded-control px-1.5 py-1 text-left transition-colors hover:bg-surface2"
                >
                  {body}
                </button>
              ) : (
                <span className="flex w-full items-center gap-2.5 px-1.5 py-1">{body}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── ranked bars ────────────────────────────────────────────────────────── */

export function CategoryBars({
  rows, onSelect,
}: { rows: Row[]; onSelect?: (category: string) => void }) {
  if (rows.length === 0) return <p className="text-sm text-ink3">Nothing categorised yet.</p>;
  const { head, tail, tailMinor } = split(rows);
  const peak = Math.abs(head[0].value.minor) || 1;
  const exp = head[0].value.exponent;
  const currency = head[0].value.currency;

  return (
    <div className="flex flex-col gap-3">
      {head.map((r, i) => {
        const body = (
          <>
            <span className="w-[7.5rem] shrink-0 truncate text-[13px] text-ink2">{prettyCategory(r.label)}</span>
            <span className="h-2.5 flex-grow overflow-hidden rounded-full bg-hair">
              <span
                className="barGrow block h-2.5 rounded-full"
                style={{
                  width: `${(Math.abs(r.value.minor) / peak) * 100}%`,
                  background: SLOTS[i],
                  animationDelay: `${140 + i * 70}ms`,
                }}
              />
            </span>
            <span className="tnum w-16 shrink-0 text-right text-[13px] font-semibold">{bare(r.value)}</span>
          </>
        );
        return onSelect ? (
          <button key={r.label} type="button" onClick={() => onSelect(r.label)}
                  className="flex items-center gap-3 rounded-control text-left transition-opacity hover:opacity-75">
            {body}
          </button>
        ) : (
          <div key={r.label} className="flex items-center gap-3">{body}</div>
        );
      })}
      {tail.length ? (
        <div className="flex items-center gap-3">
          <span className="w-[7.5rem] shrink-0 text-[13px] text-ink3">{tail.length} more</span>
          <span className="h-2.5 flex-grow overflow-hidden rounded-full bg-hair">
            <span className="barGrow block h-2.5 rounded-full"
                  style={{ width: `${(tailMinor / peak) * 100}%`, background: TAIL, animationDelay: `${140 + KEEP * 70}ms` }} />
          </span>
          <span className="tnum w-16 shrink-0 text-right text-[13px] font-semibold text-ink2">
            {bare({ minor: tailMinor, currency, exponent: exp })}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/* ── trend ──────────────────────────────────────────────────────────────── */

const W = 640, H = 190, L = 42, R = 622, BASE = 148, TOP = 18;

function niceMax(v: number) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const step = mag / 2;
  return Math.ceil(v / step) * step;
}
function compact(v: number) {
  if (v >= 1_000_000) return `${+(v / 1_000_000).toFixed(1)}m`;
  if (v >= 10_000) return `${Math.round(v / 1_000)}k`;
  if (v >= 1_000) return `${+(v / 1_000).toFixed(1)}k`;
  return String(Math.round(v));
}

export function TrendArea({
  points, activeMonth,
}: { points: { month: string; value: Money }[]; activeMonth?: string | null }) {
  const [hot, setHot] = useState<number | null>(null);
  if (points.length === 0) return <p className="text-sm text-ink3">No month has closed yet.</p>;

  const exp = points[0].value.exponent;
  const vals = points.map((p) => Math.abs(p.value.minor) / Math.pow(10, exp));
  const top = niceMax(Math.max(...vals));
  const n = points.length;
  const x = (i: number) => (n === 1 ? (L + R) / 2 : L + (i * (R - L)) / (n - 1));
  const y = (v: number) => BASE - (v / top) * (BASE - TOP);

  const line = vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${BASE} L${x(0).toFixed(1)},${BASE} Z`;
  const dash = Math.ceil((R - L) * 1.7);

  const lastI = n - 1;
  const activeI = activeMonth ? points.findIndex((p) => p.month === activeMonth) : lastI;
  const markI = hot ?? (activeI >= 0 ? activeI : lastI);
  const stride = n > 14 ? Math.ceil(n / 12) : 1;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full overflow-visible" role="img"
         aria-label={`Monthly spend across ${n} months.`}>
      <defs>
        <linearGradient id="trendWash" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.20" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" />
        </linearGradient>
      </defs>

      <line x1={L} y1={BASE} x2={R} y2={BASE} stroke="var(--line)" strokeWidth="1" />
      <line x1={L} y1={(BASE + TOP) / 2} x2={R} y2={(BASE + TOP) / 2} stroke="var(--hair)" strokeWidth="1" />
      <line x1={L} y1={TOP} x2={R} y2={TOP} stroke="var(--hair)" strokeWidth="1" />
      <text x={L - 8} y={BASE + 4} textAnchor="end" className="tnum" style={{ fontSize: 10.5, fill: "var(--ink-3)" }}>0</text>
      <text x={L - 8} y={(BASE + TOP) / 2 + 4} textAnchor="end" className="tnum" style={{ fontSize: 10.5, fill: "var(--ink-3)" }}>{compact(top / 2)}</text>
      <text x={L - 8} y={TOP + 4} textAnchor="end" className="tnum" style={{ fontSize: 10.5, fill: "var(--ink-3)" }}>{compact(top)}</text>

      <g className="washIn"><path d={area} fill="url(#trendWash)" /></g>
      <path className="drawn" d={line} fill="none" stroke="var(--accent)" strokeWidth="2.25"
            strokeLinejoin="round" strokeLinecap="round"
            style={{ strokeDasharray: dash, strokeDashoffset: dash }} />

      <g className="washIn">
        <line x1={x(markI)} y1={y(vals[markI])} x2={x(markI)} y2={BASE}
              stroke="var(--accent)" strokeWidth="1" opacity=".28" />
      </g>
      <circle className="popIn" cx={x(markI)} cy={y(vals[markI])} r="4.75"
              fill="var(--accent)" stroke="var(--surface)" strokeWidth="2.5" />

      <g className="popIn">
        <rect x={Math.min(R - 92, Math.max(L, x(markI) - 46))} y={Math.max(0, y(vals[markI]) - 32)}
              width="92" height="23" rx="7" fill="var(--surface)" stroke="var(--line)" />
        <text x={Math.min(R - 46, Math.max(L + 46, x(markI)))} y={Math.max(16, y(vals[markI]) - 16)}
              textAnchor="middle" className="tnum"
              style={{ fontSize: 11.5, fontWeight: 700, fill: "var(--ink)" }}>
          {bare(points[markI].value)}
        </text>
      </g>

      {points.map((p, i) =>
        i % stride === 0 || i === lastI ? (
          <text key={p.month} x={x(i)} y={BASE + 22} textAnchor="middle"
                style={{ fontSize: 10.5, fill: i === markI ? "var(--ink)" : "var(--ink-3)", fontWeight: i === markI ? 700 : 500 }}>
            {shortMonth(p.month)}
          </text>
        ) : null,
      )}

      {/* generous hit targets, well past the 8px marker */}
      {points.map((p, i) => (
        <rect key={`hit-${p.month}`} x={x(i) - (R - L) / (2 * Math.max(1, n - 1))} y={TOP - 10}
              width={(R - L) / Math.max(1, n - 1)} height={BASE - TOP + 30}
              fill="transparent" onMouseEnter={() => setHot(i)} onMouseLeave={() => setHot(null)} />
      ))}
    </svg>
  );
}

/* ── comparison bars, used by the plan ──────────────────────────────────── */

export function CompareBars({ rows }: { rows: { label: string; value: Money; emphasis?: boolean }[] }) {
  if (!rows.length) return null;
  const peak = Math.max(...rows.map((r) => Math.abs(r.value.minor))) || 1;
  return (
    <div className="flex flex-col gap-3.5">
      {rows.map((r, i) => (
        <div key={r.label} className="flex items-center gap-3.5">
          <span className={`w-28 shrink-0 truncate text-[13px] ${r.emphasis ? "font-bold" : "text-ink2"}`}>{r.label}</span>
          <span className="h-5 flex-grow overflow-hidden rounded-full bg-hair">
            <span className="barGrow block h-5 rounded-full"
                  style={{ width: `${(Math.abs(r.value.minor) / peak) * 100}%`, background: SLOTS[i % SLOTS.length], animationDelay: `${150 + i * 90}ms` }} />
          </span>
          <span className="tnum w-[4.75rem] shrink-0 text-right text-sm font-bold">{bare(r.value)}</span>
        </div>
      ))}
    </div>
  );
}

export function SeriesLegend({ items }: { items: { label: string; note?: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((it, i) => (
        <span key={it.label} className="inline-flex items-center gap-2 text-xs text-ink2">
          <span aria-hidden className="h-2.5 w-2.5 rounded-[3px]" style={{ background: SLOTS[i % SLOTS.length] }} />
          {it.label}
          {it.note ? <span className="font-semibold text-accentInk">{it.note}</span> : null}
        </span>
      ))}
    </div>
  );
}
