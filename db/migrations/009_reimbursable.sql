-- Money spent on someone else's behalf and paid back is NOT an expense.
--
-- The reimbursement arrives outside the card (cash, INR, a transfer), so no credit
-- ever appears to net against it. The category label is the only record that the
-- money came back — which is exactly why it has to drive the exclusion.
--
-- It stays a CARD CHARGE though: it earned cashback, it used the credit limit, and
-- it is in the statement balance. So it leaves v_spend but not the reward base.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_spend;
CREATE VIEW v_spend AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_WITHDRAWAL')
  AND merchant IS NOT 'INSTALLMENT'
  AND (category IS NULL OR category NOT LIKE 'REIMBURSABLE%');

-- What the CARD saw: everything v_spend has, plus reimbursables. This is the base
-- for reward calculation and utilisation, where a reimbursed purchase still counts.
CREATE VIEW v_card_charges AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_WITHDRAWAL')
  AND merchant IS NOT 'INSTALLMENT';

-- Money laid out for other people, kept visible rather than silently dropped.
CREATE VIEW v_reimbursable AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND category LIKE 'REIMBURSABLE%';
