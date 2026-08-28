-- Store EVERYTHING the PDF parser sees, not just the rows we understood.
-- Purpose: (a) re-derive transactions without re-opening the PDF,
--          (b) prove no line was silently dropped,
--          (c) satisfy the evidence chain in spec §19 / §23.

PRAGMA foreign_keys = ON;

-- Full per-page text, both renderings. `layout_text` preserves column geometry
-- (what a human reads); `plain_text` is the reading-order stream.
CREATE TABLE document_pages (
    document_id   TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    width         REAL,
    height        REAL,
    rotation      INTEGER,
    layout_text   TEXT,
    plain_text    TEXT,
    word_count    INTEGER,
    PRIMARY KEY (document_id, page_number)
);

-- Word-level extraction with coordinates. This is the true raw record: FAB's
-- Debit/Credit columns are distinguishable ONLY by x-position, so discarding
-- coordinates would lose information that cannot be recovered from text.
CREATE TABLE document_words (
    document_id  TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number  INTEGER NOT NULL,
    word_index   INTEGER NOT NULL,
    text         TEXT NOT NULL,
    x0           REAL NOT NULL,
    x1           REAL NOT NULL,
    top          REAL NOT NULL,
    bottom       REAL NOT NULL,
    font_name    TEXT,
    font_size    REAL,
    PRIMARY KEY (document_id, page_number, word_index)
);
CREATE INDEX idx_words_doc_page ON document_words(document_id, page_number);

-- Any table structures the extractor found, stored verbatim as JSON.
CREATE TABLE document_tables (
    document_id  TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number  INTEGER NOT NULL,
    table_index  INTEGER NOT NULL,
    bbox_json    TEXT,
    rows_json    TEXT NOT NULL,
    PRIMARY KEY (document_id, page_number, table_index)
);

-- Every visual line on every page, and what became of it. A line is either
-- consumed into a transaction, or explicitly classified. Nothing is dropped
-- silently -- 'UNPARSED' rows are a review queue, not an error.
CREATE TABLE document_lines (
    document_id   TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    page_number   INTEGER NOT NULL,
    line_index    INTEGER NOT NULL,
    raw_text      TEXT NOT NULL,
    top           REAL,
    disposition   TEXT NOT NULL CHECK (disposition IN (
        'TRANSACTION',      -- became a transactions_raw row
        'CONTINUATION',     -- detail line attached to the preceding transaction
        'HEADER',           -- column headers, account/product header block
        'SUMMARY',          -- the issuer's own totals block
        'REWARD',           -- reward/cashback block
        'BOILERPLATE',      -- T&Cs, marketing, contact details
        'UNREADABLE',       -- broken font encoding (FAB cid:, Mashreq mojibake)
        'UNPARSED')),       -- recognised as content but not understood -- review
    raw_id        TEXT REFERENCES transactions_raw(raw_id),
    note          TEXT,
    PRIMARY KEY (document_id, page_number, line_index)
);
CREATE INDEX idx_lines_disposition ON document_lines(disposition);

-- Coverage: proportion of non-boilerplate lines a parser actually understood.
-- A sudden drop signals an issuer format change.
CREATE VIEW v_parse_coverage AS
SELECT
    l.document_id,
    d.file_name,
    d.parser_name,
    d.parser_version,
    COUNT(*)                                                          AS total_lines,
    SUM(l.disposition = 'TRANSACTION')                                AS transaction_lines,
    SUM(l.disposition = 'UNPARSED')                                   AS unparsed_lines,
    SUM(l.disposition = 'UNREADABLE')                                 AS unreadable_lines,
    ROUND(100.0 * SUM(l.disposition = 'UNPARSED')
          / NULLIF(SUM(l.disposition NOT IN ('BOILERPLATE','UNREADABLE')), 0), 2)
                                                                      AS unparsed_pct
FROM document_lines l
JOIN documents d ON d.document_id = l.document_id
GROUP BY l.document_id;
