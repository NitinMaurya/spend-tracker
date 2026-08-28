-- v_position returned one row PER DOCUMENT sharing the newest statement_date, not one
-- row per account. Because the same statement arrived twice (once as a hand-supplied
-- sample, once downloaded from Gmail), every card appeared twice on the Cards screen.

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_position;
CREATE VIEW v_position AS
SELECT
    d.account_id, a.issuer, a.product_name, a.currency, a.account_type,
    a.include_in_spending, d.statement_date, d.payment_due_date,
    s.closing_balance, s.total_payment_due, s.minimum_due,
    s.credit_limit, s.available_limit,
    CASE WHEN s.credit_limit > 0 AND s.closing_balance > 0
         THEN CAST(10000.0 * s.closing_balance / s.credit_limit AS INTEGER) END AS utilisation_bps
FROM documents d
JOIN accounts a ON a.account_id = d.account_id
LEFT JOIN statement_summary s ON s.document_id = d.document_id
-- Exactly one document per account: the newest statement, and among ties the one
-- carrying the most information (a printed total beats a blank one).
WHERE d.document_id = (
    SELECT d2.document_id FROM documents d2
     LEFT JOIN statement_summary s2 ON s2.document_id = d2.document_id
     WHERE d2.account_id = d.account_id AND d2.status = 'RECONCILED'
     ORDER BY d2.statement_date DESC,
              (s2.total_payment_due IS NOT NULL) DESC,
              (s2.credit_limit IS NOT NULL) DESC,
              d2.document_id
     LIMIT 1);
