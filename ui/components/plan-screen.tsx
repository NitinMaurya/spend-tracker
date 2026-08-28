"use client";

/**
 * Plan — the product's primary output, and the step that unlocks it.
 *
 * The engine will not produce a plan from extracted rules alone, and that is
 * deliberate (D-027, P1, P3). Extraction reads a RATE and the SENTENCE it came
 * from — "5% cashback on local and international dining spends" — but it will
 * not guess which of your categories that sentence covers. A wrong guess there
 * silently misprices every recommendation downstream.
 *
 * So this screen has two states: confirm the mapping, then read the plan. The
 * verbatim quote sits beside every field while you confirm it, which is the
 * whole point — you are checking a claim against its source, not typing numbers
 * into a form.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, ApiDown, saveWallet,
  type PlanResult, type Rules, type Tier,
  type WalletAccount, type WalletCard, type WalletState,
} from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import { bpsPct, longDate, prettyCategory } from "@/lib/format";
import {
  Aside, Card, CardTitle, Chip, Code, Eyebrow, PageTitle, SectionTitle, State,
} from "@/components/ui";
import { Alert, ArrowRight, Check, Cross, Info, Plus } from "@/components/icons";

/* ── draft model ─────────────────────────────────────────────────────────── */

type DraftTier = {
  key: string;
  rate_bps: number;
  categories: string;      // comma-separated; empty = catch-all
  catchAll: boolean;
  cap: string;             // major units, as typed
  quote: string | null;
};

type Draft = {
  accountId: string;
  annualFee: string;       // major units, as typed
  lookup: string;
  tiers: DraftTier[];
  rules: Rules | null;
  loading: boolean;
  error: string | null;
};

/** A sensible first guess at the product name to search the terms library for. */
function guessLookup(a: WalletAccount): string {
  const name = (a.product_name ?? a.issuer).replace(/_/g, " ");
  const word = name.split(/\s+/).find((w) => w.length > 2 && !/^(credit|card|the)$/i.test(w));
  return (word ?? name).toLowerCase();
}

function tierFromExtracted(t: Tier, i: number): DraftTier {
  return {
    key: `x${i}`,
    rate_bps: t.rate_bps,
    categories: t.categories ?? "",
    catchAll: !t.categories,
    cap: t.cap_per_cycle != null ? String(t.cap_per_cycle / 100) : "",
    quote: t.source_quote ?? t.label ?? null,
  };
}

function blankTier(i: number): DraftTier {
  return { key: `n${i}${Math.random().toString(36).slice(2, 6)}`,
           rate_bps: 100, categories: "", catchAll: false, cap: "", quote: null };
}

function draftFor(a: WalletAccount, existing?: WalletCard): Draft {
  return {
    accountId: a.account_id,
    annualFee: existing ? String(existing.annual_fee_minor / 100) : "",
    lookup: guessLookup(a),
    rules: null,
    loading: false,
    error: null,
    tiers: existing
      ? existing.reward.tiers.map((t, i) => ({
          key: `e${i}`,
          rate_bps: t.rate_bps,
          categories: (t.categories ?? []).join(", "),
          catchAll: t.categories == null,
          cap: t.cap_per_cycle_minor != null ? String(t.cap_per_cycle_minor / 100) : "",
          quote: t.label ?? null,
        }))
      : [],
  };
}

function toWalletCard(a: WalletAccount, d: Draft): WalletCard {
  const fee = Math.round((Number(d.annualFee) || 0) * 100);
  return {
    card_id: a.account_id,
    account_id: a.account_id,
    issuer: a.issuer,
    currency: a.currency || "AED",
    annual_fee_minor: fee,
    reward: {
      unit: a.currency || "AED",
      cycle: { anchor_day: 1, key: "POSTING" },
      rounding: { mode: "HALF_UP", unit: "MINOR", scope: "CYCLE" },
      tiers: d.tiers.map((t) => ({
        categories: t.catchAll
          ? null
          : t.categories.split(",").map((c) => c.trim().toUpperCase().replace(/\s+/g, "_")).filter(Boolean),
        rate_bps: Math.round(Number(t.rate_bps) || 0),
        ...(t.cap.trim() ? { cap_per_cycle_minor: Math.round(Number(t.cap) * 100) } : {}),
        ...(t.quote ? { label: t.quote.slice(0, 180) } : {}),
      })),
    },
  };
}

/* ── the screen ──────────────────────────────────────────────────────────── */

export function PlanScreen() {
  const [wallet, setWallet] = useState<WalletState | null>(null);
  const [plan, setPlan] = useState<PlanResult | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [down, setDown] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [w, c] = await Promise.all([api.wallet(), api.categories().catch(() => [])]);
      setWallet(w);
      setCategories(c);
      setPlan(await api.plan().catch(() => null));
    } catch (e) {
      if (e instanceof ApiDown) setDown(true);
      else setFailed(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (down) {
    return (
      <State title="The engine is not running, so there is nothing to plan from.">
        <Code>.venv/bin/python -m analyser.api</Code>
      </State>
    );
  }
  if (failed) return <State title={failed} tone="bad" />;
  if (!wallet) return <p className="text-sm text-ink3">Reading your wallet…</p>;

  const ready = plan?.ready && plan.plan;

  return (
    <div className="flex flex-col gap-9">
      {ready && !editing ? (
        <PlanView
          plan={plan!}
          wallet={wallet}
          onRevise={() => setEditing(true)}
        />
      ) : (
        <Confirm
          wallet={wallet}
          categories={categories}
          reason={plan?.reason ?? "NO_WALLET"}
          detail={plan?.detail}
          onSaved={async () => { setEditing(false); await load(); }}
          onCancel={ready ? () => setEditing(false) : undefined}
        />
      )}
    </div>
  );
}

/* ── state 1 · the plan ──────────────────────────────────────────────────── */

function PlanView({
  plan, wallet, onRevise,
}: { plan: PlanResult; wallet: WalletState; onRevise: () => void }) {
  const p = plan.plan!;
  const moves = p.moves;
  const peak = Math.max(...moves.map((m) => Math.abs(m.annual_gain.minor)), 1);
  const worthIt = (p.annual_gain?.minor ?? 0) > 0;

  return (
    <>
      <section className="grid gap-5 lg:grid-cols-[24rem_1fr]">
        <Card className="rise flex flex-col p-6">
          <Eyebrow>{worthIt ? "Routing would earn you" : "Routing would earn you"}</Eyebrow>
          <p className="hero-figure mt-3">{formatAbs(p.annual_gain)}</p>
          <p className="mt-1.5 text-sm text-ink2">
            a year more than you earn today, after annual fees
          </p>
          <div className="mt-5 flex flex-col gap-2.5 border-t border-hair pt-4">
            <Row label="If you change nothing" value={formatAbs(p.value_unchanged)} />
            <Row label="If you route as planned" value={formatAbs(p.value_if_routed)} tone="ok" />
          </div>
          <p className="mt-4 text-xs leading-relaxed text-ink3">
            Both figures are reported because collapsing them into one headline overstates every
            card — the higher number quietly assumes you reorganise your spending perfectly and keep
            doing it. The gap between them is what the effort is worth.
          </p>
        </Card>

        <Card className="rise flex flex-col gap-4 p-6">
          <CardTitle
            aside={`${plan.transactions_considered} transactions · ${plan.horizon?.months} months from ${plan.horizon ? longDate(plan.horizon.start) : ""}`}
          >
            {moves.length === 0 ? "Nothing worth moving" : `${moves.length} change${moves.length === 1 ? "" : "s"}, ranked by what each is worth`}
          </CardTitle>

          {moves.length === 0 ? (
            <p className="text-sm leading-relaxed text-ink2">
              Every routable category is already on the card that pays most for it. That is a real
              result, not an empty screen — there is nothing to do.
            </p>
          ) : (
            <>
              <div className="flex flex-col gap-3.5">
                {moves.map((m, i) => (
                  <div key={`${m.category}-${m.to_card}`} className="flex flex-col gap-1.5">
                    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 text-[13.5px]">
                      <span className="tnum w-5 shrink-0 text-ink3">{i + 1}</span>
                      <span className="font-semibold">{prettyCategory(m.category)}</span>
                      <span className="text-ink3">{m.from_card ?? "unassigned"}</span>
                      <ArrowRight size={13} className="text-ink3" />
                      <span className="font-medium">{m.to_card}</span>
                      <span className="tnum ml-auto font-semibold text-ok">
                        +{formatAbs(m.annual_gain).replace(/^[A-Z]{3}\s/, "")}/yr
                      </span>
                    </div>
                    <div className="ml-7 flex items-center gap-3">
                      <span className="h-2.5 flex-grow">
                        <span
                          className="bar block h-2.5 rounded-r-[4px] bg-accent"
                          style={{
                            width: `${(Math.abs(m.annual_gain.minor) / peak) * 100}%`,
                            animationDelay: `${120 + i * 70}ms`,
                          }}
                        />
                      </span>
                      <span className="tnum w-28 shrink-0 text-right text-[11.5px] text-ink3">
                        {formatAbs(m.monthly_spend).replace(/^[A-Z]{3}\s/, "")}/month
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              {p.moves_for_80pct > 0 && moves.length > p.moves_for_80pct ? (
                <p className="flex items-start gap-2 border-t border-hair pt-3 text-xs leading-relaxed text-ink2">
                  <Info size={13} className="mt-px shrink-0 text-ink3" />
                  <span>
                    The first <strong>{p.moves_for_80pct}</strong> change
                    {p.moves_for_80pct === 1 ? "" : "s"} capture 80% of the benefit. The remaining{" "}
                    {moves.length - p.moves_for_80pct} are worth far less — stop early if you want.
                  </span>
                </p>
              ) : null}
            </>
          )}
        </Card>
      </section>

      <section className="flex flex-col gap-3">
        <SectionTitle aside={`${wallet.confirmed_count} confirmed`}>The cards this used</SectionTitle>
        <Card className="flex flex-wrap items-center gap-x-6 gap-y-3">
          {wallet.cards.map((c) => (
            <div key={c.card_id} className="flex flex-col gap-0.5">
              <span className="mono text-[12px] font-medium">{c.card_id}</span>
              <span className="text-[11.5px] text-ink3">
                {c.reward.tiers.length} tiers · fee{" "}
                <span className="tnum">
                  {formatAbs({ minor: c.annual_fee_minor, currency: c.currency, exponent: 2 })}
                </span>
              </span>
            </div>
          ))}
          <button
            type="button"
            onClick={onRevise}
            className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-control border border-line bg-surface px-4 text-[13px] font-semibold"
          >
            Revise what you confirmed
          </button>
        </Card>
        <p className="max-w-[80ch] text-xs leading-relaxed text-ink3">
          Only routable purchase spend is planned. Merchant-locked charges, direct debits and
          acceptance-limited rows stay exactly where they are, because moving them is not something
          you can actually do.
        </p>
      </section>
    </>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "ok" }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[13px] text-ink2">{label}</span>
      <span className={`tnum text-sm font-semibold ${tone === "ok" ? "text-ok" : ""}`}>{value}</span>
    </div>
  );
}

/* ── state 2 · confirm the mapping ───────────────────────────────────────── */

function Confirm({
  wallet, categories, reason, detail, onSaved, onCancel,
}: {
  wallet: WalletState;
  categories: string[];
  reason: string;
  detail?: string;
  onSaved: () => void;
  onCancel?: () => void;
}) {
  const cardByAccount = useMemo(
    () => new Map(wallet.cards.map((c) => [c.account_id, c])),
    [wallet.cards],
  );
  const usable = wallet.accounts.filter((a) => a.txns > 0);

  const [drafts, setDrafts] = useState<Record<string, Draft>>(() => {
    const out: Record<string, Draft> = {};
    for (const a of usable) {
      const existing = cardByAccount.get(a.account_id);
      if (existing) out[a.account_id] = draftFor(a, existing);
    }
    return out;
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const include = (a: WalletAccount) =>
    setDrafts((d) => ({ ...d, [a.account_id]: draftFor(a, cardByAccount.get(a.account_id)) }));
  const drop = (id: string) =>
    setDrafts((d) => { const n = { ...d }; delete n[id]; return n; });
  const patch = (id: string, p: Partial<Draft>) =>
    setDrafts((d) => ({ ...d, [id]: { ...d[id], ...p } }));

  async function findTerms(a: WalletAccount) {
    const d = drafts[a.account_id];
    patch(a.account_id, { loading: true, error: null });
    try {
      const rules = await api.rules(d.lookup.trim());
      patch(a.account_id, {
        rules,
        loading: false,
        tiers: rules.tiers.length
          ? rules.tiers.map(tierFromExtracted)
          : [blankTier(0)],
      });
    } catch (e) {
      patch(a.account_id, {
        loading: false,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  }

  const chosen = Object.keys(drafts);
  const complete = chosen.filter((id) => {
    const d = drafts[id];
    return d.tiers.length > 0 && d.tiers.every((t) => t.catchAll || t.categories.trim());
  });
  const canSave = complete.length >= 1 && complete.length === chosen.length;

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const cards = chosen.map((id) => {
        const a = usable.find((x) => x.account_id === id)!;
        return toWalletCard(a, drafts[id]);
      });
      await saveWallet({ cards, routing: wallet.routing });
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Card className="rise flex flex-col gap-3 border-l-[3px] border-l-warn">
        <div className="flex items-start gap-3">
          <Alert size={17} className="mt-0.5 shrink-0 text-warn" />
          <div className="flex flex-col gap-1.5">
            <p className="text-sm font-semibold">
              {reason === "NO_TRANSACTIONS"
                ? "No reconciled spending on the cards you confirmed"
                : "A plan needs you to confirm what each card actually pays"}
            </p>
            <p className="max-w-[82ch] text-[13px] leading-relaxed text-ink2">
              The terms extractor reads a rate and the sentence it came from, but it will not decide
              which of your categories that sentence covers. Guessing there would misprice every
              recommendation underneath it, so the engine stops and asks. Confirm the mapping once
              and the plan follows.
            </p>
          </div>
        </div>
      </Card>

      <section className="flex flex-col gap-4">
        <SectionTitle aside={`${chosen.length} of ${usable.length} cards in the plan`}>
          Confirm your cards
        </SectionTitle>

        {usable.length === 0 ? (
          <State title="No credit card has reconciled spending yet.">
            Read some statements first — the plan is priced on your own transactions.
          </State>
        ) : null}

        <div className="flex flex-col gap-4">
          {usable.map((a) => {
            const d = drafts[a.account_id];
            if (!d) {
              return (
                <Card key={a.account_id} className="flex flex-wrap items-center gap-4">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-[14.5px] font-semibold">
                      {a.product_name ?? a.issuer.replace(/_/g, " ")}
                    </span>
                    <span className="mono text-[11px] text-ink3">
                      {a.account_id} · {a.txns} transactions
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => include(a)}
                    className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-control border border-line bg-surface px-4 text-[13px] font-semibold"
                  >
                    <Plus size={14} />
                    Add to the plan
                  </button>
                </Card>
              );
            }

            return (
              <Card key={a.account_id} className="flex flex-col gap-5">
                <div className="flex flex-wrap items-start gap-4">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-[14.5px] font-semibold">
                      {a.product_name ?? a.issuer.replace(/_/g, " ")}
                    </span>
                    <span className="mono text-[11px] text-ink3">
                      {a.account_id} · {a.txns} transactions
                    </span>
                  </div>
                  <label className="flex flex-col gap-1">
                    <Eyebrow>Annual fee ({a.currency})</Eyebrow>
                    <input
                      inputMode="decimal"
                      value={d.annualFee}
                      onChange={(e) => patch(a.account_id, { annualFee: e.target.value })}
                      placeholder="0"
                      className="tnum h-9 w-28 rounded-control border border-line bg-surface px-2.5 text-sm"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => drop(a.account_id)}
                    className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-control px-3 text-[13px] font-medium text-ink2"
                  >
                    <Cross size={13} />
                    Leave out
                  </button>
                </div>

                {/* pull the extracted rules */}
                <div className="flex flex-wrap items-end gap-3 rounded-card border border-line bg-surface2 p-4">
                  <label className="flex flex-col gap-1">
                    <Eyebrow>Look up terms for</Eyebrow>
                    <input
                      value={d.lookup}
                      onChange={(e) => patch(a.account_id, { lookup: e.target.value })}
                      className="h-9 w-56 rounded-control border border-line bg-surface px-2.5 text-sm"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => void findTerms(a)}
                    disabled={d.loading}
                    className="inline-flex h-9 items-center gap-1.5 rounded-control bg-accent px-4 text-[13px] font-semibold text-white disabled:opacity-50"
                  >
                    {d.loading ? "Reading…" : "Read the terms"}
                  </button>
                  {d.rules ? (
                    <span className="flex flex-col gap-0.5 text-[11.5px] text-ink3">
                      <span>
                        {d.rules.sources.length} source
                        {d.rules.sources.length === 1 ? "" : "s"} ·{" "}
                        {d.rules.tiers.length} tier{d.rules.tiers.length === 1 ? "" : "s"} found
                      </span>
                      {d.rules.conflicts.length ? (
                        <span className="font-semibold text-warn">
                          {d.rules.conflicts.length} conflict
                          {d.rules.conflicts.length === 1 ? "" : "s"} — the lower rate is used
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    <span className="text-[11.5px] text-ink3">
                      Reads the Key Facts Statements on this machine.
                    </span>
                  )}
                  {d.error ? (
                    <span className="text-[11.5px] font-medium text-bad">{d.error}</span>
                  ) : null}
                </div>

                {/* tiers */}
                {d.tiers.length === 0 ? (
                  <p className="text-[13px] text-ink3">
                    Read the terms above, or{" "}
                    <button
                      type="button"
                      onClick={() => patch(a.account_id, { tiers: [blankTier(0)] })}
                      className="font-semibold text-accentInk underline underline-offset-2"
                    >
                      enter the rates yourself
                    </button>
                    .
                  </p>
                ) : (
                  <div className="flex flex-col gap-3">
                    <Eyebrow>
                      What it pays — assign each quoted rate to your categories
                    </Eyebrow>
                    {d.tiers.map((t, i) => (
                      <div
                        key={t.key}
                        className="flex flex-col gap-2.5 rounded-card border border-line p-3.5"
                      >
                        <div className="flex flex-wrap items-end gap-3">
                          <label className="flex flex-col gap-1">
                            <span className="text-[11px] font-medium text-ink3">Rate (bps)</span>
                            <input
                              inputMode="numeric"
                              value={t.rate_bps}
                              onChange={(e) => {
                                const tiers = [...d.tiers];
                                tiers[i] = { ...t, rate_bps: Number(e.target.value) || 0 };
                                patch(a.account_id, { tiers });
                              }}
                              className="tnum h-9 w-24 rounded-control border border-line bg-surface px-2.5 text-sm"
                            />
                          </label>
                          <span className="tnum pb-2 text-sm font-semibold">{bpsPct(t.rate_bps)}</span>
                          <label className="flex min-w-[16rem] flex-grow flex-col gap-1">
                            <span className="text-[11px] font-medium text-ink3">
                              Categories {t.catchAll ? "(everything else)" : "(comma separated)"}
                            </span>
                            <input
                              value={t.categories}
                              disabled={t.catchAll}
                              onChange={(e) => {
                                const tiers = [...d.tiers];
                                tiers[i] = { ...t, categories: e.target.value };
                                patch(a.account_id, { tiers });
                              }}
                              placeholder="DINING, GROCERIES"
                              className="h-9 rounded-control border border-line bg-surface px-2.5 text-sm disabled:bg-surface2 disabled:text-ink3"
                            />
                          </label>
                          <label className="flex flex-col gap-1">
                            <span className="text-[11px] font-medium text-ink3">
                              Cap / cycle
                            </span>
                            <input
                              inputMode="decimal"
                              value={t.cap}
                              onChange={(e) => {
                                const tiers = [...d.tiers];
                                tiers[i] = { ...t, cap: e.target.value };
                                patch(a.account_id, { tiers });
                              }}
                              placeholder="none"
                              className="tnum h-9 w-24 rounded-control border border-line bg-surface px-2.5 text-sm"
                            />
                          </label>
                          <label className="flex items-center gap-2 pb-2 text-[12.5px]">
                            <input
                              type="checkbox"
                              checked={t.catchAll}
                              onChange={(e) => {
                                const tiers = [...d.tiers];
                                tiers[i] = { ...t, catchAll: e.target.checked };
                                patch(a.account_id, { tiers });
                              }}
                            />
                            catch-all
                          </label>
                          <button
                            type="button"
                            onClick={() => {
                              const tiers = d.tiers.filter((x) => x.key !== t.key);
                              patch(a.account_id, { tiers });
                            }}
                            aria-label="Remove this tier"
                            className="pb-2 text-ink3 hover:text-bad"
                          >
                            <Cross size={15} />
                          </button>
                        </div>
                        {t.quote ? (
                          <p className="mono border-t border-hair pt-2.5 text-[11.5px] leading-relaxed text-ink2">
                            “{t.quote}”
                          </p>
                        ) : (
                          <p className="border-t border-hair pt-2.5 text-[11.5px] text-ink3">
                            Entered by hand — no quote backs this rate.
                          </p>
                        )}
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={() =>
                        patch(a.account_id, { tiers: [...d.tiers, blankTier(d.tiers.length)] })
                      }
                      className="inline-flex h-9 w-fit items-center gap-1.5 rounded-control border border-line bg-surface px-3.5 text-[13px] font-semibold"
                    >
                      <Plus size={14} />
                      Another tier
                    </button>
                  </div>
                )}
              </Card>
            );
          })}
        </div>

        {categories.length ? (
          <Aside summary="The category names the engine recognises">
            <div className="flex flex-wrap gap-1.5">
              {categories.map((c) => (
                <span
                  key={c}
                  className="mono rounded-chip border border-line bg-surface2 px-2 py-1 text-[11px]"
                >
                  {c}
                </span>
              ))}
            </div>
            <p>
              A tier can name several. Anything not named by any tier falls to the catch-all, and a
              card with no catch-all simply pays nothing on the rest.
            </p>
          </Aside>
        ) : null}

        <div className="sticky bottom-0 flex flex-wrap items-center gap-4 border-t border-line bg-bg/90 py-4 backdrop-blur">
          <div className="flex flex-col gap-0.5">
            <span className="text-[13px] font-semibold">
              {canSave
                ? `${complete.length} card${complete.length === 1 ? "" : "s"} ready`
                : chosen.length === 0
                  ? "Add at least one card"
                  : `${chosen.length - complete.length} card${chosen.length - complete.length === 1 ? "" : "s"} still need a category on every tier`}
            </span>
            {saveError ? (
              <span className="text-[12px] font-medium text-bad">{saveError}</span>
            ) : (
              <span className="text-[12px] text-ink3">
                Saved to <span className="mono">{wallet.path.replace(/^.*\/data\//, "data/")}</span>
              </span>
            )}
          </div>
          {onCancel ? (
            <button
              type="button"
              onClick={onCancel}
              className="ml-auto inline-flex h-10 items-center rounded-control px-4 text-[13px] font-semibold text-ink2"
            >
              Cancel
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void save()}
            disabled={!canSave || saving}
            className={`inline-flex h-10 items-center gap-2 rounded-control px-5 text-[13px] font-semibold text-white disabled:opacity-45 ${onCancel ? "" : "ml-auto"} bg-accent`}
          >
            {saving ? "Saving…" : "Confirm and build the plan"}
            <Check size={15} />
          </button>
        </div>
      </section>
    </>
  );
}
