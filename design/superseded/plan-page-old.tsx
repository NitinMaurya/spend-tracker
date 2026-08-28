import { Suspense } from "react";
import { api, ApiDown, type Account, type Overview } from "@/lib/api";
import { formatAbs } from "@/lib/money";
import { Aside, Card, Chip, PageTitle, SectionTitle, Stat, State, Table } from "@/components/ui";
import { EvaluatePanel } from "@/components/evaluate-panel";

export const dynamic = "force-dynamic";

/* --------------------------------------------------------------------------
   The routing plan is the product's primary output, and it cannot be produced
   from extracted rules alone: an extracted rule must be confirmed by a human
   before it is allowed to move money (D-022, D-027). So this screen states what
   the plan is, what two numbers it always reports, and exactly what is still
   missing — driven by live data wherever the API can answer, and named honestly
   where it cannot.

   No figure here is computed in TypeScript. The illustrative figures in the
   example block are literal text, fenced inside a dashed, chipped panel so they
   can never be read as the user's own money.
-------------------------------------------------------------------------- */

type Level = "product" | "issuer" | "none";

type TermsProbe = {
  account: Account;
  level: Level;
  matched: string | null;
  sources: { source: string; file: string }[];
  unreadable: number;
  conflicts: number;
};

type ProbeResult = { ok: true; probes: TermsProbe[] } | { ok: false };

async function lookup(name: string) {
  try {
    return await api.rules(name);
  } catch {
    // 404 — no terms document names this card. Rules are never inferred from a
    // neighbouring product (D-022), so a miss stays a miss.
    return null;
  }
}

/** Two lookups at most per card: the product first, the issuer only as a fallback
 *  — and an issuer-level hit is reported as weaker evidence, because a document
 *  that names the bank may describe a different product from the same bank. */
async function probeTerms(account: Account): Promise<TermsProbe> {
  const attempts: { level: Level; name: string }[] = [];
  if (account.product_name) attempts.push({ level: "product", name: account.product_name });
  if (account.issuer && account.issuer !== account.product_name)
    attempts.push({ level: "issuer", name: account.issuer });

  for (const attempt of attempts) {
    const rules = await lookup(attempt.name);
    if (rules) {
      return {
        account,
        level: attempt.level,
        matched: attempt.name,
        sources: rules.sources ?? [],
        unreadable: rules.unreadable?.length ?? 0,
        conflicts: rules.conflicts?.length ?? 0,
      };
    }
  }
  return { account, level: "none", matched: null, sources: [], unreadable: 0, conflicts: 0 };
}

async function probeAll(wallet: Account[]): Promise<ProbeResult> {
  try {
    return { ok: true, probes: await Promise.all(wallet.map(probeTerms)) };
  } catch {
    return { ok: false };
  }
}

export default async function PlanPage() {
  let overview: Overview;
  try {
    overview = await api.overview();
  } catch (err) {
    if (err instanceof ApiDown) return <ApiDownNotice />;
    throw err;
  }

  const wallet = overview.accounts.filter(
    (a) => a.account_type === "CREDIT_CARD" && a.include_in_spending === 1
  );
  const excluded = overview.accounts.filter((a) => a.include_in_spending !== 1);

  // Started once, awaited by both streamed sections. Terms extraction reads the
  // source PDFs, so it is slow — the rest of the page must not wait on it.
  const probes = probeAll(wallet);

  return (
    <main id="main" className="mx-auto flex max-w-[70rem] flex-col gap-9 px-6 pb-16 pt-8">
      <PageTitle sub="Priced against your own statements, using only rates quoted verbatim from a Key Facts Statement. Everything still blocking a full wallet-wide plan is listed first, with the action that clears it.">
        What to put on which card
      </PageTitle>

      <Suspense fallback={<SummarySkeleton overview={overview} wallet={wallet} />}>
        <Summary overview={overview} wallet={wallet} probes={probes} />
      </Suspense>

      {/* ---- 3. readiness --------------------------------------------------- */}
      <section>
        <SectionTitle>Readiness — what is blocking a real plan</SectionTitle>
        <Suspense fallback={<ReadinessSkeleton />}>
          <Readiness overview={overview} wallet={wallet} excluded={excluded} probes={probes} />
        </Suspense>
      </section>

      {/* ---- price a card against your own spending ------------------------ */}
      <section className="flex flex-col gap-4">
        <SectionTitle aside="the one comparison the engine can serve over HTTP today">
          Is a card worth it?
        </SectionTitle>
        <EvaluatePanel />
      </section>

      {/* ---- 4. the commands ------------------------------------------------ */}
      <section>
        <SectionTitle>Once every condition is met</SectionTitle>
        <Card>
          <p className="text-sm text-ink2">
            The plan is produced on the command line, from the confirmed wallet — not from this
            interface, which never computes a figure of its own.
          </p>
          <div className="mt-4 space-y-4">
            <div>
              <Cmd>python -m analyser plan</Cmd>
              <p className="mt-1 text-xs text-ink3">
                The routing plan across the whole wallet: per category, the destination card, how much
                is worth routing there, the cap that binds it, and every category it recommends leaving
                where it is.
              </p>
            </div>
            <div>
              <Cmd>python -m analyser value &lt;card&gt;</Cmd>
              <p className="mt-1 text-xs text-ink3">
                One card, both numbers: value if you change nothing, and value if you route as planned —
                each with its confidence, its binding cap, and the exclusions it could not evaluate.
              </p>
            </div>
            {wallet.length > 0 ? (
              <div className="rounded-lg border border-line bg-line2/40 p-3">
                <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                  For the cards currently in this wallet
                </p>
                <ul className="mono mt-2 space-y-1 overflow-x-auto text-xs text-ink2">
                  {wallet.map((a) => (
                    <li key={a.account_id} className="whitespace-pre">
                      python -m analyser value {a.account_id}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
          <p className="mt-5 border-t border-line pt-4 text-xs text-ink3">
            Where a rule cannot be evaluated — an exclusion that is undetectable from statement text, a
            conflict between two sources — the plan reports it as UNKNOWABLE and holds that spend out of
            both numbers rather than assuming in the card&rsquo;s favour (spec §G5, §P1).
          </p>
        </Card>
      </section>
      {/* ---- background, folded away ---------------------------------------- */}
      <section className="flex flex-col gap-3">
        <Aside summary="What a routing plan actually is, and why two numbers are always reported">
          <p>
            The detail below explains the shape of the output and why a single headline figure would
            overstate every card. It is reference material, not something to read before acting.
          </p>
        </Aside>
      </section>

      {/* ---- 1. what a routing plan is ------------------------------------- */}
      <section>
        <SectionTitle>What a routing plan is</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <p className="text-sm leading-relaxed text-ink2">
              A routing plan is a set of{" "}
              <span className="font-medium text-ink">instructions about your own spending</span>: for
              each category you actually spend in, which card it should go on, how much of it, and
              whether it is worth moving at all. Most categories should not move.
            </p>
            <dl className="mt-4 space-y-3 text-sm">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                  The question it answers
                </dt>
                <dd className="mt-0.5 text-ink">
                  &ldquo;Where do I put groceries next month, and how much of them?&rdquo;
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                  The question it does not answer
                </dt>
                <dd className="mt-0.5 text-ink2">
                  &ldquo;Is this card any good?&rdquo; A card is only good or bad relative to the spend
                  you actually have and the card the spend would leave (D-027).
                </dd>
              </div>
            </dl>
            <p className="mt-4 text-xs text-ink3">
              A plan line is only worth stating when it names a category, a destination, a limit, and
              the card the spend leaves. Anything less is a product advertisement.
            </p>
          </Card>

          {/* Illustration — dashed and chipped so it cannot be mistaken for real data. */}
          <div className="rounded-xl border border-dashed border-ink3/60 bg-line2/30 p-5">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Chip tone="accent">example</Chip>
              <span className="text-xs text-ink3">
                Illustration only — invented cards and figures, not your data
              </span>
            </div>
            <ul className="space-y-3 text-sm">
              <li className="border-l-2 border-ok pl-3">
                <p className="font-medium text-ink">Move groceries to Card B</p>
                <p className="mt-0.5 text-ink2">
                  5% there against 1% on Card A — but capped at AED 100 per cycle, so route only the
                  first <span className="tnum">AED 2,000</span> of groceries each month and leave the
                  rest on Card A.
                </p>
              </li>
              <li className="border-l-2 border-warn pl-3">
                <p className="font-medium text-ink">Keep utilities on Card A</p>
                <p className="mt-0.5 text-ink2">
                  Card B pays 0.33% on utilities against 1% here. Moving this category loses money.
                </p>
              </li>
              <li className="border-l-2 border-ink3 pl-3">
                <p className="font-medium text-ink">Do not move dining</p>
                <p className="mt-0.5 text-ink2">
                  Both cards pay the same rate. The gain is nil; the switching effort is not.
                </p>
              </li>
            </ul>
            <p className="mt-4 text-xs text-ink3">
              Note the shape: two of the three lines say <em>do nothing</em>, and the one move is
              bounded by a cap. A plan in which every category moves is a sign the rules were not read
              carefully.
            </p>
          </div>
        </div>
      </section>

      {/* ---- 2. two numbers ------------------------------------------------ */}
      <section>
        <SectionTitle>Why two numbers are always reported</SectionTitle>
        <Card>
          <div className="grid gap-5 md:grid-cols-2">
            <div className="rounded-lg border border-line bg-line2/40 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                Value if you change nothing
              </p>
              <p className="mt-1 text-sm text-ink2">
                What the card earns on your spending exactly as it falls today — no re-routing, no
                change of habit, caps applied where they would actually bind.
              </p>
            </div>
            <div className="rounded-lg border border-line bg-line2/40 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-ink3">
                Value if you route as planned
              </p>
              <p className="mt-1 text-sm text-ink2">
                What it earns once the plan is followed — and only for the spend the plan actually
                moves, up to each cap.
              </p>
            </div>
          </div>
          <p className="mt-5 border-t border-line pt-4 text-sm leading-relaxed text-ink2">
            Collapsing the two into a single headline overstates every card, because the higher figure
            silently assumes you reorganise your spending perfectly and keep doing it. Reporting both
            makes the price of the plan visible: the gap between them is what the effort is worth, and
            when that gap is small the honest recommendation is to leave things alone.
          </p>
          <p className="mt-3 text-xs text-ink3">
            Both figures arrive already computed from the engine, each with its own confidence and the
            cap that bound it. Neither is ever derived in this interface (D-002, D-008, D-029).
          </p>
        </Card>
      </section>

    </main>
  );
}

/* --- readiness, streamed because terms extraction reads the source PDFs --- */

function gateState(overview: Overview) {
  const coverage = overview.gates.find((g) => g.gate === "COVERAGE");
  const uncat = overview.gates.find((g) => g.gate === "UNCATEGORIZED_SPEND");
  return {
    coverage,
    uncat,
    coverageOk: coverage ? !coverage.failing : overview.months_covered >= 6,
    uncatOk: uncat ? !uncat.failing : false,
  };
}

function termsState(result: ProbeResult, wallet: Account[]) {
  if (!result.ok) return { confirmed: 0, weak: 0, ok: false, probes: [] as TermsProbe[] };
  const confirmed = result.probes.filter((p) => p.level === "product").length;
  const weak = result.probes.filter((p) => p.level === "issuer").length;
  return {
    confirmed,
    weak,
    ok: wallet.length > 0 && confirmed === wallet.length,
    probes: result.probes,
  };
}

async function Summary({
  overview,
  wallet,
  probes,
}: {
  overview: Overview;
  wallet: Account[];
  probes: Promise<ProbeResult>;
}) {
  const result = await probes;
  const { coverageOk, uncatOk, coverage, uncat } = gateState(overview);
  const terms = termsState(result, wallet);
  // data/wallet.json has no endpoint by design — it is written by hand, so it is
  // never satisfied from here.
  const met = [coverageOk, uncatOk, false, terms.ok].filter(Boolean).length;

  return (
    <div className="space-y-3">
      <Card className="border-warn/40 bg-warnSoft/40">
        <div className="flex flex-wrap items-center gap-3">
          <Chip tone="bad">not ready</Chip>
          <p className="text-sm text-ink2">
            <span className="tnum font-semibold text-ink">{met} of 4</span> readiness conditions met. No
            plan is shown until all four hold: an unconfirmed rule that moves real money is worse than no
            plan at all (D-027).
          </p>
        </div>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Reward cycles covered"
          value={
            <>
              {overview.months_covered} <span className="text-sm font-normal text-ink3">/ 6</span>
            </>
          }
          tone={coverageOk ? "ok" : "bad"}
          hint={coverage?.detail ?? "6 full cycles minimum"}
        />
        <Stat
          label="Uncategorized spend"
          value={
            <>
              {overview.uncategorized_pct}
              <span className="text-sm font-normal text-ink3">%</span>
            </>
          }
          tone={uncatOk ? "ok" : "bad"}
          hint={`${formatAbs(overview.uncategorized_spend)} of ${formatAbs(overview.total_spend)}`}
        />
        <Stat
          label="Cards with own terms"
          value={
            result.ok ? (
              <>
                {terms.confirmed} <span className="text-sm font-normal text-ink3">/ {wallet.length}</span>
              </>
            ) : (
              "—"
            )
          }
          tone={result.ok ? (terms.ok ? "ok" : "bad") : undefined}
          hint={result.ok ? "every wallet card, not just the candidate" : "terms lookup unavailable"}
        />
        <Stat
          label="data/wallet.json"
          value="absent"
          tone="bad"
          hint="confirmed rules per wallet card"
        />
      </div>
    </div>
  );
}

async function Readiness({
  overview,
  wallet,
  excluded,
  probes,
}: {
  overview: Overview;
  wallet: Account[];
  excluded: Account[];
  probes: Promise<ProbeResult>;
}) {
  const result = await probes;
  const { coverage, uncat, coverageOk, uncatOk } = gateState(overview);
  const terms = termsState(result, wallet);

  return (
    <div className="space-y-3">
      <Table head={["Condition", "State", "Now", "Required", "Next action"]}>
        <tr className="border-b border-line align-top">
          <td className="px-3 py-3">
            <p className="font-medium">Statement coverage</p>
            <p className="mt-0.5 text-xs text-ink3">
              Caps, cycles and anniversary bonuses only reveal themselves over several cycles.
            </p>
          </td>
          <td className="px-3 py-3">
            <Chip tone={coverageOk ? "ok" : "bad"}>{coverageOk ? "met" : "blocking"}</Chip>
          </td>
          <td className="tnum px-3 py-3">{overview.months_covered} cycles</td>
          <td className="tnum px-3 py-3">6 cycles</td>
          <td className="px-3 py-3 text-ink2">
            Ingest more statements, for every wallet card and not only the candidate:
            <Cmd>python -m analyser ingest &lt;statement.pdf&gt;</Cmd>
            <Src>gate COVERAGE — {coverage?.detail ?? "6 of 6 months minimum"}</Src>
          </td>
        </tr>

        <tr className="border-b border-line align-top">
          <td className="px-3 py-3">
            <p className="font-medium">Uncategorized spend</p>
            <p className="mt-0.5 text-xs text-ink3">
              Spend with no category cannot be routed, and quietly distorts both numbers if ignored.
            </p>
          </td>
          <td className="px-3 py-3">
            <Chip tone={uncatOk ? "ok" : "bad"}>{uncatOk ? "met" : "blocking"}</Chip>
          </td>
          <td className="tnum px-3 py-3">
            {overview.uncategorized_pct}%
            <span className="block text-xs text-ink3">{formatAbs(overview.uncategorized_spend)}</span>
          </td>
          <td className="tnum px-3 py-3">&le; 10% by value</td>
          <td className="px-3 py-3 text-ink2">
            {uncatOk ? (
              <>Nothing to do — re-check after each ingest, since new merchants arrive uncategorized.</>
            ) : (
              <>
                Clear the queue on the Review screen, or from the command line:
                <Cmd>python -m analyser review</Cmd>
              </>
            )}
            <Src>gate UNCATEGORIZED_SPEND — {uncat?.detail ?? "at or below 10% by value"}</Src>
          </td>
        </tr>

        <tr className="border-b border-line align-top">
          <td className="px-3 py-3">
            <p className="font-medium mono">data/wallet.json</p>
            <p className="mt-0.5 text-xs text-ink3">
              Confirmed rules for every wallet card. Extracted rules are evidence, not authority.
            </p>
          </td>
          <td className="px-3 py-3">
            <Chip tone="bad">blocking</Chip>
          </td>
          <td className="px-3 py-3">absent</td>
          <td className="px-3 py-3 tnum">
            {wallet.length} confirmed card{wallet.length === 1 ? "" : "s"}
          </td>
          <td className="px-3 py-3 text-ink2">
            Read each card&rsquo;s extracted rules and its source quote on the Cards screen, then write
            the rates, caps and exclusions you have confirmed into the file by hand:
            <Cmd>{`$EDITOR data/wallet.json`}</Cmd>
            <Src>
              D-022, D-027 — an extracted rule must be confirmed by a human before it drives money. The
              API deliberately exposes no endpoint that would let this interface write the file for you.
            </Src>
          </td>
        </tr>

        <tr className="align-top">
          <td className="px-3 py-3">
            <p className="font-medium">Terms document per card</p>
            <p className="mt-0.5 text-xs text-ink3">
              Every card in the wallet — the &ldquo;change nothing&rdquo; number is only as good as the
              rules of the card the spend would leave.
            </p>
          </td>
          <td className="px-3 py-3">
            <Chip tone={!result.ok ? "warn" : terms.ok ? "ok" : "bad"}>
              {!result.ok ? "unknown" : terms.ok ? "met" : "blocking"}
            </Chip>
          </td>
          <td className="tnum px-3 py-3">
            {result.ok ? `${terms.confirmed} of ${wallet.length}` : "—"}
            {result.ok && terms.weak > 0 ? (
              <span className="block text-xs text-warn">+{terms.weak} issuer-level only</span>
            ) : null}
          </td>
          <td className="tnum px-3 py-3">
            {wallet.length} of {wallet.length}
          </td>
          <td className="px-3 py-3 text-ink2">
            Add a KFS or T&amp;C document for each card missing one, then re-extract:
            <Cmd>python -m analyser terms &lt;kfs.pdf&gt;</Cmd>
            <Src>
              D-022 — rules are never inferred from a neighbouring product, so a missing document stays
              missing rather than borrowing the rates of another card.
            </Src>
          </td>
        </tr>
      </Table>

      <Card>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <SectionTitle>Terms coverage by wallet card</SectionTitle>
          <span className="text-xs text-ink3">
            probed live against <span className="mono">/api/cards/&lt;card&gt;/rules</span>
          </span>
        </div>

        {!result.ok ? (
          <p className="text-sm text-ink2">
            The terms lookup could not be reached, so this condition is reported as unknown rather than
            assumed met.
          </p>
        ) : wallet.length === 0 ? (
          <p className="text-sm text-ink2">
            No credit-card account is marked as included in spending yet, so there is no wallet to plan
            for.
          </p>
        ) : (
          <Table head={["Card", "Terms", "Matched on", "Source documents", "Notes"]}>
            {terms.probes.map((p) => (
              <tr key={p.account.account_id} className="border-b border-line align-top last:border-0">
                <td className="px-3 py-2">
                  <p className="font-medium">{p.account.product_name ?? p.account.issuer}</p>
                  <p className="mono text-xs text-ink3">{p.account.account_id}</p>
                </td>
                <td className="px-3 py-2">
                  <Chip tone={p.level === "product" ? "ok" : p.level === "issuer" ? "warn" : "bad"}>
                    {p.level === "product" ? "found" : p.level === "issuer" ? "issuer only" : "missing"}
                  </Chip>
                </td>
                <td className="mono px-3 py-2 text-xs text-ink2">{p.matched ?? "—"}</td>
                <td className="px-3 py-2 text-xs text-ink2">
                  {p.sources.length === 0 ? (
                    "—"
                  ) : (
                    <ul className="space-y-0.5">
                      {p.sources.map((s) => (
                        <li key={`${s.source}:${s.file}`}>
                          <span className="font-semibold text-ink3">{s.source}</span>{" "}
                          <span className="mono break-all">{s.file}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-ink2">
                  {p.level === "none" ? (
                    <>No terms document names this card. Its rules will not be guessed (D-022).</>
                  ) : (
                    <div className="space-y-1">
                      {p.level === "issuer" ? (
                        <p className="text-warn">
                          Matched the issuer, not the product — the document may describe a different
                          card from the same bank. Confirm it before it is allowed to move money.
                        </p>
                      ) : null}
                      <div className="flex flex-wrap gap-1.5">
                        {p.conflicts > 0 ? (
                          <Chip tone="warn">
                            {p.conflicts} conflict{p.conflicts === 1 ? "" : "s"}
                          </Chip>
                        ) : null}
                        {p.unreadable > 0 ? <Chip tone="warn">{p.unreadable} unreadable</Chip> : null}
                        {p.conflicts === 0 && p.unreadable === 0 ? (
                          <span className="text-ink3">extracted cleanly — still unconfirmed</span>
                        ) : null}
                      </div>
                      <p className="text-ink3">Review the quotes on the Cards screen.</p>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}

        {excluded.length > 0 ? (
          <p className="mt-3 text-xs text-ink3">
            Held out of the wallet and out of every plan figure:{" "}
            {excluded.map((a) => (
              <span key={a.account_id} className="mono">
                {a.account_id} ({a.account_type.toLowerCase()}){" "}
              </span>
            ))}
            — not a credit card, or flagged out of spending, so its transactions are not routable.
          </p>
        ) : null}
      </Card>
    </div>
  );
}

/* --- skeletons ------------------------------------------------------------ */

function SummarySkeleton({ overview, wallet }: { overview: Overview; wallet: Account[] }) {
  const { coverageOk, uncatOk, coverage, uncat } = gateState(overview);
  return (
    <div className="space-y-3">
      <Card className="border-line">
        <div className="flex flex-wrap items-center gap-3">
          <Chip tone="neutral">checking</Chip>
          <p className="text-sm text-ink2">
            Reading the terms documents for {wallet.length} wallet card
            {wallet.length === 1 ? "" : "s"} — this reads the source PDFs, so it takes a moment.
          </p>
        </div>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Reward cycles covered"
          value={
            <>
              {overview.months_covered} <span className="text-sm font-normal text-ink3">/ 6</span>
            </>
          }
          tone={coverageOk ? "ok" : "bad"}
          hint={coverage?.detail ?? "6 full cycles minimum"}
        />
        <Stat
          label="Uncategorized spend"
          value={
            <>
              {overview.uncategorized_pct}
              <span className="text-sm font-normal text-ink3">%</span>
            </>
          }
          tone={uncatOk ? "ok" : "bad"}
          hint={uncat?.detail ?? "at or below 10% by value"}
        />
        <Stat label="Cards with own terms" value="…" hint="reading terms documents" />
        <Stat label="data/wallet.json" value="absent" tone="bad" hint="confirmed rules per wallet card" />
      </div>
    </div>
  );
}

function ReadinessSkeleton() {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        <Chip tone="neutral">checking</Chip>
        <p className="text-sm text-ink2">
          Checking which wallet cards have a terms document of their own. Nothing is assumed while this
          runs.
        </p>
      </div>
    </Card>
  );
}

/* --- small local presentational helpers ---------------------------------- */

function Cmd({ children }: { children: React.ReactNode }) {
  return (
    <code className="mono mt-1.5 block overflow-x-auto whitespace-pre rounded border border-line bg-line2/60 px-2 py-1.5 text-xs text-ink">
      {children}
    </code>
  );
}

function Src({ children }: { children: React.ReactNode }) {
  return <p className="mt-1.5 text-xs text-ink3">{children}</p>;
}

function ApiDownNotice() {
  return (
    <div className="space-y-6">
      <PageTitle sub="The routing plan reads live data to tell you what is still missing.">Routing plan</PageTitle>
      <State title="The analyser API is not reachable.">
        <p>Start it from the project root, then reload this page:</p>
        <code className="mono mt-2 block overflow-x-auto whitespace-pre rounded border border-line bg-line2/60 px-2 py-1.5 text-xs text-ink">
          .venv/bin/python -m analyser.api
        </code>
        <p className="mt-2 text-xs text-ink3">
          Nothing is cached or assumed while it is down — no figure is shown that cannot be sourced.
        </p>
      </State>
    </div>
  );
}
