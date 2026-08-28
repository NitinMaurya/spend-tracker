"use client";

/**
 * Tidy up — the small queue of spending the categoriser could not place.
 *
 * Every figure here is rendered from the Money the API computed; nothing is
 * summed, rated or divided in TypeScript (D-002, D-008, D-029). Ordering is the
 * API's too: /api/review returns rows by value, largest first (D-016d).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiDown, type ReviewRow } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { Card, Chip, State } from "@/components/ui";

type SaveState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "saved"; note: string; written: string[]; canonical: string; category: string; match: string }
  | { phase: "error"; message: string };

type Draft = { match: string; canonical: string; category: string };

/* ---------- confidence ---------------------------------------------------- */

function confidenceTone(c: string | null): "ok" | "warn" | "bad" | "neutral" {
  const v = (c ?? "UNKNOWN").toUpperCase();
  if (v === "HIGH" || v === "CONFIRMED" || v === "CORRECTED") return "ok";
  if (v === "MEDIUM" || v === "LOW") return "warn";
  if (v === "UNKNOWN" || v === "NONE") return "bad";
  return "neutral";
}

function confidenceWord(c: string | null): string {
  const v = (c ?? "UNKNOWN").toUpperCase();
  if (v === "UNKNOWN" || v === "NONE") return "no idea what this is";
  if (v === "LOW") return "a guess, not a good one";
  if (v === "MEDIUM") return "a reasonable guess";
  return v.toLowerCase();
}

/* ---------- match prefill -------------------------------------------------
   `match` is an uppercase substring of the raw description. It is what will be
   tested against FUTURE statements, so it must be the stable part: drop card
   fragments, reference numbers, dates and trailing digits, then keep the first
   few words. The user can always edit it — this is only a starting point.     */

const NOISE = /^(\d+|[0-9*x#-]{3,}|AED|USD|EUR|POS|VISA|MASTERCARD|TXN|REF|PURCHASE|PAYMENT\d+)$/i;

function suggestMatch(raw: string | null, merchant: string | null): string {
  const source = (raw ?? merchant ?? "").toUpperCase();
  const words = source
    .replace(/[^A-Z0-9&' .-]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .filter((w) => !NOISE.test(w));
  if (words.length === 0) return source.trim().slice(0, 24);
  return words.slice(0, 3).join(" ").slice(0, 32);
}

function prettyDate(d: string): string {
  const t = Date.parse(d);
  if (Number.isNaN(t)) return d;
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(new Date(t));
}

const SUB = "A short list of spending that has not been labelled yet. Label it once and it stays labelled.";

/* ---------- page ---------------------------------------------------------- */


/**
 * Repayments — card payments and rows on a settlement account — are money moving
 * between your own accounts, not spending. Counting them twice is the single
 * easiest way to get a spending total wrong, so they are off by default.
 */
function RepaymentToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2.5 rounded-card border border-line bg-card2 px-3.5 py-2.5">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 accent-[var(--accent)]"
      />
      <span className="text-xs">
        <span className="font-medium text-ink">Show repayments</span>
        <span className="ml-1.5 text-ink3">card payments &amp; transfers</span>
      </span>
    </label>
  );
}

export function FixupsPanel() {
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [down, setDown] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [saves, setSaves] = useState<Record<string, SaveState>>({});
  const [showWhy, setShowWhy] = useState(false);
  // Repayments (card payments, settlement-account rows) are money moving between
  // your own accounts, not spending. Categorising them is meaningless work, so
  // they are hidden unless asked for.
  const [showRepayments, setShowRepayments] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [r, c] = await Promise.all([api.review(showRepayments), api.categories()]);
        if (!alive) return;
        setRows(r);
        setCategories(c);
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiDown) setDown(e.message);
        else setFailed(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [showRepayments]);

  const draftFor = useCallback(
    (row: ReviewRow): Draft =>
      drafts[row.txn_id] ?? {
        match: suggestMatch(row.raw_description, row.merchant),
        canonical: row.merchant ?? "",
        category: row.category ?? "",
      },
    [drafts]
  );

  const setDraft = (id: string, patch: Partial<Draft>, base: Draft) =>
    setDrafts((d) => ({ ...d, [id]: { ...base, ...patch } }));

  async function save(row: ReviewRow) {
    const d = draftFor(row);
    const match = d.match.trim().toUpperCase();
    if (!match) {
      setSaves((s) => ({
        ...s,
        [row.txn_id]: {
          phase: "error",
          message: "A match string is required — it is what future statements are tested against.",
        },
      }));
      return;
    }
    setSaves((s) => ({ ...s, [row.txn_id]: { phase: "saving" } }));
    try {
      const res = await api.addCorrection({
        match,
        canonical: d.canonical.trim() || undefined,
        category: d.category || undefined,
      });
      setSaves((s) => ({
        ...s,
        [row.txn_id]: {
          phase: "saved",
          note: res.note,
          written: res.written ?? [],
          canonical: d.canonical.trim(),
          category: d.category,
          match,
        },
      }));
      setOpen((o) => (o === row.txn_id ? null : o));
    } catch (e) {
      setSaves((s) => ({
        ...s,
        [row.txn_id]: { phase: "error", message: e instanceof Error ? e.message : String(e) },
      }));
    }
  }

  /* ---------- counts (rows, never money) ---------------------------------- */

  const unknownCount = useMemo(
    () => (rows ?? []).filter((r) => (r.category_confidence ?? "UNKNOWN").toUpperCase() === "UNKNOWN").length,
    [rows]
  );
  const savedCount = Object.values(saves).filter((s) => s.phase === "saved").length;
  const remaining = rows ? rows.length - savedCount : 0;

  /* ---------- states ------------------------------------------------------ */

  if (down) {
    return (
      <>
        <State title="The analyser is not running, so there is nothing to tidy yet.">
          <p>Start it, then reload this page:</p>
          <p className="mono mt-2 rounded-card border border-line bg-line2 px-3 py-2 text-ink">
            .venv/bin/python -m analyser.api
          </p>
        </State>
      </>
    );
  }

  if (failed) {
    return (
      <>
        <State title="This list could not be loaded.">
          <p className="mono">{failed}</p>
        </State>
      </>
    );
  }

  if (!rows) {
    return (
      <>
        <Card className="shadow-card">
          <p className="text-sm text-ink2">Looking for anything that still needs a label…</p>
        </Card>
      </>
    );
  }

  const allDone = remaining <= 0;

  return (
    <>

      {/* Hero — how much work is actually left */}
      <section className="rise mb-8 rounded-card border border-line bg-card p-6 shadow-card sm:p-8">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink3">Waiting on you</p>
            <p className="hero-figure mt-2 text-6xl text-ink sm:text-7xl">{remaining}</p>
            <p className="mt-2 max-w-[42ch] text-sm text-ink2">
              {allDone
                ? "All labelled. Nothing else needs a decision right now."
                : remaining === 1
                  ? "one payment your spending breakdown cannot place yet"
                  : `payments your spending breakdown cannot place yet${
                      unknownCount ? ` — ${unknownCount} of them with no category at all` : ""
                    }`}
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <MiniStat label="Labelled just now" value={savedCount} tone={savedCount > 0 ? "ok" : undefined} />
            <MiniStat label="In the list" value={rows.length} />
            <RepaymentToggle on={showRepayments} onChange={setShowRepayments} />
          </div>
        </div>

        <p className="mt-6 max-w-[74ch] border-t border-line pt-5 text-sm leading-relaxed text-ink2">
          <span className="font-medium text-ink">Biggest amounts first, on purpose.</span> One large unknown
          bends your category totals far more than forty small ones, so work down from the top and stop
          whenever you like — what is left behind is the cheap stuff. Labels you set here are permanent: they
          outrank the app&apos;s own guesses and apply to every future statement too.
        </p>

        <button
          type="button"
          onClick={() => setShowWhy((v) => !v)}
          className="mt-4 rounded-full border border-line px-3 py-1 text-xs font-medium text-ink2 transition-colors hover:border-accent hover:bg-accentSoft hover:text-accent"
        >
          {showWhy ? "Hide the details" : "Where does a label get saved?"}
        </button>

        {showWhy ? (
          <div className="rise mt-4 rounded-card border border-line bg-card2 p-4">
            <p className="max-w-[80ch] text-sm text-ink2">
              Two plain text files you own: <span className="mono text-ink">data/merchant_map.csv</span> and{" "}
              <span className="mono text-ink">data/category_overrides.csv</span>. No hidden database — you can
              open them in any editor, and to undo a label you delete its line.
            </p>
            <p className="mt-2 max-w-[80ch] text-sm text-ink2">
              A label takes effect on the <span className="font-medium text-ink">next import</span>, so the
              figures on this screen will not move until then. A re-parse never overwrites it (D-001, spec §18).
            </p>
            <p className="mt-2 max-w-[80ch] text-sm text-ink3">
              The <span className="mono">match</span> text is the load-bearing part: an uppercase fragment
              tested against the raw bank description of future transactions. Keep the merchant name, drop
              reference numbers and dates.
            </p>
          </div>
        ) : null}
      </section>

      {rows.length === 0 ? (
        <State title="Nothing to tidy.">
          <p>
            Every payment already has a category the app is confident about. Anything new and unrecognised will
            show up here after your next import.
          </p>
        </State>
      ) : (
        <div className="space-y-4">
          {rows.map((row, i) => {
            const d = draftFor(row);
            const state: SaveState = saves[row.txn_id] ?? { phase: "idle" };
            return (
              <RowCard
                key={row.txn_id}
                row={row}
                index={i}
                draft={d}
                state={state}
                isOpen={open === row.txn_id}
                categories={categories}
                onToggle={() => setOpen(open === row.txn_id ? null : row.txn_id)}
                onChange={(patch) => setDraft(row.txn_id, patch, d)}
                onSave={() => save(row)}
              />
            );
          })}
        </div>
      )}

      <p className="mt-8 max-w-[74ch] text-xs leading-relaxed text-ink3">
        The raw description under each payment is exactly what the bank sent — it is shown so you can check the
        app is not putting words in your statement&apos;s mouth.
      </p>
    </>
  );
}

/* ---------- small pieces -------------------------------------------------- */

function MiniStat({ label, value, tone }: { label: string; value: number; tone?: "ok" }) {
  return (
    <div className="rounded-card border border-line bg-card2 px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-[0.07em] text-ink3">{label}</p>
      <p className={`tnum display mt-1 text-2xl font-semibold ${tone === "ok" ? "text-ok" : "text-ink"}`}>{value}</p>
    </div>
  );
}

/* ---------- one payment + its inline editor ------------------------------- */

function RowCard({
  row,
  index,
  draft,
  state,
  isOpen,
  categories,
  onToggle,
  onChange,
  onSave,
}: {
  row: ReviewRow;
  index: number;
  draft: Draft;
  state: SaveState;
  isOpen: boolean;
  categories: string[];
  onToggle: () => void;
  onChange: (patch: Partial<Draft>) => void;
  onSave: () => void;
}) {
  const saved = state.phase === "saved" ? state : null;
  const settled = !!saved;

  return (
    <article
      className={`rise rounded-card border p-5 shadow-card transition-colors sm:p-6 ${
        settled ? "border-ok/40 bg-okSoft/40" : "border-line bg-card hover:shadow-lift"
      }`}
      style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
        {/* identity */}
        <div className="min-w-[16rem] flex-1">
          <h3 className="display text-lg font-semibold text-ink">
            {saved?.canonical || row.merchant || "Unrecognised payment"}
          </h3>
          {saved?.canonical && saved.canonical !== (row.merchant ?? "") ? (
            <p className="mt-0.5 text-xs text-ink3">
              was <span className="mono">{row.merchant ?? "—"}</span>
            </p>
          ) : null}

          <p className="mono mt-2 max-w-[52ch] text-xs leading-relaxed text-ink3">
            {row.raw_description ?? "— no description came through on this line —"}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {saved?.category ? (
              <Chip tone="ok">{saved.category}</Chip>
            ) : row.category ? (
              <Chip tone="neutral">{row.category}</Chip>
            ) : (
              <Chip tone="bad">no category</Chip>
            )}
            <span className="text-xs text-ink3">
              {settled ? "labelled by you" : confidenceWord(row.category_confidence)}
            </span>
          </div>
        </div>

        {/* money + action */}
        <div className="flex flex-col items-end gap-3">
          <p className="tnum display text-2xl font-semibold text-ink">{formatMoney(row.amount, { sign: true })}</p>
          <p className="tnum text-xs text-ink3">{prettyDate(row.txn_date)}</p>
          <p className="mono text-[11px] text-ink3">{row.account_id}</p>
          <button
            type="button"
            onClick={onToggle}
            className={`mt-1 rounded-full px-4 py-1.5 text-xs font-semibold transition-colors ${
              isOpen
                ? "border border-line bg-card2 text-ink2 hover:text-ink"
                : settled
                  ? "border border-ok/40 bg-card text-ok hover:bg-okSoft"
                  : "bg-accent text-card hover:opacity-90"
            }`}
          >
            {isOpen ? "Close" : settled ? "Change it" : "Give it a label"}
          </button>
        </div>
      </div>

      {/* satisfying saved state */}
      {saved && !isOpen ? (
        <div className="rise mt-5 rounded-card border border-ok/30 bg-card/70 px-4 py-3">
          <p className="text-sm font-medium text-ok">Saved — and it will hold for future statements.</p>
          <p className="mono mt-1 text-xs text-ink2">
            {saved.match} → {saved.canonical || "(name unchanged)"}
            {saved.category ? ` · ${saved.category}` : ""}
          </p>
          <p className="mt-1 text-xs text-ink3">
            {saved.note}
            {saved.written.length ? (
              <>
                {" "}
                <span className="mono">{saved.written.join("  ·  ")}</span>
              </>
            ) : null}
          </p>
        </div>
      ) : null}

      {/* editor */}
      {isOpen ? (
        <div className="rise mt-5 border-t border-line pt-5">
          <div className="grid gap-5 lg:grid-cols-2">
            <Field
              label="What should this be called?"
              hint="The name you want to see in your spending breakdown."
            >
              <input
                value={draft.canonical}
                onChange={(e) => onChange({ canonical: e.target.value })}
                spellCheck={false}
                placeholder={row.merchant ?? "merchant name"}
                className="w-full rounded-card border border-line bg-card px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-accent"
              />
            </Field>

            <Field label="Which category?" hint="Leave blank to fix only the name.">
              <select
                value={draft.category}
                onChange={(e) => onChange({ category: e.target.value })}
                className="w-full rounded-card border border-line bg-card px-3 py-2 text-sm text-ink outline-none transition-colors focus:border-accent"
              >
                <option value="">— leave it uncategorised —</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>

            <Field
              label="Recognise it next time by"
              hint="An uppercase fragment of the bank's description. Keep the stable part; drop reference numbers and dates."
            >
              <input
                value={draft.match}
                onChange={(e) => onChange({ match: e.target.value.toUpperCase() })}
                spellCheck={false}
                className="mono w-full rounded-card border border-line bg-card px-3 py-2 text-xs text-ink outline-none transition-colors focus:border-accent"
              />
            </Field>

            <div className="flex items-end justify-start lg:justify-end">
              <button
                type="button"
                onClick={onSave}
                disabled={state.phase === "saving"}
                className="rounded-full bg-accent px-5 py-2 text-sm font-semibold text-card transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {state.phase === "saving" ? "Saving…" : "Save this label"}
              </button>
            </div>
          </div>

          {state.phase === "error" ? (
            <p className="mt-4 rounded-card border border-bad/30 bg-badSoft px-4 py-3 text-xs text-bad">
              Nothing was saved: {state.message}
            </p>
          ) : null}

          {saved ? (
            <p className="mt-4 rounded-card border border-ok/30 bg-okSoft px-4 py-3 text-xs text-ok">
              {saved.note}
              {saved.written.length ? ` · ${saved.written.join("  ·  ")}` : ""}
            </p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">{label}</span>
      {children}
      {hint ? <span className="mt-1.5 block max-w-[46ch] text-[11px] leading-relaxed text-ink3">{hint}</span> : null}
    </label>
  );
}
