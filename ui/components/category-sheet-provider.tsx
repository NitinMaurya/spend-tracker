/**
 * Makes the category detail sheet reachable from ANY page.
 *
 * Mounted once in the root layout, so a chart, a chip or a table row anywhere in
 * the app can open it without each page wiring up its own copy — and there is only
 * ever one sheet on screen.
 */
"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CategorySheet } from "@/components/category-sheet";
import type { Period } from "@/lib/api";

type Ctx = { open: (category: string) => void; close: () => void };

const CategorySheetContext = createContext<Ctx>({ open: () => {}, close: () => {} });

export function useCategorySheet() {
  return useContext(CategorySheetContext);
}

export function CategorySheetProvider({ children }: { children: React.ReactNode }) {
  const [category, setCategory] = useState<string | null>(null);
  const search = useSearchParams();

  // The sheet inherits whatever window the page is showing (D-038), read from the
  // URL so it works the same on every page without being passed down.
  const period: Period = useMemo(() => ({
    from: search.get("from") ?? undefined,
    to: search.get("to") ?? undefined,
    label: search.get("label") ?? "All time",
  }), [search]);

  const open = useCallback((c: string) => setCategory(c), []);
  const close = useCallback(() => setCategory(null), []);
  const value = useMemo(() => ({ open, close }), [open, close]);

  return (
    <CategorySheetContext.Provider value={value}>
      {children}
      <CategorySheet category={category} period={period} onClose={close} />
    </CategorySheetContext.Provider>
  );
}
