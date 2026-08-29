-- Money in against a cost is not a cost.
--
-- 012 sent every FEE and INTEREST row to SPENT on the strength of its type
-- alone, so interest CREDITED to you landed in the spend column: savings
-- interest on a current account, and a waived interest charge reversed back
-- onto a card. Both are money arriving.
--
-- Which one it is depends on the account, and this is the same balance-sheet
-- rule the typing layer uses: interest paid on an asset you hold is earnings,
-- while interest handed back on a debt is a charge being undone.

PRAGMA foreign_keys = OFF;

DROP VIEW IF EXISTS v_income;
DROP VIEW IF EXISTS v_spend;
DROP VIEW IF EXISTS v_card_charges;
DROP VIEW IF EXISTS v_reimbursable;
DROP VIEW IF EXISTS v_financing;
DROP VIEW IF EXISTS v_transactions;

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
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) = 'LOAN_REPAYMENT' THEN 'REPAID'
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('SALARY','INCOME') THEN 'EARNED'
        -- A fee or interest row that ARRIVES is the opposite of what its type
        -- says. On an account you hold it is a payment to you; on a debt it is a
        -- charge being reversed.
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) IN ('FEE','INTEREST')
             AND t.amount_minor > 0
            THEN CASE WHEN a.account_type IN ('BANK','CURRENT','SAVINGS','WALLET')
                      THEN 'EARNED' ELSE 'REFUNDED' END
        -- Settling a card is money coming from another account of yours. Paired
        -- or not, that is a movement, and calling it anything else is what made
        -- a ledger report your own repayments as income.
        WHEN COALESCE(t.user_txn_type, t.system_txn_type) = 'PAYMENT' THEN 'MOVED'
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

PRAGMA foreign_keys = ON;

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

CREATE VIEW v_income AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND transfer_group_id IS NULL
  AND flow = 'EARNED';
