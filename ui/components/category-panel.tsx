/**
 * Category bars wired to the app-wide detail sheet. A thin client shell so a server
 * component can render clickable bars.
 */
"use client";

import { CategoryBars } from "@/components/charts";
import { useCategorySheet } from "@/components/category-sheet-provider";
import type { Money } from "@/lib/money";

export function CategoryPanel({
  rows,
}: {
  rows: { label: string; value: Money; pct: number; txns?: number }[];
}) {
  const sheet = useCategorySheet();
  return <CategoryBars rows={rows} onSelect={sheet.open} />;
}
