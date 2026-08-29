"use client";

/** Thin client shell so a server component can render clickable category charts. */

import { CategoryDonut, CategoryBars } from "@/components/charts";
import { useCategorySheet } from "@/components/category-sheet-provider";
import type { Money } from "@/lib/money";

type Row = { label: string; value: Money; pct: number; txns?: number };

export function CategoryPanel({ rows }: { rows: Row[] }) {
  const sheet = useCategorySheet();
  return <CategoryBars rows={rows} onSelect={sheet.open} />;
}

export function CategoryDonutPanel({ rows, total }: { rows: Row[]; total: Money | null }) {
  const sheet = useCategorySheet();
  return <CategoryDonut rows={rows} total={total} onSelect={sheet.open} />;
}
