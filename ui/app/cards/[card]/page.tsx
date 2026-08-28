/**
 * One card: what the bank sent for it, month by month.
 *
 * Selecting a card should answer "what do I have from this card and what was on
 * each statement" — so statements lead. Terms and rates live on /plan, where a
 * KFS is dropped; they are not what you want when inspecting an account.
 */
import Link from "next/link";
import { api, ApiDown, type AccountDetail, type AccountStatement } from "@/lib/api";
import { formatAbs, formatMoney } from "@/lib/money";
import { Card, CardTitle, Chip, PageTitle, State } from "@/components/ui";
import { CategoryTag } from "@/components/category-tag";

export const dynamic = "force-dynamic";

const STATUS: Record<string, "ok" | "bad" | "warn" | "neutral"> = {
  RECONCILED: "ok", REJECTED: "bad", PARSED: "warn",
};

function monthLabel(iso: string | null) {
  if (!iso) return "—";
  const [y, m] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString("en", {
    month: "long", year: "numeric", timeZone: "UTC",
  });
}

function daysUntil(iso: string | null) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const due = Date.UTC(y, m - 1, d);
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((due - today) / 86_400_000);
}

export default async function CardPage({ params }: { params: Promise<{ card: string }> }) {
  const { card } = await params;

  let data: AccountDetail;
  try {
    data = await api.account(decodeURIComponent(card));
  } catch (err) {
    if (err instanceof ApiDown) {
      return (
        <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-6 px-6 pb-16 pt-8">
        <State title="The analyser isn’t running">
          Start it with <code className="mono">.venv/bin/python -m analyser.api</code>
        </State>
        </main>
      );
    }
    return (
      <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-6 px-6 pb-16 pt-8">
        <PageTitle>Card not found</PageTitle>
        <State title={`Nothing here for “${decodeURIComponent(card)}”`}>
          <Link href="/" className="text-accent underline underline-offset-2">
            Back to Money
          </Link>
        </State>
      </main>
    );
  }

  const { account: a, position: p, statements, totals, rewards } = data;
  const due = p?.total_payment_due?.minor ? p.total_payment_due : null;
  const days = daysUntil(p?.payment_due_date ?? null);

  return (
    <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-6 px-6 pb-16 pt-8">
      <div className="mb-2">
        <Link href="/" className="text-xs text-ink3 hover:text-ink">← Money</Link>
      </div>

      <PageTitle sub={`${a.issuer_name}${a.masked_number ? ` · ${a.masked_number}` : ""}`}>
        {a.product_name ?? a.account_id}
      </PageTitle>

      {/* Position ─────────────────────────────────────────── */}
      <section className="rise mb-8 grid gap-3 sm:grid-cols-4">
        <Metric label="Spent" value={formatAbs(totals.spend)}
                hint={`${totals.transactions} purchases · ${totals.months} months`} />
        <Metric label="Owed now" value={due ? formatAbs(due) : "Nothing"}
                tone={due ? "warn" : "ok"}
                hint={p?.payment_due_date
                  ? `due ${p.payment_due_date}${days !== null ? ` · ${days} days` : ""}`
                  : undefined} />
        <Metric label="Credit limit"
                value={p?.credit_limit ? formatAbs(p.credit_limit) : "not printed"}
                hint={p?.utilisation_bps != null
                  ? `${(p.utilisation_bps / 100).toFixed(1)}% used` : undefined} />
        <Metric label="Statements" value={String(statements.length)}
                hint={`${statements.filter((s) => s.status === "RECONCILED").length} read`} />
      </section>

      {/* Statements — the point of this page ───────────────── */}
      <section className="rise mb-8" style={{ animationDelay: "60ms" }}>
        <CardTitle>Statements</CardTitle>
        {statements.length === 0 ? (
          <State title="No statements yet for this card">
            Add them on the{" "}
            <Link href="/statements" className="text-accent underline underline-offset-2">
              Statements
            </Link>{" "}
            page.
          </State>
        ) : (
          <ul className="flex flex-col gap-2">
            {statements.map((s) => <StatementRow key={s.document_id} s={s} />)}
          </ul>
        )}
      </section>

      {/* Rewards the issuer printed ────────────────────────── */}
      {rewards.length > 0 && (
        <section className="rise mb-8" style={{ animationDelay: "120ms" }}>
          <CardTitle>Rewards the bank reported</CardTitle>
          <p className="mb-3 max-w-[70ch] text-sm text-ink2">
            Figures printed on the statements themselves — used to check the engine’s
            own reward maths against what the bank actually paid.
          </p>
          <ul className="flex flex-col gap-1.5">
            {rewards.map((r, i) => (
              <li key={i}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card border border-line bg-surface px-4 py-2.5 text-sm">
                <span className="tnum text-xs text-ink3">
                  {r.cycle_start ?? "—"} → {r.cycle_end ?? "—"}
                </span>
                <span className="min-w-0 flex-1">{r.category_label ?? r.reward_program ?? "Balance"}</span>
                {r.rate_bps != null && (
                  <span className="tnum text-xs text-ink3">{(r.rate_bps / 100).toFixed(2)}%</span>
                )}
                {r.earned && <span className="tnum font-medium">{formatAbs(r.earned)} earned</span>}
                {r.closing_balance && (
                  <span className="tnum text-xs text-ink3">
                    balance {formatAbs(r.closing_balance)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Recent spending ───────────────────────────────────── */}
      {data.transactions.length > 0 && (
        <section className="rise" style={{ animationDelay: "180ms" }}>
          <CardTitle>Recent spending on this card</CardTitle>
          <ul className="flex flex-col gap-1">
            {data.transactions.slice(0, 25).map((t) => (
              <li key={t.txn_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-sm hover:bg-surface2">
                <span className="tnum w-24 shrink-0 text-xs text-ink3">{t.txn_date}</span>
                <span className="min-w-0 flex-1 truncate">{t.merchant ?? "—"}</span>
                <CategoryTag txnId={t.txn_id} category={t.category} merchant={t.merchant} />
                <span className="tnum font-medium">{formatAbs(t.amount)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

function Metric({ label, value, hint, tone }: {
  label: string; value: string; hint?: string; tone?: "ok" | "warn";
}) {
  const colour = tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--ink)";
  return (
    <div className="rounded-card border border-line bg-surface px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">{label}</p>
      <p className="tnum display mt-1 text-xl font-semibold" style={{ color: colour }}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink3">{hint}</p>}
    </div>
  );
}

function StatementRow({ s }: { s: AccountStatement }) {
  return (
    <li className="rounded-card border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Chip tone={STATUS[s.status] ?? "neutral"}>
          {s.status === "RECONCILED" ? "read" : s.status.toLowerCase()}
        </Chip>
        <span className="min-w-0 flex-1 font-medium">{monthLabel(s.statement_date)}</span>
        <span className="tnum text-sm text-ink2">{s.txns} transactions</span>
        {s.purchases_debits && (
          <span className="tnum text-sm">
            <span className="text-ink3">spent </span>
            {formatAbs(s.purchases_debits)}
          </span>
        )}
        {s.payments_credits && s.payments_credits.minor !== 0 && (
          <span className="tnum text-sm">
            <span className="text-ink3">paid </span>
            {formatAbs(s.payments_credits)}
          </span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink3">
        {s.period_start && s.period_end && <span className="tnum">{s.period_start} → {s.period_end}</span>}
        {s.payment_due_date && <span className="tnum">due {s.payment_due_date}</span>}
        {s.total_payment_due && <span className="tnum">balance {formatMoney(s.total_payment_due)}</span>}
        <span className="mono truncate">{s.file_name}</span>
        {s.email_url && (
          <a
            href={s.email_url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 text-accent underline underline-offset-2"
            title={s.subject ?? "Open the original email"}
          >
            open email ↗
          </a>
        )}
      </div>
      {s.reject_reason && (
        <p className="mt-1.5 text-xs" style={{ color: "var(--bad)" }}>{s.reject_reason}</p>
      )}
    </li>
  );
}
