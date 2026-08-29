"""Income typing — a salary credit is read off the page, never inferred.

The invented amounts here are deliberate: this repo is public, so no fixture
carries a real pay figure.
"""
import pytest
from analyser.normalize import classify_txn_type
from analyser.domain.model import TxnType

pytestmark = pytest.mark.red


class TestSalaryIsNamedNotGuessed:
    @pytest.mark.parametrize("desc", [
        "SALARY CREDIT SALARY FROM -XXX00-XXX-00 FOR T",
        "Salary Credit",
        "MONTHLY SALARY TRANSFER",
    ])
    def test_named_salary_credits_are_income(self, desc):
        assert classify_txn_type(desc, 1_000_00) == TxnType.SALARY

    def test_an_unnamed_credit_stays_unknown(self):
        """The whole point: money in that the statement does not NAME is not income.

        A bare inbound transfer could be a refund, a loan, or a friend paying you
        back. Typing it as earnings would invent income out of an unlabelled row.
        """
        assert classify_txn_type("CR 000000 FROM 000000", 800_00, None, "BANK") \
            == TxnType.UNKNOWN

    def test_a_named_movement_is_a_transfer_not_income(self):
        """Money in that the statement names as a MOVEMENT is not earnings.

        This is the other half of refusing to guess: an inbound wire is not
        unknown -- the page says what it is -- but what it says is "this money
        moved", not "this money was earned"."""
        for desc in ("BANKNET TRANSFER MOBILE BANKING TRANSFER FROM",
                     "INWARD REMITTANCE TT REF: FT000000XXX0",
                     "NEFT CR 000000"):
            assert classify_txn_type(desc, 5_000_00, None, "BANK") == TxnType.TRANSFER

    def test_inward_remittance_is_not_a_loan(self):
        """Regression: the instalment rule used to match "EMI" as a bare
        substring, so INWARD REMITTANCE and EMIRATES NBD were both typed as loan
        instalments -- an arriving wire booked as borrowing."""
        assert classify_txn_type("INWARD REMITTANCE TT REF: FT000000XXX0",
                                 5_000_00, None, "BANK") == TxnType.TRANSFER
        assert classify_txn_type("EMIRATES NBD TRANSFER", -1_000_00, None, "BANK") \
            == TxnType.TRANSFER

    def test_money_leaving_is_never_income_however_it_is_labelled(self):
        """A salary-advance repayment or a payroll fee mentions salary while money
        LEAVES. Typing that as earnings would credit income that never arrived."""
        assert classify_txn_type("SALARY ADVANCE REPAYMENT", -500_00) != TxnType.SALARY
        assert classify_txn_type("PAYROLL SALARY PROCESSING FEE", -25_00) != TxnType.SALARY

    def test_salary_does_not_disturb_existing_typing(self):
        """The rule sits above the generic keyword table; nothing else may shift."""
        assert classify_txn_type("PAYMENT RECEIVED - THANK YOU", 564_00) == TxnType.PAYMENT
        assert classify_txn_type("EXAMPLE TRAVEL DUBAI AE", -870_19) == TxnType.PURCHASE
        assert classify_txn_type("QC 12 M @ 0% + 4% PF", -1_000_00) == TxnType.LOAN_REPAYMENT


class TestIncomeIsNotSpend:
    def test_salary_is_not_in_the_spend_type_set(self):
        assert TxnType.SALARY not in TxnType.SPEND
        assert TxnType.SALARY in TxnType.EARNED
