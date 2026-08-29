-- Spend Tracker — initial schema
-- Money is ALWAYS stored as INTEGER minor units (fils). Never REAL.
-- Dates are ALWAYS ISO-8601 TEXT (YYYY-MM-DD).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- accounts: one row per card or bank account we track
-- ---------------------------------------------------------------
CREATE TABLE accounts (
    account_id           TEXT PRIMARY KEY,     -- slug, e.g. 'fab-blue-signature'
    issuer               TEXT NOT NULL,        -- 'FAB', 'MASHREQ', 'ENBD', ...
    product_name         TEXT,                 -- 'BLUE FAB SIGNAT'
    account_type         TEXT NOT NULL
        CHECK (account_type IN ('CREDIT_CARD','BANK','CREDIT_FACILITY')),
    currency             TEXT NOT NULL DEFAULT 'AED',
    masked_number        TEXT,                 -- '4XXX XX** **** NNNN' — never the full PAN
    -- Wio-style facilities settle other cards; their outflows are not spending.
    include_in_spending  INTEGER NOT NULL DEFAULT 1 CHECK (include_in_spending IN (0,1)),
    notes                TEXT
);

-- ---------------------------------------------------------------
-- documents: one row per ingested PDF. content_hash makes re-ingest a no-op.
-- ---------------------------------------------------------------
CREATE TABLE documents (
    document_id       TEXT PRIMARY KEY,        -- sha256 of file bytes
    account_id        TEXT NOT NULL REFERENCES accounts(account_id),
    source_kind       TEXT NOT NULL CHECK (source_kind IN ('LOCAL','GMAIL')),
    source_ref        TEXT NOT NULL,           -- file path, or gmail message-id + attachment hash
    file_name         TEXT NOT NULL,
    parser_name       TEXT NOT NULL,
    parser_version    INTEGER NOT NULL,
    statement_date    TEXT,
    period_start      TEXT,
    period_end        TEXT,
    page_count        INTEGER,
    ingested_at       TEXT NOT NULL,
    status            TEXT NOT NULL
        CHECK (status IN ('PARSED','RECONCILED','REJECTED')),
    reject_reason     TEXT
);
CREATE UNIQUE INDEX idx_documents_source ON documents(source_kind, source_ref);

-- ---------------------------------------------------------------
-- statement_summary: the issuer's own printed totals.
-- This is the reconciliation anchor — extraction is only trusted if it closes.
-- ---------------------------------------------------------------
CREATE TABLE statement_summary (
    document_id        TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    opening_balance    INTEGER,
    purchases_debits   INTEGER,
    cash_advances      INTEGER,
    finance_charges    INTEGER,
    payments_credits   INTEGER,
    closing_balance    INTEGER,
    total_payment_due  INTEGER,
    minimum_due        INTEGER,
    credit_limit       INTEGER,
    available_limit    INTEGER
);

-- ---------------------------------------------------------------
-- transactions_raw: append-only. Never UPDATEd, never DELETEd.
-- Preserves the evidence chain required by spec §19.
-- ---------------------------------------------------------------
CREATE TABLE transactions_raw (
    raw_id           TEXT PRIMARY KEY,          -- deterministic hash, see analyser/ids.py
    document_id      TEXT NOT NULL REFERENCES documents(document_id),
    account_id       TEXT NOT NULL REFERENCES accounts(account_id),
    page_number      INTEGER NOT NULL,
    line_index       INTEGER NOT NULL,          -- ordinal within the statement, preserves order
    raw_text         TEXT NOT NULL,             -- the source line(s), verbatim
    txn_date         TEXT,
    posting_date     TEXT,
    raw_description  TEXT NOT NULL,
    amount_minor     INTEGER NOT NULL,          -- signed: negative = money leaving (spend)
    currency         TEXT NOT NULL,
    -- Populated only when the statement shows the original foreign amount.
    fx_amount_minor  INTEGER,
    fx_currency      TEXT
);
CREATE INDEX idx_raw_document ON transactions_raw(document_id);

-- ---------------------------------------------------------------
-- transactions: the normalized, mutable layer. One row per raw row.
-- system_* is machine-owned; user_* is human-owned and always wins.
-- ---------------------------------------------------------------
CREATE TABLE transactions (
    txn_id              TEXT PRIMARY KEY REFERENCES transactions_raw(raw_id),
    account_id          TEXT NOT NULL REFERENCES accounts(account_id),
    txn_date            TEXT NOT NULL,
    posting_date        TEXT,
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,

    system_txn_type     TEXT NOT NULL CHECK (system_txn_type IN (
        'PURCHASE','REFUND','PAYMENT','FEE','INTEREST','CASH_ADVANCE',
        'CASH_WITHDRAWAL','REVERSAL','ADJUSTMENT','TRANSFER','UNKNOWN')),
    user_txn_type       TEXT,

    system_merchant     TEXT,
    user_merchant       TEXT,

    system_category     TEXT,
    user_category       TEXT,
    category_confidence TEXT CHECK (category_confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN')),

    -- Set when this row is one leg of an inter-account transfer (card payment
    -- appearing on both the card and the funding account).
    transfer_group_id   TEXT,
    excluded            INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0,1)),
    exclude_reason      TEXT
);
CREATE INDEX idx_txn_account_date ON transactions(account_id, txn_date);
CREATE INDEX idx_txn_transfer ON transactions(transfer_group_id);

-- Effective values: user correction wins, else system value.
CREATE VIEW v_transactions AS
SELECT
    t.txn_id,
    t.account_id,
    a.issuer,
    t.txn_date,
    t.posting_date,
    t.amount_minor,
    t.currency,
    COALESCE(t.user_txn_type, t.system_txn_type)  AS txn_type,
    COALESCE(t.user_merchant, t.system_merchant)  AS merchant,
    COALESCE(t.user_category, t.system_category)  AS category,
    CASE WHEN t.user_category IS NOT NULL THEN 'HIGH' ELSE t.category_confidence END AS confidence,
    t.excluded,
    t.transfer_group_id,
    a.include_in_spending
FROM transactions t
JOIN accounts a ON a.account_id = t.account_id;

-- Spend only: excludes non-spend types, excluded rows, transfer legs,
-- and accounts flagged as settlement facilities (e.g. Wio).
CREATE VIEW v_spend AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_ADVANCE','CASH_WITHDRAWAL');

-- ---------------------------------------------------------------
-- reward_statements: the issuer's OWN printed reward figures.
-- Ground truth to validate the reward engine against.
-- ---------------------------------------------------------------
CREATE TABLE reward_statements (
    reward_id        TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    account_id       TEXT NOT NULL REFERENCES accounts(account_id),
    reward_unit      TEXT NOT NULL CHECK (reward_unit IN ('AED','POINTS','MILES')),
    -- Mashreq's cashback cycle (6th->5th) differs from its statement cycle.
    cycle_start      TEXT,
    cycle_end        TEXT,
    category_label   TEXT,                      -- 'Noon Spend', or NULL for account-level
    spend_minor      INTEGER,
    rate_bps         INTEGER,                   -- 500 = 5.00%
    opening_balance  INTEGER,
    earned           INTEGER,
    adjusted         INTEGER,
    redeemed         INTEGER,
    closing_balance  INTEGER,
    source_page      INTEGER
);
CREATE INDEX idx_reward_account ON reward_statements(account_id);

CREATE TABLE schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
