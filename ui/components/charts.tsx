"use client";

/**
 * Charts.
 *
 * Colour is assigned by FIXED SLOT, never by rank, so filtering a category out
 * never repaints the survivors. Six slots exist and no seventh: the palette is
 * validated for colour-vision deficiency in both modes at exactly that count,
 * and the tail folds into a neutral. Every slice and bar is direct-labelled,
 * which is the secondary encoding the palette's CVD band requires.
 *
 * Motion rule (this bit was a real bug once): every reveal animates FROM a
 * hidden keyframe TO the element's natural resting style, with fill-mode
 * `forwards` and never `both`. Nothing is hidden by an inline style or by a
 * `to`-state that only a running animation can rescue, because CSS animations
 * do not run on a hidden page. Hover feedback is opacity and weight only —
 * colour is bound to the entity and is never re-mapped.
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

/** The glossy top-light every filled mark shares, so bars and ring read as one system. */
const SHEEN = "linear-gradient(180deg, var(--mark-hi) 0%, var(--mark-mid) 58%, var(--mark-lo) 100%)";

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

  /* Geometry only — never money. A 3px surface gap separates touching arcs and
     each arc is capped round, so the cap radius is discounted from the drawn
     length; a slice too thin to round keeps a butt cap rather than bulging. */
  const BOX = 216, R = 85, STROKE = 20, C = 2 * Math.PI * R;
  const GAP = 2;
  const CAP = STROKE;
  let cursor = 0;

  const arcs = segs.map((s) => {
    const span = (s.pct / 100) * C;
    const round = span > CAP + GAP + 7;
    const inset = round ? CAP / 2 + GAP / 2 : GAP / 2;
    const len = Math.max(0.6, span - (round ? CAP + GAP : GAP));
    const off = -(cursor + inset);
    cursor += span;
    return { ...s, len, off, round };
  });

  const shown = hot ? arcs.find((a) => a.key === hot) : null;

  return (
    <div className="flex flex-col items-center gap-7 sm:flex-row sm:items-center sm:gap-9">
      <div className="relative shrink-0" style={{ width: BOX, height: BOX }}>
        <svg width={BOX} height={BOX} viewBox={`0 0 ${BOX} ${BOX}`} role="img"
             aria-label={`Spending by category, ${segs.length} groups, largest ${segs[0].name}.`}>
          <defs>
            {/* counter-rotates the -90° dial so the highlight still falls from above */}
            <linearGradient id="stRingSheen" x1="0" y1="0" x2="0" y2="1" gradientTransform="rotate(90 .5 .5)">
              <stop offset="0%" stopColor="var(--mark-hi)" />
              <stop offset="58%" stopColor="var(--mark-mid)" />
              <stop offset="100%" stopColor="var(--mark-lo)" />
            </linearGradient>
            <filter id="stRingLift" x="-25%" y="-25%" width="150%" height="150%">
              <feDropShadow dx="0" dy="1.5" stdDeviation="2.5" floodColor="var(--mark-shadow)" />
            </filter>
          </defs>

          <g transform={`translate(${BOX / 2},${BOX / 2}) rotate(-90)`}>
            {/* the unspent groove, edged top and bottom so the band reads as a channel */}
            <circle r={R} fill="none" stroke="var(--hair)" strokeWidth={STROKE} />
            <circle r={R + STROKE / 2} fill="none" stroke="var(--line)" strokeWidth="1" opacity=".55" />
            <circle r={R - STROKE / 2} fill="none" stroke="var(--line)" strokeWidth="1" opacity=".55" />

            <g filter="url(#stRingLift)">
              {arcs.map((s) => {
                const dim = hot !== null && hot !== s.key;
                const lift = hot === s.key;
                return (
                  <circle
                    key={s.key}
                    className="sweep"
                    r={R}
                    fill="none"
                    stroke={s.colour}
                    strokeWidth={lift ? STROKE + 3 : STROKE}
                    strokeLinecap={s.round ? "round" : "butt"}
                    strokeDasharray={`${s.len} ${C - s.len}`}
                    strokeDashoffset={s.off}
                    opacity={dim ? 0.22 : 1}
                    onMouseEnter={() => setHot(s.key)}
                    onMouseLeave={() => setHot(null)}
                    onClick={s.selectable && onSelect ? () => onSelect(s.key) : undefined}
                    style={{
                      // rests at its own offset; the sweep departs from a closed ring
                      ["--sweep-from" as string]: String(s.off + C),
                      animationDelay: "140ms",
                      transition: "opacity .18s ease-out, stroke-width .18s ease-out",
                      cursor: s.selectable && onSelect ? "pointer" : "default",
                    }}
                  />
                );
              })}
            </g>

            {/* same dial, painted again as light — depth without touching hue */}
            <g pointerEvents="none">
              {arcs.map((s) => (
                <circle
                  key={`sheen-${s.key}`}
                  className="sweep"
                  r={R}
                  fill="none"
                  stroke="url(#stRingSheen)"
                  strokeWidth={hot === s.key ? STROKE + 3 : STROKE}
                  strokeLinecap={s.round ? "round" : "butt"}
                  strokeDasharray={`${s.len} ${C - s.len}`}
                  strokeDashoffset={s.off}
                  opacity={hot !== null && hot !== s.key ? 0.22 : 1}
                  style={{
                    ["--sweep-from" as string]: String(s.off + C),
                    animationDelay: "140ms",
                    transition: "opacity .18s ease-out, stroke-width .18s ease-out",
                  }}
                />
              ))}
            </g>
          </g>
        </svg>

        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-9 text-center">
          {shown ? (
            <>
              <span className="max-w-full truncate text-[11px] font-semibold uppercase tracking-[.09em] text-ink3">
                {shown.name}
              </span>
              <span className="tnum mt-1 text-[21px] font-bold tracking-[-.03em] text-ink">{bare(shown.value)}</span>
              <span className="tnum mt-0.5 text-[12px] text-ink3">{Math.round(shown.pct)}% of total</span>
            </>
          ) : (
            <>
              <span className="text-[11px] font-semibold uppercase tracking-[.09em] text-ink3">
                {total?.currency ?? "AED"} total
              </span>
              <span className="tnum mt-1 text-[24px] font-bold tracking-[-.035em] text-ink">{bare(total)}</span>
              <span className="mt-0.5 text-[12px] text-ink3">{segs.length} groups</span>
            </>
          )}
        </div>
      </div>

      <ul className="flex w-full min-w-0 flex-col gap-px">
        {segs.map((s) => {
          const dim = hot !== null && hot !== s.key;
          const body = (
            <>
              <span aria-hidden className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: s.colour, backgroundImage: SHEEN }} />
              <span className="min-w-0 flex-grow truncate text-[13px] font-medium text-ink2">{s.name}</span>
              <span className="tnum shrink-0 text-[13px] font-semibold tracking-[-.01em] text-ink">{bare(s.value)}</span>
              <span className="tnum w-10 shrink-0 text-right text-[12px] tabular-nums text-ink3">
                {Math.round(s.pct)}%
              </span>
            </>
          );
          return (
            <li key={s.key} style={{ opacity: dim ? 0.42 : 1, transition: "opacity .18s ease-out" }}>
              {s.selectable && onSelect ? (
                <button
                  type="button"
                  onMouseEnter={() => setHot(s.key)}
                  onMouseLeave={() => setHot(null)}
                  onFocus={() => setHot(s.key)}
                  onBlur={() => setHot(null)}
                  onClick={() => onSelect(s.key)}
                  className="flex w-full items-center gap-3 rounded-control px-2 py-[7px] text-left transition-colors hover:bg-surface2"
                >
                  {body}
                </button>
              ) : (
                <span
                  onMouseEnter={() => setHot(s.key)}
                  onMouseLeave={() => setHot(null)}
                  className="flex w-full items-center gap-3 px-2 py-[7px]"
                >
                  {body}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── ranked bars ────────────────────────────────────────────────────────── */

function Bar({ pct, colour, delay, height }: { pct: number; colour: string; delay: number; height: number }) {
  return (
    <span className="relative block flex-grow overflow-hidden rounded-full bg-hair"
          style={{ height, boxShadow: "inset 0 0 0 1px var(--mark-groove)" }}>
      <span
        className="barGrow block rounded-full"
        style={{
          height,
          width: `${Math.max(pct, 1.2)}%`,
          background: colour,
          backgroundImage: SHEEN,
          animationDelay: `${delay}ms`,
        }}
      />
    </span>
  );
}

export function CategoryBars({
  rows, onSelect,
}: { rows: Row[]; onSelect?: (category: string) => void }) {
  const [hot, setHot] = useState<string | null>(null);
  if (rows.length === 0) return <p className="text-sm text-ink3">Nothing categorised yet.</p>;
  const { head, tail, tailMinor, tailPct } = split(rows);
  const peak = Math.abs(head[0].value.minor) || 1;
  const exp = head[0].value.exponent;
  const currency = head[0].value.currency;

  const line = (
    label: string,
    value: Money,
    pct: number,
    width: number,
    colour: string,
    delay: number,
    muted: boolean,
  ) => (
    <>
        <span className={`w-[7.5rem] shrink-0 truncate text-[13px] font-medium ${muted ? "text-ink3" : "text-ink2"}`}>
          {label}
        </span>
        <Bar pct={width} colour={colour} delay={delay} height={10} />
        <span className="tnum w-[4.5rem] shrink-0 text-right text-[13px] font-semibold tracking-[-.01em] text-ink">
          {bare(value)}
        </span>
      <span className="tnum w-9 shrink-0 text-right text-[12px] text-ink3">{Math.round(pct)}%</span>
    </>
  );

  return (
    <div className="flex flex-col gap-1">
      {head.map((r, i) => {
        const dim = hot !== null && hot !== r.label;
        const body = line(
          prettyCategory(r.label), r.value, r.pct,
          (Math.abs(r.value.minor) / peak) * 100, SLOTS[i], 140 + i * 70, false,
        );
        const style = { opacity: dim ? 0.45 : 1, transition: "opacity .18s ease-out" };
        return onSelect ? (
          <button key={r.label} type="button" onClick={() => onSelect(r.label)} style={style}
                  onMouseEnter={() => setHot(r.label)} onMouseLeave={() => setHot(null)}
                  onFocus={() => setHot(r.label)} onBlur={() => setHot(null)}
                  className="flex items-center gap-3 rounded-control px-2 py-[7px] text-left transition-colors hover:bg-surface2">
            {body}
          </button>
        ) : (
          <div key={r.label} style={style} className="flex items-center gap-3 px-2 py-[7px]">{body}</div>
        );
      })}
      {tail.length ? (
        <div className="flex items-center gap-3 px-2 py-[7px]"
             style={{ opacity: hot !== null ? 0.45 : 1, transition: "opacity .18s ease-out" }}>
          {line(`${tail.length} more`, { minor: tailMinor, currency, exponent: exp },
                tailPct, (tailMinor / peak) * 100, TAIL, 140 + KEEP * 70, true)}
        </div>
      ) : null}
    </div>
  );
}

/* ── trend ──────────────────────────────────────────────────────────────── */

const W = 640, H = 206, L = 44, R = 624, BASE = 156, TOP = 20;

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
  const slot = (R - L) / Math.max(1, n - 1);

  const bandX = Math.max(L - 6, x(markI) - slot / 2);
  const bandW = Math.min(R + 6, x(markI) + slot / 2) - bandX;

  const tipW = 96, tipH = 25;
  const tipX = Math.min(R - tipW, Math.max(L - 8, x(markI) - tipW / 2));
  const tipY = Math.max(0, y(vals[markI]) - 36);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full overflow-visible" role="img"
         aria-label={`Monthly spend across ${n} months.`}>
      <defs>
        <linearGradient id="trendWash" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.30" />
          <stop offset="45%" stopColor="var(--accent)" stopOpacity="0.12" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
        <filter id="stTrendGlow" x="-12%" y="-40%" width="124%" height="200%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
        <filter id="stTipLift" x="-40%" y="-80%" width="180%" height="280%">
          <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="var(--mark-shadow)" />
        </filter>
      </defs>

      {/* hovered column, so the read follows the pointer before the tooltip does */}
      <rect x={bandX} y={TOP - 8} width={bandW} height={BASE - TOP + 8}
            fill="var(--surface-2)" opacity=".6" rx="6" />

      {/* grid restraint: one solid baseline, two dashed whispers above it */}
      {[TOP, (BASE + TOP) / 2].map((gy) => (
        <line key={gy} x1={L} y1={gy} x2={R} y2={gy} stroke="var(--hair)" strokeWidth="1" strokeDasharray="2 6" />
      ))}
      <line x1={L} y1={BASE} x2={R} y2={BASE} stroke="var(--line)" strokeWidth="1" />

      {[[BASE, "0"], [(BASE + TOP) / 2, compact(top / 2)], [TOP, compact(top)]].map(([gy, t]) => (
        <text key={String(t)} x={L - 10} y={(gy as number) + 3.5} textAnchor="end" className="tnum"
              style={{ fontSize: 10, fill: "var(--ink-3)", letterSpacing: ".02em" }}>{t}</text>
      ))}

      <g className="washIn"><path d={area} fill="url(#trendWash)" /></g>

      {/* the line, twice: a soft bloom beneath the crisp stroke */}
      <path className="washIn" d={line} fill="none" stroke="var(--accent)" strokeWidth="6"
            strokeLinejoin="round" strokeLinecap="round" opacity=".10" filter="url(#stTrendGlow)" />
      <path className="drawn" d={line} fill="none" stroke="var(--accent)" strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round"
            style={{ strokeDasharray: dash, ["--draw-len" as string]: String(dash) }} />

      {n <= 16 ? (
        <g className="washIn">
          {vals.map((v, i) => (
            <circle key={points[i].month} cx={x(i)} cy={y(v)} r="2.4"
                    fill="var(--surface)" stroke="var(--accent)" strokeWidth="1.5"
                    opacity={i === markI ? 0 : 0.45} />
          ))}
        </g>
      ) : null}

      <g className="washIn">
        <line x1={x(markI)} y1={y(vals[markI]) + 6} x2={x(markI)} y2={BASE}
              stroke="var(--accent)" strokeWidth="1" strokeDasharray="2 3" opacity=".45" />
      </g>
      <circle className="popIn" cx={x(markI)} cy={y(vals[markI])} r="8"
              fill="var(--accent)" opacity=".16" />
      <circle className="popIn" cx={x(markI)} cy={y(vals[markI])} r="4.75"
              fill="var(--accent)" stroke="var(--surface)" strokeWidth="2.5" />

      <g className="popIn" filter="url(#stTipLift)">
        <rect x={tipX} y={tipY} width={tipW} height={tipH} rx="8"
              fill="var(--surface)" stroke="var(--line)" />
        <text x={tipX + tipW / 2} y={tipY + tipH / 2 + 4} textAnchor="middle" className="tnum"
              style={{ fontSize: 11.5, fontWeight: 700, fill: "var(--ink)", letterSpacing: "-.01em" }}>
          {bare(points[markI].value)}
        </text>
      </g>

      {points.map((p, i) =>
        i % stride === 0 || i === lastI ? (
          <text key={p.month} x={x(i)} y={BASE + 21} textAnchor="middle"
                style={{
                  fontSize: 10.5,
                  letterSpacing: ".04em",
                  fill: i === markI ? "var(--ink)" : "var(--ink-3)",
                  fontWeight: i === markI ? 700 : 500,
                }}>
            {shortMonth(p.month)}
          </text>
        ) : null,
      )}

      {/* generous hit targets, well past the 8px marker */}
      {points.map((p, i) => (
        <rect key={`hit-${p.month}`} x={x(i) - slot / 2} y={TOP - 10}
              width={slot} height={BASE - TOP + 30}
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
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <div key={r.label} className="flex items-center gap-3.5">
          <span className={`w-28 shrink-0 truncate text-[13px] ${r.emphasis ? "font-bold text-ink" : "font-medium text-ink2"}`}>
            {r.label}
          </span>
          <Bar pct={(Math.abs(r.value.minor) / peak) * 100} colour={SLOTS[i % SLOTS.length]}
               delay={150 + i * 90} height={18} />
          <span className="tnum w-[4.75rem] shrink-0 text-right text-sm font-bold tracking-[-.015em] text-ink">
            {bare(r.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function SeriesLegend({ items }: { items: { label: string; note?: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
      {items.map((it, i) => (
        <span key={it.label}
              className="inline-flex items-center gap-2 rounded-full bg-surface2 py-1 pl-2 pr-2.5 text-xs font-medium text-ink2">
          <span aria-hidden className="h-2 w-2 rounded-full"
                style={{ background: SLOTS[i % SLOTS.length], backgroundImage: SHEEN }} />
          {it.label}
          {it.note ? <span className="font-semibold text-accentInk">{it.note}</span> : null}
        </span>
      ))}
    </div>
  );
}
