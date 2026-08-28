-- D-028e, finally implemented. A bank may identify the same card in more than one
-- way across its own documents: CBD prints the PAN ("4XXXXX******0000") on a card
-- statement and an account number ("1009296748") on another, and both refer to one
-- card. Without aliases each identifier created its own account and split the history.

PRAGMA foreign_keys = ON;

CREATE TABLE account_aliases (
    alias       TEXT PRIMARY KEY,        -- normalised identifier (last 4 digits + issuer)
    account_id  TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    source      TEXT NOT NULL,           -- the raw identifier as printed
    linked_at   TEXT NOT NULL,
    -- AUTO links are a heuristic and must stay visible so a wrong merge can be found;
    -- USER links are explicit and authoritative.
    link_kind   TEXT NOT NULL DEFAULT 'AUTO' CHECK (link_kind IN ('AUTO', 'USER'))
);
CREATE INDEX idx_alias_account ON account_aliases(account_id);
