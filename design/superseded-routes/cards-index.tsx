import Link from "next/link";
import { redirect } from "next/navigation";
import { api, ApiDown, type Position, type RewardRow } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { Meter } from "@/components/charts";
import { Card, Chip, Empty, H1, H2 } from "@/components/ui";

export const dynamic = "force-dynamic";

/* ── dates ────────────────────────────────────────────────────────────────
   Day counting is calendar arithmetic, not money arithmetic. Every figure on
   this page arrives already computed by the engine (D-029) and is rendered
   only through formatMoney.                                                */

function startOfDayUTC(d: Date) {
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return null;
  const due = Date.UTC(y, m - 1, d);
  return Math.round((due - startOfDayUTC(new Date())) / 86_400_000);
}

function prettyDate(iso: string | null): string {
  if (!iso) return "not printed";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function duePhrase(days: number | null): string {
  if (days === null) return "no due date printed";
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days > 0) return `in ${days} days`;
  return days === -1 ? "1 day overdue" : `${Math.abs(days)} days overdue`;
}

function dueTone(days: number | null): "ok" | "warn" | "bad" | "neutral" {
  if (days === null) return "neutral";
  if (days < 0) return "bad";
  if (days <= 3) return "warn";
  return "ok";
}

/** FAB and CBD are acronyms; MASHREQ is a word. Short tokens keep their caps. */
function issuerLabel(issuer: string) {
  return issuer
    .split("_")
    .map((w) => (w.length <= 3 ? w : w.charAt(0) + w.slice(1).toLowerCase()))
    .join(" ");
}

/** Two colour stops per issuer so each card face is recognisable at a glance. */
function faceGradient(i: number) {
  const stops = [
    ["var(--s1)", "var(--accent)"],
    ["var(--s2)", "var(--s3)"],
    ["var(--s4)", "var(--s5)"],
    ["var(--accent-2)", "var(--s6)"],
    ["var(--s3)", "var(--s1)"],
  ][i % 5];
  return `linear-gradient(135deg, ${stops[0]}, ${stops[1]})`;
}

/** The reward line the statements themselves printed — balance if there is one,
    otherwise the cycle rate the issuer stated. Never inferred. */
function rewardNote(rows: RewardRow[]): string | null {
  if (!rows.length) return null;
  const withBalance = rows.filter((r) => r.closing_balance);
  if (withBalance.length) {
    const r = withBalance[withBalance.length - 1];
    const unit = r.reward_unit === r.closing_balance?.currency ? "" : `${r.reward_unit} `;
    return `${formatMoney(r.closing_balance)} of ${unit}rewards on file`;
  }
  const rated = rows.filter((r) => r.rate_bps != null);
  if (rated.length) {
    const r = rated[rated.length - 1];
    const pct = new Intl.NumberFormat("en-AE", { maximumFractionDigits: 2 }).format(
      (r.rate_bps as number) / 100
    );
    return `earning ${pct}% on ${r.category_label ?? "stated spend"} this cycle`;
  }
  return null;
}

/** Names printed verbatim in the ingested terms documents — good starting points. */
const KNOWN_TERMS = ["noon", "Cashback", "Platinum", "Elite", "Solitaire", "World", "Signature", "Titanium"];

async function lookup(formData: FormData) {
  "use server";
  const raw = String(formData.get("card") ?? "").trim();
  if (!raw) redirect("/cards");
  redirect(`/cards/${encodeURIComponent(raw)}`);
}

export default async function WalletPage() {
  let positions: Position[];
  let rewards: RewardRow[] = [];
  try {
    positions = await api.positions();
    rewards = await api.rewards();
  } catch (err) {
    if (err instanceof ApiDown) return <ApiDownCard />;
    return <FailureCard message={err instanceof Error ? err.message : String(err)} />;
  }

  const rewardsFor = (id: string) => rewards.filter((r) => r.account_id === id);

  const spending = positions.filter((p) => p.include_in_spending !== 0);
  const settlement = positions.filter((p) => p.include_in_spending === 0);

  // The one thing you actually need to know: what lands next.
  const upcoming = spending
    .filter((p) => p.payment_due_date && (daysUntil(p.payment_due_date) ?? -1) >= 0)
    .sort((a, b) => (a.payment_due_date! < b.payment_due_date! ? -1 : 1));
  const next = upcoming[0] ?? null;
  const nextDays = next ? daysUntil(next.payment_due_date) : null;

  if (positions.length === 0) {
    return (
      <div className="space-y-8">
        <H1 sub="Your cards, what they owe and when it lands.">Wallet</H1>
        <Empty title="No accounts yet.">
          Ingest a statement and the card shows up here with its balance and due date.
        </Empty>
      </div>
    );
  }

  return (
    <div className="space-y-10">
      <H1 sub="What each card owes, when it is due, and how much of its limit is in use. Tap a card for the reward rates behind it.">
        Wallet
      </H1>

      {/* ── hero: the next payment ──────────────────────────────────── */}
      <section
        className="rise rounded-card border border-line bg-card p-6 shadow-card sm:p-8"
        style={{ animationDelay: "0ms" }}
      >
        {next ? (
          <div className="flex flex-wrap items-end justify-between gap-6">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink3">
                Next payment
              </p>
              <p className="hero-figure mt-2 text-[clamp(2.4rem,7vw,3.8rem)]">
                {next.total_payment_due ? formatMoney(next.total_payment_due) : "not printed"}
              </p>
              <p className="mt-3 text-sm text-ink2">
                <span className="font-medium text-ink">
                  {next.product_name ?? issuerLabel(next.issuer)}
                </span>{" "}
                · {prettyDate(next.payment_due_date)}
              </p>
            </div>
            <div className="flex flex-col items-start gap-3">
              <Chip tone={dueTone(nextDays)}>{duePhrase(nextDays)}</Chip>
              <Link
                href={`/cards/${encodeURIComponent(next.account_id)}`}
                className="text-sm font-medium text-accent transition-opacity hover:opacity-80"
              >
                See this card&rsquo;s rules →
              </Link>
            </div>
          </div>
        ) : (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink3">
              Next payment
            </p>
            <p className="display mt-2 text-2xl">Nothing is due right now.</p>
            <p className="mt-2 max-w-[60ch] text-sm text-ink2">
              No ingested statement carries a future payment due date. That means none was printed —
              not that nothing is owed.
            </p>
          </div>
        )}
      </section>

      {/* ── the wallet ──────────────────────────────────────────────── */}
      <section>
        <H2>Your cards</H2>
        <div className="grid gap-4 md:grid-cols-2">
          {spending.map((p, i) => (
            <CardTile key={p.account_id} p={p} index={i} rewards={rewardsFor(p.account_id)} />
          ))}
        </div>
      </section>

      {settlement.length > 0 ? (
        <section>
          <H2>Settlement accounts</H2>
          <div className="grid gap-4 md:grid-cols-2">
            {settlement.map((p, i) => (
              <CardTile
                key={p.account_id}
                p={p}
                index={spending.length + i}
                rewards={rewardsFor(p.account_id)}
              />
            ))}
          </div>
        </section>
      ) : null}

      {/* ── lookup ──────────────────────────────────────────────────── */}
      <section>
        <H2>Look up a card by name</H2>
        <Card className="rounded-card shadow-card">
          <form action={lookup} className="flex flex-wrap items-center gap-2">
            <label htmlFor="card" className="sr-only">
              Card name as printed in the terms document
            </label>
            <input
              id="card"
              name="card"
              type="text"
              placeholder="noon, Cashback, Platinum…"
              autoComplete="off"
              className="min-w-[15rem] flex-1 rounded-lg border border-line bg-bg px-3.5 py-2.5 text-sm text-ink placeholder:text-ink3 focus:border-accent focus:outline-none"
            />
            <button
              type="submit"
              className="rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90"
            >
              Show rules
            </button>
          </form>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-ink3">Found in your terms documents:</span>
            {KNOWN_TERMS.map((t) => (
              <Link
                key={t}
                href={`/cards/${encodeURIComponent(t)}`}
                className="rounded-full border border-line bg-bg2 px-2.5 py-1 text-xs text-ink2 transition-colors hover:border-accent hover:text-accent"
              >
                {t}
              </Link>
            ))}
          </div>
          <p className="mt-3 max-w-[72ch] text-xs text-ink3">
            The match is on the card name as printed in the terms document, which is often not the
            product name on your statement. If nothing names the card, the lookup says so rather than
            borrowing a similar product&rsquo;s rules.
          </p>
        </Card>
      </section>
    </div>
  );
}

/* ── one card ─────────────────────────────────────────────────────────── */

function CardTile({ p, index, rewards }: { p: Position; index: number; rewards: RewardRow[] }) {
  const days = daysUntil(p.payment_due_date);
  const isSettlement = p.include_in_spending === 0;
  const note = rewardNote(rewards);

  return (
    <Link
      href={`/cards/${encodeURIComponent(p.account_id)}`}
      className="rise group block rounded-card border border-line bg-card p-5 shadow-card transition-shadow hover:shadow-lift"
      style={{ animationDelay: `${60 + index * 60}ms` }}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5 h-9 w-12 shrink-0 rounded-md"
          style={{ background: faceGradient(index) }}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{p.product_name ?? issuerLabel(p.issuer)}</p>
          <p className="mt-0.5 text-xs text-ink3">
            {issuerLabel(p.issuer)} · <span className="mono">{p.account_id}</span>
          </p>
        </div>
        {isSettlement ? <Chip tone="neutral">settlement</Chip> : null}
      </div>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.07em] text-ink3">
            {isSettlement ? "Balance" : "Owed"}
          </p>
          <p className="display tnum mt-1 text-[1.75rem] font-semibold leading-none">
            {p.total_payment_due ? (
              formatMoney(p.total_payment_due)
            ) : (
              <span className="text-lg text-ink3">not printed</span>
            )}
          </p>
        </div>
        {isSettlement ? (
          <div className="max-w-[22ch] text-right text-xs text-ink3">
            No payment falls due on a settlement account.
          </div>
        ) : (
          <div className="text-right">
            <p className="text-[11px] font-medium uppercase tracking-[0.07em] text-ink3">Due</p>
            <p className="tnum mt-1 text-sm font-medium">{prettyDate(p.payment_due_date)}</p>
            <div className="mt-1.5 flex justify-end">
              <Chip tone={dueTone(days)}>{duePhrase(days)}</Chip>
            </div>
          </div>
        )}
      </div>

      <div className="mt-5 border-t border-line pt-4">
        {isSettlement ? null : p.utilisation_bps !== null ? (
          <Meter bps={p.utilisation_bps} label="limit used" />
        ) : p.credit_limit ? (
          <p className="tnum text-xs text-ink3">
            Limit {formatMoney(p.credit_limit)}
            {p.available_limit ? <> · {formatMoney(p.available_limit)} available</> : null} ·
            utilisation not computed
          </p>
        ) : (
          <Meter bps={null} />
        )}

        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-ink3">
          <div className="flex gap-1.5">
            <dt>Statement</dt>
            <dd className="tnum text-ink2">{prettyDate(p.statement_date)}</dd>
          </div>
          {p.minimum_due ? (
            <div className="flex gap-1.5">
              <dt>Minimum</dt>
              <dd className="tnum text-ink2">{formatMoney(p.minimum_due)}</dd>
            </div>
          ) : null}
          {p.closing_balance ? (
            <div className="flex gap-1.5">
              <dt>Closing</dt>
              <dd className="tnum text-ink2">{formatMoney(p.closing_balance)}</dd>
            </div>
          ) : null}
        </dl>

        {note ? <p className="mt-2 text-xs text-accentInk">{note}</p> : null}

        {isSettlement ? (
          <p className="mt-3 max-w-[52ch] text-xs text-ink3">
            Money leaving this account is payment to your other cards, not spending — so it is kept
            out of every spending total.
          </p>
        ) : null}
      </div>
    </Link>
  );
}

/* ── failure states ───────────────────────────────────────────────────── */

function ApiDownCard() {
  return (
    <div className="space-y-8">
      <H1 sub="Your cards, what they owe and when it lands.">Wallet</H1>
      <Empty title="The analyser is not running.">
        <p>Start it, then reload this page:</p>
        <p className="mono mt-2 rounded-lg border border-line bg-bg2 px-3 py-2 text-xs">
          .venv/bin/python -m analyser.api
        </p>
      </Empty>
    </div>
  );
}

function FailureCard({ message }: { message: string }) {
  return (
    <div className="space-y-8">
      <H1 sub="Your cards, what they owe and when it lands.">Wallet</H1>
      <Empty title="Your positions could not be loaded.">
        <p>{message}</p>
      </Empty>
    </div>
  );
}
