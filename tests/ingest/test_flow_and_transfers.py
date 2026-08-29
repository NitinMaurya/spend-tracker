"""The economic-effect axis, and the transfer linking that makes it true.

Invented data throughout — this repository is public.
"""
import pytest


@pytest.fixture
def conn(tmp_path):
    from analyser.db import connect, migrate
    c = connect(str(tmp_path / "t.db"))
    migrate(c)
    for aid, kind, spend in (("bank-1", "BANK", 0), ("bank-2", "BANK", 0),
                             ("card-1", "CREDIT_CARD", 1), ("card-2", "CREDIT_CARD", 1)):
        c.execute("INSERT INTO accounts (account_id,issuer,account_type,currency,"
                  "include_in_spending) VALUES (?,'TESTBANK',?,'AED',?)", (aid, kind, spend))
    c.execute("INSERT INTO documents (document_id,account_id,source_kind,source_ref,"
              "file_name,parser_name,parser_version,ingested_at,status)"
              " VALUES ('d1','bank-1','LOCAL','r','f.pdf','test',1,'now','RECONCILED')")
    return c


def add(conn, txn_id, account, amount_minor, ttype, *, date="2026-01-15"):
    conn.execute("INSERT INTO transactions_raw (raw_id,document_id,account_id,page_number,"
                 "line_index,raw_text,txn_date,posting_date,raw_description,amount_minor,"
                 "currency) VALUES (?,'d1',?,1,1,'x',?,?,'x',?,'AED')",
                 (txn_id, account, date, date, amount_minor))
    conn.execute("INSERT INTO transactions (txn_id,account_id,txn_date,posting_date,"
                 "amount_minor,currency,system_txn_type) VALUES (?,?,?,?,?,'AED',?)",
                 (txn_id, account, date, date, amount_minor, ttype))
    conn.commit()


def flow_of(conn, txn_id):
    return conn.execute("SELECT flow FROM v_transactions WHERE txn_id=?", (txn_id,)).fetchone()[0]


class TestFlow:
    def test_paying_your_own_card_is_not_income(self, conn):
        """The largest single source of confusion: a card payment is money
        arriving on the card, and a ledger built on direction alone calls that
        income. It is your own money arriving from another of your accounts."""
        add(conn, "t1", "card-1", 5_000_00, "PAYMENT")
        assert flow_of(conn, "t1") == "MOVED"
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 0

    def test_salary_is_the_only_thing_that_earns(self, conn):
        add(conn, "t1", "bank-1", 20_000_00, "SALARY")
        add(conn, "t2", "card-1", 5_000_00, "PAYMENT")
        add(conn, "t3", "bank-1", 3_000_00, "TRANSFER")
        earned = conn.execute("SELECT COALESCE(SUM(amount_minor),0) FROM v_transactions"
                              " WHERE flow='EARNED'").fetchone()[0]
        assert earned == 20_000_00

    def test_a_wire_out_is_moved_not_spent(self, conn):
        add(conn, "t1", "bank-1", -25_000_00, "TRANSFER")
        assert flow_of(conn, "t1") == "MOVED"

    def test_a_drawdown_reads_as_borrowing_even_once_paired(self, conn):
        """Pairing must not outrank the debt. If it did, the single most
        important fact about the row — that the money is owed — would be lost to
        "internal movement"."""
        add(conn, "t1", "card-1", -35_900_00, "LOAN_DISBURSED")
        add(conn, "t2", "bank-1", 35_900_00, "TRANSFER")
        from analyser.matching import link_transfers
        link_transfers(conn, apply=True)
        assert flow_of(conn, "t1") == "BORROWED"
        assert flow_of(conn, "t2") == "MOVED"

    def test_an_emi_repays_it_does_not_spend(self, conn):
        add(conn, "t1", "card-1", -6_900_00, "LOAN_REPAYMENT")
        assert flow_of(conn, "t1") == "REPAID"

    def test_unnamed_money_in_earns_nothing(self, conn):
        add(conn, "t1", "bank-1", 9_000_00, "UNKNOWN")
        assert flow_of(conn, "t1") == "UNKNOWN"
        assert conn.execute("SELECT COUNT(*) FROM v_income").fetchone()[0] == 0


class TestTransferLinking:
    def test_both_legs_of_one_movement_are_paired(self, conn):
        add(conn, "t1", "bank-1", -1_000_00, "TRANSFER")
        add(conn, "t2", "card-1", 1_000_00, "PAYMENT")
        from analyser.matching import link_transfers
        assert link_transfers(conn, apply=True)["written"] == 2
        groups = {r[0] for r in conn.execute(
            "SELECT transfer_group_id FROM transactions WHERE transfer_group_id IS NOT NULL")}
        assert len(groups) == 1
        assert flow_of(conn, "t1") == "MOVED"

    def test_linking_is_idempotent(self, conn):
        add(conn, "t1", "bank-1", -1_000_00, "TRANSFER")
        add(conn, "t2", "card-1", 1_000_00, "PAYMENT")
        from analyser.matching import link_transfers
        link_transfers(conn, apply=True)
        assert link_transfers(conn, apply=True)["written"] == 0

    def test_a_salary_is_never_swallowed_by_a_coincidence(self, conn):
        """Without this guard, a salary and an unrelated same-sized outgoing on
        the same day would pair and cancel, erasing the month's income."""
        add(conn, "t1", "bank-1", 20_000_00, "SALARY")
        add(conn, "t2", "card-1", -20_000_00, "PURCHASE")
        from analyser.matching import link_transfers
        assert link_transfers(conn, apply=True)["written"] == 0
        assert flow_of(conn, "t1") == "EARNED"

    def test_competing_candidates_are_never_auto_paired(self, conn):
        """A wrong pairing reconciles perfectly against both statements, so it
        would be invisible. Ambiguity is reported, not resolved."""
        add(conn, "t1", "bank-1", -1_000_00, "TRANSFER")
        add(conn, "t2", "card-1", 1_000_00, "PAYMENT")
        add(conn, "t3", "card-2", 1_000_00, "PAYMENT")
        from analyser.matching import link_transfers
        r = link_transfers(conn, apply=True)
        assert r["written"] == 0
        assert len(r["ambiguous"]) == 1

    def test_legs_pair_even_when_a_statement_omits_the_posting_date(self, conn):
        add(conn, "t1", "bank-1", -1_000_00, "TRANSFER")
        add(conn, "t2", "card-1", 1_000_00, "PAYMENT")
        conn.execute("UPDATE transactions SET posting_date=NULL")
        conn.commit()
        from analyser.matching import link_transfers
        assert link_transfers(conn, apply=True)["written"] == 2


class TestEveryEffectPointsOneWay:
    """A bucket holding both credits and debits cannot be reported as one figure:
    whichever side is shown hides the other. Only MOVED and NEUTRAL are allowed
    both, because being the same money twice is what they mean."""

    def test_settling_a_card_is_a_movement_not_a_category_of_its_own(self, conn):
        add(conn, "t1", "card-1", 5_000_00, "PAYMENT")
        assert flow_of(conn, "t1") == "MOVED"

    def test_repaid_holds_only_instalments(self, conn):
        add(conn, "t1", "card-1", 5_000_00, "PAYMENT")
        add(conn, "t2", "card-1", -6_900_00, "LOAN_REPAYMENT")
        directions = conn.execute(
            "SELECT SUM(amount_minor > 0), SUM(amount_minor < 0)"
            "  FROM v_transactions WHERE flow='REPAID'").fetchone()
        assert directions == (0, 1)

    def test_interest_paid_to_you_is_not_spending(self, conn):
        """Savings interest arrives on an account you hold: earnings. A waived
        charge handed back on a card is a cost being undone, not income."""
        add(conn, "t1", "bank-1", 13_91, "INTEREST")
        add(conn, "t2", "card-1", 189_41, "INTEREST")
        add(conn, "t3", "card-1", -250_00, "INTEREST")
        assert flow_of(conn, "t1") == "EARNED"
        assert flow_of(conn, "t2") == "REFUNDED"
        assert flow_of(conn, "t3") == "SPENT"

    def test_nothing_that_arrived_is_ever_counted_as_spending(self, conn):
        for i, (acct, ttype) in enumerate([
            ("bank-1", "SALARY"), ("card-1", "PAYMENT"), ("bank-1", "TRANSFER"),
            ("bank-1", "INTEREST"), ("card-1", "INTEREST"), ("card-1", "REFUND"),
            ("bank-1", "UNKNOWN"),
        ]):
            add(conn, f"t{i}", acct, 1_000_00, ttype, date=f"2026-01-{i + 1:02d}")
        credits_in_spend = conn.execute(
            "SELECT COUNT(*) FROM v_transactions"
            " WHERE flow='SPENT' AND amount_minor > 0").fetchone()[0]
        assert credits_in_spend == 0
