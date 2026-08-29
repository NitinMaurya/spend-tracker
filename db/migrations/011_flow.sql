-- Two questions, not one.
--
-- A ledger built on "did money enter or leave this account" answers a
-- bookkeeping question, then gets read as if it answered an economic one. They
-- disagree constantly: paying your own card bill is money arriving on the card,
-- a wire to your family is money leaving an account without anything being
-- bought, and drawing a loan is money arriving that you now owe. Presented as
-- one axis, a ledger reports borrowed money as income and rent as a purchase.
--
-- So `flow` is added ALONGSIDE the sign, never replacing it:
--
--   EARNED    net worth up, from outside
--   SPENT     net worth down, to outside
--   MOVED     between accounts you own -- nets to zero, counted in neither
--   BORROWED  cash in, debt up
--   REPAID    debt down (a card payment, an EMI)
--   REFUNDED  a reversal of earlier spending
--   NEUTRAL   bookkeeping that nets to zero
--   UNKNOWN   money in that the statement never named -- refused, not guessed
--
-- It is DERIVED, never stored, so it cannot drift from the type it is built on
-- and needs no backfill when the rules improve.

PRAGMA foreign_keys = OFF;

DROP VIEW IF EXISTS v_income;
DROP VIEW IF EXISTS v_spend;
DROP VIEW IF EXISTS v_card_charges;
DROP VIEW IF EXISTS v_reimbursable;
DROP VIEW IF EXISTS v_financing;
DROP VIEW IF EXISTS v_transactions;

CREATE TABLE transactions_new (
    txn_id              TEXT PRIMARY KEY REFERENCES transactions_raw(raw_id),
    account_id          TEXT NOT NULL REFERENCES accounts(account_id),
    txn_date            TEXT NOT NULL,
    posting_date        TEXT,
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,

    system_txn_type     TEXT NOT NULL CHECK (system_txn_type IN (
        'PURCHASE','REFUND','PAYMENT','FEE','INTEREST','CASH_ADVANCE',
        'CASH_WITHDRAWAL','REVERSAL','ADJUSTMENT','TRANSFER','UNKNOWN',
        'SALARY','INCOME','CHEQUE','LOAN_DISBURSED','LOAN_REPAYMENT')),
    user_txn_type       TEXT,

    system_merchant     TEXT,
    user_merchant       TEXT,

    system_category     TEXT,
    user_category       TEXT,
    category_confidence TEXT CHECK (category_confidence IN ('HIGH','MEDIUM','LOW','UNKNOWN')),

    transfer_group_id   TEXT,
    excluded            INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0,1)),
    exclude_reason      TEXT
);

INSERT INTO transactions_new SELECT * FROM transactions;
DROP TABLE transactions;
ALTER TABLE transactions_new RENAME TO transactions;

CREATE INDEX idx_txn_account_date ON transactions(account_id, txn_date);
CREATE INDEX idx_txn_transfer ON transactions(transfer_group_id);

-- Connection-level setting: leaving it off would disable every ON DELETE
-- CASCADE for the rest of the session that ran the migration.
PRAGMA foreign_keys = ON;

CREATE VIEW v_transactions AS
SELECT
    t.txn_id,
    t.account_id,
    a.issuer,
    a.account_type,
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
    a.include_in_spending,
    CASE
        -- Debt first, and deliberately ABOVE the transfer test. A drawdown that
        -- has been paired with the account it landed in is still borrowing; if
        -- the pairing outranked it, the single most important fact about the row
        -- -- that you now owe the money -- would be lost to "internal movement".
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) = 'LOAN_DISBURSED' THEN 'BORROWED'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('LOAN_REPAYMENT','PAYMENT') THEN 'REPAID'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('SALARY','INCOME') THEN 'EARNED'
        -- A confirmed pair is the same money seen twice. Whatever each leg was
        -- called, together they net to nothing.
        WHEN t.transfer_group_id IS NOT NULL THEN 'MOVED'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('TRANSFER','CHEQUE') THEN 'MOVED'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('REFUND','REVERSAL') THEN 'REFUNDED'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) = 'ADJUSTMENT' THEN 'NEUTRAL'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN
             ('PURCHASE','CASH_ADVANCE','CASH_WITHDRAWAL','FEE','INTEREST') THEN 'SPENT'
        ELSE 'UNKNOWN'
    END AS flow
FROM transactions t
JOIN accounts a ON a.account_id = t.account_id;

CREATE VIEW v_spend AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_WITHDRAWAL')
  AND merchant IS NOT 'INSTALLMENT'
  AND (category IS NULL OR category NOT LIKE 'REIMBURSABLE%');

CREATE VIEW v_card_charges AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_WITHDRAWAL')
  AND merchant IS NOT 'INSTALLMENT';

CREATE VIEW v_reimbursable AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND category LIKE 'REIMBURSABLE%';

CREATE VIEW v_financing AS
SELECT t.*, r.raw_description
  FROM v_transactions t
  JOIN transactions_raw r ON r.raw_id = t.txn_id
 WHERE r.raw_description LIKE '%QC %M%'
    OR r.raw_description LIKE '%EMI%'
    OR r.raw_description LIKE '%INSTALLMENT%'
    OR r.raw_description LIKE '%INSTALMENT%'
    OR r.raw_description LIKE 'LOC-%';

-- Income is now defined by economic effect rather than by a type list, so a new
-- kind of earnings starts counting the moment it is typed, with no view change.
CREATE VIEW v_income AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND transfer_group_id IS NULL
  AND flow = 'EARNED';
