import type { Money } from "./money";

const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8787";

export class ApiDown extends Error {}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiDown(
      "Cannot reach the analyser API. Start it with:  .venv/bin/python -m analyser.api"
    );
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `${res.status} ${path}`);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}

// ---- shapes mirroring analyser/api.py -------------------------------------

export type Gate = { gate: string; failing: boolean; detail: string };

export type Account = {
  account_id: string; issuer: string; product_name: string | null;
  account_type: string; currency: string; include_in_spending: number; txns: number;
};

export type Overview = {
  documents: Record<string, number>;
  transactions: number;
  accounts: Account[];
  total_spend: Money | null;
  uncategorized_spend: Money | null;
  uncategorized_pct: number;
  months_covered: number;
  gates: Gate[];
};

export type DocumentRow = {
  document_id: string; file_name: string; parser_name: string; parser_version: number;
  status: "RECONCILED" | "PARSED" | "REJECTED"; reject_reason: string | null;
  statement_date: string | null; period_start: string | null; period_end: string | null;
  page_count: number | null; ingested_at: string; account_id: string;
  txns: number; lines: number; unparsed: number;
};

export type Txn = {
  txn_id: string; account_id: string; txn_date: string; posting_date: string | null;
  amount: Money; currency: string; merchant: string | null; category: string | null;
  txn_type: string; category_confidence: string | null; raw_description: string | null;
  card: string;
  corrected: boolean; excluded: number; transfer_group_id: string | null;
};

export type ReviewRow = {
  txn_id: string; account_id: string; txn_date: string; amount: Money;
  merchant: string | null; category: string | null; category_confidence: string | null;
  raw_description: string | null;
};

export type Tier = {
  rate_bps: number; categories?: string | null; label?: string | null;
  source?: string; source_quote?: string; cap_per_cycle?: number | null;
};

export type Rules = {
  card: string;
  sources: { source: string; file: string }[];
  unreadable: { file: string; reason: string }[];
  precedence: string;
  tiers: Tier[];
  exclusions: { label: string; detectability?: string; source_quote?: string }[];
  cycle: { anchor_day?: number; key?: string } | null;
  expiry_months: number | null;
  fx_spread_bps: number | null;
  fx_total_bps: number | null;
  conflicts: { rule: string; values?: unknown[]; sources?: string[] }[];
};

export type RewardRow = {
  account_id: string; category_label: string | null; reward_unit: string;
  spend_minor: Money | null; rate_bps: number | null; earned: Money | null;
  opening_balance: Money | null; closing_balance: Money | null;
  cycle_start: string | null; cycle_end: string | null;
};

export type CategorySlice = { category: string; spend: Money; txns: number; pct: number };
export type ByCategory = { total: Money | null; categories: CategorySlice[] };
export type MonthPoint = {
  month: string; spend: Money; txns: number;
  change: Money | null; change_pct: number | null;
};
export type Trend = { months: MonthPoint[]; current: MonthPoint | null; average: Money | null };
export type MerchantRow = { merchant: string; category: string | null; spend: Money; txns: number };
export type RecurringRow = MerchantRow & { months: number; total: Money; typical: Money };
export type LargestRow = {
  txn_id: string; txn_date: string; merchant: string | null; category: string | null;
  account_id: string; amount: Money;
};
export type Position = {
  account_id: string; issuer: string; product_name: string | null; currency: string;
  account_type: string; include_in_spending: number;
  statement_date: string | null; payment_due_date: string | null;
  closing_balance: Money | null; total_payment_due: Money | null; minimum_due: Money | null;
  credit_limit: Money | null; available_limit: Money | null; utilisation_bps: number | null;
};
export type EvalLine = {
  category: string; spend: Money; rate_bps: number; reward: Money;
  matched_rule: string | null; match: "EXPLICIT" | "CATCH_ALL" | "NONE";
};
export type Evaluation = {
  file: string; card: string; cards_found: string[]; months_of_data: number;
  tiers: Tier[]; exclusions: { label: string; detectability?: string; source_quote?: string }[];
  conflicts: { rule: string }[];
  observed_reward: Money; annualised_reward: Money | null;
  annual_fee: Money; net_annual: Money | null;
  lines: EvalLine[];
  verdict: string | null; verdict_blocked: boolean; verdict_blocked_reason: string | null;
};

export async function evaluateCard(file: File, cardName?: string): Promise<Evaluation> {
  const fd = new FormData();
  fd.append("file", file);
  if (cardName) fd.append("card_name", cardName);
  const res = await fetch(`${BASE}/api/evaluate`, { method: "POST", body: fd });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (body as { detail?: unknown }).detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d ?? res.status));
  }
  return body as Evaluation;
}

export type LibraryFile = {
  file_name: string; status: string | null; locked: boolean;
  statement_date: string | null; reject_reason: string | null;
  txns: number | null; size_bytes: number;
};
export type LibraryBank = {
  issuer_id: string; name: string; has_parser: boolean; has_password: boolean;
  total: number; read: number; rejected: number; pending: number; locked: number;
  transactions: number; files: LibraryFile[];
};
export type Library = {
  banks: LibraryBank[]; directory: string;
  totals: { files: number; read: number; rejected: number; pending: number;
            locked: number; transactions: number };
};
export type ProcessResult = {
  file_name: string; status: string; detail?: string | null;
  account_id?: string; transactions?: number; pages?: number;
};

export async function uploadStatements(files: File[]) {
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`${BASE}/api/statements/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json() as Promise<{
    saved: { file_name: string; size_bytes: number }[];
    rejected: { file_name: string; reason: string }[];
    note: string;
  }>;
}

export async function processStatements() {
  const res = await fetch(`${BASE}/api/statements/process`, { method: "POST" });
  if (!res.ok) throw new Error(`Processing failed (${res.status})`);
  return res.json() as Promise<{ results: ProcessResult[]; reconciled: number; total: number }>;
}

export type LockedBank = {
  issuer_id: string; name: string; total: number; unlocked: number; examples: string[];
};
export type PasswordStatus = {
  banks: LockedBank[]; locked_banks: number; locked_files: number;
};

export async function saveStatementPassword(password: string, label = "") {
  const res = await fetch(`${BASE}/api/statements/password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password, label }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail ?? "Could not save that password.");
  return body as { issuer_id: string; name: string; unlocked: number; files: string[]; note: string };
}

export type GmailStatus = {
  configured: boolean; connected: boolean; scope: string;
  setup_doc: string; email: string | null; messages_total?: number; error?: string;
};
export type GmailMail = {
  id: string; from: string; subject: string; date: string; attachments: string[];
};

async function postPlain<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "POST" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail ?? `Failed (${res.status})`);
  return body as T;
}

export const gmail = {
  status: () => get<GmailStatus>("/api/gmail/status"),
  connect: () => postPlain<{ connected: boolean; email: string }>("/api/gmail/connect"),
  disconnect: () => postPlain<{ disconnected: boolean }>("/api/gmail/disconnect"),
  search: (limit = 25) => get<GmailMail[]>(`/api/gmail/search?limit=${limit}`),
  download: (limit = 25) =>
    postPlain<{ saved: { file_name: string; from: string; subject: string }[]; skipped: string[] }>(
      `/api/gmail/download?limit=${limit}`),
};

export type DataRange = { first: string | null; last: string | null; transactions: number; months: string[] };

/** A date window. Built here so every screen scopes the same way. */
export type Period = { from?: string; to?: string; label: string };

/** The window the app opens on: the current calendar year (D-038). */
export function defaultPeriod(year: string | null): Period {
  if (!year) return { label: "All time" };
  return { label: year, from: `${year}-01-01`, to: `${year}-12-31` };
}

export function qs(p?: Period, extra: Record<string, string | number> = {}) {
  const s = new URLSearchParams();
  if (p?.from) s.set("from_date", p.from);
  if (p?.to) s.set("to_date", p.to);
  for (const [k, v] of Object.entries(extra)) s.set(k, String(v));
  const out = s.toString();
  return out ? `?${out}` : "";
}

export type CalMonth = {
  month: string; spend: Money; txns: number;
  change: Money | null; change_pct: number | null;
};
export type CalYear = {
  year: string;
  is_current: boolean; spend: Money; txns: number; average_month: Money | null;
  busiest_month: string | null; quietest_month: string | null; months: CalMonth[];
};

export type AccountStatement = {
  document_id: string; file_name: string; statement_date: string | null;
  period_start: string | null; period_end: string | null;
  payment_due_date: string | null; status: string; reject_reason: string | null;
  page_count: number | null; parser_name: string; txns: number;
  purchases_debits: Money | null; payments_credits: Money | null;
  closing_balance: Money | null; total_payment_due: Money | null;
  credit_limit: Money | null;
  email_url: string | null;
  subject: string | null;
  sender: string | null;
};
export type AccountDetail = {
  account: {
    account_id: string; issuer: string; issuer_name: string;
    product_name: string | null; account_type: string; currency: string;
    masked_number: string | null; include_in_spending: number;
  };
  position: Position | null;
  statements: AccountStatement[];
  transactions: { txn_id: string; txn_date: string; merchant: string | null;
                  category: string | null; amount: Money }[];
  totals: { spend: Money; transactions: number; months: number };
  rewards: { reward_program: string | null; reward_unit: string;
             cycle_start: string | null; cycle_end: string | null;
             category_label: string | null; rate_bps: number | null;
             earned: Money | null; closing_balance: Money | null }[];
};

export async function setCategory(
  txnId: string, category: string, applyToMerchant?: boolean,
) {
  const res = await fetch(`${BASE}/api/transactions/${txnId}/category`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // Omit the flag and the server decides by category: a reimbursable is a
    // one-off, "Lulu is groceries" is a standing rule.
    body: JSON.stringify(
      applyToMerchant === undefined
        ? { category }
        : { category, apply_to_merchant: applyToMerchant }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail ?? "Could not save.");
  return body as {
    txn_id: string; merchant: string | null; category: string;
    updated: number; note: string; applied_to_merchant: boolean;
  };
}

export type CategoryCharge = {
  txn_id: string; txn_date: string; merchant: string | null; category: string | null;
  account_id: string; card: string; amount: Money; raw_description: string | null;
};
export type CategoryMonth = {
  month: string; spend: Money; count: number; charges: CategoryCharge[];
};
export type CategoryDetail = {
  category: string; total: Money; count: number;
  months: CategoryMonth[];
  merchants: { merchant: string; spend: Money; count: number }[];
};

/* ── evidence: where a single figure came from ───────────────────────────── */

export type EvidenceLine = {
  page_number: number; line_index: number; raw_text: string;
  disposition: string; is_this_charge: boolean;
};
export type Evidence = {
  txn_id: string;
  amount: Money; fx: Money | null;
  txn_date: string | null; posting_date: string | null;
  merchant: string | null; category: string | null;
  category_confidence: string | null; corrected: boolean;
  excluded: boolean; exclude_reason: string | null; is_transfer: boolean;
  source: {
    raw_text: string; raw_description: string;
    page_number: number; line_index: number;
    printed_at_line: number | null;
    context: EvidenceLine[];
  };
  document: {
    document_id: string; file_name: string;
    parser_name: string; parser_version: number;
    status: string; reject_reason: string | null;
    statement_date: string | null; period_start: string | null; period_end: string | null;
    page_count: number | null; ingested_at: string;
  };
  account: {
    account_id: string; issuer: string;
    product_name: string | null; account_type: string;
  };
};

/* ── wallet & plan ───────────────────────────────────────────────────────── */

export type WalletTier = {
  categories: string[] | null;
  rate_bps: number;
  cap_per_cycle_minor?: number | null;
  label?: string | null;
};
export type WalletCard = {
  card_id: string; account_id: string; issuer: string; currency: string;
  annual_fee_minor: number;
  reward: {
    unit: string;
    cycle: { anchor_day: number; key: string };
    rounding: { mode: string; unit: string; scope: string };
    tiers: WalletTier[];
  };
};
export type WalletAccount = {
  account_id: string; issuer: string; product_name: string | null;
  currency: string; account_type: string; txns: number;
  confirmed: boolean; tier_count: number; annual_fee: Money | null;
};
export type WalletState = {
  path: string; exists: boolean;
  cards: WalletCard[];
  routing: { merchant_locked: string[]; direct_debit: string[] };
  accounts: WalletAccount[];
  confirmed_count: number;
};

export type PlanMove = {
  category: string; from_card: string | null; to_card: string;
  monthly_spend: Money; annual_gain: Money;
};
export type PlanResult = {
  ready: boolean;
  reason: "NO_WALLET" | "NO_TRANSACTIONS" | null;
  detail?: string;
  wallet_path: string;
  horizon?: { start: string; months: number };
  cards?: string[];
  transactions_considered?: number;
  plan: {
    value_unchanged: Money | null;
    value_if_routed: Money | null;
    annual_gain: Money | null;
    moves: PlanMove[];
    moves_for_80pct: number;
  } | null;
};

export async function saveWallet(body: {
  cards: WalletCard[];
  routing?: { merchant_locked: string[]; direct_debit: string[] };
}) {
  const res = await fetch(`${BASE}/api/wallet`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (out as { detail?: unknown }).detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d ?? res.status));
  }
  return out as { path: string; cards: number; note: string };
}

export type IncomeMonth = { month: string; earned: Money; txns: number };

export type Income = {
  total: Money | null;
  transactions: number;
  months: IncomeMonth[];
  months_covered: number;
  /** Mean month. Skewed by a bonus month -- show `typical` beside it. */
  average: Money | null;
  /** Median month: what an ordinary pay cheque actually looks like. */
  typical: Money | null;
  sources: { kind: string; earned: Money; txns: number }[];
  /** Only months where BOTH income and card spending are known. */
  compared: {
    months: string[];
    earned: Money | null;
    spent: Money | null;
    /** Card spend as a share of income. NOT a savings rate -- rent and
     *  transfers leave the current account without touching a card. */
    card_spend_pct: number | null;
  };
  income_only_months: string[];
  spend_only_months: string[];
};

export const api = {
  categoryDetail: (category: string, p?: Period) =>
    get<CategoryDetail>(
      `/api/analytics/category/${encodeURIComponent(category)}${qs(p)}`),
  account: (id: string) => get<AccountDetail>(`/api/accounts/${encodeURIComponent(id)}`),
  calendar: () =>
    get<{ years: CalYear[]; default_year: string | null; current_year: string }>(
      "/api/analytics/calendar"),
  range: () => get<DataRange>("/api/analytics/range"),
  locked: () => get<PasswordStatus>("/api/statements/passwords"),
  library: () => get<Library>("/api/statements/library"),
  byCategory: (p?: Period) => get<ByCategory>(`/api/analytics/by-category${qs(p)}`),
  trend: () => get<Trend>("/api/analytics/trend"),
  income: (p?: Period) => get<Income>(`/api/income${qs(p)}`),
  merchants: (n = 10, p?: Period) =>
    get<MerchantRow[]>(`/api/analytics/by-merchant${qs(p, { limit: n })}`),
  recurring: (minMonths = 2) =>
    get<RecurringRow[]>(`/api/analytics/recurring?min_months=${minMonths}`),
  largest: (n = 8, p?: Period) =>
    get<LargestRow[]>(`/api/analytics/largest${qs(p, { limit: n })}`),
  positions: () => get<Position[]>("/api/positions"),
  overview: (p?: Period) => get<Overview>(`/api/overview${qs(p)}`),
  documents: () => get<DocumentRow[]>("/api/documents"),
  transactions: (q = "") => get<Txn[]>(`/api/transactions${q}`),
  evidence: (txnId: string) =>
    get<Evidence>(`/api/transactions/${encodeURIComponent(txnId)}/evidence`),
  transactionsIn: (p?: Period, extra: Record<string, string | number> = {}) =>
    get<Txn[]>(`/api/transactions${qs(p, extra)}`),
  review: (includeRepayments = false) =>
    get<ReviewRow[]>(`/api/review?include_repayments=${includeRepayments}`),
  categories: () => get<string[]>("/api/categories"),
  rewards: () => get<RewardRow[]>("/api/rewards"),
  rules: (card: string) => get<Rules>(`/api/cards/${encodeURIComponent(card)}/rules`),
  wallet: () => get<WalletState>("/api/wallet"),
  plan: (months = 12) => get<PlanResult>(`/api/plan?months=${months}`),
  addCorrection: (b: { match?: string; canonical?: string; category?: string }) =>
    post<{ written: string[]; note: string }>("/api/corrections", b),
};

/* ── ledger: every transaction on every account ──────────────────────────────
 *
 * Mirrors /api/ledger in analyser/api.py. Unlike everything above it, these rows
 * are NOT filtered to card spending: bank debits, card payments, fees, interest
 * and salary all appear. `amount` is therefore SIGNED — negative left, positive
 * arrived — and must never be shown through formatAbs, which would drop the one
 * fact that tells a salary from a restaurant bill.
 *
 * Money in and money out arrive as two separate figures already summed by the
 * engine, per currency, with transfer legs left out so nothing is counted twice.
 */

export type LedgerRow = {
  txn_id: string; account_id: string; txn_date: string; posting_date: string | null;
  amount: Money; currency: string;
  direction: "IN" | "OUT";
  txn_type: string; merchant: string | null; category: string | null;
  confidence: string | null; raw_description: string | null;
  card: string; issuer: string; product_name: string | null; account_type: string;
  include_in_spending: number;
  excluded: number; transfer_group_id: string | null;
  is_transfer: boolean; counted: boolean;
  /** What the row did to your net worth, as opposed to which way it crossed
   *  an account. Paying a card is money IN and REPAID at the same time. */
  flow: LedgerFlow;
};

export type LedgerFlow =
  | "EARNED" | "SPENT" | "MOVED" | "BORROWED" | "REPAID"
  | "REFUNDED" | "NEUTRAL" | "UNKNOWN";

export type LedgerFlowTotal = {
  flow: LedgerFlow; currency: string; txns: number;
  money_in: Money; money_out: Money; net: Money;
};

export type LedgerCurrencyTotal = {
  currency: string;
  money_in: Money; money_out: Money; net: Money;
  in_count: number; out_count: number; counted_rows: number;
};

export type Ledger = {
  rows: LedgerRow[];
  page: { limit: number; offset: number; returned: number; total: number; has_more: boolean };
  totals: {
    by_currency: LedgerCurrencyTotal[];
    by_flow: LedgerFlowTotal[];
    counted_rows: number; transfer_legs: number; excluded_rows: number;
    omitted_rows: number; basis: string; flow_basis: string;
  };
  facets: {
    accounts: { account_id: string; card: string; account_type: string;
                issuer: string; product_name: string | null; txns: number }[];
    types: { txn_type: string; txns: number }[];
    flows: { flow: LedgerFlow; txns: number }[];
  };
  range: { first: string | null; last: string | null };
};

export type LedgerQuery = {
  account_id?: string; account_type?: string; txn_type?: string;
  direction?: "in" | "out"; flow?: string; q?: string; limit?: number; offset?: number;
};

export function fetchLedger(p?: Period, f: LedgerQuery = {}): Promise<Ledger> {
  const extra: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(f)) {
    if (v !== undefined && v !== null && v !== "") extra[k] = v as string | number;
  }
  return get<Ledger>(`/api/ledger${qs(p, extra)}`);
}

/** The month/year calendar over EVERY transaction, not just card spending. */
export function fetchLedgerCalendar() {
  return get<{ years: CalYear[]; default_year: string | null; current_year: string }>(
    "/api/ledger/calendar");
}
