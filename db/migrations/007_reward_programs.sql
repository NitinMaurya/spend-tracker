-- Reward UNIT and reward PROGRAM are different things. Emirates NBD calls its
-- currency "Plus Points"; FAB calls its "Al-Futtaim Rewards"; Mashreq has "Vantage".
-- All are points. Squeezing the programme name into the unit column made the CHECK
-- constraint reject five real statements outright (D-024).

PRAGMA foreign_keys = ON;

ALTER TABLE reward_statements RENAME TO reward_statements_old;

CREATE TABLE reward_statements (
    reward_id        TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    account_id       TEXT NOT NULL REFERENCES accounts(account_id),
    reward_unit      TEXT NOT NULL CHECK (reward_unit IN ('AED','POINTS','MILES')),
    reward_program   TEXT,                     -- 'Plus Points', 'Vantage', ...
    cycle_start      TEXT,
    cycle_end        TEXT,
    category_label   TEXT,
    spend_minor      INTEGER,
    rate_bps         INTEGER,
    opening_balance  INTEGER,
    earned           INTEGER,
    adjusted         INTEGER,
    redeemed         INTEGER,
    closing_balance  INTEGER,
    source_page      INTEGER
);

INSERT INTO reward_statements (
    reward_id, document_id, account_id, reward_unit, cycle_start, cycle_end,
    category_label, spend_minor, rate_bps, opening_balance, earned, adjusted,
    redeemed, closing_balance, source_page)
SELECT reward_id, document_id, account_id, reward_unit, cycle_start, cycle_end,
       category_label, spend_minor, rate_bps, opening_balance, earned, adjusted,
       redeemed, closing_balance, source_page
  FROM reward_statements_old;

DROP TABLE reward_statements_old;
CREATE INDEX idx_reward_account ON reward_statements(account_id);
