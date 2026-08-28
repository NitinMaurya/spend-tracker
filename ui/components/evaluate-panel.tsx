"use client";

/**
 * Evaluate a card — the headline feature.
 *
 * Drop a Key Facts Statement and find out whether that card is worth it GIVEN HOW
 * YOU ACTUALLY SPEND. Every figure on this screen arrives computed by the engine
 * (D-029); nothing here does money arithmetic. The only maths is turning an
 * already-computed rate in basis points into a percentage and a bar width.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiDown,
  evaluateCard,
  type EvalLine,
  type Evaluation,
  type Overview,
  type Tier,
} from "@/lib/api";
import { formatAbs, formatMoney, isNegative } from "@/lib/money";
import { prettyCategory } from "@/lib/format";
import { Card, Chip, PageTitle, CardTitle } from "@/components/ui";

/** The API prints a tier's wording under `category`; older shapes used label/categories. */
type TierView = Tier & { category?: string | null };

/** A 400 from /api/evaluate carries a structured detail — often with the products it did find. */
type EvalFailure = { message: string; cards_found?: string[]; hint?: string };

const SAMPLES = [
  "sample_kfs/Mashreq-Cards-KFS-new-en-ar.pdf",
  "sample_kfs/adcb-credit-cards-kfs.pdf",
];

/** rate_bps is a rate, not money — safe to render as a percentage. */
function ratePct(bps: number): string {
  return `${(bps / 100).toFixed(2).replace(/\.?0+$/, "")}%`;
}

function parseFailure(err: unknown): EvalFailure {
  const raw = err instanceof Error ? err.message : String(err);
  try {
    const parsed = JSON.parse(raw) as EvalFailure;
    if (parsed && typeof parsed === "object" && typeof parsed.message === "string") return parsed;
  } catch {
    /* not JSON — it is already a sentence */
  }
  return { message: raw };
}

const MATCH_TONE = { EXPLICIT: "ok", CATCH_ALL: "neutral", NONE: "warn" } as const;
const MATCH_WORD = {
  EXPLICIT: "Named",
  CATCH_ALL: "All other",
  NONE: "No rate",
} as const;

export function EvaluatePanel() {
  const [file, setFile] = useState<File | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [result, setResult] = useState<Evaluation | null>(null);
  const [failure, setFailure] = useState<EvalFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [apiDown, setApiDown] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const dragDepth = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    api
      .overview()
      .then((o) => live && setOverview(o))
      .catch((e) => {
        if (live && e instanceof ApiDown) setApiDown(true);
      });
    return () => {
      live = false;
    };
  }, []);

  const run = useCallback(async (f: File, cardName?: string) => {
    setBusy(true);
    setFailure(null);
    setChosen(cardName ?? null);
    try {
      const out = await evaluateCard(f, cardName);
      setResult(out);
      setChosen(out.card);
      setApiDown(false);
    } catch (err) {
      if (err instanceof TypeError) {
        setApiDown(true);
        setResult(null);
      } else {
        setResult(null);
        setFailure(parseFailure(err));
      }
    } finally {
      setBusy(false);
    }
  }, []);

  const accept = useCallback(
    (f: File | null | undefined) => {
      if (!f) return;
      setFile(f);
      setResult(null);
      setFailure(null);
      void run(f);
    },
    [run]
  );

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    accept(e.dataTransfer.files?.[0]);
  }

  /* the products this document mentions — from a result, or from a failure that still listed them */
  const found = result?.cards_found ?? failure?.cards_found ?? [];
  const multiple = found.length > 1;

  return (
    <div className="space-y-9">
      

      {apiDown ? (
        <Card className="border-warn/40 bg-warnSoft/40">
          <p className="font-medium">The analyser isn&apos;t running.</p>
          <p className="mt-1 text-sm text-ink2">
            Start it and this page will pick straight up:
          </p>
          <p className="mono mt-2 rounded-lg bg-bg px-3 py-2 text-[12.5px] text-ink2">
            .venv/bin/python -m analyser.api
          </p>
        </Card>
      ) : null}

      {/* ── the drop zone ─────────────────────────────────────────────── */}
      <section className="rise">
        <label
          onDragEnter={(e) => {
            e.preventDefault();
            dragDepth.current += 1;
            setDragging(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={() => {
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (dragDepth.current === 0) setDragging(false);
          }}
          onDrop={onDrop}
          className={`block cursor-pointer rounded-card border-2 border-dashed p-10 text-center shadow-card transition-all sm:p-14 ${
            dragging
              ? "scale-[1.005] border-accent bg-accentSoft"
              : "border-line bg-surface hover:border-accent/60 hover:bg-surface2"
          } ${result || failure ? "p-6 sm:p-8" : ""}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="sr-only"
            onChange={(e) => accept(e.target.files?.[0])}
          />
          <span
            aria-hidden
            className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl text-[20px] text-white"
            style={{ background: "var(--accent)" }}
          >
            ↓
          </span>
          <p className="display text-lg font-semibold">
            {dragging ? "Drop it here" : file ? file.name : "Drop a Key Facts Statement"}
          </p>
          <p className="mx-auto mt-1.5 max-w-[46ch] text-sm text-ink2">
            {file
              ? "Drop another PDF, or click to choose a different one."
              : "A PDF from the bank — the sheet that lists the cashback rates, the annual fee and the exclusions. Or click to browse."}
          </p>
        </label>

        <p className="mt-3 text-xs text-ink3">
          The file is read in memory and never stored. Nothing is uploaded off this machine.
        </p>

        <p className="mt-2 text-xs text-ink3">
          Two samples already sit in the project if you want something to try:{" "}
          {SAMPLES.map((s, i) => (
            <span key={s}>
              {i ? " and " : ""}
              <span className="mono text-ink2">{s}</span>
            </span>
          ))}
          . A browser can&apos;t open a path on its own, so drag one in from Finder.
        </p>
      </section>

      {busy ? <Working /> : null}

      {/* ── which product? ────────────────────────────────────────────── */}
      {!busy && multiple ? (
        <section className="rise" style={{ animationDelay: "60ms" }}>
          <CardTitle>Which product is this?</CardTitle>
          <Card>
            <div className="flex flex-wrap gap-2">
              {found.map((name) => {
                const active = chosen === name;
                return (
                  <button
                    key={name}
                    type="button"
                    disabled={!file}
                    onClick={() => file && run(file, name)}
                    className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                      active
                        ? "border-accent bg-accent text-white"
                        : "border-line bg-bg text-ink2 hover:border-accent/60 hover:text-ink"
                    }`}
                  >
                    {name}
                  </button>
                );
              })}
            </div>
            <p className="mt-3 max-w-[70ch] text-xs text-ink3">
              This document prices {found.length} products in one table. Guessing would apply a
              neighbouring card&apos;s rates to your spending, so it asks instead.
            </p>
          </Card>
        </section>
      ) : null}

      {/* ── a document that yielded nothing ───────────────────────────── */}
      {!busy && failure ? (
        <Card className="rise border-warn/40">
          <div className="flex items-start gap-3">
            <Chip tone="warn">nothing read</Chip>
            <div>
              <p className="font-medium">{failure.message}</p>
              {failure.cards_found?.length ? (
                <p className="mt-1.5 max-w-[70ch] text-sm text-ink2">
                  The product names above were found in the document, but no reward rates could be
                  read for the one that was tried. Pick a product to try it directly.
                </p>
              ) : (
                <p className="mt-1.5 max-w-[70ch] text-sm text-ink2">
                  Nothing is assumed when a rate can&apos;t be read — an empty answer is better than
                  an invented one.
                </p>
              )}
            </div>
          </div>
        </Card>
      ) : null}

      {!busy && result ? <Result e={result} overview={overview} /> : null}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────── */

function Working() {
  return (
    <Card className="rise">
      <div className="flex items-center gap-3">
        <span
          aria-hidden
          className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-line"
          style={{ borderTopColor: "var(--accent)" }}
        />
        <div>
          <p className="font-medium">Reading the document…</p>
          <p className="text-sm text-ink2">
            Pulling the rate table out of the PDF and pricing it against your statements.
          </p>
        </div>
      </div>
    </Card>
  );
}

function Result({ e, overview }: { e: Evaluation; overview: Overview | null }) {
  const netBad = isNegative(e.net_annual);
  const monthWord = e.months_of_data === 1 ? "month" : "months";

  return (
    <div className="space-y-8">
      {/* ── hero ─────────────────────────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "80ms" }}>
        <div className="rounded-card border border-line bg-surface p-6 shadow-lift sm:p-8">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
              {e.card} · a year at your rate of spending
            </p>
          </div>

          <p className="hero-figure mt-3 text-[clamp(2.6rem,8vw,4.4rem)]">
            {formatMoney(e.annualised_reward)}
          </p>
          <p className="mt-2 max-w-[62ch] text-sm text-ink2">
            {e.annualised_reward
              ? `Projected reward, from ${formatAbs(e.observed_reward)} actually earned across ${e.months_of_data} ${monthWord} of statements.`
              : "Not enough was readable to project a year of rewards."}
            {overview?.total_spend ? (
              <> Your spending over that window: {formatAbs(overview.total_spend)}.</>
            ) : null}
          </p>

          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <Figure label="Earned so far" value={formatAbs(e.observed_reward)}
                    hint={`${e.months_of_data} ${monthWord} of real statements`} />
            <Figure label="Annual fee" value={formatAbs(e.annual_fee)}
                    hint={e.annual_fee.minor === 0 ? "no fee printed on this product" : "as printed in the document"} />
            <Figure
              label="Net for the year"
              value={formatMoney(e.net_annual, { sign: true })}
              hint={netBad ? "the fee outruns the reward" : "reward after the fee"}
              tone={netBad ? "bad" : "ok"}
            />
          </div>
        </div>
      </section>

      {/* ── verdict ──────────────────────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "140ms" }}>
        {e.verdict_blocked ? (
          <Card className="border-warn/40 bg-warnSoft/30">
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone="warn">too early to call it</Chip>
              <span className="text-sm font-medium">Here is what it looks like so far</span>
            </div>
            <p className="mt-2 max-w-[74ch] text-sm text-ink2">
              {e.verdict_blocked_reason ??
                "There isn't enough history yet to stand behind a verdict."}
            </p>
            <p className="mt-2 max-w-[74ch] text-sm text-ink3">
              The projection above is real — it just rests on a short window. Add more statements
              and the same screen will answer the question outright.
            </p>
          </Card>
        ) : (
          <Card className={netBad ? "border-bad/40 bg-badSoft/30" : "border-ok/40 bg-okSoft/30"}>
            <div className="flex flex-wrap items-center gap-2">
              <Chip tone={netBad ? "bad" : "ok"}>verdict</Chip>
            </div>
            <p className="display mt-2 text-xl font-semibold">{e.verdict ?? "—"}</p>
          </Card>
        )}
      </section>

      {/* ── per-category breakdown ───────────────────────────────────── */}
      <section className="rise" style={{ animationDelay: "200ms" }}>
        <CardTitle>Where the reward would come from</CardTitle>
        <Breakdown lines={e.lines} />
        <p className="mt-3 max-w-[76ch] text-xs text-ink3">
          Matching your categories onto the card&apos;s wording is inferred, not certain — bank
          statements carry no MCC codes, so &ldquo;dining&rdquo; on the card and{" "}
          <span className="mono">RESTAURANTS</span> in your ledger are lined up by name.
        </p>
      </section>

      {/* ── below the fold ───────────────────────────────────────────── */}
      <section className="rise grid gap-4 lg:grid-cols-2" style={{ animationDelay: "260ms" }}>
        <Fine title="What the document actually says">
          {e.tiers.length ? (
            <ul className="space-y-2.5">
              {(e.tiers as TierView[]).map((t, i) => (
                <li key={i} className="border-l-2 border-line2 pl-3">
                  <p className="tnum text-sm font-semibold">{ratePct(t.rate_bps)}</p>
                  <p className="mt-0.5 text-xs text-ink2">
                    {t.source_quote ?? t.category ?? t.label ?? t.categories ?? "—"}
                  </p>
                  {t.cap_per_cycle ? (
                    <p className="tnum mt-0.5 text-xs text-ink3">capped per cycle</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink3">No rate lines were readable.</p>
          )}
        </Fine>

        <Fine title="Exclusions and conflicts">
          {e.exclusions.length === 0 && e.conflicts.length === 0 ? (
            <p className="text-sm text-ink3">
              None printed in this document. That is not proof there are none — only that none were
              found in the text.
            </p>
          ) : (
            <div className="space-y-4">
              {e.exclusions.length ? (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                    Spending that earns nothing
                  </p>
                  <ul className="space-y-1.5">
                    {e.exclusions.map((x, i) => (
                      <li key={i} className="text-sm text-ink2">
                        <span className="text-ink">{x.label}</span>
                        {x.detectability ? (
                          <span className="ml-2 text-xs text-ink3">
                            detectable from statements: {x.detectability.toLowerCase()}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {e.conflicts.length ? (
                <div>
                  <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                    The document contradicts itself
                  </p>
                  <ul className="space-y-1.5">
                    {e.conflicts.map((c, i) => (
                      <li key={i} className="mono text-xs text-ink2">
                        {c.rule}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          )}
        </Fine>
      </section>

      <p className="text-xs text-ink3">
        Read from <span className="mono text-ink2">{e.file}</span> in memory. The file was never
        written to disk.
      </p>
    </div>
  );
}

function Figure({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "ok" | "bad";
}) {
  const colour = tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : "";
  return (
    <div className="rounded-card border border-line bg-surface2 px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">{label}</p>
      <p className={`tnum display mt-1 text-2xl font-semibold ${colour}`}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-ink3">{hint}</p> : null}
    </div>
  );
}

function Breakdown({ lines }: { lines: EvalLine[] }) {
  if (!lines.length) {
    return (
      <Card>
        <p className="text-sm text-ink3">
          None of your spending lined up with this card&apos;s rate table.
        </p>
      </Card>
    );
  }
  const topRate = Math.max(...lines.map((l) => l.rate_bps), 1);

  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <ul className="divide-y divide-line">
        {lines.map((l, i) => (
          <li key={`${l.category}-${i}`} className="px-4 py-3.5 sm:px-5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <span className="flex items-center gap-2.5 text-sm font-medium">
                {prettyCategory(l.category)}
                <Chip tone={MATCH_TONE[l.match]}>{MATCH_WORD[l.match]}</Chip>
              </span>
              <span className="flex items-baseline gap-4">
                <span className="tnum text-sm text-ink2">{formatAbs(l.spend)}</span>
                <span className="tnum w-14 text-right text-sm font-medium text-ink2">
                  {ratePct(l.rate_bps)}
                </span>
                <span className="tnum w-24 text-right text-sm font-semibold">
                  {formatAbs(l.reward)}
                </span>
              </span>
            </div>

            {/* width encodes the earn RATE against the best rate on this card — never money */}
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-hair">
              <div
                className="grow h-full rounded-full"
                style={{
                  width: `${Math.max((l.rate_bps / topRate) * 100, 2)}%`,
                  background:
                    l.match === "EXPLICIT"
                      ? "var(--accent)"
                      : l.match === "CATCH_ALL"
                        ? "var(--ink-3)"
                        : "var(--warn)",
                  animationDelay: `${i * 45}ms`,
                }}
              />
            </div>

            {l.match === "EXPLICIT" && l.matched_rule ? (
              <p className="mt-2 border-l-2 border-accentSoft pl-2.5 text-xs italic text-ink3">
                “{l.matched_rule}”
              </p>
            ) : null}
            {l.match === "CATCH_ALL" ? (
              <p className="mt-2 text-xs text-ink3">
                Not named by the card — this fell to the &ldquo;all other purchases&rdquo; rate.
              </p>
            ) : null}
            {l.match === "NONE" ? (
              <p className="mt-2 text-xs text-ink3">
                Nothing in the rate table covers this, and there is no catch-all to fall back on.
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      <div className="flex items-baseline justify-between gap-4 border-t border-line bg-surface2 px-4 py-3 text-xs text-ink3 sm:px-5">
        <span>category · your spend · rate · reward</span>
        <span>{lines.length} categories priced</span>
      </div>
    </div>
  );
}

function Fine({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-card border border-line bg-surface px-5 py-4 shadow-card">
      <summary className="flex cursor-pointer list-none items-center justify-between text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
        {title}
        <span aria-hidden className="text-base transition-transform group-open:rotate-45">
          +
        </span>
      </summary>
      <div className="mt-3.5">{children}</div>
    </details>
  );
}
