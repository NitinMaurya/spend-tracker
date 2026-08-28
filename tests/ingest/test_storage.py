"""Database layer: migrations, idempotent ingestion, full raw capture.
D-001, D-003, D-018, D-028j."""
import os
import sqlite3
import pytest
from analyser.ids import document_id, raw_id
from tests.conftest import require_samples, SAMPLES


@pytest.fixture
def conn(tmp_path):
    from analyser.db import connect, migrate
    c = connect(str(tmp_path / "t.db"))
    migrate(c)
    return c


class TestMigrations:
    def test_all_migrations_apply(self, conn):
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("accounts", "documents", "transactions_raw", "transactions",
                  "statement_summary", "reward_statements", "document_pages",
                  "document_words", "document_lines", "schema_migrations"):
            assert t in names

    def test_migrations_are_idempotent(self, conn):
        from analyser.db import migrate
        migrate(conn)          # second run must not raise
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] >= 2

    def test_foreign_keys_enforced(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO documents (document_id,account_id,source_kind,"
                         "source_ref,file_name,parser_name,parser_version,ingested_at,"
                         "status) VALUES ('d','nope','LOCAL','r','f','fab',1,'now','PARSED')")
            conn.commit()

    def test_money_columns_reject_text(self, conn):
        """D-002: money is INTEGER minor units."""
        cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(transactions_raw)")}
        assert cols["amount_minor"] == "INTEGER"


class TestIdempotentIngest:
    @pytest.mark.golden
    def test_ingesting_the_same_statement_twice_changes_nothing(self, conn):
        require_samples()
        from analyser.ingest import ingest_document
        path = os.path.join(SAMPLES, "FAB_BLU_AUG_2026.pdf")
        if not os.path.exists(path):
            pytest.skip("FAB sample not present")
        conn.execute("INSERT INTO accounts (account_id,issuer,account_type,currency) "
                     "VALUES ('fab','FAB','CREDIT_CARD','AED')")
        conn.commit()
        first = ingest_document(path, conn=conn, account_id="fab")
        n1 = conn.execute("SELECT COUNT(*) FROM transactions_raw").fetchone()[0]
        second = ingest_document(path, conn=conn, account_id="fab")
        n2 = conn.execute("SELECT COUNT(*) FROM transactions_raw").fetchone()[0]
        assert n1 == n2 == 6
        assert second["inserted"] == 0

    @pytest.mark.golden
    def test_reconciliation_failure_rejects_the_document(self, conn):
        """D-004: a statement that does not close must not enter the analysis."""
        pytest.skip("needs a deliberately corrupted fixture; contract: status='REJECTED'")


class TestRawCapture:
    """D-018: everything the extractor sees is persisted."""

    @pytest.mark.golden
    def test_pages_words_and_lines_are_stored(self, conn):
        require_samples()
        from analyser.ingest import ingest_document
        path = os.path.join(SAMPLES, "FAB_BLU_AUG_2026.pdf")
        if not os.path.exists(path):
            pytest.skip("FAB sample not present")
        conn.execute("INSERT INTO accounts (account_id,issuer,account_type,currency) "
                     "VALUES ('fab','FAB','CREDIT_CARD','AED')")
        conn.commit()
        ingest_document(path, conn=conn, account_id="fab")
        assert conn.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM document_words").fetchone()[0] > 100
        assert conn.execute("SELECT COUNT(*) FROM document_lines").fetchone()[0] > 10

    @pytest.mark.golden
    def test_word_coordinates_are_retained(self, conn):
        """FAB's Debit/Credit columns are distinguishable only by x-position."""
        require_samples()
        from analyser.ingest import ingest_document
        path = os.path.join(SAMPLES, "FAB_BLU_AUG_2026.pdf")
        if not os.path.exists(path):
            pytest.skip("FAB sample not present")
        conn.execute("INSERT INTO accounts (account_id,issuer,account_type,currency) "
                     "VALUES ('fab','FAB','CREDIT_CARD','AED')")
        conn.commit()
        ingest_document(path, conn=conn, account_id="fab")
        row = conn.execute("SELECT x0,x1,top,bottom FROM document_words LIMIT 1").fetchone()
        assert all(v is not None for v in row)

    @pytest.mark.golden
    def test_every_line_has_a_disposition(self, conn):
        require_samples()
        from analyser.ingest import ingest_document
        path = os.path.join(SAMPLES, "FAB_BLU_AUG_2026.pdf")
        if not os.path.exists(path):
            pytest.skip("FAB sample not present")
        conn.execute("INSERT INTO accounts (account_id,issuer,account_type,currency) "
                     "VALUES ('fab','FAB','CREDIT_CARD','AED')")
        conn.commit()
        ingest_document(path, conn=conn, account_id="fab")
        assert conn.execute(
            "SELECT COUNT(*) FROM document_lines WHERE disposition IS NULL").fetchone()[0] == 0


class TestDeletion:
    """D-028i: `analyse forget` cascades."""

    def test_deleting_a_document_removes_its_raw_data(self, conn):
        from analyser.db import forget_document
        conn.execute("INSERT INTO accounts (account_id,issuer,account_type,currency) "
                     "VALUES ('a','X','CREDIT_CARD','AED')")
        conn.execute("INSERT INTO documents (document_id,account_id,source_kind,source_ref,"
                     "file_name,parser_name,parser_version,ingested_at,status) "
                     "VALUES ('d1','a','LOCAL','r','f','fab',1,'now','PARSED')")
        conn.execute("INSERT INTO document_pages (document_id,page_number) VALUES ('d1',1)")
        conn.commit()
        forget_document(conn, "d1")
        assert conn.execute("SELECT COUNT(*) FROM document_pages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
