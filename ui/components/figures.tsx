"use client";

/**
 * Animated figures.
 *
 * The tween is display only. It never decides a reported value: the element is
 * seeded with the exact server-formatted string, every frame interpolates a
 * throwaway display number, and the final frame writes the server string back
 * verbatim. Under reduced motion the string is simply left alone. No figure on
 * this screen is ever computed in TypeScript (D-002, D-008, D-029).
 */

import { useEffect, useRef } from "react";

function prefersReduced() {
  return typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function CountUp({
  value, text, className = "", duration = 1100, delay = 120,
}: {
  /** The numeric magnitude to tween toward, in major units. */
  value: number;
  /** The exact server-formatted string. This is what rests on screen. */
  text: string;
  className?: string;
  duration?: number;
  delay?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || prefersReduced() || !Number.isFinite(value) || value === 0) return;

    // Keep the server string's own shape (currency prefix, grouping, decimals)
    // by swapping only the digit run inside it.
    const digits = /[\d][\d,.\s]*/;
    const match = text.match(digits);
    if (!match) return;

    const decimals = (match[0].split(".")[1] ?? "").replace(/\D/g, "").length;
    const fmt = new Intl.NumberFormat("en-AE", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });

    let raf = 0;
    let start = 0;
    const from = 0;
    const to = Math.abs(value);

    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / duration);
      // exponential ease-out
      const eased = 1 - Math.pow(1 - p, 4);
      el.textContent = text.replace(digits, fmt.format(from + (to - from) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
      else el.textContent = text;                  // rest on the server's own string
    };

    const timer = window.setTimeout(() => {
      el.textContent = text.replace(digits, fmt.format(0));
      raf = requestAnimationFrame(tick);
    }, delay);

    return () => {
      window.clearTimeout(timer);
      cancelAnimationFrame(raf);
      el.textContent = text;
    };
  }, [value, text, duration, delay]);

  return <span ref={ref} className={className}>{text}</span>;
}

/** A small trend line that rides inside a tile. Context, never the main read. */
export function Sparkline({
  points, className = "", width = 108, height = 30,
}: { points: number[]; className?: string; width?: number; height?: number }) {
  if (points.length < 2) return null;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const d = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(height - 2 - ((v - min) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const lastX = width;
  const lastY = height - 2 - ((points[points.length - 1] - min) / span) * (height - 4);
  return (
    <svg width={width} height={height} className={className} aria-hidden focusable="false">
      <path
        className="drawn"
        d={d}
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ strokeDasharray: 400, ["--draw-len" as string]: "400" }}
      />
      <circle className="popIn" cx={lastX} cy={lastY} r="2.75" fill="var(--accent)" />
    </svg>
  );
}
