"use client";

/**
 * The Evidence drawer — click a figure, see where it came from.
 *
 * "Full traceability" (spec P5) used to be a sentence in the page footer. The
 * data was always there: the raw row keeps the statement line verbatim with its
 * page, the document keeps the parser that read it and whether it reconciled
 * against the issuer's own printed totals. This makes that a behaviour.
 *
 * Mounted once by the root layout, so any figure anywhere can open it and there
 * is only ever one drawer on screen.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import { api, type Evidence } from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import { longDate, prettyCategory } from "@/lib/format";
import { Chip, Label } from "@/components/ui";
import { Check, Alert, Doc } from "@/components/icons";
import { Drawer, DrawerSkeleton } from "@/components/drawer";

type Ctx = { open: (txnId: string) => void; close: () => void };
const EvidenceContext = createContext<Ctx>({ open: () => {}, close: () => {} });

export function useEvidence() {
  return useContext(EvidenceContext);
}

export function EvidenceProvider({ children }: { children: React.ReactNode }) {
  const [txnId, setTxnId] = useState<string | null>(null);
  const open = useCallback((id: string) => setTxnId(id), []);
  const close = useCallback(() => setTxnId(null), []);
  const value = useMemo(() => ({ open, close }), [open, close]);
  return (
    <EvidenceContext.Provider value={value}>
      {children}
      <EvidenceDrawer txnId={txnId} onClose={close} />
    </EvidenceContext.Provider>
  );
}

/** The affordance. Wraps a figure so clicking it reveals its source. */
export function Traceable({
  txnId, children, className = "",
}: { txnId: string; children: React.ReactNode; className?: string }) {
  const { open } = useEvidence();
  return (
    <button
      type="button"
      onClick={() => open(txnId)}
      title="Where did this figure come from?"
      className={`rounded-control underline decoration-dotted decoration-mute underline-offset-[3px] transition-colors hover:decoration-accent ${className}`}
    >
      {children}
    </button>
  );
}

const STATUS_TONE: Record<string, "ok" | "warn" | "bad"> = {
  RECONCILED: "ok", PARSED: "warn", REJECTED: "bad",
};

function DispositionLine({ line }: { line: Evidence["source"]["context"][number] }) {
  const here = line.is_this_charge;
  return (
    <div
      className={`flex gap-3 px-3 py-1.5 ${here ? "bg-accentSoft" : ""}`}
      dir="auto"
    >
      <span className="mono w-7 shrink-0 text-right text-[10.5px] text-ink3">{line.line_index}</span>
      <span className={`mono grow text-[11.5px] leading-relaxed ${here ? "font-medium text-ink" : "text-ink2"}`}>
        {line.raw_text}
      </span>
      <span className="mono w-[5.5rem] shrink-0 text-[10px] uppercase text-ink3">
        {line.disposition.toLowerCase()}
      </span>
    </div>
  );
}

function EvidenceDrawer({ txnId, onClose }: { txnId: string | null; onClose: () => void }) {
  const [data, setData] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!txnId) { setData(null); setError(null); return; }
    let alive = true;
    api.evidence(txnId)
      .then((d) => { if (alive) setData(d); })
      .catch((e) => { if (alive) setError(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [txnId]);

  if (!txnId) return null;
  const doc = data?.document;

  return (
    <Drawer
      open
      onClose={onClose}
      title="Where this figure comes from"
      icon={<Doc size={16} className="text-ink2" />}
    >
      {error ? (
          <div className="px-6 py-6">
            <Chip tone="bad" icon={<Alert size={12} />}>no stored line</Chip>
            <p className="mt-3 text-sm text-ink2">{error}</p>
          </div>
      ) : !data ? (
        <DrawerSkeleton />
      ) : (
          <div className="flex flex-col gap-7 px-6 py-6">
            {/* the figure under inspection */}
            <div className="flex flex-col gap-1.5">
              <Label>The figure</Label>
              <p className="tnum text-3xl font-semibold leading-none tracking-[-.02em]">
                {formatAbs(data.amount)}
              </p>
              <p className="text-[13px] text-ink2">
                {data.merchant ?? "merchant not printed"}
                {data.txn_date ? ` · ${longDate(data.txn_date)}` : ""}
              </p>
              {data.fx ? (
                <p className="text-xs text-ink3">
                  Charged abroad as <span className="tnum">{formatMoney(data.fx)}</span>.
                </p>
              ) : null}
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {data.category ? (
                  <Chip tone={data.corrected ? "ok" : "neutral"}>
                    {prettyCategory(data.category)}
                    {data.corrected ? " · you set this" : ""}
                  </Chip>
                ) : (
                  <Chip tone="warn" icon={<Alert size={12} />}>uncategorised</Chip>
                )}
                {data.is_transfer ? <Chip tone="neutral">matched as a transfer</Chip> : null}
                {data.excluded ? (
                  <Chip tone="neutral">excluded{data.exclude_reason ? ` · ${data.exclude_reason}` : ""}</Chip>
                ) : null}
              </div>
            </div>

            {/* the statement line, verbatim */}
            <div className="flex flex-col gap-2.5">
              <Label>What the statement actually printed</Label>
              <div className="overflow-hidden rounded-card border border-line bg-surface2">
                <div className="flex items-center gap-2 border-b border-line px-3 py-2">
                  <span className="mono text-[11px] text-ink3">
                    page {data.source.page_number}
                    {data.source.printed_at_line != null ? ` · line ${data.source.printed_at_line}` : ""}
                  </span>
                  <span className="mono ml-auto text-[11px] text-ink3">
                    charge {data.source.line_index + 1} on this page
                  </span>
                </div>
                {data.source.context.length ? (
                  <div className="divide-y divide-hair">
                    {data.source.context.map((l) => (
                      <DispositionLine key={`${l.page_number}-${l.line_index}`} line={l} />
                    ))}
                  </div>
                ) : (
                  <p className="mono px-3 py-2.5 text-[11.5px] text-ink" dir="auto">
                    {data.source.raw_text}
                  </p>
                )}
              </div>
              <p className="text-xs leading-relaxed text-ink3">
                The highlighted line is this charge; the lines around it are what the issuer printed
                beside it. A <span className="mono">continuation</span> row belongs to the same
                charge — it is usually where the reference number and the real merchant name sit.
              </p>
            </div>

            {/* the description the categoriser saw */}
            {data.source.raw_description !== data.source.raw_text ? (
              <div className="flex flex-col gap-2">
                <Label>The description the categoriser read</Label>
                <p className="mono break-words rounded-card border border-line bg-surface2 px-3 py-2.5 text-[11.5px] leading-relaxed text-ink2" dir="auto">
                  {data.source.raw_description}
                </p>
              </div>
            ) : null}

            {/* provenance */}
            <div className="grid grid-cols-2 gap-x-5 gap-y-4 border-t border-line pt-5">
              <div className="col-span-2 flex flex-col gap-1">
                <Label>Statement</Label>
                <p className="mono break-all text-[12px]">{doc!.file_name}</p>
              </div>
              <div className="flex flex-col gap-1">
                <Label>Parser</Label>
                <p className="mono text-[12px]">
                  {doc!.parser_name} v{doc!.parser_version}
                </p>
              </div>
              <div className="flex flex-col gap-1">
                <Label>Reconciled</Label>
                <span>
                  <Chip
                    tone={STATUS_TONE[doc!.status] ?? "neutral"}
                    icon={doc!.status === "RECONCILED" ? <Check size={12} /> : <Alert size={12} />}
                  >
                    {doc!.status.toLowerCase()}
                  </Chip>
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <Label>Card</Label>
                <p className="text-[12.5px]">
                  {data.account.product_name ?? data.account.issuer.replace(/_/g, " ")}
                </p>
                <p className="mono text-[11px] text-ink3">{data.account.account_id}</p>
              </div>
              <div className="flex flex-col gap-1">
                <Label>Statement date</Label>
                <p className="tnum text-[12.5px]">
                  {doc!.statement_date ? longDate(doc!.statement_date) : "not printed"}
                </p>
                {doc!.page_count ? (
                  <p className="mono text-[11px] text-ink3">{doc!.page_count} pages</p>
                ) : null}
              </div>
              {doc!.reject_reason ? (
                <p className="col-span-2 text-xs leading-relaxed text-bad">{doc!.reject_reason}</p>
              ) : null}
              <p className="col-span-2 border-t border-hair pt-4 text-xs leading-relaxed text-ink3">
                {doc!.status === "RECONCILED"
                  ? "This statement's transactions add up to the totals the issuer printed on it. Nothing here was inferred, and nothing left this machine."
                  : "This statement did not reconcile against its own printed totals, so it is held aside rather than folded quietly into your figures."}
              </p>
            </div>
          </div>
      )}
    </Drawer>
  );
}
