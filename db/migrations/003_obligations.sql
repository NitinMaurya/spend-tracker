-- Money-management data (D-031): what is owed, when, and how much credit is in use.
-- The statements already print all of this; it simply was not being captured.

PRAGMA foreign_keys = ON;

ALTER TABLE documents ADD COLUMN payment_due_date TEXT;

-- Latest statement per account: the current position for each card.
CREATE VIEW v_position AS
SELECT
    d.account_id,
    a.issuer,
    a.product_name,
    a.currency,
    a.account_type,
    a.include_in_spending,
    d.statement_date,
    d.payment_due_date,
    s.closing_balance,
    s.total_payment_due,
    s.minimum_due,
    s.credit_limit,
    s.available_limit,
    -- utilisation in basis points, computed here so no client ever divides money
    CASE WHEN s.credit_limit > 0 AND s.closing_balance > 0
         THEN CAST(10000.0 * s.closing_balance / s.credit_limit AS INTEGER) END AS utilisation_bps
FROM documents d
JOIN accounts a ON a.account_id = d.account_id
LEFT JOIN statement_summary s ON s.document_id = d.document_id
WHERE d.status = 'RECONCILED'
  AND d.statement_date = (
      SELECT MAX(d2.statement_date) FROM documents d2
       WHERE d2.account_id = d.account_id AND d2.status = 'RECONCILED');
