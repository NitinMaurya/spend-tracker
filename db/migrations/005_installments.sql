-- D-028b, applied to real data. A credit-card loan ("QC 12 M @ 0% + 4% PF" — Quick
-- Cash over 12 months) is BORROWING, and the monthly EMI that repays it is DEBT
-- SERVICE. Neither is spending.
--
-- Left as PURCHASE, five EMI rows accounted for AED 14,958 — 57% of the recorded
-- spend — inflating every category total and every card valuation derived from them.

PRAGMA foreign_keys = ON;

-- SQLite cannot alter a CHECK constraint, so v_spend does the excluding. INSTALLMENT
-- rows are still stored and still visible; they simply are not spending.
DROP VIEW IF EXISTS v_spend;
CREATE VIEW v_spend AS
SELECT * FROM v_transactions
WHERE excluded = 0
  AND include_in_spending = 1
  AND transfer_group_id IS NULL
  AND txn_type IN ('PURCHASE','CASH_WITHDRAWAL')
  AND merchant IS NOT 'INSTALLMENT';

-- Rows whose description marks them as loan or instalment activity.
CREATE VIEW v_financing AS
SELECT t.*, r.raw_description
  FROM v_transactions t
  JOIN transactions_raw r ON r.raw_id = t.txn_id
 WHERE r.raw_description LIKE '%QC %M%'
    OR r.raw_description LIKE '%EMI%'
    OR r.raw_description LIKE '%INSTALLMENT%'
    OR r.raw_description LIKE '%INSTALMENT%'
    OR r.raw_description LIKE 'LOC-%';
