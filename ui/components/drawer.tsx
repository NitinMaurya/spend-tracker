"use client";

/**
 * The drawer shell — overlay, escape, focus, scroll. One implementation, because
 * the Evidence drawer and the card drawer are the same object with different
 * contents, and two copies of this drift.
 */

import { useEffect, useRef, type ReactNode } from "react";
import { Cross } from "./icons";

export function Drawer({
  open, onClose, title, icon, width = "38rem", children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  icon?: ReactNode;
  width?: string;
  children: ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    };
    window.addEventListener("keydown", onKey);
    closeRef.current?.focus();
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-ink/20 backdrop-blur-[1px]"
      />
      <aside
        className="slide-in relative flex h-full w-full flex-col overflow-y-auto border-l border-line bg-surface shadow-sheet"
        style={{ maxWidth: width }}
      >
        <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-surface px-6 py-4">
          {icon}
          <p className="text-sm font-semibold">{title}</p>
          <span className="mono ml-auto text-[11px] text-ink3">esc</span>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close" className="text-ink3 hover:text-ink">
            <Cross size={16} />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}

export function DrawerSkeleton() {
  return (
    <div className="flex flex-col gap-4 px-6 py-6">
      <div className="h-7 w-40 animate-pulse rounded bg-surface2" />
      <div className="h-24 animate-pulse rounded-card bg-surface2" />
      <div className="h-32 animate-pulse rounded-card bg-surface2" />
    </div>
  );
}
