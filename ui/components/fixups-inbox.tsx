"use client";

/**
 * Fix-ups — a single-focus triage queue.
 *
 * Categorisation quality gates every figure downstream (a plan priced on
 * mislabelled spend is worse than no plan), so the job worth optimising is
 * speed: one row in focus, the keyboard does the work, and the queue advances
 * itself. The old screen was a list of expandable forms, which made you aim a
 * mouse at every row.
 *
 * Two constraints shape it:
 *   · No money arithmetic happens here. Totals and shares are whatever the
 *     engine computed (D-002, D-008, D-029) -- this file only ever displays
 *     them, and counts ROWS when it needs a number of its own.
 *   · There is no "unset" in the data model, so there is no undo. Re-assigning
 *     IS the correction, and the screen says so rather than offering a button
 *     that cannot work.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiDown, setCategory,
  type Overview, type ReviewRow,
} from "@/lib/api";
import { formatAbs } from "@/lib/money";
import { longDate, prettyCategory } from "@/lib/format";
import { EngineDownPanel } from "@/components/engine-down";
import { Card, CardTitle, Chip, Code, Label, Kbd, SectionTitle, State } from "@/components/ui";
import { Alert, ArrowRight, Check, Info } from "@/components/icons";
import { Traceable } from "@/components/evidence-drawer";

function confidenceTone(c: string | null): "warn" | "bad" | "neutral" {
  const v = (c ?? "UNKNOWN").toUpperCase();
  if (v === "UNKNOWN" || v === "NONE") return "bad";
  if (v === "LOW" || v === "MEDIUM") return "warn";
  return "neutral";
}

function confidenceWord(c: string | null): string {
  const v = (c ?? "UNKNOWN").toUpperCase();
  if (v === "UNKNOWN" || v === "NONE") return "no idea what this is";
  if (v === "LOW") return "a guess, and not a good one";
  if (v === "MEDIUM") return "a reasonable guess";
  return v.toLowerCase();
}

type Done = { txnId: string; category: string; cleared: number };

export function FixupsInbox() {
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [cursor, setCursor] = useState(0);
  const [done, setDone] = useState<Done[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [down, setDown] = useState(false);
  const [showRepayments, setShowRepayments] = useState(false);
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [r, c, o] = await Promise.all([
          api.review(showRepayments),
          api.categories().catch(() => []),
          api.overview().catch(() => null),
        ]);
        if (!alive) return;
        setRows(r);
        setCategories(c);
        setOverview(o);
        setCursor(0);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiDown) setDown(true);
        else setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { alive = false; };
  }, [showRepayments]);

  const pending = useMemo(
    () => (rows ?? []).filter((r) => !done.some((d) => d.txnId === r.txn_id)),
    [rows, done],
  );
  const focused = pending[Math.min(cursor, Math.max(0, pending.length - 1))] ?? null;

  // Assigning teaches a merchant rule, so other rows from the same merchant go
  // too. Counting ROWS is fine; summing their money here would not be.
  const siblings = useMemo(
    () =>
      focused?.merchant
        ? pending.filter((r) => r.txn_id !== focused.txn_id && r.merchant === focused.merchant).length
        : 0,
    [pending, focused],
  );

  const shortlist = useMemo(() => {
    const q = query.trim().toUpperCase();
    const list = q ? categories.filter((c) => c.includes(q.replace(/\s+/g, "_"))) : categories;
    return list.slice(0, 9);
  }, [categories, query]);

  const assign = useCallback(
    async (category: string) => {
      if (!focused || saving) return;
      setSaving(true);
      setError(null);
      try {
        const res = await setCategory(focused.txn_id, category);
        setDone((d) => [...d, { txnId: focused.txn_id, category, cleared: res.updated }]);
        setQuery("");
        setCursor((c) => Math.min(c, Math.max(0, pending.length - 2)));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setSaving(false);
      }
    },
    [focused, saving, pending.length],
  );

  const move = useCallback(
    (delta: number) =>
      setCursor((c) => Math.max(0, Math.min(pending.length - 1, c + delta))),
    [pending.length],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const el = e.target as HTMLElement | null;
      const typing = el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
      if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); return; }
      if (typing && e.key !== "Escape") {
        // digits still assign while the filter box has focus — that is the flow:
        // narrow, then pick.
        if (/^[1-9]$/.test(e.key) && shortlist.length >= Number(e.key)) {
          e.preventDefault();
          void assign(shortlist[Number(e.key) - 1]);
        }
        return;
      }
      if (e.key === "Escape") { (el as HTMLInputElement | null)?.blur(); setQuery(""); return; }
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); move(1); return; }
      if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); move(-1); return; }
      if (e.key === "s") { e.preventDefault(); move(1); return; }
      if (/^[1-9]$/.test(e.key) && shortlist.length >= Number(e.key)) {
        e.preventDefault();
        void assign(shortlist[Number(e.key) - 1]);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [assign, move, shortlist]);

  if (down) {
    return (
      <EngineDownPanel />
    );
  }
  if (!rows) return <p className="text-sm text-ink3">Reading the queue…</p>;

  const total = rows.length;
  const cleared = done.length;

  return (
    <div className="flex flex-col gap-6">
      {/* how much value is waiting on a decision — server-computed, always */}
      {overview ? (
        <Card className="flex flex-col gap-3">
          <CardTitle aside="share of value, computed by the engine">
            How much rides on this
          </CardTitle>
          <div className="flex flex-col gap-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[13px] text-ink2">
                Uncategorised spend
                {overview.uncategorized_spend ? (
                  <>
                    {" — "}
                    <span className="tnum font-semibold text-ink">
                      {formatAbs(overview.uncategorized_spend)}
                    </span>
                    {" of "}
                    <span className="tnum">{formatAbs(overview.total_spend)}</span>
                  </>
                ) : null}
              </span>
              <span
                className={`tnum text-sm font-semibold ${
                  overview.uncategorized_pct > 10 ? "text-warn" : "text-ok"
                }`}
              >
                {overview.uncategorized_pct}%
              </span>
            </div>
            <div
              className={`h-2 overflow-hidden rounded-full ${
                overview.uncategorized_pct > 10 ? "bg-warnSoft" : "bg-okSoft"
              }`}
            >
              <div
                className={`bar h-full rounded-full ${
                  overview.uncategorized_pct > 10 ? "bg-warn" : "bg-ok"
                }`}
                style={{ width: `${Math.max(1.5, Math.min(100, overview.uncategorized_pct))}%` }}
              />
            </div>
            <p className="text-xs leading-relaxed text-ink3">
              A card recommendation is only trustworthy while this stays at or below 10% by value —
              the gate is weighted by money, not by how many rows are left.
            </p>
          </div>
        </Card>
      ) : null}

      {total === 0 ? (
        <State title="Nothing needs fixing." tone="ok">
          <p>
            Every charge the engine kept has a category it is confident about. Rows land here when a
            statement brings a merchant it cannot place — assign it once and the rule sticks, so the
            same charge never asks twice.
          </p>
          <label className="mt-3 inline-flex items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              checked={showRepayments}
              onChange={(e) => setShowRepayments(e.target.checked)}
            />
            Also show card payments and transfers
            <span className="text-ink3">— money between your own accounts, not spending</span>
          </label>
        </State>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-4">
            <SectionTitle aside={`ranked by what each row is worth`}>The queue</SectionTitle>
            <span className="ml-auto flex items-center gap-3 text-xs text-ink3">
              <span className="tnum">
                {cleared} of {total} cleared
              </span>
              <span className="h-1.5 w-32 overflow-hidden rounded-full bg-hair">
                <span
                  className="block h-full rounded-full bg-accent transition-[width] duration-300"
                  style={{ width: `${total ? (cleared / total) * 100 : 0}%` }}
                />
              </span>
            </span>
          </div>

          <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
            {/* queue */}
            <Card pad={false} className="max-h-[34rem] self-start overflow-y-auto py-1">
              {pending.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-ink3">Queue cleared.</p>
              ) : (
                pending.map((r, i) => {
                  const on = focused?.txn_id === r.txn_id;
                  return (
                    <button
                      key={r.txn_id}
                      type="button"
                      onClick={() => setCursor(i)}
                      className={`flex w-full items-center gap-2.5 border-b border-hair px-3.5 py-2.5 text-left last:border-0 ${
                        on ? "border-l-[3px] border-l-accent bg-accentSoft pl-3" : ""
                      }`}
                    >
                      <span className="mono w-5 shrink-0 text-[11px] text-ink3">{i + 1}</span>
                      <span className="flex min-w-0 flex-grow flex-col gap-0.5">
                        <span className="truncate text-[13px] font-medium">
                          {r.merchant ?? "not printed"}
                        </span>
                        <span className="mono truncate text-[10.5px] text-ink3">
                          {r.txn_date} · {r.account_id}
                        </span>
                      </span>
                      <span className="tnum shrink-0 text-[13px] font-semibold">
                        {formatAbs(r.amount).replace(/^[A-Z]{3}\s/, "")}
                      </span>
                    </button>
                  );
                })
              )}
              {done.length ? (
                <div className="border-t border-line px-3.5 py-2.5">
                  {done.slice(-4).map((d) => (
                    <p key={d.txnId} className="flex items-center gap-2 py-0.5 text-[11.5px] text-ok">
                      <Check size={12} />
                      <span className="mono">{prettyCategory(d.category)}</span>
                      {d.cleared > 1 ? (
                        <span className="text-ink3">· {d.cleared} rows</span>
                      ) : null}
                    </p>
                  ))}
                </div>
              ) : null}
            </Card>

            {/* the focused row */}
            {focused ? (
              <Card className="slide-in flex flex-col gap-5 p-6">
                <div className="flex flex-wrap items-start justify-between gap-5">
                  <div className="flex flex-col gap-1.5">
                    <Label>
                      {cursor + 1} of {pending.length} left
                    </Label>
                    <span className="serif text-[26px] leading-tight">
                      {focused.merchant ?? "Merchant not printed"}
                    </span>
                    {focused.raw_description ? (
                      <span className="mono max-w-[52ch] break-words text-[11.5px] text-ink2" dir="auto">
                        {focused.raw_description}
                      </span>
                    ) : null}
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Traceable txnId={focused.txn_id} className="tnum text-[34px] font-semibold leading-none tracking-[-.025em]">
                      {formatAbs(focused.amount).replace(/^[A-Z]{3}\s/, "")}
                    </Traceable>
                    <span className="text-[12.5px] text-ink2">
                      {longDate(focused.txn_date)} · {focused.account_id}
                    </span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Chip tone={confidenceTone(focused.category_confidence)} icon={<Alert size={12} />}>
                    {confidenceWord(focused.category_confidence)}
                  </Chip>
                  {focused.category ? (
                    <Chip tone="neutral">currently {prettyCategory(focused.category)}</Chip>
                  ) : null}
                </div>

                {/* the picker */}
                <div className="flex flex-col gap-2.5">
                  <div className="flex flex-wrap items-center gap-3">
                    <Label>Assign a category</Label>
                    <input
                      ref={searchRef}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="type to narrow, then press a number"
                      className="h-8 w-64 rounded-control border border-line bg-surface px-2.5 text-[13px]"
                    />
                    <span className="flex items-center gap-1.5 text-[11.5px] text-ink3">
                      <Kbd>/</Kbd> to search
                    </span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {shortlist.map((c, i) => (
                      <button
                        key={c}
                        type="button"
                        disabled={saving}
                        onClick={() => void assign(c)}
                        className="flex items-center gap-2.5 rounded-[8px] border border-line px-3 py-2 text-left text-[13.5px] transition-colors hover:border-accent disabled:opacity-50"
                      >
                        <Kbd>{i + 1}</Kbd>
                        {prettyCategory(c)}
                      </button>
                    ))}
                    {shortlist.length === 0 ? (
                      <p className="text-[13px] text-ink3">
                        Nothing matches “{query}”. Clear the box to see the full list.
                      </p>
                    ) : null}
                  </div>
                </div>

                {siblings > 0 ? (
                  <p className="flex items-start gap-2.5 rounded-card bg-accentSoft px-3.5 py-3 text-[13px] leading-relaxed">
                    <Info size={15} className="mt-px shrink-0 text-accentInk" />
                    <span>
                      Assigning this also writes the rule{" "}
                      <span className="mono text-[12px] font-medium">
                        {focused.merchant} → …
                      </span>
                      , which clears <strong>{siblings}</strong> more row
                      {siblings === 1 ? "" : "s"} in this queue.
                    </span>
                  </p>
                ) : null}

                {error ? (
                  <p className="text-[13px] font-medium text-bad">{error}</p>
                ) : null}

                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-hair pt-4 text-xs text-ink2">
                  <span className="flex items-center gap-1.5"><Kbd>J</Kbd><Kbd>K</Kbd> move</span>
                  <span className="flex items-center gap-1.5"><Kbd>1</Kbd>–<Kbd>9</Kbd> assign</span>
                  <span className="flex items-center gap-1.5"><Kbd>S</Kbd> skip</span>
                  <span className="flex items-center gap-1.5">
                    click the figure <ArrowRight size={12} /> its statement line
                  </span>
                  <span className="ml-auto text-ink3">
                    rules are written to <span className="mono">data/category_overrides.csv</span>
                  </span>
                </div>
                <p className="text-[11.5px] leading-relaxed text-ink3">
                  There is no undo: the data model has no way to un-set a category. Re-assigning is
                  the correction, and a category you set always outranks anything the engine
                  inferred — a later re-ingest will not overwrite it.
                </p>
              </Card>
            ) : (
              <State title="Queue cleared." tone="ok">
                Every row you were shown now has a category.
              </State>
            )}
          </div>
        </>
      )}
    </div>
  );
}
