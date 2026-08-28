"""SQLite storage layer: connection, migrations, cascade deletion, backups.

D-001 (a single local SQLite file is the system of record),
D-028i (`analyse forget` cascades),
D-028j (snapshot to data/backups/, keep the last 10).

The schema itself lives in db/migrations/*.sql and is never edited from here --
this module only applies those files, in order, exactly once each.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone

# Project root == the directory containing the `analyser` package.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, "db", "migrations")
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "data", "analyser.db")

#: How many snapshots to retain (D-028j).
BACKUP_RETENTION = 10

_MIGRATION_NAME = re.compile(r"^(\d+)_.*\.sql$")


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------

def connect(path=DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open `path` with foreign keys enforced and WAL journaling.

    Foreign keys are OFF by default in SQLite and are a per-connection setting,
    so every connection must opt in -- the ON DELETE CASCADE clauses declared in
    the migrations are inert without it.
    """
    path = str(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path)
    # WAL lets a reader (e.g. a snapshot) run while a write is in flight.
    # In-memory databases cannot do WAL; that is not an error worth raising.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------

def _migration_files(migrations_dir=MIGRATIONS_DIR):
    """[(version:int, name:str, abspath:str)] sorted by numeric version."""
    if not os.path.isdir(migrations_dir):
        return []
    found = []
    for name in os.listdir(migrations_dir):
        match = _MIGRATION_NAME.match(name)
        if match:
            found.append((int(match.group(1)), name,
                          os.path.join(migrations_dir, name)))
    found.sort(key=lambda row: row[0])
    return found


def _table_exists(conn, table) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _applied_versions(conn) -> set:
    """Empty before 001 runs -- 001_init.sql is what creates schema_migrations."""
    if not _table_exists(conn, "schema_migrations"):
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn, migrations_dir=MIGRATIONS_DIR) -> list:
    """Apply every pending migration in numeric order. Returns versions applied.

    Idempotent: a second call is a no-op and must not raise. The bootstrap case
    is that schema_migrations does not exist yet, because 001_init.sql is what
    creates it -- so applied versions are read defensively.
    """
    applied = _applied_versions(conn)
    newly_applied = []

    for version, name, path in _migration_files(migrations_dir):
        if version in applied:
            continue
        with open(path, "r", encoding="utf-8") as handle:
            script = handle.read()
        # executescript commits any open transaction first, then runs the DDL.
        conn.executescript(script)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?,?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        newly_applied.append(version)

    # A pre-existing database may carry the schema without the bookkeeping rows.
    if not newly_applied and _table_exists(conn, "schema_migrations"):
        conn.commit()

    return newly_applied


# ---------------------------------------------------------------------------
# deletion (D-028i)
# ---------------------------------------------------------------------------

# Order matters: children before parents. The migrations declare ON DELETE
# CASCADE on the document_* tables, statement_summary and reward_statements,
# but NOT on transactions_raw -> documents, nor on transactions -> raw, nor on
# document_lines.raw_id -> transactions_raw. Those must be deleted by hand, and
# document_lines must go before transactions_raw it points at.
_CASCADE_TABLES = (
    "document_lines",
    "document_words",
    "document_tables",
    "document_pages",
    "statement_summary",
    "reward_statements",
    "transactions_raw",
)


def forget_document(conn, document_id) -> None:
    """Delete a document and every row that references it (D-028i).

    Covers pages, words, tables, lines, raw and normalized transactions,
    the summary block and rewards. Commits.
    """
    # Normalized rows are keyed by the raw_id they were derived from.
    if _table_exists(conn, "transactions") and _table_exists(conn, "transactions_raw"):
        conn.execute(
            "DELETE FROM transactions WHERE txn_id IN "
            "(SELECT raw_id FROM transactions_raw WHERE document_id=?)",
            (document_id,),
        )

    for table in _CASCADE_TABLES:
        if _table_exists(conn, table):
            conn.execute(f"DELETE FROM {table} WHERE document_id=?", (document_id,))

    conn.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# backups (D-028j)
# ---------------------------------------------------------------------------

def _backups_dir(db_path) -> str:
    """`data/backups/`, as a sibling of the database file (D-001: data/analyser.db)."""
    parent = os.path.dirname(os.path.abspath(str(db_path)))
    return os.path.join(parent or os.path.join(PROJECT_ROOT, "data"), "backups")


def _prune(backups_dir, keep=BACKUP_RETENTION) -> None:
    entries = [
        os.path.join(backups_dir, name)
        for name in os.listdir(backups_dir)
        if name.startswith("analyser-") and name.endswith(".db")
    ]
    # Names are timestamp-ordered, so they sort lexicographically by age;
    # mtime is the primary key so a restored/touched file is not misjudged.
    entries.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)), reverse=True)
    for stale in entries[keep:]:
        try:
            os.remove(stale)
        except OSError:
            pass


def snapshot(db_path=DEFAULT_DB_PATH, keep=BACKUP_RETENTION) -> str:
    """Copy the database to data/backups/analyser-<ISO>.db, keeping the newest 10.

    Uses SQLite's online backup API so the copy is a single consistent file even
    when WAL has uncheckpointed pages -- a plain file copy would silently leave
    recent commits behind in the -wal sidecar.
    """
    db_path = str(db_path)
    backups_dir = _backups_dir(db_path)
    os.makedirs(backups_dir, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(backups_dir, f"analyser-{stamp}.db")
    suffix = 1
    while os.path.exists(dest):
        dest = os.path.join(backups_dir, f"analyser-{stamp}-{suffix}.db")
        suffix += 1

    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
    except sqlite3.DatabaseError:
        # Not a usable SQLite file (or backup unsupported) -- fall back to bytes.
        if os.path.exists(dest):
            os.remove(dest)
        shutil.copy2(db_path, dest)
    finally:
        source.close()

    _prune(backups_dir, keep)
    return dest


def merge_accounts(conn, source_id, target_id):
    """Fold `source_id` into `target_id`: one card, one account (D-028e).

    Banks identify the same card differently across their own documents -- CBD prints
    a PAN on one statement and an account number on another -- and each identifier
    created its own account. Merging repoints every child row and records the old id
    as an alias so future statements resolve straight to the target.
    """
    from datetime import datetime, timezone

    if source_id == target_id:
        return 0
    moved = 0
    for table in ("documents", "transactions_raw", "transactions", "reward_statements"):
        cur = conn.execute(f"UPDATE {table} SET account_id=? WHERE account_id=?",
                           (target_id, source_id))
        moved += cur.rowcount or 0
    src = conn.execute("SELECT masked_number FROM accounts WHERE account_id=?",
                       (source_id,)).fetchone()
    conn.execute(
        "INSERT OR REPLACE INTO account_aliases (alias,account_id,source,linked_at,link_kind)"
        " VALUES (?,?,?,?,'USER')",
        (source_id, target_id, (src[0] if src else "") or "",
         datetime.now(timezone.utc).isoformat()))
    conn.execute("DELETE FROM accounts WHERE account_id=?", (source_id,))
    conn.commit()
    return moved
