"use client";

/**
 * A card, on top of wherever you were.
 *
 * Cards used to be a top-level tab, which gave a reference lookup the same
 * weight as the dashboard. What you actually want when you click a card is
 * "what has this card sent me and what was on each statement" — so statements
 * lead, and the whole thing is a drawer you dismiss.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type AccountDetail } from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import { bpsPct, cardName, daysUntil, dueLabel, dueTone, longDate, prettyCategory } from "@/lib/format";
import { Chip, Eyebrow, Meter } from "@/components/ui";
import { Alert, ArrowRight, Check, Clock } from "@/components/icons";
import { Drawer, DrawerSkeleton } from "@/components/drawer";
import { Traceable } from "@/components/evidence-drawer";

type Ctx = { open: (accountId: string) => void; close: () => void };
const CardCtx = createContext<Ctx>({ open: () => {}, close: () => {} });

export function useCardDrawer() {
  return useContext(CardCtx);
}

export function CardDrawerProvider({ children }: { children: React.ReactNode }) {
  const [id, setId] = useState<string | null>(null);
  const open = useCallback((a: string) => setId(a), []);
  const close = useCallback(() => setId(null), []);
  const value = useMemo(() => ({ open, close }), [open, close]);
  return (
    <CardCtx.Provider value={value}>
      {children}
      <CardDrawer accountId={id} onClose={close} />
    </CardCtx.Provider>
  );
}

/** Wraps a card's name so clicking it opens the card. */
export function CardLink({
  accountId, children, className = "",
}: { accountId: string; children: React.ReactNode; className?: string }) {
  const { open } = useCardDrawer();
  return (
    <button
      type="button"
      onClick={() => open(accountId)}
      className={`text-left transition-colors hover:text-accentInk ${className}`}
    >
      {children}
    </button>
  );
}

const STATUS: Record<string, "ok" | "bad" | "warn"> = {
  RECONCILED: "ok", REJECTED: "bad", PARSED: "warn",
};

function utilTone(bps: number | null): "ok" | "warn" | "bad" {
  if (bps == null) return "ok";
  const pct = bps / 100;
  if (pct >= 80) return "bad";
  if (pct >= 50) return "warn";
  return "ok";
}

function CardDrawer({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const [data, setData] = useState<AccountDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) { setData(null); setError(null); return; }
    let alive = true;
    api.account(accountId)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [accountId]);

  if (!accountId) return null;
  const a = data?.account;
  const p = data?.position;

  return (
    <Drawer open onClose={onClose} title={a ? cardName({ product_name: a.product_name, issuer: a.issuer }) : "Card"} width="40rem">
      {error ? (
        <div className="px-6 py-6">
          <Chip tone="bad" icon={<Alert size={12} />}>not found</Chip>
          <p className="mt-3 text-sm text-ink2">{error}</p>
        </div>
      ) : !data ? (
        <DrawerSkeleton />
      ) : (
        <div className="flex flex-col gap-7 px-6 py-6">
          {/* identity + what it owes */}
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex flex-col gap-1">
              <span className="serif text-[24px] leading-tight">
                {cardName({ product_name: a!.product_name, issuer: a!.issuer })}
              </span>
              <span className="mono text-[11.5px] text-ink3">
                {a!.issuer_name}
                {a!.masked_number ? ` · ${a!.masked_number}` : ""} · {a!.account_id}
              </span>
            </div>
            {p?.payment_due_date && p.total_payment_due?.minor ? (
              <Chip tone={dueTone(daysUntil(p.payment_due_date))} icon={<Clock size={12} />}>
                {dueLabel(daysUntil(p.payment_due_date))}
              </Chip>
            ) : (
              <Chip tone="ok" icon={<Check size={12} />}>settled</Chip>
            )}
          </div>

          {p ? (
            <div className="flex flex-col gap-4 rounded-card border border-line bg-surface2 p-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1">
                  <Eyebrow>Total payment due</Eyebrow>
                  <p className="tnum text-2xl font-semibold leading-none">
                    {formatAbs(p.total_payment_due)}
                  </p>
                  {p.payment_due_date ? (
                    <p className="text-[12.5px] text-ink2">by {longDate(p.payment_due_date)}</p>
                  ) : null}
                </div>
                <div className="flex flex-col gap-1">
                  <Eyebrow>Closing balance</Eyebrow>
                  <p className="tnum text-2xl font-semibold leading-none">
                    {formatAbs(p.closing_balance)}
                  </p>
                  {p.minimum_due ? (
                    <p className="tnum text-[12.5px] text-ink2">
                      minimum {formatAbs(p.minimum_due)}
                    </p>
                  ) : null}
                </div>
              </div>
              {p.utilisation_bps != null && p.credit_limit ? (
                <Meter
                  pct={p.utilisation_bps / 100}
                  tone={utilTone(p.utilisation_bps)}
                  label="Limit in use"
                  right={`${Math.round(p.utilisation_bps / 100)}% of ${formatAbs(p.credit_limit)}`}
                />
              ) : (
                <p className="text-xs text-ink3">No credit limit was printed on the latest statement.</p>
              )}
            </div>
          ) : null}

          <div className="grid grid-cols-3 gap-4 border-y border-hair py-4">
            <div className="flex flex-col gap-1">
              <Eyebrow>Spend on record</Eyebrow>
              <p className="tnum text-lg font-semibold">{formatAbs(data.totals.spend)}</p>
            </div>
            <div className="flex flex-col gap-1">
              <Eyebrow>Transactions</Eyebrow>
              <p className="tnum text-lg font-semibold">{data.totals.transactions}</p>
            </div>
            <div className="flex flex-col gap-1">
              <Eyebrow>Months</Eyebrow>
              <p className="tnum text-lg font-semibold">{data.totals.months}</p>
            </div>
          </div>

          {/* statements lead */}
          <div className="flex flex-col gap-3">
            <Eyebrow>Statements ({data.statements.length})</Eyebrow>
            {data.statements.length === 0 ? (
              <p className="text-sm text-ink3">No statement has been read for this card yet.</p>
            ) : (
              <div className="flex flex-col">
                {data.statements.slice(0, 14).map((s) => (
                  <div
                    key={s.document_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hair py-2.5 last:border-0"
                  >
                    <span className="tnum w-24 shrink-0 text-[13px] font-medium">
                      {s.statement_date ? longDate(s.statement_date) : "no date"}
                    </span>
                    <Chip tone={STATUS[s.status] ?? "neutral"}>
                      {s.status.toLowerCase()}
                    </Chip>
                    <span className="tnum text-[12.5px] text-ink2">
                      {s.txns} txns
                    </span>
                    {s.purchases_debits ? (
                      <span className="tnum ml-auto text-[13px] font-semibold">
                        {formatAbs(s.purchases_debits)}
                      </span>
                    ) : null}
                    {s.reject_reason ? (
                      <p className="w-full text-[11.5px] leading-relaxed text-bad">{s.reject_reason}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* what the bank itself reported */}
          {data.rewards.length ? (
            <div className="flex flex-col gap-3">
              <Eyebrow>Rewards the bank reported</Eyebrow>
              <div className="flex flex-col">
                {data.rewards.slice(0, 8).map((r, i) => (
                  <div
                    key={`${r.cycle_start}-${i}`}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-hair py-2 last:border-0"
                  >
                    <span className="text-[13px] font-medium">
                      {r.category_label ? prettyCategory(r.category_label) : (r.reward_program ?? "reward")}
                    </span>
                    {r.rate_bps != null ? (
                      <span className="tnum text-[12px] text-ink3">{bpsPct(r.rate_bps)}</span>
                    ) : null}
                    <span className="mono ml-auto text-[12.5px] font-semibold">
                      {r.earned ? formatMoney(r.earned) : "—"}
                    </span>
                    <span className="mono w-20 shrink-0 text-right text-[11.5px] text-ink3">
                      {r.reward_unit}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-xs leading-relaxed text-ink3">
                Reported by the issuer, separately from anything the plan computes, so the two can be
                compared rather than conflated. Units differ by card and are never added together.
              </p>
            </div>
          ) : null}

          {/* recent spending */}
          {data.transactions.length ? (
            <div className="flex flex-col gap-3">
              <Eyebrow>Recent spending</Eyebrow>
              <div className="flex flex-col">
                {data.transactions.slice(0, 12).map((t) => (
                  <div
                    key={t.txn_id}
                    className="flex items-center gap-3 border-b border-hair py-2 last:border-0"
                  >
                    <span className="tnum w-16 shrink-0 text-[12.5px] text-ink3">
                      {t.txn_date.slice(5)}
                    </span>
                    <span className="min-w-0 flex-grow truncate text-[13px]">
                      {t.merchant ?? <span className="text-ink3">not printed</span>}
                    </span>
                    <span className="shrink-0 text-[11.5px] text-ink3">
                      {t.category ? prettyCategory(t.category) : "—"}
                    </span>
                    <Traceable txnId={t.txn_id} className="tnum shrink-0 text-[13px] font-semibold">
                      {formatAbs(t.amount).replace(/^[A-Z]{3}\s/, "")}
                    </Traceable>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <Link
            href={`/cards/${encodeURIComponent(a!.account_id)}`}
            className="inline-flex h-9 w-fit items-center gap-1.5 rounded-control border border-line bg-surface px-4 text-[13px] font-semibold"
          >
            Open as a page
            <ArrowRight size={14} />
          </Link>
        </div>
      )}
    </Drawer>
  );
}
