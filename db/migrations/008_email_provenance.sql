-- Trace a statement back to the email it arrived in (D-035 extended).
--
-- Keyed by FILE NAME rather than document_id: the email is known at download time,
-- before anything is parsed, and the link must survive a database rebuild or a
-- re-ingest under a new document id.

PRAGMA foreign_keys = ON;

CREATE TABLE gmail_messages (
    file_name    TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL,
    thread_id    TEXT,
    subject      TEXT,
    sender       TEXT,
    received_at  TEXT,
    attachment   TEXT,          -- the attachment name as Gmail held it
    fetched_at   TEXT NOT NULL
);
CREATE INDEX idx_gmail_message ON gmail_messages(message_id);
