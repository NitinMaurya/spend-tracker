"""v_income — what counts as money coming in, at the database boundary.

All figures invented: this repository is public and no fixture may carry a real
pay figure.
"""
import pytest


@pytest.fixture
def conn(tmp_path):
    from analyser.db import connect, migrate
    c = connect(str(tmp_path / "t.db"))
    migrate(c)
    c.execute("INSERT INTO accounts (account_id,issuer,account_type,currency,"
              "include_in_spending) VALUES ('bank-1','TESTBANK','BANK','AED',0)")
    c.execute("INSERT INTO accounts (account_id,issuer,account_type,currency,"
              "include_in_spending) VALUES ('card-1','TESTBANK','CREDIT_CARD','AED',1)")
    c.execute("INSERT INTO documents (document_id,account_id,source_kind,source_ref,"
              "file_name,parser_name,parser_version,ingested_at,status)"
              " VALUES ('d1','bank-1','LOCAL','r','f.pdf','test',1,'now','RECONCILED')")
    return c


def add(conn, txn_id, account, amount_minor, ttype, *, date="2026-01-15",
        excluded=0, transfer=None):
    conn.execute("INSERT INTO transactions_raw (raw_id,document_id,account_id,"
                 "page_number,line_index,raw_text,txn_date,raw_description,"
                 "amount_minor,currency) VALUES (?,'d1',?,1,1,'x',?,'x',?, 'AED')",
                 (txn_id, account, date, amount_minor))
    conn.execute("INSERT INTO transactions (txn_id,account_id,txn_date,amount_minor,"
                 "currency,system_txn_type,excluded,transfer_group_id)"
                 " VALUES (?,?,?,?,'AED',?,?,?)",
                 (txn_id, account, date, amount_minor, ttype, excluded, transfer))
    conn.commit()


class TestIncomeView:
    def test_salary_on_a_non_spending_account_still_counts(self, conn):
        """The regression this view exists to prevent.

        A salary lands on the current account, which is flagged
        include_in_spending = 0 precisely because its activity is not spending.
        Filtering income on that flag would hide every pay cheque.
        """
        add(conn, "t1", "bank-1", 1_000_00, "SALARY")
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 1
        assert conn.execute("SELECT SUM(amount_minor) FROM v_income").fetchone()[0] == 1_000_00

    def test_spending_is_not_income(self, conn):
        add(conn, "t1", "card-1", -250_00, "PURCHASE")
        add(conn, "t2", "bank-1", 1_000_00, "SALARY")
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 1

    def test_income_is_not_spending(self, conn):
        """The mirror: a pay cheque must never inflate the spend total."""
        add(conn, "t1", "bank-1", 1_000_00, "SALARY")
        assert conn.execute("SELECT COUNT(*) FROM v_spend").fetchone()[0] == 0

    def test_unnamed_credits_are_excluded(self, conn):
        add(conn, "t1", "bank-1", 500_00, "UNKNOWN")
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 0

    def test_a_transfer_between_your_own_accounts_is_not_earnings(self, conn):
        add(conn, "t1", "bank-1", 900_00, "SALARY", transfer="g1")
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 0

    def test_excluded_rows_are_dropped(self, conn):
        add(conn, "t1", "bank-1", 900_00, "SALARY", excluded=1)
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 0


class TestMigrationPreservesExistingViews:
    def test_the_rebuild_left_every_view_in_place(self, conn):
        """010 drops and recreates the views over transactions to rebuild the
        table. Any one of them going missing would silently blank a screen."""
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'")}
        for v in ("v_transactions", "v_spend", "v_card_charges", "v_reimbursable",
                  "v_financing", "v_position", "v_parse_coverage", "v_income"):
            assert v in views, f"{v} did not survive the table rebuild"

    def test_financing_still_matches_both_spellings(self, conn):
        """The rebuild restores v_financing by hand; both INSTALMENT spellings
        must survive that copy."""
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='v_financing'"
                           ).fetchone()[0]
        assert "%INSTALLMENT%" in sql
        assert "%INSTALMENT%" in sql.replace("%INSTALLMENT%", "", 1)
