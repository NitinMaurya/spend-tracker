/**
 * A category you can change, wherever a charge appears.
 *
 * Corrections have to be possible from anywhere, because you notice a wrong
 * category while looking at spending — not while sitting on a review screen
 * (spec §18). Saving applies the change immediately AND writes the rule to
 * data/category_overrides.csv, so the same correction is never needed twice.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { api, setCategory } from "@/lib/api";
import { Chip } from "@/components/ui";
import { useCategorySheet } from "@/components/category-sheet-provider";

let CACHE: string[] | null = null;

export function CategoryTag({
  txnId, category, merchant, onChanged,
}: {
  txnId: string;
  category: string | null;
  merchant?: string | null;
  onChanged?: (category: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(category);
  const [options, setOptions] = useState<string[]>(CACHE ?? []);
  const [saving, setSaving] = useState(false);
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const sheet = useCategorySheet();

  useEffect(() => {
    if (!open || CACHE) return;
    void api.categories().then((c) => { CACHE = c; setOptions(c); }).catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  const save = async (next: string, scope?: boolean) => {
    setSaving(true);
    try {
      const r = await setCategory(txnId, next, scope);
      setValue(next);
      setNote(r.note);
      if (!options.includes(next)) {
        CACHE = [...(CACHE ?? options), next].sort();
        setOptions(CACHE);
      }
      setCustom("");
      onChanged?.(next);
      setOpen(false);
      setTimeout(() => setNote(null), 4000);
    } catch {
      setNote("Could not save that.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <span className="relative inline-flex items-center" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={merchant ? `Change the category for ${merchant}` : "Change category"}
        className="cursor-pointer rounded-full transition-opacity hover:opacity-70"
      >
        {value ? (
          <Chip tone="neutral">{value.replace(/_/g, " ").toLowerCase()}</Chip>
        ) : (
          <Chip tone="warn">set category</Chip>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-56 rounded-card border border-line bg-surface p-1.5 shadow-lift">
          {/* Money you laid out for someone else is not an expense — and it is a
              one-off, so it must NOT become a rule about the merchant. */}
          <button
            type="button"
            disabled={saving}
            onClick={() => void save("REIMBURSABLE", false)}
            className="mb-1.5 flex w-full items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-sm hover:bg-surface2"
          >
            <span aria-hidden>↩</span>
            <span>
              <span className="font-medium">Someone paid me back</span>
              <span className="block text-[11px] text-ink3">
                this charge only · drops out of your expenses
              </span>
            </span>
          </button>

          {value && (
            <button
              type="button"
              onClick={() => { setOpen(false); sheet.open(value); }}
              className="mb-1.5 flex w-full items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-sm hover:bg-surface2"
            >
              <span aria-hidden>⌕</span>
              <span>
                <span className="font-medium">
                  See all {value.replace(/_/g, " ").toLowerCase()} charges
                </span>
                <span className="block text-[11px] text-ink3">month by month</span>
              </span>
            </button>
          )}

          <p className="px-2 py-1 text-[11px] text-ink3">
            {merchant ? <>A category below applies to all <b className="text-ink2">{merchant}</b> charges</>
                      : "Applies to this charge"}
          </p>
          {/* A label of your own. The taxonomy is a starting point, not a fixed
              list — spec §F3 requires it to be extensible, and the categories that
              matter are the ones you actually think in. */}
          <form
            className="mb-1.5 flex gap-1 border-b border-line pb-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              const label = custom.trim();
              if (label) void save(label.toUpperCase().replace(/\s+/g, "_"));
            }}
          >
            <input
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder="Your own label…"
              className="min-w-0 flex-1 rounded-lg border border-line bg-bg px-2 py-1.5 text-sm"
            />
            <button
              type="submit"
              disabled={saving || !custom.trim()}
              className="rounded-lg px-2.5 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              Add
            </button>
          </form>

          <div className="max-h-64 overflow-y-auto">
            {options.map((c) => (
              <button
                key={c}
                type="button"
                disabled={saving}
                onClick={() => void save(c)}
                className={`block w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors hover:bg-accentSoft hover:text-accentInk ${
                  c === value ? "bg-accentSoft font-medium text-accentInk" : "text-ink2"
                }`}
              >
                {c.replace(/_/g, " ").toLowerCase()}
              </button>
            ))}
          </div>
        </div>
      )}

      {note && (
        <span className="ml-2 whitespace-nowrap text-xs" style={{ color: "var(--ok)" }}>
          {note}
        </span>
      )}
    </span>
  );
}
