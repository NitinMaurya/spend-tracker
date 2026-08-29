-- Money coming IN, starting with salary.
--
-- Until now every credit the engine could not name landed in UNKNOWN, which is the
-- right default -- inventing a purpose for money-in is exactly the guess this engine
-- refuses to make. But a salary credit is not a guess: the statement line says
-- SALARY, on a bank account, with a positive amount. That is a fact printed on the
-- page, so it earns its own type rather than being lumped in with the unnamed.
--
-- SQLite cannot ALTER a CHECK constraint, so the table is rebuilt. DROP TABLE and
-- ALTER TABLE RENAME both validate every view in the schema, so the views over
-- transactions come down first and go back up afterwards -- unchanged except for
-- the new v_income. Nothing holds a foreign key pointing AT transactions, so the
-- rebuild itself is a plain copy-drop-rename.

PRAGMA foreign_keys = OFF;

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
        'SALARY','INCOME')),
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

-- Back ON immediately: this is a CONNECTION-level setting, not a statement-level
-- one, so leaving it off would silently disable every ON DELETE CASCADE for the
-- rest of the session that ran the migration.
PRAGMA foreign_keys = ON;

-- --- views restored, verbatim apart from v_income ---------------------------

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

-- Money that arrived and is yours to keep.
--
-- Deliberately NOT filtered by include_in_spending: that flag answers "does this
-- account's activity count as spending", and a salary lands on the current account
-- precisely because it is not spending. Filtering on it here would hide every pay
-- cheque. Transfer legs are still excluded -- moving your own money between your
-- own accounts is not earning it.
CREATE VIEW v_income AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND transfer_group_id IS NULL
  AND txn_type IN ('SALARY','INCOME');
